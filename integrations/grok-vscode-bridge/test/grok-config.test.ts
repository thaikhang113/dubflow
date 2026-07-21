import { describe, it, expect } from "vitest";
import {
  configForcesAlwaysApprove,
  isAlwaysApprovePermission,
  readUiPermissionMode,
} from "../src/grok-config";

// A realistic grok config.toml, mirroring the on-disk shape.
const CONFIG = (permission: string) => `[cli]
installer = "internal"
auto_update = false
channel = "stable"

[features]
feedback = true
support_permission = true

[ui]
max_thoughts_width = 120
fork_secondary_model = "grok-build"
yolo = false
compact_mode = false
permission_mode = "${permission}"

[marketplace]
official_marketplace_auto_installed = true

[[marketplace.sources]]
name = "xAI Official"
git = "https://github.com/xai-org/plugin-marketplace.git"

[models]
default = "grok-build"
`;

describe("isAlwaysApprovePermission", () => {
  it("matches the hyphenated value grok writes", () => {
    expect(isAlwaysApprovePermission("always-approve")).toBe(true);
  });

  it("accepts the underscore variant and stray case/whitespace", () => {
    expect(isAlwaysApprovePermission("always_approve")).toBe(true);
    expect(isAlwaysApprovePermission("  Always-Approve  ")).toBe(true);
  });

  it("rejects other modes and empties", () => {
    expect(isAlwaysApprovePermission("ask")).toBe(false);
    expect(isAlwaysApprovePermission("")).toBe(false);
    expect(isAlwaysApprovePermission(undefined)).toBe(false);
  });
});

describe("readUiPermissionMode", () => {
  it("reads permission_mode from the [ui] table", () => {
    expect(readUiPermissionMode(CONFIG("always-approve"))).toBe("always-approve");
    expect(readUiPermissionMode(CONFIG("ask"))).toBe("ask");
  });

  it("returns undefined when the key is absent", () => {
    expect(readUiPermissionMode("[ui]\nyolo = false\n")).toBeUndefined();
    expect(readUiPermissionMode("")).toBeUndefined();
  });

  it("ignores a permission_mode outside the [ui] table", () => {
    const toml = `[other]\npermission_mode = "always-approve"\n\n[ui]\nyolo = false\n`;
    expect(readUiPermissionMode(toml)).toBeUndefined();
  });

  it("does not misread the array table [[marketplace.sources]] as [ui]", () => {
    // The array-table line must not flip the in-ui flag on.
    const toml = `[[marketplace.sources]]\npermission_mode = "always-approve"\n`;
    expect(readUiPermissionMode(toml)).toBeUndefined();
  });

  it("strips inline comments and single quotes", () => {
    expect(readUiPermissionMode(`[ui]\npermission_mode = 'ask' # default\n`)).toBe("ask");
  });

  it("tolerates CRLF line endings", () => {
    expect(readUiPermissionMode(`[ui]\r\npermission_mode = "always-approve"\r\n`)).toBe(
      "always-approve",
    );
  });
});

describe("configForcesAlwaysApprove", () => {
  it("true when global config sets always-approve", () => {
    expect(configForcesAlwaysApprove({ global: CONFIG("always-approve") })).toBe(true);
  });

  it("false when global config is the default ask", () => {
    expect(configForcesAlwaysApprove({ global: CONFIG("ask") })).toBe(false);
  });

  it("false when neither config is present", () => {
    expect(configForcesAlwaysApprove({})).toBe(false);
    expect(configForcesAlwaysApprove({ project: undefined, global: undefined })).toBe(false);
  });

  it("project config overrides global (project ask beats global always-approve)", () => {
    expect(
      configForcesAlwaysApprove({ project: CONFIG("ask"), global: CONFIG("always-approve") }),
    ).toBe(false);
  });

  it("project config overrides global (project always-approve beats global ask)", () => {
    expect(
      configForcesAlwaysApprove({ project: CONFIG("always-approve"), global: CONFIG("ask") }),
    ).toBe(true);
  });

  it("falls back to global when project has no permission_mode", () => {
    const projectWithoutKey = `[ui]\nyolo = false\n`;
    expect(
      configForcesAlwaysApprove({ project: projectWithoutKey, global: CONFIG("always-approve") }),
    ).toBe(true);
  });
});
