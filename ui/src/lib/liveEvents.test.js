import { describe, it, expect } from "vitest";
import { applyEvent, closedCountDeltas, applyCountDeltas } from "./liveEvents.js";

const base = (overrides = {}) => ({
  ref: "SOS-1",
  title: "een",
  state: "todo",
  priority: "none",
  assignee: null,
  labels: [],
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  last_activity_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

const state = (items, extra = {}) => ({
  items,
  project: "SOS",
  showArchived: false,
  ...extra,
});

describe("applyEvent", () => {
  it("null bij ongeldig event", () => {
    expect(applyEvent(state([]), null)).toBeNull();
    expect(applyEvent(state([]), {})).toBeNull();
  });

  it("item.created voegt een nieuwe kaart toe", () => {
    const snap = base({ ref: "SOS-2", title: "nieuw" });
    const next = applyEvent(state([base()]), {
      type: "item.created",
      project: "SOS",
      item: snap,
    });
    expect(next).toHaveLength(2);
    expect(next.map((i) => i.ref)).toContain("SOS-2");
  });

  it("item.created van een ander project raakt het board niet", () => {
    const items = [base()];
    const next = applyEvent(state(items), {
      type: "item.created",
      project: "BETON",
      item: base({ ref: "BETON-9" }),
    });
    expect(next).toBe(items); // ongewijzigd, geen reload
  });

  it("item.updated vervangt de kaart en verhuist van kolom (state-wissel)", () => {
    const next = applyEvent(state([base(), base({ ref: "SOS-2" })]), {
      type: "item.updated",
      project: "SOS",
      item: base({ state: "in-progress", title: "gewijzigd" }),
    });
    const row = next.find((i) => i.ref === "SOS-1");
    expect(row.state).toBe("in-progress");
    expect(row.title).toBe("gewijzigd");
    expect(next).toHaveLength(2);
  });

  it("item.archived haalt de kaart van het board als archief verborgen is", () => {
    const next = applyEvent(state([base(), base({ ref: "SOS-2" })]), {
      type: "item.archived",
      project: "SOS",
      item: base({ archived_at: "2026-02-02T00:00:00Z" }),
    });
    expect(next.map((i) => i.ref)).toEqual(["SOS-2"]);
  });

  it("item.archived behoudt de kaart (gemarkeerd) als archief zichtbaar is", () => {
    const snap = base({ archived_at: "2026-02-02T00:00:00Z" });
    const next = applyEvent(state([base()], { showArchived: true }), {
      type: "item.archived",
      project: "SOS",
      item: snap,
    });
    expect(next).toHaveLength(1);
    expect(next[0].archived_at).toBeTruthy();
  });

  it("item.restored zet de kaart terug (archived_at leeg)", () => {
    const archived = base({ archived_at: "2026-02-02T00:00:00Z" });
    const next = applyEvent(state([archived], { showArchived: true }), {
      type: "item.restored",
      project: "SOS",
      item: base({ archived_at: null }),
    });
    expect(next[0].archived_at).toBeNull();
  });

  it("item.moved verwijdert het bron-item (payload.from)", () => {
    const next = applyEvent(state([base(), base({ ref: "SOS-2" })]), {
      type: "item.moved",
      payload: { from: "SOS-1", to: "BETON-5" },
    });
    expect(next.map((i) => i.ref)).toEqual(["SOS-2"]);
  });

  it("item.deleted verwijdert op payload.ref", () => {
    const next = applyEvent(state([base(), base({ ref: "SOS-2" })]), {
      type: "item.deleted",
      payload: { ref: "SOS-2" },
    });
    expect(next.map((i) => i.ref)).toEqual(["SOS-1"]);
  });

  it("comment.created verfrist de snapshot (last_activity) zonder reload", () => {
    const next = applyEvent(state([base()]), {
      type: "comment.created",
      project: "SOS",
      item: base({ last_activity_at: "2026-03-03T00:00:00Z" }),
    });
    expect(next[0].last_activity_at).toBe("2026-03-03T00:00:00Z");
  });

  it("wiki.compiled is een no-op voor het board", () => {
    const items = [base()];
    expect(applyEvent(state(items), { type: "wiki.compiled" })).toBe(items);
  });

  it("event zonder snapshot → null (reload-fallback)", () => {
    expect(
      applyEvent(state([base()]), { type: "item.updated", project: "SOS" })
    ).toBeNull();
  });

  it("een onbekend event-type met snapshot draagt has_guardrail mee (BETON-420)", () => {
    // `item.guardrail_set` is geen type dat de reducer kent; hij valt door naar
    // de up-sert uit de meegestuurde snapshot, en die snapshot is
    // `compact(serialize(...))` uit api/stream.py — dus `has_guardrail` komt
    // mee en de rode rand verschijnt zonder herladen. Deze test is de grendel
    // op dat gedrag; er is in de reducer géén guardrail-specifieke tak.
    const next = applyEvent(state([base({ has_guardrail: false })]), {
      type: "item.guardrail_set",
      project: "SOS",
      item: base({ has_guardrail: true }),
    });
    expect(next).toHaveLength(1);
    expect(next[0].has_guardrail).toBe(true);
  });

  it("verwijderen van een onbekende ref laat de lijst ongemoeid", () => {
    const items = [base()];
    const next = applyEvent(state(items), {
      type: "item.deleted",
      payload: { ref: "SOS-99" },
    });
    expect(next).toBe(items);
  });
});

describe("closedCountDeltas (BETON-359)", () => {
  it("+1 als een item een closed-state binnenkomt", () => {
    const before = [base({ ref: "SOS-1", state: "todo" })];
    const after = [
      base({ ref: "SOS-1", state: "todo" }),
      base({ ref: "SOS-2", state: "done" }),
    ];
    expect(closedCountDeltas(before, after, ["done"])).toEqual({ done: 1 });
  });

  it("-1 als een item een closed-state verlaat (state gewisseld)", () => {
    const before = [base({ ref: "SOS-1", state: "done" })];
    const after = [base({ ref: "SOS-1", state: "todo" })];
    expect(closedCountDeltas(before, after, ["done"])).toEqual({ done: -1 });
  });

  it("geen delta als er niets verandert in de closed-states", () => {
    const before = [base({ ref: "SOS-1", state: "todo" }), base({ ref: "SOS-2", state: "done" })];
    const after = [base({ ref: "SOS-1", state: "in-progress" }), base({ ref: "SOS-2", state: "done" })];
    expect(closedCountDeltas(before, after, ["done"])).toEqual({});
  });

  it("meerdere closed-states tegelijk, alleen de gewijzigde komen terug", () => {
    const before = [base({ ref: "SOS-1", state: "done" })];
    const after = [base({ ref: "SOS-1", state: "cancelled" })];
    expect(closedCountDeltas(before, after, ["done", "cancelled"])).toEqual({
      done: -1,
      cancelled: 1,
    });
  });

  it("negeert open states (niet in closedStateNames)", () => {
    const before = [base({ ref: "SOS-1", state: "todo" })];
    const after = [base({ ref: "SOS-1", state: "in-progress" })];
    expect(closedCountDeltas(before, after, ["done"])).toEqual({});
  });
});

describe("applyCountDeltas (BETON-359)", () => {
  it("telt een delta bij een bestaande count op", () => {
    expect(applyCountDeltas({ done: 40 }, { done: 1 })).toEqual({ done: 41 });
  });

  it("start vanaf 0 voor een nog onbekende state", () => {
    expect(applyCountDeltas({}, { done: 1 })).toEqual({ done: 1 });
  });

  it("klemt op 0, wordt nooit negatief", () => {
    expect(applyCountDeltas({ done: 0 }, { done: -1 })).toEqual({ done: 0 });
  });

  it("muteert de invoer niet", () => {
    const counts = { done: 40 };
    applyCountDeltas(counts, { done: 1 });
    expect(counts).toEqual({ done: 40 });
  });

  it("zonder deltas blijft de map ongewijzigd (nieuwe referentie, gelijke inhoud)", () => {
    const counts = { done: 40 };
    expect(applyCountDeltas(counts, {})).toEqual(counts);
  });
});
