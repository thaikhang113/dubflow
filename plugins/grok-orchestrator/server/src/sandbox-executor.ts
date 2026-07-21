import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync, statSync } from "node:fs";
import path from "node:path";

const SHELL_META = /[|&;<>`$(){}\[\]*?!~]/;
const MAX_OUTPUT_BYTES = 1_000_000;
const MAX_WALL_TIME_MS = 120_000;
const MAX_CPU_SECONDS = 120;
const MAX_MEMORY_BYTES = 2_147_483_648;
const MAX_PROCESSES = 128;

export function parseArgv(command: string): string[] {
  if (/[\n\r\0]/.test(command)) throw new Error("shell syntax denied");
  const argv: string[] = [];
  let current = "";
  let quote: "'" | '"' | undefined;
  let escaped = false;
  for (const character of command.trim()) {
    if (escaped) {
      current += character;
      escaped = false;
    } else if (!quote && SHELL_META.test(character)) {
      throw new Error("shell syntax denied");
    } else if (character === "\\" && quote !== "'") {
      escaped = true;
    } else if (quote) {
      if (character === quote) quote = undefined;
      else current += character;
    } else if (character === "'" || character === '"') {
      quote = character;
    } else if (/\s/.test(character)) {
      if (current) argv.push(current);
      current = "";
    } else {
      current += character;
    }
  }
  if (quote || escaped) throw new Error("shell syntax denied");
  if (current) argv.push(current);
  if (argv.length === 0) throw new Error("empty command denied");
  return argv;
}

export interface SandboxArgsOptions {
  worktreeRoot: string;
  cwd: string;
  argv: string[];
  gitMetadataRoot?: string;
  network?: boolean;
}

export function buildSandboxArgs(options: SandboxArgsOptions): string[] {
  const root = path.resolve(options.worktreeRoot);
  const cwd = path.resolve(options.cwd);
  if (path.relative(root, cwd).startsWith("..")) throw new Error("sandbox cwd outside worktree");
  if (options.gitMetadataRoot && !path.isAbsolute(options.gitMetadataRoot)) {
    throw new Error("sandbox Git metadata path must be absolute");
  }
  const args = ["--die-with-parent", "--new-session", "--unshare-all"];
  if (!options.network) args.push("--unshare-net");
  args.push("--clearenv", "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin", "--setenv", "HOME", "/tmp/home");
  for (const systemRoot of ["/usr", "/bin", "/lib", "/lib64"]) {
    if (existsSync(systemRoot)) args.push("--ro-bind", systemRoot, systemRoot);
  }
  if (options.gitMetadataRoot) {
    const gitMetadataRoot = path.resolve(options.gitMetadataRoot);
    args.push("--ro-bind", gitMetadataRoot, gitMetadataRoot);
  }
  args.push("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/tmp/home", "--bind", root, root, "--chdir", cwd, "--", ...options.argv);
  return args;
}

export interface SandboxProcess {
  id: string;
  child: ChildProcessWithoutNullStreams;
  output: string;
  truncated: boolean;
  exitCode: number | null;
  watchdog: NodeJS.Timeout;
}

export class SandboxExecutor {
  #binary: string;
  #limitBinary: string;
  #root: string;
  #gitMetadataRoot?: string;
  #processes = new Map<string, SandboxProcess>();
  #nextId = 1;

  constructor(worktreeRoot: string, binary = "/usr/bin/bwrap", limitBinary = "/usr/bin/prlimit", gitMetadataRoot?: string) {
    if (!path.isAbsolute(binary) || !existsSync(binary)) throw new Error("bubblewrap isolation is required");
    if (!path.isAbsolute(limitBinary) || !existsSync(limitBinary)) throw new Error("prlimit resource isolation is required");
    this.#root = path.resolve(worktreeRoot);
    if (gitMetadataRoot) {
      if (!path.isAbsolute(gitMetadataRoot) || !existsSync(gitMetadataRoot) || !statSync(gitMetadataRoot).isDirectory()) {
        throw new Error("Git metadata directory is required for linked worktrees");
      }
      this.#gitMetadataRoot = path.resolve(gitMetadataRoot);
    }
    this.#binary = binary;
    this.#limitBinary = limitBinary;
  }

  create(command: string, cwd = this.#root, outputLimit = 1_000_000): { terminalId: string } {
    const argv = parseArgv(command);
    const id = `terminal-${this.#nextId++}`;
    const boundedOutputLimit = Math.min(MAX_OUTPUT_BYTES, Math.max(1, Math.floor(outputLimit)));
    const limitedArgv = [this.#limitBinary, `--as=${MAX_MEMORY_BYTES}`, `--nproc=${MAX_PROCESSES}`, `--cpu=${MAX_CPU_SECONDS}`, "--", ...argv];
    const child = spawn(this.#binary, buildSandboxArgs({
      worktreeRoot: this.#root,
      cwd,
      argv: limitedArgv,
      ...(this.#gitMetadataRoot ? { gitMetadataRoot: this.#gitMetadataRoot } : {}),
    }), {
      cwd: this.#root,
      env: {},
      stdio: ["pipe", "pipe", "pipe"],
      detached: true,
    });
    child.stdin.end();
    const watchdog = setTimeout(() => this.kill(id), MAX_WALL_TIME_MS);
    const record: SandboxProcess = { id, child, output: "", truncated: false, exitCode: null, watchdog };
    this.#processes.set(id, record);
    const collect = (chunk: Buffer): void => {
      const remaining = boundedOutputLimit - Buffer.byteLength(record.output);
      if (remaining <= 0) { record.truncated = true; this.kill(id); return; }
      record.output += chunk.subarray(0, remaining).toString("utf8");
      if (chunk.byteLength > remaining) { record.truncated = true; this.kill(id); }
    };
    child.stdout.on("data", collect);
    child.stderr.on("data", collect);
    child.on("exit", (code) => { clearTimeout(record.watchdog); record.exitCode = code ?? 1; });
    return { terminalId: id };
  }

  output(terminalId: string): { output: string; exitStatus: { exitCode: number } | null; truncated: boolean } {
    const record = this.#require(terminalId);
    return { output: record.output, exitStatus: record.exitCode === null ? null : { exitCode: record.exitCode }, truncated: record.truncated };
  }

  waitForExit(terminalId: string): Promise<{ exitCode: number }> {
    const record = this.#require(terminalId);
    if (record.exitCode !== null) return Promise.resolve({ exitCode: record.exitCode });
    return new Promise((resolve) => record.child.once("exit", (code) => resolve({ exitCode: code ?? 1 })));
  }

  kill(terminalId: string): void {
    const record = this.#require(terminalId);
    if (record.child.pid) {
      try { process.kill(-record.child.pid, "SIGKILL"); } catch { record.child.kill("SIGKILL"); }
    }
  }

  release(terminalId: string): void {
    const record = this.#require(terminalId);
    if (record.exitCode === null) this.kill(terminalId);
    clearTimeout(record.watchdog);
    this.#processes.delete(terminalId);
  }

  killAll(): void { for (const id of this.#processes.keys()) this.kill(id); }

  #require(id: string): SandboxProcess {
    const record = this.#processes.get(id);
    if (!record) throw new Error("unknown terminal");
    return record;
  }
}
