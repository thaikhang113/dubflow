// Privacy-first, cookieless usage telemetry via Aptabase. We send exactly ONE
// event — `session_start`, on the first real user message of a session (never
// the primer / empty sessions) — carrying only an anonymous install id + the
// chosen mode/model/effort. No content (prompts, code, paths) is ever sent, and
// the IP is used by Aptabase only to derive country, then discarded. The whole
// thing is gated on VS Code's global telemetry setting + `grok.telemetry.enabled`.
//
// This module is pure + fire-and-forget: the builders have no I/O (unit-tested),
// and `postEvent` never throws or blocks the caller.
import * as https from "node:https";

// Aptabase ingestion app keys (region-prefixed write-only keys meant to ship in
// the client, not secrets). Two projects keep test traffic out of the real
// analytics: the **extension always reports to PROD** (dev host, local install,
// and the published Marketplace build alike); the **DEV** key is used only by the
// `telemetry:probe` script / tests, so probe traffic lands in a separate project.
export const APTABASE_APP_KEY_PROD = "A-EU-2294571902";
export const APTABASE_APP_KEY_DEV = "A-EU-5074036690";

/** The label Aptabase shows as the SDK that sent the event. */
export const TELEMETRY_SDK = "grok-vscode-phuryn";

export interface SystemProps {
  appVersion: string;
  osName: string;
  osVersion: string;
  locale: string;
  isDebug: boolean;
}

export interface SessionStartProps {
  /** Anonymous, per-install GUID — a property like model/effort, not an identity. */
  installId: string;
  mode: string;
  model: string;
  effort: string;
}

export interface AptabaseEvent {
  timestamp: string;
  sessionId: string;
  eventName: string;
  systemProps: Record<string, unknown>;
  props: Record<string, unknown>;
}

/**
 * Base URL for the Aptabase ingest API, derived from the app key's region prefix
 * (`A-EU-…` / `A-US-…`). Returns undefined for `A-DEV-…` / malformed keys (self-
 * hosted needs an explicit host we don't support here), which disables sending.
 */
export function aptabaseHost(appKey: string): string | undefined {
  const region = appKey.split("-")[1];
  if (region === "EU") return "https://eu.aptabase.com";
  if (region === "US") return "https://us.aptabase.com";
  return undefined;
}

/** Map a Node `process.platform` to a human OS name for `systemProps.osName`. */
export function osNameFromPlatform(platform: string): string {
  if (platform === "darwin") return "macOS";
  if (platform === "win32") return "Windows";
  if (platform === "linux") return "Linux";
  return platform;
}

/** Telemetry sends only when BOTH the VS Code global setting and our own opt-out
 *  allow it. Default-on, but the global setting always wins. */
export function shouldSendTelemetry(globalEnabled: boolean, settingEnabled: boolean): boolean {
  return globalEnabled && settingEnabled;
}

/** Build the Aptabase `session_start` event body. Pure — no clock, no network;
 *  the caller supplies `sessionId` + `timestamp` so it's deterministic in tests. */
export function buildSessionStartEvent(
  props: SessionStartProps,
  sys: SystemProps,
  sessionId: string,
  timestamp: string,
): AptabaseEvent {
  return {
    timestamp,
    sessionId,
    eventName: "session_start",
    systemProps: {
      isDebug: sys.isDebug,
      locale: sys.locale,
      osName: sys.osName,
      osVersion: sys.osVersion,
      appVersion: sys.appVersion,
      sdkVersion: `${TELEMETRY_SDK}@${sys.appVersion}`,
    },
    props: {
      installId: props.installId,
      mode: props.mode,
      model: props.model,
      effort: props.effort,
    },
  };
}

/**
 * Fire-and-forget POST of an event to Aptabase. Never throws, never blocks — any
 * failure (offline, DNS, 4xx) is swallowed (optionally logged). A no-op if the
 * app key has no resolvable region host.
 */
export function postEvent(appKey: string, event: AptabaseEvent, log?: (msg: string) => void): void {
  const host = aptabaseHost(appKey);
  if (!host) return;
  try {
    const body = JSON.stringify(event);
    const url = new URL(`${host}/api/v0/event`);
    const req = https.request(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "App-Key": appKey,
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => res.resume(), // drain so the socket can close
    );
    req.on("error", (e) => log?.(`[telemetry] ${e.message}`));
    req.write(body);
    req.end();
  } catch (e) {
    log?.(`[telemetry] ${(e as Error).message}`);
  }
}
