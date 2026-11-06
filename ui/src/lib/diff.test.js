import { describe, it, expect } from "vitest";
import { lineDiff, diffStat } from "./diff.js";

describe("lineDiff", () => {
  it("markeert een gewijzigde regel als del + add", () => {
    const d = lineDiff("regel een\nregel twee", "regel een\nregel TWEE");
    expect(d).toEqual([
      { type: "ctx", text: "regel een" },
      { type: "del", text: "regel twee" },
      { type: "add", text: "regel TWEE" },
    ]);
  });

  it("identieke tekst → alles context", () => {
    const d = lineDiff("a\nb", "a\nb");
    expect(d.every((s) => s.type === "ctx")).toBe(true);
  });

  it("lege oude tekst (eerste revisie) → alles toegevoegd", () => {
    const d = lineDiff("", "nieuw\ntweede");
    expect(d).toEqual([
      { type: "add", text: "nieuw" },
      { type: "add", text: "tweede" },
    ]);
  });

  it("null-invoer telt als nul regels (lege diff)", () => {
    expect(lineDiff(null, null)).toEqual([]);
  });

  it("een toegevoegde regel tussen bestaande regels blijft context eromheen", () => {
    const d = lineDiff("a\nc", "a\nb\nc");
    expect(d).toEqual([
      { type: "ctx", text: "a" },
      { type: "add", text: "b" },
      { type: "ctx", text: "c" },
    ]);
  });

  it("een verwijderde regel", () => {
    const d = lineDiff("a\nb\nc", "a\nc");
    expect(d).toEqual([
      { type: "ctx", text: "a" },
      { type: "del", text: "b" },
      { type: "ctx", text: "c" },
    ]);
  });
});

describe("diffStat", () => {
  it("telt toegevoegde en verwijderde regels", () => {
    const d = lineDiff("a\nb\nc", "a\nx\nc\nd");
    expect(diffStat(d)).toEqual({ added: 2, removed: 1 });
  });
});


it("houdt een grote regeldiff begrensd zonder inhoud te verliezen", () => {
  const before = Array(2000).fill("oud").join("\n");
  const after = Array(2000).fill("nieuw").join("\n");
  const diff = lineDiff(before, after);
  expect(diff.filter(s => s.type === "del")).toHaveLength(2000);
  expect(diff.filter(s => s.type === "add")).toHaveLength(2000);
});
