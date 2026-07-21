import { describe, it, expect } from "vitest";
import {
  moveViewContainerFor,
  PANEL_CONTAINER_ID,
  PRIMARY_CONTAINER_ID,
  SECONDARY_CONTAINER_ID,
} from "../src/view-move";

describe("gear-menu Move view destinations", () => {
  it("maps each destination to its extension-owned container", () => {
    expect(moveViewContainerFor("panel")).toBe(PANEL_CONTAINER_ID);
    expect(moveViewContainerFor("sidebar")).toBe(PRIMARY_CONTAINER_ID);
    expect(moveViewContainerFor("auxiliarybar")).toBe(SECONDARY_CONTAINER_ID);
  });

  it("returns null for anything else — callers fall back to the built-in picker", () => {
    expect(moveViewContainerFor(undefined)).toBeNull();
    expect(moveViewContainerFor("")).toBeNull();
    expect(moveViewContainerFor("editor")).toBeNull();
    expect(moveViewContainerFor(42)).toBeNull();
  });

  it("container ids carry the workbench prefix package.json contributions get", () => {
    for (const id of [PANEL_CONTAINER_ID, PRIMARY_CONTAINER_ID, SECONDARY_CONTAINER_ID]) {
      expect(id.startsWith("workbench.view.extension.")).toBe(true);
    }
  });
});
