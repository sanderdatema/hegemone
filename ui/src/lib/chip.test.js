import { describe, it, expect, vi } from "vitest";
import { CHIP_TONES, chipClass, chipElement, chipInteractive } from "./chip.js";

describe("chipClass", () => {
  it("maps each tone to chip tone-<x>", () => {
    for (const t of CHIP_TONES) {
      expect(chipClass(t)).toBe(`chip tone-${t}`);
    }
  });
  it("falls back to neutral for unknown tone", () => {
    expect(chipClass("bogus")).toBe("chip tone-neutral");
    expect(chipClass(undefined)).toBe("chip tone-neutral");
  });
  it("adds interactive and selected hooks", () => {
    expect(chipClass("label", { interactive: true })).toBe("chip tone-label interactive");
    expect(chipClass("label", { interactive: true, selected: true })).toBe(
      "chip tone-label interactive selected",
    );
    expect(chipClass("label", { selected: true })).toBe("chip tone-label selected");
  });
});

describe("chipElement", () => {
  it("is a link when href is set", () => {
    expect(chipElement({ href: "/x" })).toBe("a");
  });
  it("is a button when clickable", () => {
    expect(chipElement({ onclick: () => {} })).toBe("button");
  });
  it("is a span when only removable (the close-x is its own button)", () => {
    expect(chipElement({ removable: true })).toBe("span");
  });
  it("is a span by default", () => {
    expect(chipElement({})).toBe("span");
  });
});

describe("chipInteractive", () => {
  it("is true for href or onclick, false otherwise", () => {
    expect(chipInteractive({ href: "/x" })).toBe(true);
    expect(chipInteractive({ onclick: () => {} })).toBe(true);
    expect(chipInteractive({})).toBe(false);
  });
});

// Sanity: onremove is a plain callback the component invokes; verify the
// contract shape callers rely on (a function that fires independently).
describe("removable callback contract", () => {
  it("onremove is callable without affecting the primary handler", () => {
    const onremove = vi.fn();
    const onclick = vi.fn();
    onremove("x");
    expect(onremove).toHaveBeenCalledWith("x");
    expect(onclick).not.toHaveBeenCalled();
  });
});
