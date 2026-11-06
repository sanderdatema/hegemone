import { describe, it, expect } from "vitest";
import {
  SEGMENTED_VARIANTS,
  segmentedClass,
  containerRole,
  itemAriaProps,
  willFire,
} from "./segmentedControl.js";

describe("segmentedClass", () => {
  it("maps each known variant to segmented + variant-<x>", () => {
    for (const v of SEGMENTED_VARIANTS) {
      expect(segmentedClass(v)).toBe(`segmented variant-${v}`);
    }
  });

  it("falls back to accent for unknown/empty variant", () => {
    expect(segmentedClass("nope")).toBe("segmented variant-accent");
    expect(segmentedClass(undefined)).toBe("segmented variant-accent");
  });
});

describe("containerRole", () => {
  it("is radiogroup by default and for radio mode", () => {
    expect(containerRole("radio")).toBe("radiogroup");
    expect(containerRole(undefined)).toBe("radiogroup");
  });
  it("is group for pressed (toggle-button) mode", () => {
    expect(containerRole("pressed")).toBe("group");
  });
});

describe("itemAriaProps", () => {
  it("radio mode: role radio + aria-checked reflects active, no aria-pressed", () => {
    expect(itemAriaProps("radio", true)).toEqual({
      role: "radio",
      ariaChecked: true,
      ariaPressed: undefined,
    });
    expect(itemAriaProps("radio", false).ariaChecked).toBe(false);
  });
  it("pressed mode: aria-pressed reflects active, no role/aria-checked", () => {
    expect(itemAriaProps("pressed", true)).toEqual({
      role: undefined,
      ariaChecked: undefined,
      ariaPressed: true,
    });
    expect(itemAriaProps("pressed", false).ariaPressed).toBe(false);
  });
});

describe("willFire", () => {
  it("fires when selecting a different, enabled value", () => {
    expect(willFire("a", "b", false)).toBe(true);
  });
  it("does not fire when reselecting the active value", () => {
    expect(willFire("a", "a", false)).toBe(false);
  });
  it("does not fire when disabled", () => {
    expect(willFire("a", "b", true)).toBe(false);
  });
});
