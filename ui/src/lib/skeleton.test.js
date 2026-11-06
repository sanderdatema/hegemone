import { describe, it, expect } from "vitest";
import { resolveSkeletonCount, lineWidths, skeletonRows } from "./skeleton.js";

describe("resolveSkeletonCount", () => {
  it("valt terug op de preset-default zonder telling", () => {
    expect(resolveSkeletonCount("rows", undefined)).toBe(4);
    expect(resolveSkeletonCount("card", undefined)).toBe(3);
    expect(resolveSkeletonCount("lines", undefined)).toBe(3);
    expect(resolveSkeletonCount("title", undefined)).toBe(1);
  });

  it("klemt tegen ondergrens (minimaal 1)", () => {
    expect(resolveSkeletonCount("lines", 0)).toBe(1);
    expect(resolveSkeletonCount("lines", -5)).toBe(1);
  });

  it("klemt tegen bovengrens (maximaal 20)", () => {
    expect(resolveSkeletonCount("rows", 500)).toBe(20);
  });

  it("rondt af en accepteert een geldige telling", () => {
    expect(resolveSkeletonCount("rows", 7.9)).toBe(7);
  });

  it("valt terug op 'lines'-default voor een onbekende preset", () => {
    expect(resolveSkeletonCount("onzin", undefined)).toBe(3);
  });
});

describe("lineWidths", () => {
  it("levert de cyclische breedtes voor het gevraagde aantal", () => {
    expect(lineWidths(3)).toEqual(["100%", "100%", "65%"]);
  });

  it("herhaalt de cyclus bij meer regels dan de cyclus lang is", () => {
    expect(lineWidths(4)).toEqual(["100%", "100%", "65%", "100%"]);
  });

  it("default naar 3 regels zonder telling", () => {
    expect(lineWidths(undefined)).toHaveLength(3);
  });
});

describe("skeletonRows", () => {
  it("title levert precies één head-rij, ongeacht count", () => {
    expect(skeletonRows("title", 5)).toEqual([{ kind: "head" }]);
  });

  it("rows levert N row-descriptors", () => {
    expect(skeletonRows("rows", 2)).toEqual([{ kind: "row" }, { kind: "row" }]);
  });

  it("card levert N card-descriptors", () => {
    expect(skeletonRows("card", 2)).toEqual([{ kind: "card" }, { kind: "card" }]);
  });

  it("lines levert line-descriptors met breedte", () => {
    expect(skeletonRows("lines", 2)).toEqual([
      { kind: "line", width: "100%" },
      { kind: "line", width: "100%" },
    ]);
  });

  it("onbekende preset gedraagt zich als 'lines'", () => {
    expect(skeletonRows("wut", 1)).toEqual([{ kind: "line", width: "100%" }]);
  });
});
