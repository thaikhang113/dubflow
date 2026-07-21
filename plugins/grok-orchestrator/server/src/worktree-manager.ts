import { execFile } from "node:child_process";
import { mkdir, realpath } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const exec = promisify(execFile);
const MAX_DIFF_BYTES = 1_000_000;

interface BoundedOutput { output: string; truncated: boolean }

export interface WorktreeRecord {
  repoRoot: string;
  worktreeRoot: string;
  baseSha: string;
}

export interface WorktreeDiff {
  diff: string;
  stat: string;
  files: string[];
  hasChanges: boolean;
  truncated: boolean;
}

async function git(cwd: string, args: string[], maxBuffer = MAX_DIFF_BYTES + 65_536): Promise<string> {
  const result = await exec("git", ["-C", cwd, ...args], { encoding: "utf8", maxBuffer });
  return result.stdout;
}

async function boundedGit(cwd: string, args: string[], maxBytes: number, acceptedExitCodes = new Set([0])): Promise<BoundedOutput> {
  try {
    const result = await exec("git", ["-C", cwd, ...args], { encoding: "utf8", maxBuffer: maxBytes });
    return { output: result.stdout, truncated: false };
  } catch (error) {
    const failure = error as Error & { code?: string | number; stdout?: string };
    if (failure.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER") {
      return { output: failure.stdout ?? "", truncated: true };
    }
    if (typeof failure.code === "number" && acceptedExitCodes.has(failure.code)) {
      return { output: failure.stdout ?? "", truncated: false };
    }
    throw error;
  }
}

export class WorktreeManager {
  #root: string;

  constructor(stateRoot: string) {
    this.#root = path.join(stateRoot, "worktrees");
  }

  async createWorktree(sessionId: string, requestedRepoRoot: string, baseRef: string): Promise<WorktreeRecord> {
    const repoRoot = await realpath(requestedRepoRoot);
    const topLevel = (await git(repoRoot, ["rev-parse", "--show-toplevel"])).trim();
    if (await realpath(topLevel) !== repoRoot) throw new Error("repo_root must be the git top level");
    const baseSha = (await git(repoRoot, ["rev-parse", "--verify", `${baseRef}^{commit}`])).trim();
    if (!/^[0-9a-f]{40}$/i.test(baseSha)) throw new Error("unable to lock base SHA");
    await mkdir(this.#root, { recursive: true, mode: 0o700 });
    const worktreeRoot = path.join(this.#root, sessionId);
    await exec("git", ["-C", repoRoot, "worktree", "add", "--detach", worktreeRoot, baseSha], {
      encoding: "utf8",
      maxBuffer: 256_000,
    });
    return { repoRoot, worktreeRoot: await realpath(worktreeRoot), baseSha };
  }

  async getDiff(worktreeRoot: string): Promise<WorktreeDiff> {
    const root = await realpath(worktreeRoot);
    const status = await git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]);
    const entries = status.split("\0").filter(Boolean);
    const files = [...new Set(entries.map((entry) => entry.slice(3)))];
    const untrackedFiles = entries.filter((entry) => entry.startsWith("?? ")).map((entry) => entry.slice(3));
    const tracked = await boundedGit(root, ["diff", "--no-ext-diff", "--binary", "--", "."], MAX_DIFF_BYTES);
    let diff = tracked.output;
    let truncated = tracked.truncated;
    for (const file of untrackedFiles) {
      const remaining = MAX_DIFF_BYTES - Buffer.byteLength(diff);
      if (remaining <= 0) { truncated = true; break; }
      const untracked = await boundedGit(root, ["diff", "--no-ext-diff", "--binary", "--no-index", "--", "/dev/null", file], remaining, new Set([0, 1]));
      diff += untracked.output;
      if (untracked.truncated) { truncated = true; break; }
    }
    const trackedStat = await git(root, ["diff", "--no-ext-diff", "--stat", "--", "."]);
    const stat = untrackedFiles.length > 0 ? `${trackedStat}${untrackedFiles.length} untracked file(s)\n` : trackedStat;
    if (truncated) diff = `${diff}\n[diff truncated]\n`;
    return { diff, stat, files, hasChanges: files.length > 0, truncated };
  }

  async removeWorktree(repoRoot: string, worktreeRoot: string): Promise<void> {
    const diff = await this.getDiff(worktreeRoot);
    if (diff.hasChanges) throw new Error("refusing to remove a worktree with changes");
    await exec("git", ["-C", await realpath(repoRoot), "worktree", "remove", await realpath(worktreeRoot)], {
      encoding: "utf8",
      maxBuffer: 256_000,
    });
  }
}
