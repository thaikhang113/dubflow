import { describe, it, expect } from "vitest";
import * as os from "node:os";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { TerminalManager, resolveExitCode, buildKillPlan, resolveTerminalShell } from "../src/terminal-manager";

// Use `node -e` everywhere so tests are deterministic on Windows, macOS, and Linux.
// Quoting strategy: single-quote the outer node script, escape inner single quotes if any.
const nodeEval = (script: string) => `node -e "${script.replace(/"/g, '\\"')}"`;

describe("TerminalManager", () => {
  it("captures stdout from a quick command", async () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({ command: nodeEval("process.stdout.write('HELLO_TM')") });
    const { exitCode } = await m.waitForExit(terminalId);
    expect(exitCode).toBe(0);
    const r = m.output(terminalId);
    expect(r.output).toContain("HELLO_TM");
    expect(r.exitStatus).toEqual({ exitCode: 0 });
    expect(r.truncated).toBe(false);
    m.release(terminalId);
  });

  it("captures stderr and nonzero exit", async () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({
      command: nodeEval("process.stderr.write('ERR'); process.exit(7)"),
    });
    const r = await m.waitForExit(terminalId);
    // The Windows host is PowerShell (#46). Windows PowerShell 5.1 collapses any
    // non-zero native exit to 1 (pwsh 7 preserves the exact code); /bin/sh passes
    // it through. Assert failure is detected everywhere, exact code only off-win32
    // (this box may resolve to 5.1, so don't assert exactly 7 on Windows).
    expect(r.exitCode).not.toBe(0);
    if (process.platform !== "win32") expect(r.exitCode).toBe(7);
    const out = m.output(terminalId);
    expect(out.output).toContain("ERR");
    m.release(terminalId);
  });

  it("respects outputByteLimit and sets truncated flag", async () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({
      command: nodeEval("process.stdout.write('a'.repeat(5000))"),
      outputByteLimit: 100,
    });
    await m.waitForExit(terminalId);
    const r = m.output(terminalId);
    expect(r.output.length).toBeLessThanOrEqual(100);
    expect(r.truncated).toBe(true);
    m.release(terminalId);
  });

  // Regression: truncating at a byte boundary must not split a multi-byte UTF-8
  // character into a replacement char (U+FFFD). '✓' is 3 bytes; a 100-byte limit
  // lands mid-character. Pre-fix `Buffer.toString` on the partial slice produced
  // a trailing '�'; a StringDecoder buffers the incomplete bytes instead.
  it("does not emit U+FFFD when truncation splits a multi-byte character", async () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({
      // 60 copies of '✓' = 180 bytes; limit 100 cuts mid-character.
      command: nodeEval("process.stdout.write('\\u2713'.repeat(60))"),
      outputByteLimit: 100,
    });
    await m.waitForExit(terminalId);
    const r = m.output(terminalId);
    expect(r.truncated).toBe(true);
    expect(r.output).not.toContain("�");
    expect(/^✓+$/.test(r.output)).toBe(true);
    m.release(terminalId);
  });

  it("returns exitStatus null while still running", () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({
      command: nodeEval("setTimeout(()=>{}, 5000)"),
    });
    const r = m.output(terminalId);
    expect(r.exitStatus).toBeNull();
    m.kill(terminalId);
    m.release(terminalId);
  });

  it("injects env from {name,value} pairs", async () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({
      command: nodeEval("process.stdout.write(process.env.GROK_TEST_VAR || '')"),
      env: [{ name: "GROK_TEST_VAR", value: "INJECTED" }],
    });
    await m.waitForExit(terminalId);
    expect(m.output(terminalId).output).toContain("INJECTED");
    m.release(terminalId);
  });

  it("honors cwd", async () => {
    const m = new TerminalManager();
    const tmp = os.tmpdir();
    const { terminalId } = m.create({
      command: nodeEval("process.stdout.write(process.cwd())"),
      cwd: tmp,
    });
    await m.waitForExit(terminalId);
    // On macOS tmpdir() resolves a /private/var symlink; normalize both sides.
    const got = m.output(terminalId).output.trim().toLowerCase();
    expect(got).toContain(tmp.replace(/\\/g, "/").toLowerCase().split("/").pop()!);
  });

  it("waitForExit resolves immediately if already exited", async () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({ command: nodeEval("process.exit(0)") });
    await m.waitForExit(terminalId);
    const r = await m.waitForExit(terminalId);
    expect(r.exitCode).toBe(0);
    m.release(terminalId);
  });

  it("output() throws on unknown terminalId", () => {
    const m = new TerminalManager();
    expect(() => m.output("nope")).toThrowError(/unknown terminalId/);
  });

  it("kill+release on a missing id is a no-op", () => {
    const m = new TerminalManager();
    expect(() => m.kill("nope")).not.toThrow();
    expect(() => m.release("nope")).not.toThrow();
  });

  it("disposeAll kills outstanding terminals", () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({
      command: nodeEval("setTimeout(()=>{}, 60000)"),
    });
    m.disposeAll();
    expect(() => m.output(terminalId)).toThrow();
  });

  // Regression: a process killed by a signal must not be reported as a clean
  // exit (code 0). The old `code ?? 0` masked signal kills as success, so the
  // agent assumed a command it interrupted had actually succeeded.
  it("reports a non-zero exit code when a running process is killed", async () => {
    const m = new TerminalManager();
    const { terminalId } = m.create({ command: nodeEval("setInterval(()=>{}, 1000)") });
    await new Promise((r) => setTimeout(r, 150)); // let it start
    m.kill(terminalId);
    const { exitCode } = await m.waitForExit(terminalId);
    expect(exitCode).not.toBe(0);
    m.release(terminalId);
  });
});

