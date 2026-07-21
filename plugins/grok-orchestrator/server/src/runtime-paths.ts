import path from "node:path";

export function runtimePaths(env: NodeJS.ProcessEnv = process.env): { socketPath: string; stateRoot: string; tokenPath: string } {
  const runtimeRoot = env.XDG_RUNTIME_DIR;
  if (!runtimeRoot || !path.isAbsolute(runtimeRoot)) throw new Error("XDG_RUNTIME_DIR must be an absolute path");
  const stateBase = env.XDG_STATE_HOME ?? (env.HOME ? path.join(env.HOME, ".local", "state") : undefined);
  if (!stateBase || !path.isAbsolute(stateBase)) throw new Error("XDG_STATE_HOME or HOME must be absolute");
  const stateRoot = path.join(stateBase, "openclaw-grok-broker");
  return { socketPath: path.join(runtimeRoot, "openclaw-grok-broker.sock"), stateRoot, tokenPath: path.join(stateRoot, "auth-token") };
}
