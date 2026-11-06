import { describe, it, expect } from "vitest";
import { needsTypedConfirm, typedCountValid, summarizePreview } from "./triageChat.js";

describe("needsTypedConfirm", () => {
  it("false zonder voorstel", () => {
    expect(needsTypedConfirm(null)).toBe(false);
  });
  it("false op/onder de drempel", () => {
    expect(needsTypedConfirm({ total_count: 10, threshold: 10 })).toBe(false);
    expect(needsTypedConfirm({ total_count: 3, threshold: 10 })).toBe(false);
  });
  it("true boven de drempel", () => {
    expect(needsTypedConfirm({ total_count: 11, threshold: 10 })).toBe(true);
  });
});

describe("typedCountValid", () => {
  const proposal = { total_count: 12 };
  it("waar bij exact match (getal of string)", () => {
    expect(typedCountValid(proposal, 12)).toBe(true);
    expect(typedCountValid(proposal, "12")).toBe(true);
  });
  it("onwaar bij mismatch of leeg", () => {
    expect(typedCountValid(proposal, 11)).toBe(false);
    expect(typedCountValid(proposal, "")).toBe(false);
    expect(typedCountValid(null, 0)).toBe(false);
  });
});

describe("summarizePreview", () => {
  it("toont de eerste N refs en telt de rest als hidden", () => {
    const refs = Array.from({ length: 10 }, (_, i) => `SOS-${i + 1}`);
    const s = summarizePreview({ verb: "archive", refs, count: 10 }, 8);
    expect(s.shown).toHaveLength(8);
    expect(s.hidden).toBe(2);
    expect(s.count).toBe(10);
    expect(s.verb).toBe("archive");
  });
  it("geen verborgen refs onder de limiet", () => {
    const s = summarizePreview({ verb: "archive", refs: ["SOS-1"] }, 8);
    expect(s.hidden).toBe(0);
    expect(s.shown).toEqual(["SOS-1"]);
  });
  it("create_item zonder refs toont de detail-titel", () => {
    const s = summarizePreview({ verb: "create_item", refs: [], count: 1, detail: "Nieuw" });
    expect(s.shown).toEqual([]);
    expect(s.detail).toBe("Nieuw");
  });
});
