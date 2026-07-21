import path from "node:path";

export type PermissionDecision = "allow" | "approval" | "deny";

export type PermissionRequest =
  | { type: "read"; path: string }
  | { type: "write"; path: string }
  | { type: "command"; argv: string[]; network?: boolean };

export interface PermissionResult {
  decision: PermissionDecision;
  reason: string;
}

export interface PermissionPolicyOptions {
  worktreeRoot: string;
  allowedCommands: string[][];
}

const PROTECTED_SEGMENTS = new Set([
  ".env",
  ".git",
  ".ssh",
  "cookies",
  "credentials",
  "docker.sock",
  "id_rsa",
  "id_ed25519",
]);

const DENIED_COMMANDS = new Set(["bash", "sh", "zsh", "sudo", "su", "docker", "systemctl", "service"]);

export class PermissionPolicy {
  #root: string;
  #allowedCommands: string[][];

  constructor(options: PermissionPolicyOptions) {
    this.#root = path.resolve(options.worktreeRoot);
    this.#allowedCommands = options.allowedCommands.map((argv) => [...argv]);
  }

  classify(request: PermissionRequest): PermissionResult {
    if (request.type !== "command") {
      const candidate = path.isAbsolute(request.path) ? path.resolve(request.path) : path.resolve(this.#root, request.path);
      const relative = path.relative(this.#root, candidate);
      if (relative.startsWith("..") || path.isAbsolute(relative)) {
        return { decision: "deny", reason: "outside_worktree" };
      }
      const segments = relative.split(path.sep).map((segment) => segment.toLowerCase());
      if (segments.some((segment) => PROTECTED_SEGMENTS.has(segment) || /(?:token|secret|cookie|credential)/i.test(segment))) {
        return { decision: "deny", reason: "protected_path" };
      }
      return { decision: "allow", reason: "inside_worktree" };
    }

    if (request.argv.length === 0 || request.argv.some((arg) => /[\0\r\n]/.test(arg))) {
      return { decision: "deny", reason: "invalid_argv" };
    }
    const [command, action] = request.argv;
    if (!command || DENIED_COMMANDS.has(command)) return { decision: "deny", reason: "denied_command" };
    if (command === "git" && (action === "commit" || action === "push" || action === "reset" || action === "clean")) {
      return { decision: "deny", reason: "denied_git_action" };
    }
    if (request.network) return { decision: "approval", reason: "network_requested" };
    if (command === "curl" || command === "wget" || (command === "npm" && (action === "install" || action === "ci"))) {
      return { decision: "approval", reason: "network_or_install" };
    }
    const allowed = this.#allowedCommands.some(
      (entry) => entry.length === request.argv.length && entry.every((arg, index) => request.argv[index] === arg),
    );
    return allowed
      ? { decision: "allow", reason: "session_allowlist" }
      : { decision: "approval", reason: "command_not_allowlisted" };
  }
}
