import { describe, it, expect } from "vitest";
import {
  VIEWS,
  DEFAULT_VIEW,
  VIEW_KEY,
  isView,
  readView,
  hidesProjectFilters,
  OVERLAYS,
  isOverlay,
  pushOverlay,
  popOverlay,
  closeOverlay,
  topOverlay,
  hasOverlay,
  FILTER_KEYS,
  countActiveFilters,
  countPanelFilters,
  activeFilterChips,
  readPersisted,
  writePersisted,
} from "./viewState.js";

describe("basis-content-view", () => {
  it("kent precies bord/lijst/wiki/activiteit/overzicht", () => {
    expect(VIEWS).toEqual(["board", "list", "wiki", "activity", "overview"]);
  });

  it("isView herkent alleen geldige views", () => {
    expect(isView("board")).toBe(true);
    expect(isView("wiki")).toBe(true);
    expect(isView("activity")).toBe(true);
    expect(isView("overview")).toBe(true);
    expect(isView("inbox")).toBe(false); // inbox is een overlay, geen view
    expect(isView(null)).toBe(false);
  });

  it("readView valideert en valt terug op het bord", () => {
    expect(readView("list")).toBe("list");
    expect(readView("wiki")).toBe("wiki");
    expect(readView(null)).toBe(DEFAULT_VIEW);
    expect(readView("onzin")).toBe(DEFAULT_VIEW);
    // Oude persistente waarden (board/list) blijven geldig.
    expect(readView("board")).toBe("board");
  });

  it("hidesProjectFilters dekt alle niet-project-views", () => {
    // De board-zoekbalk en de filter-pills horen alleen bij bord/lijst; de
    // andere views hebben hun eigen navigatie of gaan over álle projecten.
    expect(hidesProjectFilters("wiki")).toBe(true);
    expect(hidesProjectFilters("activity")).toBe(true);
    expect(hidesProjectFilters("overview")).toBe(true);
    expect(hidesProjectFilters("board")).toBe(false);
    expect(hidesProjectFilters("list")).toBe(false);
  });

  it("gebruikt de bestaande persist-key", () => {
    expect(VIEW_KEY).toBe("betonning-view");
  });
});

describe("overlay-stack", () => {
  it("inbox en de mobiele filter-sheet zijn overlays, geen views", () => {
    expect(isOverlay("inbox")).toBe(true);
    expect(isOverlay("filters")).toBe(true);
    expect(isOverlay("board")).toBe(false);
    expect(OVERLAYS).toContain("palette");
    expect(OVERLAYS).toContain("mine");
  });

  it("pushOverlay legt bovenop en negeert onbekende namen", () => {
    let s = [];
    s = pushOverlay(s, "mine");
    s = pushOverlay(s, "inbox");
    expect(s).toEqual(["mine", "inbox"]);
    expect(pushOverlay(s, "onzin")).toEqual(["mine", "inbox"]);
  });

  it("pushOverlay dedupliceert: opnieuw openen verhuist naar de top", () => {
    let s = ["mine", "inbox", "palette"];
    s = pushOverlay(s, "mine");
    expect(s).toEqual(["inbox", "palette", "mine"]);
    // geen dubbele entry
    expect(s.filter((o) => o === "mine").length).toBe(1);
  });

  it("topOverlay geeft de bovenste of null", () => {
    expect(topOverlay([])).toBe(null);
    expect(topOverlay(["mine", "inbox"])).toBe("inbox");
  });

  it("hasOverlay checkt aanwezigheid", () => {
    expect(hasOverlay(["mine"], "mine")).toBe(true);
    expect(hasOverlay(["mine"], "inbox")).toBe(false);
    expect(hasOverlay(null, "mine")).toBe(false);
  });

  it("closeOverlay verwijdert een specifieke laag, idempotent", () => {
    expect(closeOverlay(["mine", "inbox"], "mine")).toEqual(["inbox"]);
    // niet aanwezig → ongewijzigd
    expect(closeOverlay(["inbox"], "mine")).toEqual(["inbox"]);
  });

  it("popOverlay sluit de bovenste (Esc) in LIFO-volgorde", () => {
    let s = ["mine", "inbox", "palette"];
    let r = popOverlay(s);
    expect(r.closed).toBe("palette");
    expect(r.stack).toEqual(["mine", "inbox"]);

    r = popOverlay(r.stack);
    expect(r.closed).toBe("inbox");
    expect(r.stack).toEqual(["mine"]);

    r = popOverlay(r.stack);
    expect(r.closed).toBe("mine");
    expect(r.stack).toEqual([]);

    r = popOverlay(r.stack);
    expect(r.closed).toBe(null);
    expect(r.stack).toEqual([]);
  });
});

