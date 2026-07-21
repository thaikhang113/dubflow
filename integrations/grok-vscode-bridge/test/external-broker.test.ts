import { describe, expect, it } from "vitest";
import * as path from "node:path";
import { ExternalBrokerClient, resolveBrokerRuntimeDir } from "../src/external-broker";

describe("resolveBrokerRuntimeDir", () => {
  it("uses an absolute XDG_RUNTIME_DIR when available", () => {
    expect(resolveBrokerRuntimeDir({ XDG_RUNTIME_DIR: "/tmp/runtime" }, "linux", 1000)).toBe("/tmp/runtime");
  });

  it("falls back to the Linux per-user runtime directory", () => {
    expect(resolveBrokerRuntimeDir({}, "linux", 1000)).toBe("/run/user/1000");
  });

  it("rejects a relative configured runtime directory", () => {
    expect(() => resolveBrokerRuntimeDir({ XDG_RUNTIME_DIR: "relative" }, "linux", 1000)).toThrow(
      "XDG_RUNTIME_DIR is unavailable",
    );
  });

  it("fails when neither XDG nor a Linux uid fallback is available", () => {
    expect(() => resolveBrokerRuntimeDir({}, "darwin", undefined)).toThrow("XDG_RUNTIME_DIR is unavailable");
  });
});

describe("ExternalBrokerClient", () => {
  it("builds broker paths when VS Code omits XDG_RUNTIME_DIR on Linux", () => {
    const client = new ExternalBrokerClient({ HOME: "/home/tester" }, "linux", 1000);
    expect(client.socketPath).toBe(path.join("/run/user/1000", "openclaw-grok-broker.sock"));
    expect(client.tokenPath).toBe(path.join("/home/tester", ".local", "state", "openclaw-grok-broker", "auth-token"));
  });
});
