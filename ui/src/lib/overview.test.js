import { describe, it, expect } from "vitest";
import { countsText, countParts, splitProjects, isQuiet } from "./overview.js";

const NOW = Date.UTC(2026, 9, 25);
const day = (n) => new Date(NOW - n * 86400000).toISOString();
const p = (key, extra = {}) => ({
  key, name: key, open: 1, in_progress: 0, blocked: 0, unassigned: 0,
  open_questions: 0, unread: 0, last_activity_at: day(1), ...extra,
});

describe("countsText (BETON-464)", () => {
  it("laat nullen weg en gebruikt woorden", () => {
    expect(countsText(p("A", { in_progress: 4, open_questions: 7, unread: 5 }))).toBe("4 lopend · 7 vragen · 5 ongelezen");
  });
  it("enkelvoud en leeg", () => {
    expect(countsText(p("A", { open_questions: 1 }))).toBe("1 vraag");
    expect(countsText(p("A"))).toBe("");
  });
  it("markeert vragen en ongelezen als voor jou", () => {
    const parts = countParts(p("A", { blocked: 2, unread: 1 }));
    expect(parts.map((x) => !!x.mine)).toEqual([false, true]);
  });
});

describe("splitProjects (BETON-464)", () => {
  it("iets voor jou eerst, dan laatste activiteit", () => {
    const { active } = splitProjects([
      p("OUD", { last_activity_at: day(10) }),
      p("NIEUW", { last_activity_at: day(0) }),
      p("JOU", { unread: 1, last_activity_at: day(20) }),
    ], NOW);
    expect(active.map((x) => x.key)).toEqual(["JOU", "NIEUW", "OUD"]);
  });
  it("stil: >30 dagen zonder activiteit, ook zonder activiteit helemaal", () => {
    expect(isQuiet(p("A", { open: 0, last_activity_at: day(31) }), NOW)).toBe(true);
    expect(isQuiet(p("A", { open: 0, last_activity_at: null }), NOW)).toBe(true);
    expect(isQuiet(p("A", { open: 0, last_activity_at: day(29) }), NOW)).toBe(false);
    // open tickets houden een project niet meer actief (BETON-475)
    expect(isQuiet(p("A", { open: 3, last_activity_at: day(90) }), NOW)).toBe(true);
    expect(isQuiet(p("A", { open: 0, last_activity_at: day(2) }), NOW)).toBe(false);
  });
  it("stille projecten staan in quiet op key", () => {
    const { active, quiet } = splitProjects([
      p("B", { open: 0, last_activity_at: day(60) }),
      p("A", { open: 0, last_activity_at: day(60) }),
      p("C"),
    ], NOW);
    expect(active.map((x) => x.key)).toEqual(["C"]);
    expect(quiet.map((x) => x.key)).toEqual(["A", "B"]);
  });
});

it("houdt nieuwe lege projecten actief tot dertig dagen na aanmaak (BETON-491)", () => {
  expect(isQuiet(p("N", { last_activity_at: null, created_at: day(0) }), NOW)).toBe(false);
  expect(isQuiet(p("N", { last_activity_at: null, created_at: day(30) }), NOW)).toBe(false);
  expect(isQuiet(p("N", { last_activity_at: null, created_at: day(31) }), NOW)).toBe(true);
});
