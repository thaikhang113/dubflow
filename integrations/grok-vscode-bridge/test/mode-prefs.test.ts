import { describe, it, expect } from "vitest";
import { modeToRemember, startsInYolo } from "../src/mode-prefs";

describe("remembered mode preference (#25)", () => {
  it("remembers a switch to Agent or Auto accept, but never Plan", () => {
    expect(modeToRemember("agent")).toBe("agent");
    expect(modeToRemember("yolo")).toBe("yolo");
    // Plan is a transient per-task choice — leave the remembered preference alone.
    expect(modeToRemember("plan")).toBeNull();
  });

  it("starts a NEW session in Auto accept only when that's the remembered mode", () => {
    expect(startsInYolo("yolo", false)).toBe(true);
    expect(startsInYolo("agent", false)).toBe(false);
    expect(startsInYolo("", false)).toBe(false); // unset = Agent
    expect(startsInYolo(undefined, false)).toBe(false);
  });

  it("never pre-applies the remembered mode on a resume (those are verdict-driven)", () => {
    expect(startsInYolo("yolo", true)).toBe(false);
    expect(startsInYolo("agent", true)).toBe(false);
  });
});