// Real-shell integration for #46: on Windows the agent's `terminal/*` commands
// now run under PowerShell, so PowerShell-only syntax that cmd.exe cannot run
// must succeed end-to-end through TerminalManager. These spawn the actual host
// shell, so they only make sense on Windows — skipped on the Linux CI box, where
// the host is /bin/sh and unchanged. (CLAUDE.md's "node -e everywhere" rule is
// for the cross-platform tests above; proving the PowerShell switch inherently
// needs PowerShell syntax, so this block is the deliberate exception.)
const describeWin = process.platform === "win32" ? describe : describe.skip;

describeWin("Windows PowerShell host (#46)", () => {
  const runToEnd = async (command: string) => {
    const m = new TerminalManager();
    const { terminalId } = m.create({ command });
    const { exitCode } = await m.waitForExit(terminalId);
    const output = m.output(terminalId).output;
    m.release(terminalId);
    return { exitCode, output };
  };

  it("runs a PowerShell pipeline cmd.exe cannot (the issue's failure mode)", async () => {
    // Under the old cmd host this errored: "'Measure-Object' is not recognized".
    const { exitCode, output } = await runToEnd("'a','b','c' | Measure-Object | ForEach-Object { $_.Count }");
    expect(exitCode).toBe(0);
    expect(output).toContain("3");
  });

  it("runs a cmdlet that is not a cmd builtin (Get-Date)", async () => {
    const { exitCode, output } = await runToEnd("Get-Date -Format yyyy");
    expect(exitCode).toBe(0);
    expect(output.trim()).toMatch(/^\d{4}$/);
  });

  it("executes inside a real PowerShell host ($PSVersionTable resolves)", async () => {
    // cmd would treat "$PSVersionTable.PSVersion.Major" as an unknown command;
    // PowerShell prints the host major version (5 for Windows PowerShell, 7 for pwsh).
    const { exitCode, output } = await runToEnd("$PSVersionTable.PSVersion.Major");
    expect(exitCode).toBe(0);
    expect(output.trim()).toMatch(/^\d+$/);
  });

  it("survives a Format-List pipeline (the exact re-wrap the agent had to do)", async () => {
    const { exitCode, output } = await runToEnd("[pscustomobject]@{ RepoRoot = 'demo' } | Format-List");
    expect(exitCode).toBe(0);
    expect(output).toMatch(/RepoRoot/);
    expect(output).toMatch(/demo/);
  });

  it("resolves the host shell to a PowerShell, never cmd.exe, on this box", () => {
    const shell = resolveTerminalShell("win32", (name) => {
      try {
        const out = execFileSync("where", [name], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
        const first = out.split(/\r?\n/)[0]?.trim();
        return first && existsSync(first) ? first : undefined;
      } catch {
        return undefined;
      }
    });
    // pwsh may be absent; either PowerShell is acceptable, cmd (true) is not.
    expect(shell).not.toBe(true);
    expect(String(shell).toLowerCase()).toMatch(/pwsh\.exe$|powershell\.exe$/);
  });
});

describe("resolveExitCode", () => {
  it("passes through a real exit code, including 0", () => {
    expect(resolveExitCode(0, null)).toBe(0);
    expect(resolveExitCode(7, null)).toBe(7);
  });

  it("maps a signal kill to 128 + signum (SIGTERM -> 143), never 0", () => {
    expect(resolveExitCode(null, "SIGTERM")).toBe(128 + os.constants.signals.SIGTERM);
    expect(resolveExitCode(null, "SIGTERM")).toBe(143);
    expect(resolveExitCode(null, "SIGKILL")).toBe(128 + os.constants.signals.SIGKILL);
    expect(resolveExitCode(null, "SIGTERM")).not.toBe(0);
  });
});

describe("buildKillPlan", () => {
  it("uses taskkill with /T /F (tree + force) on Windows", () => {
    const plan = buildKillPlan(1234, "win32");
    expect(plan.kind).toBe("taskkill");
    if (plan.kind === "taskkill") {
      expect(plan.file).toBe("taskkill");
      expect(plan.args).toContain("/T");
      expect(plan.args).toContain("/F");
      expect(plan.args).toContain("1234");
    }
  });

  it("uses a SIGTERM signal on POSIX", () => {
    const plan = buildKillPlan(1234, "linux");
    expect(plan).toEqual({ kind: "signal", signal: "SIGTERM" });
  });
});

describe("resolveTerminalShell", () => {
  // Fake PATH resolver: returns a path only for the listed names.
  const has = (map: Record<string, string>) => (name: string) => map[name];
  const PWSH = "C:\\Program Files\\PowerShell\\7\\pwsh.exe";
  const POWERSHELL = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";

  it("returns true (/bin/sh) on POSIX without probing PATH", () => {
    let probed = false;
    const shell = resolveTerminalShell("linux", () => {
      probed = true;
      return undefined;
    });
    expect(shell).toBe(true);
    expect(probed).toBe(false); // never shell out to `where` off Windows
  });

  it("returns true on darwin", () => {
    expect(resolveTerminalShell("darwin", () => PWSH)).toBe(true);
  });

  it("prefers pwsh.exe (PowerShell 7) on Windows when available", () => {
    expect(resolveTerminalShell("win32", has({ pwsh: PWSH, powershell: POWERSHELL }))).toBe(PWSH);
  });

  it("falls back to powershell.exe (5.1) when pwsh is absent", () => {
    expect(resolveTerminalShell("win32", has({ powershell: POWERSHELL }))).toBe(POWERSHELL);
  });

  it("falls back to cmd.exe (shell:true) when neither PowerShell is on PATH", () => {
    expect(resolveTerminalShell("win32", () => undefined)).toBe(true);
  });

  it("probes pwsh before powershell", () => {
    const order: string[] = [];
    resolveTerminalShell("win32", (name) => {
      order.push(name);
      return undefined;
    });
    expect(order).toEqual(["pwsh", "powershell"]);
  });

  it("pref 'cmd' forces cmd.exe (shell:true) on Windows without probing PATH", () => {
    let probed = false;
    const shell = resolveTerminalShell("win32", () => {
      probed = true;
      return PWSH;
    }, "cmd");
    expect(shell).toBe(true);
    expect(probed).toBe(false); // escape hatch short-circuits before `where`
  });

  it("pref 'cmd' is a no-op on POSIX (still /bin/sh)", () => {
    expect(resolveTerminalShell("linux", () => undefined, "cmd")).toBe(true);
  });

  it("pref 'auto' matches the default (PowerShell on Windows)", () => {
    expect(resolveTerminalShell("win32", has({ pwsh: PWSH }), "auto")).toBe(PWSH);
  });
});
