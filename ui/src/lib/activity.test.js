import { describe, it, expect } from "vitest";
import { buildFeed } from "./activity.js";

const at = (min) => new Date(Date.UTC(2026, 9, 25, 12, 0) - min * 60000).toISOString();
const ev = (id, min, extra = {}) => ({
  id,
  type: "item.updated",
  actor: "person",
  ref: "BETON-1",
  created_at: at(min),
  payload: { description_md: { from: "a", to: "b" } },
  ...extra,
});

describe("buildFeed (BETON-463)", () => {
  it("voegt opeenvolgende gelijke events samen met count", () => {
    const out = buildFeed([ev(3, 0), ev(2, 1), ev(1, 2)]);
    expect(out).toHaveLength(1);
    expect(out[0].count).toBe(3);
    expect(out[0].id).toBe(3);
    expect(out[0].oldest_created_at).toBe(at(2));
  });
  it("breekt bij ander veld, andere actor, ander item", () => {
    const out = buildFeed([
      ev(4, 0),
      ev(3, 1, { payload: { title: { from: "a", to: "b" } } }),
      ev(2, 2, { actor: "triage" }),
      ev(1, 3, { ref: "BETON-2" }),
    ]);
    expect(out).toHaveLength(4);
  });
  it("breekt als het venster van 10 minuten overschreden wordt", () => {
    expect(buildFeed([ev(2, 0), ev(1, 10)])).toHaveLength(1);
    expect(buildFeed([ev(2, 0), ev(1, 11)])).toHaveLength(2);
    // reeks beslaat hooguit 10 minuten, ook als elke stap klein is
    expect(buildFeed([ev(4, 0), ev(3, 6), ev(2, 12)])).toHaveLength(2);
  });
  it("een tussenliggend ander event breekt de reeks", () => {
    const mid = ev(2, 1, { ref: "BETON-9" });
    expect(buildFeed([ev(3, 0), mid, ev(1, 2)])).toHaveLength(3);
  });
  it("verbergt wiki.compiled standaard, toont hem met showInternal", () => {
    const w = { id: 5, type: "wiki.compiled", actor: "triage", ref: "BETON-1", created_at: at(0), payload: { pages: ["x"] } };
    expect(buildFeed([w])).toEqual([]);
    expect(buildFeed([w], { showInternal: true })).toHaveLength(1);
  });
  it("laat priority-only events weg en strip priority uit gemengde events", () => {
    const only = ev(1, 0, { payload: { priority: { from: null, to: "medium" } } });
    expect(buildFeed([only])).toEqual([]);
    const mixed = ev(2, 0, { payload: { priority: { from: null, to: "low" }, workload: { from: null, to: "light" } } });
    const out = buildFeed([mixed]);
    expect(out).toHaveLength(1);
    expect("priority" in out[0].payload).toBe(false);
  });
  it("voegt niet-update events samen op gelijke omschrijving", () => {
    const c = (id, min) => ({ id, type: "comment.created", actor: "claude", ref: "BETON-1", created_at: at(min), payload: {} });
    expect(buildFeed([c(2, 0), c(1, 1)])[0].count).toBe(2);
  });
});