describe("filters", () => {
  const empty = { assignee: "", label: "", workload: "", milestone: "", q: "" };

  it("telt actieve filters", () => {
    expect(countActiveFilters(empty)).toBe(0);
    expect(countActiveFilters({ ...empty, assignee: "person" })).toBe(1);
    expect(
      countActiveFilters({ ...empty, assignee: "person", q: "bug", label: "ui" }),
    ).toBe(3);
    expect(countActiveFilters(null)).toBe(0);
  });

  it("q (vrije zoektekst) telt mee als filter", () => {
    expect(FILTER_KEYS).toContain("q");
    expect(countActiveFilters({ ...empty, q: "iets" })).toBe(1);
  });

  describe("countPanelFilters (BETON-398)", () => {
    it("alleen q actief: het paneel telt 0, de brede teller wél 1", () => {
      // Badge en paneel gingen vóór de fix over verschillende verzamelingen:
      // "Filter 1" met een leeg paneel — precies de melding.
      expect(countPanelFilters({ ...empty, q: "376" })).toBe(0);
      expect(countActiveFilters({ ...empty, q: "376" })).toBe(1);
    });

    it("een snelfilter (bv. mine) telt niet mee in het paneel", () => {
      expect(countPanelFilters({ mine: true })).toBe(0);
    });

    it("een label-filter telt in allebei mee", () => {
      expect(countPanelFilters({ ...empty, label: "ui" })).toBe(1);
      expect(countActiveFilters({ ...empty, label: "ui" })).toBe(1);
    });

    it("'toon gearchiveerde items' telt mee als die aanstaat", () => {
      expect(countPanelFilters(empty, { archived: true })).toBe(1);
      expect(countPanelFilters(empty, { archived: false })).toBe(0);
      expect(countPanelFilters(empty)).toBe(0);
    });

    it("combineert paneelfilters + archief", () => {
      expect(countPanelFilters({ ...empty, assignee: "person" }, { archived: true })).toBe(2);
    });

    it("geen filters → 0", () => {
      expect(countPanelFilters(null)).toBe(0);
    });
  });

  it("activeFilterChips levert verwijderbare chips in vaste volgorde", () => {
    const chips = activeFilterChips({
      ...empty,
      workload: "heavy",
      assignee: "person",
    });
    // volgorde volgt FILTER_KEYS: assignee vóór workload
    expect(chips.map((c) => c.key)).toEqual(["assignee", "workload"]);
    expect(chips[0]).toMatchObject({ key: "assignee", field: "Toegewezen aan", value: "person" });
    expect(chips[1]).toMatchObject({ key: "workload", value: "Zwaar" });
  });

  it("activeFilterChips is leeg zonder filters", () => {
    expect(activeFilterChips(empty)).toEqual([]);
    expect(activeFilterChips(null)).toEqual([]);
  });
});

describe("snelfilters (BETON-357)", () => {
  it("FILTER_KEYS kent de nieuwe snelfilter-velden", () => {
    expect(FILTER_KEYS).toEqual(
      expect.arrayContaining(["mine", "unread", "question", "due", "unassigned", "state"]),
    );
  });

  it("countActiveFilters telt de nieuwe velden mee", () => {
    expect(countActiveFilters({ mine: true })).toBe(1);
    expect(countActiveFilters({ mine: true, unread: true, due: "week" })).toBe(3);
    expect(countActiveFilters({ mine: false, unassigned: false })).toBe(0);
  });

  it("activeFilterChips geeft boolean-chips zonder waarde", () => {
    const chips = activeFilterChips({ mine: true, unassigned: true });
    expect(chips).toEqual([
      { key: "mine", field: "Aan mij", value: null, boolean: true },
      { key: "unassigned", field: "Zonder assignee", value: null, boolean: true },
    ]);
  });

  it("activeFilterChips vertaalt de due-waarde naar NL", () => {
    expect(activeFilterChips({ due: "week" })).toEqual([
      { key: "due", field: "Deadline", value: "Deze week" },
    ]);
    expect(activeFilterChips({ due: "overdue" })).toEqual([
      { key: "due", field: "Deadline", value: "Te laat" },
    ]);
  });

  it("activeFilterChips toont de status-filterwaarde as-is", () => {
    expect(activeFilterChips({ state: "in-progress" })).toEqual([
      { key: "state", field: "Status", value: "in-progress" },
    ]);
  });
});

describe("readPersisted/writePersisted (BETON-364)", () => {
  // node-testomgeving, geen jsdom → geen globale localStorage. readPersisted
  // guardt daarop en valt terug op fallback; writePersisted vangt de throw.
  it("valt terug op fallback zonder localStorage", () => {
    expect(readPersisted("x", (v) => v === "a", "fallback")).toBe("fallback");
  });

  it("accepteert een waarde die de validator goedkeurt (null zonder localStorage faalt altijd de validator)", () => {
    expect(readPersisted("x", (v) => v == null, "fallback")).toBe(null);
  });

  it("writePersisted gooit niet als localStorage ontbreekt", () => {
    expect(() => writePersisted("x", "y")).not.toThrow();
  });
});
