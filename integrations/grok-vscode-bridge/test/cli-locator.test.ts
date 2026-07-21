import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  locateGrokCli,
  extensionWasUpgraded,
  parseGrokVersion,
  isStdioBrokenGrokVersion,
  compareVersionTuple,
  grokUpdatePolicy,
  shouldReactivelyDowngrade,
  isLockedBinaryError,
  GROK_STDIO_DOWNGRADE_TARGET,
} from "../src/cli-locator";

const IS_WIN = process.platform === "win32";
const PATH_SEP = IS_WIN ? ";" : ":";
const FAKE_BIN_NAME = IS_WIN ? "grok.cmd" : "grok";

describe("locateGrokCli", () => {
  let tmpDir: string;
  let fakeBin: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "grok-locate-"));
    fakeBin = path.join(tmpDir, FAKE_BIN_NAME);
    if (IS_WIN) {
      fs.writeFileSync(fakeBin, "@echo mock\r\n");
    } else {
      fs.writeFileSync(fakeBin, "#!/bin/sh\necho mock\n");
      fs.chmodSync(fakeBin, 0o755);
    }
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("returns the configured path when it exists", () => {
    expect(locateGrokCli(fakeBin)).toBe(fakeBin);
  });

  it("returns undefined when configured path is missing", () => {
    expect(locateGrokCli(path.join(tmpDir, "missing"))).toBeUndefined();
  });

  it("falls back to PATH when no config and no ~/.grok/bin/grok", () => {
    const originalPath = process.env.PATH;
    process.env.PATH = tmpDir + PATH_SEP + (originalPath ?? "");
    try {
      const result = locateGrokCli("");
      // Either ~/.grok/bin/grok wins (if installed) or PATH lookup finds the fake.
      const found = result?.toLowerCase();
      expect(found === fakeBin.toLowerCase() || !!found?.includes("grok")).toBe(true);
    } finally {
      process.env.PATH = originalPath;
    }
  });

  it("returns undefined when nothing found", () => {
    const originalPath = process.env.PATH;
    const originalHome = process.env.HOME;
    const originalUserProfile = process.env.USERPROFILE;
    process.env.PATH = "";
    process.env.HOME = tmpDir;
    process.env.USERPROFILE = tmpDir;
    try {
      expect(locateGrokCli("")).toBeUndefined();
    } finally {
      process.env.PATH = originalPath;
      if (originalHome) process.env.HOME = originalHome;
      if (originalUserProfile) process.env.USERPROFILE = originalUserProfile;
    }
  });
});

describe("extensionWasUpgraded", () => {
  it("is false on a fresh install (no prior version recorded)", () => {
    expect(extensionWasUpgraded(undefined, "1.4.0")).toBe(false);
    expect(extensionWasUpgraded("", "1.4.0")).toBe(false);
  });

  it("is false when the version is unchanged (plain restart)", () => {
    expect(extensionWasUpgraded("1.4.0", "1.4.0")).toBe(false);
  });

  it("is true when the extension version changed (an upgrade)", () => {
    expect(extensionWasUpgraded("1.3.2", "1.4.0")).toBe(true);
  });

  it("is true even on a downgrade (any version mismatch re-syncs the CLI)", () => {
    expect(extensionWasUpgraded("1.4.0", "1.3.2")).toBe(true);
  });

  it("is false defensively when the current version is empty", () => {
    expect(extensionWasUpgraded("1.4.0", "")).toBe(false);
  });
});

describe("parseGrokVersion", () => {
  it("parses the real --version banner", () => {
    expect(parseGrokVersion("grok 0.2.64 (9a9ac25b10) [stable]")).toEqual([0, 2, 64]);
  });

  it("parses a bare version string", () => {
    expect(parseGrokVersion("0.2.60")).toEqual([0, 2, 60]);
  });

  it("parses double-digit and larger components", () => {
    expect(parseGrokVersion("grok 1.10.205 (abc) [alpha]")).toEqual([1, 10, 205]);
  });

  it("returns undefined when no X.Y.Z is present", () => {
    expect(parseGrokVersion("grok (dev build)")).toBeUndefined();
    expect(parseGrokVersion("")).toBeUndefined();
    expect(parseGrokVersion(undefined as unknown as string)).toBeUndefined();
  });
});

