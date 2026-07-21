import { lstat, realpath } from "node:fs/promises";
import path from "node:path";

const PROTECTED = /^(?:\.env(?:\..*)?|\.git|\.ssh|cookies?|credentials?|docker\.sock|id_(?:rsa|ed25519)|.*(?:token|secret|api[_-]?key).*)$/i;

export class PathGuard {
  #root: string;

  private constructor(root: string) {
    this.#root = root;
  }

  static async create(root: string): Promise<PathGuard> {
    return new PathGuard(await realpath(root));
  }

  async assertAllowed(candidate: string, operation: "read" | "write"): Promise<string> {
    const absolute = path.resolve(candidate);
    const lexicalRelative = path.relative(this.#root, absolute);
    if (lexicalRelative.startsWith("..") || path.isAbsolute(lexicalRelative)) throw new Error("path outside worktree");
    if (lexicalRelative.split(path.sep).some((segment) => PROTECTED.test(segment))) throw new Error("protected path");

    let resolved: string;
    try {
      const info = await lstat(absolute);
      if (info.isSymbolicLink()) throw new Error("symlink target denied");
      resolved = await realpath(absolute);
    } catch (error) {
      if (operation === "read") throw error;
      const parent = await realpath(path.dirname(absolute));
      resolved = path.join(parent, path.basename(absolute));
    }
    const realRelative = path.relative(this.#root, resolved);
    if (realRelative.startsWith("..") || path.isAbsolute(realRelative)) throw new Error("symlink escape denied");
    return resolved;
  }
}
