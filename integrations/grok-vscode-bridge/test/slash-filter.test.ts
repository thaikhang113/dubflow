import { describe, it, expect } from "vitest";
import {
  applySlashPick,
  filterAdvertisedCommands,
  filterCommands,
  getSlashQuery,
  HIDDEN_SLASH_COMMANDS,
  matchSlashCommand,
} from "../src/slash-filter";

describe("getSlashQuery", () => {
  it("returns null when no slash at line start", () => {
    expect(getSlashQuery("hello", 5)).toBeNull();
    expect(getSlashQuery("hello /not", 10)).toBeNull();
  });

  it("returns query when slash is at start of input", () => {
    expect(getSlashQuery("/com", 4)).toBe("com");
  });

  it("returns query when slash is at start of new line", () => {
    expect(getSlashQuery("hi\n/pla", 7)).toBe("pla");
  });

  it("ignores text after the caret", () => {
    expect(getSlashQuery("/co  more", 3)).toBe("co");
  });

  it("returns empty string for bare `/`", () => {
    expect(getSlashQuery("/", 1)).toBe("");
  });
});

describe("filterCommands", () => {
  const cmds = [
    { name: "compact", description: "Compress conversation" },
    { name: "clear", description: "" },
    { name: "context", description: "Show context" },
    { name: "yolo", description: "Toggle auto-approve" },
  ];

  it("empty query returns all", () => {
    expect(filterCommands(cmds, "")).toEqual(cmds);
  });

  it("filters by prefix", () => {
    expect(filterCommands(cmds, "co").map((c) => c.name)).toEqual([
      "compact",
      "context",
    ]);
  });

  it("is case-insensitive", () => {
    expect(filterCommands(cmds, "CO").map((c) => c.name)).toEqual([
      "compact",
      "context",
    ]);
  });

  it("returns empty when no matches", () => {
    expect(filterCommands(cmds, "zzz")).toEqual([]);
  });
});

describe("applySlashPick", () => {
  it("replaces the partial /q with /name and trailing space", () => {
    const r = applySlashPick("/com", 4, "compact");
    expect(r.text).toBe("/compact ");
    expect(r.caret).toBe(9);
  });

  it("preserves text after caret", () => {
    const r = applySlashPick("/co rest", 3, "compact");
    expect(r.text).toBe("/compact  rest");
    expect(r.caret).toBe(9);
  });

  it("works at start of new line", () => {
    const r = applySlashPick("hi\n/pla", 7, "plan");
    expect(r.text).toBe("hi\n/plan ");
    expect(r.caret).toBe(9);
  });
});

describe("filterAdvertisedCommands", () => {
  it("drops /always-approve (#31) and /context (#39) from the advertised list", () => {
    const cmds = [
      { name: "compact", description: "Compress conversation" },
      { name: "always-approve", description: "Auto-approve everything" },
      { name: "context", description: "Show context" },
      { name: "session-info", description: "Show session info" },
    ];
    expect(filterAdvertisedCommands(cmds).map((c) => c.name)).toEqual(["compact", "session-info"]);
  });

  it("leaves a list without hidden commands untouched", () => {
    const cmds = [{ name: "compact" }, { name: "session-info" }];
    expect(filterAdvertisedCommands(cmds)).toEqual(cmds);
  });

  it("HIDDEN_SLASH_COMMANDS contains always-approve and context", () => {
    expect(HIDDEN_SLASH_COMMANDS.has("always-approve")).toBe(true);
    expect(HIDDEN_SLASH_COMMANDS.has("context")).toBe(true);
  });

  it("keeps the resulting list out of the dispatch gate too", () => {
    const cmds = [{ name: "compact" }, { name: "always-approve" }];
    const names = filterAdvertisedCommands(cmds).map((c) => c.name);
    // Filtered out → matchSlashCommand won't recognize it as a command.
    expect(matchSlashCommand("/always-approve", names)).toBeNull();
    expect(matchSlashCommand("/compact", names)).toBe("compact");
  });
});

describe("matchSlashCommand", () => {
  const commands = ["compact", "context", "imagine-video", "user:code-review"];

  it("matches an advertised command at position 0, with or without args", () => {
    expect(matchSlashCommand("/compact", commands)).toBe("compact");
    expect(matchSlashCommand("/compact focus on the tests", commands)).toBe("compact");
    expect(matchSlashCommand("/imagine-video a red cube", commands)).toBe("imagine-video");
    expect(matchSlashCommand("/user:code-review src/a.ts", commands)).toBe("user:code-review");
  });

  it("matches a multi-line prompt whose first line is the command", () => {
    expect(matchSlashCommand("/compact\n\nkeep the recent work", commands)).toBe("compact");
  });

  it("rejects prose that merely starts with a slash", () => {
    // Unix paths have no token boundary: `tmp` is followed by `/`, not whitespace.
    expect(matchSlashCommand("/tmp/foo is broken", commands)).toBeNull();
    expect(matchSlashCommand("/tmp/foo", ["tmp"])).toBeNull();
    expect(matchSlashCommand("please /compact", commands)).toBeNull();
    expect(matchSlashCommand("/", commands)).toBeNull();
    expect(matchSlashCommand("/ compact", commands)).toBeNull();
  });

  it("rejects unknown commands once the CLI has advertised its list", () => {
    expect(matchSlashCommand("/notacommand do it", commands)).toBeNull();
    expect(matchSlashCommand("/compact-ish", commands)).toBeNull();
  });

  it("falls back to shape alone before available_commands arrives", () => {
    expect(matchSlashCommand("/compact", [])).toBe("compact");
    expect(matchSlashCommand("/tmp/foo is broken", [])).toBeNull();
  });
});