describe("isStdioBrokenGrokVersion (issue #22)", () => {
  it("flags the bounded broken range 0.2.61–0.2.70 on Windows", () => {
    // 0.2.61–0.2.64 hung at `initialize`; 0.2.67/0.2.69/0.2.70 at `session/new`. Fixed in 0.2.71.
    for (const p of ["0.2.61", "0.2.64", "0.2.67", "0.2.69", "0.2.70"]) {
      expect(isStdioBrokenGrokVersion(`grok ${p} (x) [stable]`, "win32")).toBe(true);
    }
  });

  it("does not flag the supported 0.2.71+ or anything 0.2.60 and older (the fix is above the range)", () => {
    for (const p of ["0.2.71", "0.2.72", "0.3.0", "1.0.0", "0.2.60", "0.2.59", "0.1.211"]) {
      expect(isStdioBrokenGrokVersion(`grok ${p} (x) [stable]`, "win32")).toBe(false);
    }
    expect(GROK_STDIO_DOWNGRADE_TARGET).toBe("0.2.72");
  });

  it("never flags non-Windows platforms (the bug is Windows-only)", () => {
    expect(isStdioBrokenGrokVersion("grok 0.2.64 (x) [stable]", "linux")).toBe(false);
    expect(isStdioBrokenGrokVersion("grok 0.2.64 (x) [stable]", "darwin")).toBe(false);
  });

  it("is false defensively when the version is unparseable", () => {
    expect(isStdioBrokenGrokVersion("grok (dev)", "win32")).toBe(false);
    expect(isStdioBrokenGrokVersion("", "win32")).toBe(false);
  });
});

describe("compareVersionTuple", () => {
  it("orders by major, then minor, then patch", () => {
    expect(compareVersionTuple([0, 2, 60], [0, 2, 61])).toBeLessThan(0);
    expect(compareVersionTuple([0, 2, 64], [0, 2, 60])).toBeGreaterThan(0);
    expect(compareVersionTuple([0, 2, 60], [0, 2, 60])).toBe(0);
    expect(compareVersionTuple([1, 0, 0], [0, 9, 9])).toBeGreaterThan(0);
    expect(compareVersionTuple([0, 3, 0], [0, 2, 99])).toBeGreaterThan(0);
  });
});

describe("grokUpdatePolicy (issue #22 update pause lifted in 0.2.71)", () => {
  it("allows updates on every platform now that the regression is fixed (no block, no pin)", () => {
    for (const plat of ["win32", "linux", "darwin"] as const) {
      for (const v of ["0.2.60", "0.2.67", "0.2.70", "0.2.71", "0.2.72"]) {
        const p = grokUpdatePolicy(`grok ${v} (x) [stable]`, plat);
        expect(p.allow).toBe(true);
        expect(p.target).toBeUndefined();
        expect(p.note).toBeUndefined();
      }
    }
  });

  it("allows when the version is unparseable too", () => {
    const p = grokUpdatePolicy("grok (dev build)", "win32");
    expect(p.allow).toBe(true);
    expect(p.target).toBeUndefined();
  });
});

describe("shouldReactivelyDowngrade (issue #22 — backstop for a future build above 0.2.72)", () => {
  it("downgrades any Windows build ABOVE the supported 0.2.72", () => {
    for (const v of ["0.2.73", "0.2.99", "0.3.0", "1.0.0"]) {
      expect(shouldReactivelyDowngrade(`grok ${v} (x) [stable]`, "win32")).toBe(true);
    }
  });

  it("never downgrades 0.2.72 or below — the loop guard once the pin lands", () => {
    // The known broken range (0.2.61–0.2.70) is handled proactively; 0.2.72 is the
    // floor (0.2.71 was the fix, now superseded on stable), so reactive must not fire
    // on it or anything older.
    for (const v of ["0.2.72", "0.2.71", "0.2.70", "0.2.60", "0.1.211"]) {
      expect(shouldReactivelyDowngrade(`grok ${v} (x) [stable]`, "win32")).toBe(false);
    }
  });

  it("is Windows-only", () => {
    for (const plat of ["linux", "darwin"] as const) {
      expect(shouldReactivelyDowngrade("grok 0.2.99 (x) [stable]", plat)).toBe(false);
    }
  });

  it("leaves an unparseable version alone (no spurious downgrade)", () => {
    expect(shouldReactivelyDowngrade("grok (dev build)", "win32")).toBe(false);
    expect(shouldReactivelyDowngrade("", "win32")).toBe(false);
  });
});

describe("isLockedBinaryError (CLI-update lock retry)", () => {
  it("detects grok's real locked-executable failure (worth a retry)", () => {
    const real =
      "Command failed: C:\\Users\\Dell\\.grok\\bin\\grok.exe update\n" +
      "Error: Auto-update failed: cannot rename locked executable " +
      "C:\\Users\\Dell\\.grok\\bin\\grok.exe: Access is denied. (os error 5)";
    expect(isLockedBinaryError(real)).toBe(true);
  });

  it("matches each lock signature independently and is case-insensitive", () => {
    expect(isLockedBinaryError("cannot rename LOCKED EXECUTABLE")).toBe(true);
    expect(isLockedBinaryError("Access is Denied.")).toBe(true);
    expect(isLockedBinaryError("failed (os error 5)")).toBe(true);
  });

  it("does not match unrelated update failures (those are real, no retry)", () => {
    expect(isLockedBinaryError("network timeout while downloading grok")).toBe(false);
    expect(isLockedBinaryError("ENOENT: grok not found")).toBe(false);
    expect(isLockedBinaryError("")).toBe(false);
  });
});
