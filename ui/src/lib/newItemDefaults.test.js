import { describe, it, expect } from "vitest";
import { newItemDefaults } from "./newItemDefaults.js";

describe("newItemDefaults", () => {
  it("triage aan: belofte zichtbaar, meer opties dicht", () => {
    expect(newItemDefaults({ key: "BETON", triage_enabled: true })).toEqual({
      showTriageHint: true,
      moreOpen: false,
    });
  });
  it("triage uit: geen belofte, meer opties dicht", () => {
    expect(newItemDefaults({ key: "TODAY", triage_enabled: false })).toEqual({
      showTriageHint: false,
      moreOpen: false,
    });
  });
  it("onbekend project of ontbrekend veld telt als uit", () => {
    expect(newItemDefaults(null).showTriageHint).toBe(false);
    expect(newItemDefaults({ key: "X" }).moreOpen).toBe(false);
  });
});
