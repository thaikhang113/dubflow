import { describe, it, expect } from "vitest";
import {
  aptabaseHost,
  osNameFromPlatform,
  shouldSendTelemetry,
  buildSessionStartEvent,
  postEvent,
  APTABASE_APP_KEY_PROD,
  APTABASE_APP_KEY_DEV,
} from "../src/telemetry";

describe("aptabaseHost — region from app key", () => {
  it("resolves EU and US keys to their ingest hosts", () => {
    expect(aptabaseHost("A-EU-5074036690")).toBe("https://eu.aptabase.com");
    expect(aptabaseHost("A-US-1234567890")).toBe("https://us.aptabase.com");
  });
  it("returns undefined (sending disabled) for self-hosted or malformed keys", () => {
    expect(aptabaseHost("A-DEV-0000000000")).toBeUndefined();
    expect(aptabaseHost("nonsense")).toBeUndefined();
  });
});

describe("postEvent never throws (telemetry can't impact the user)", () => {
  it("swallows a build/serialize failure instead of throwing", () => {
    // A circular event fails JSON.stringify *before* any network call, so this
    // exercises the try/catch with zero network — proving a malformed event can
    // never bubble into the caller's turn.
    const circular: any = { eventName: "session_start" };
    circular.self = circular;
    expect(() => postEvent(APTABASE_APP_KEY_PROD, circular)).not.toThrow();
  });
  it("is a no-op for an app key with no resolvable region (no network, no throw)", () => {
    const ev = buildSessionStartEvent(
      { installId: "i", mode: "agent", model: "m", effort: "" },
      { appVersion: "1", osName: "macOS", osVersion: "1", locale: "en", isDebug: true },
      "s",
      "2026-06-29T00:00:00.000Z",
    );
    expect(() => postEvent("A-DEV-0000000000", ev)).not.toThrow();
  });
});

describe("prod vs dev app keys", () => {
  it("are distinct EU projects (so probe traffic can't land in prod)", () => {
    expect(APTABASE_APP_KEY_PROD).not.toBe(APTABASE_APP_KEY_DEV);
    expect(aptabaseHost(APTABASE_APP_KEY_PROD)).toBe("https://eu.aptabase.com");
    expect(aptabaseHost(APTABASE_APP_KEY_DEV)).toBe("https://eu.aptabase.com");
  });
});

describe("osNameFromPlatform", () => {
  it("maps Node platforms to human OS names, passing through the unknown", () => {
    expect(osNameFromPlatform("darwin")).toBe("macOS");
    expect(osNameFromPlatform("win32")).toBe("Windows");
    expect(osNameFromPlatform("linux")).toBe("Linux");
    expect(osNameFromPlatform("freebsd")).toBe("freebsd");
  });
});

describe("shouldSendTelemetry — both gates must allow", () => {
  it("only sends when the global setting AND our own opt-in are both on", () => {
    expect(shouldSendTelemetry(true, true)).toBe(true);
    expect(shouldSendTelemetry(false, true)).toBe(false); // VS Code global off wins
    expect(shouldSendTelemetry(true, false)).toBe(false); // our opt-out
    expect(shouldSendTelemetry(false, false)).toBe(false);
  });
});

describe("buildSessionStartEvent", () => {
  const sys = {
    appVersion: "1.4.24",
    osName: "macOS",
    osVersion: "23.6.0",
    locale: "en",
    isDebug: false,
  };
  const props = { installId: "abc-123", mode: "yolo", model: "grok-build", effort: "high" };
  const ev = buildSessionStartEvent(props, sys, "sess-1", "2026-06-29T00:00:00.000Z");

  it("emits a single session_start with the supplied id + timestamp", () => {
    expect(ev.eventName).toBe("session_start");
    expect(ev.sessionId).toBe("sess-1");
    expect(ev.timestamp).toBe("2026-06-29T00:00:00.000Z");
  });

  it("carries the install id + mode/model/effort as props (no content)", () => {
    expect(ev.props).toEqual({
      installId: "abc-123",
      mode: "yolo",
      model: "grok-build",
      effort: "high",
    });
  });

  it("reports system props incl. a versioned sdk label", () => {
    expect(ev.systemProps.osName).toBe("macOS");
    expect(ev.systemProps.appVersion).toBe("1.4.24");
    expect(ev.systemProps.sdkVersion).toBe("grok-vscode-phuryn@1.4.24");
    expect(ev.systemProps.isDebug).toBe(false);
  });
});
