import { describe, it, expect } from "vitest";
import { mergeRecentItems, filterControlsVisible } from "./allProjectsScope.js";

describe("mergeRecentItems", () => {
  it("sorteert samengevoegde items op recentheid (nieuwste eerst)", () => {
    const sos = [
      { ref: "SOS-1", last_activity_at: "2026-07-01T10:00:00Z" },
      { ref: "SOS-2", last_activity_at: "2026-07-10T10:00:00Z" },
    ];
    const brand = [{ ref: "BRAND-3", last_activity_at: "2026-07-05T10:00:00Z" }];
    const merged = mergeRecentItems([sos, brand]);
    expect(merged.map((i) => i.ref)).toEqual(["SOS-2", "BRAND-3", "SOS-1"]);
  });

  it("valt terug op created_at als last_activity_at ontbreekt", () => {
    const items = [
      [
        { ref: "A-1", created_at: "2026-01-01T00:00:00Z" },
        { ref: "A-2", last_activity_at: "2026-06-01T00:00:00Z" },
      ],
    ];
    expect(mergeRecentItems(items).map((i) => i.ref)).toEqual(["A-2", "A-1"]);
  });

  it("begrenst tot limit", () => {
    const items = [Array.from({ length: 15 }, (_, i) => ({ ref: `X-${i}`, created_at: `2026-01-${String(i + 1).padStart(2, "0")}T00:00:00Z` }))];
    expect(mergeRecentItems(items, 10)).toHaveLength(10);
  });

  it("negeert lege/ontbrekende invoer zonder te crashen", () => {
    expect(mergeRecentItems(undefined)).toEqual([]);
    expect(mergeRecentItems([[], null, undefined])).toEqual([]);
  });

  it("items zonder bruikbare datum belanden achteraan, niet crashend", () => {
    const items = [
      [
        { ref: "NODATE" },
        { ref: "WITHDATE", created_at: "2026-01-01T00:00:00Z" },
      ],
    ];
    expect(mergeRecentItems(items).map((i) => i.ref)).toEqual(["WITHDATE", "NODATE"]);
  });
});

describe("filterControlsVisible", () => {
  it("verbergt filter-controls in de 'alle projecten'-scope", () => {
    expect(filterControlsVisible("all")).toBe(false);
  });

  it("toont filter-controls in de project-scope", () => {
    expect(filterControlsVisible("project")).toBe(true);
  });
});
