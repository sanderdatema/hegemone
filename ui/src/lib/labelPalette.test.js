import { describe, it, expect } from "vitest";
import {
  setLabelPalette,
  setLabelLoader,
  labelHueOf,
  ensureProjectLabels,
  projectKeyOfRef,
} from "./labelPalette.svelte.js";
import { labelHue } from "./avatar.js";

const L = (...names) => names.map((name) => ({ name, color: null }));

describe("labelPalette per project", () => {
  it("geeft hetzelfde label in twee projecten elk zijn eigen tint", async () => {
    setLabelPalette(L("bug", "feature"), "BETON");
    setLabelLoader(async (key) => (key === "BRAND" ? L("a", "bug") : []));
    await ensureProjectLabels("BRAND");
    expect(labelHueOf("bug", "BETON")).not.toBe(labelHueOf("bug", "BRAND"));
    expect(labelHueOf("bug")).toBe(labelHueOf("bug", "BETON"));
  });

  it("valt terug op de naam-hash zonder register en laadt lui één keer", async () => {
    setLabelPalette(L("bug"), "BETON");
    let calls = 0;
    setLabelLoader(async () => {
      calls++;
      return L("a", "bug");
    });
    expect(labelHueOf("bug", "TOR")).toBe(labelHue("bug"));
    labelHueOf("bug", "TOR");
    await ensureProjectLabels("TOR");
    expect(calls).toBe(1);
    expect(labelHueOf("bug", "TOR")).not.toBe(labelHue("bug"));
  });

  it("projectKeyOfRef knipt op het laatste streepje", () => {
    expect(projectKeyOfRef("BRAND-12")).toBe("BRAND");
    expect(projectKeyOfRef("A-B-3")).toBe("A-B");
    expect(projectKeyOfRef(null)).toBe(null);
  });
});
