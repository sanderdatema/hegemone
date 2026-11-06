import { describe, it, expect } from "vitest";
import {
  fuzzyScore,
  fuzzyMatch,
  rankItems,
  moveIndex,
  isTypingTarget,
  shortcutAction,
  drawerShortcutAction,
  shortcutHelp,
  SHORTCUTS,
} from "./palette.js";

describe("fuzzyScore / fuzzyMatch (BETON-56)", () => {
  it("matcht een subsequence", () => {
    expect(fuzzyMatch("nt", "Nieuw ticket")).toBe(true);
    expect(fuzzyMatch("xyz", "Nieuw ticket")).toBe(false);
  });
  it("lege query matcht neutraal", () => {
    expect(fuzzyScore("", "van alles")).toBe(0);
  });
  it("aaneengesloten + woordbegin scoort hoger dan verspreid", () => {
    expect(fuzzyScore("new", "new item")).toBeGreaterThan(fuzzyScore("new", "n e w x"));
  });
  it("case-insensitief", () => {
    expect(fuzzyMatch("SOS", "sos-42 iets")).toBe(true);
  });
});

describe("rankItems (BETON-56)", () => {
  const items = [
    { label: "Nieuw ticket", keywords: "new create" },
    { label: "Open wiki", keywords: ["memory", "notes"] },
    { label: "Wissel view" },
  ];
  it("filtert en sorteert op score", () => {
    const out = rankItems(items, "wiki");
    expect(out[0].label).toBe("Open wiki");
  });
  it("matcht op keywords", () => {
    const out = rankItems(items, "create");
    expect(out.map((i) => i.label)).toContain("Nieuw ticket");
  });
  it("lege query behoudt volgorde", () => {
    expect(rankItems(items, "  ").map((i) => i.label)).toEqual(items.map((i) => i.label));
  });
  it("geen match → lege lijst", () => {
    expect(rankItems(items, "zzzzz")).toEqual([]);
  });
});

describe("moveIndex (BETON-56)", () => {
  it("wrapt rond", () => {
    expect(moveIndex(0, -1, 3)).toBe(2);
    expect(moveIndex(2, 1, 3)).toBe(0);
    expect(moveIndex(1, 1, 3)).toBe(2);
  });
  it("lege lijst → 0", () => {
    expect(moveIndex(0, 1, 0)).toBe(0);
  });
});

describe("isTypingTarget (BETON-56/64)", () => {
  it("herkent invoervelden", () => {
    expect(isTypingTarget({ tagName: "INPUT" })).toBe(true);
    expect(isTypingTarget({ tagName: "textarea" })).toBe(true);
    expect(isTypingTarget({ tagName: "SELECT" })).toBe(true);
    expect(isTypingTarget({ tagName: "DIV", isContentEditable: true })).toBe(true);
  });
  it("de eigen keuzelijst telt mee: knop én open menu (BETON-439)", () => {
    // Vóór BETON-439 was dit een native <select>; nu vangt het bord anders
    // de pijltjes (focus naar een kaart) en letters (sneltoetsen) af.
    const inSelect = (sel) => ({ tagName: "DIV", closest: (q) => (q.includes(sel) ? {} : null) });
    expect(isTypingTarget(inSelect("[data-select-content]"))).toBe(true);
    expect(isTypingTarget(inSelect("[data-select-trigger]"))).toBe(true);
  });
  it("gewone elementen niet", () => {
    expect(isTypingTarget({ tagName: "DIV", closest: () => null })).toBe(false);
    expect(isTypingTarget({ tagName: "DIV" })).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

describe("shortcutAction (BETON-56/64)", () => {
  it("Cmd/Ctrl+K opent het palette", () => {
    expect(shortcutAction({ key: "k", metaKey: true })).toEqual({ type: "palette" });
    expect(shortcutAction({ key: "K", ctrlKey: true })).toEqual({ type: "palette" });
  });
  it("kale letters/tekens", () => {
    expect(shortcutAction({ key: "c" })).toEqual({ type: "new-item" });
    expect(shortcutAction({ key: "/" })).toEqual({ type: "focus-search" });
    expect(shortcutAction({ key: "?" })).toEqual({ type: "toggle-hints" });
    expect(shortcutAction({ key: "g" })).toEqual({ type: "chord-start", chord: "g" });
  });
  it("kaartnavigatie via pijl en j/k", () => {
    expect(shortcutAction({ key: "j" })).toEqual({ type: "nav-card", delta: 1 });
    expect(shortcutAction({ key: "ArrowUp" })).toEqual({ type: "nav-card", delta: -1 });
    expect(shortcutAction({ key: "Enter" })).toEqual({ type: "open-card" });
  });
  it("g-chord: volgende letter kiest project", () => {
    expect(shortcutAction({ key: "s" }, { chord: "g" })).toEqual({ type: "goto-project", char: "s" });
    expect(shortcutAction({ key: "Enter" }, { chord: "g" })).toEqual({ type: "chord-cancel" });
  });
  it("negeert andere modifier-combo's", () => {
    expect(shortcutAction({ key: "c", metaKey: true })).toBeNull();
    expect(shortcutAction({ key: "a", altKey: true })).toBeNull();
  });

  // BETON-361: acties op de gefocuste kaart en globale navigatie.
  it("kaart-acties x/a/s/l/e/m", () => {
    expect(shortcutAction({ key: "x" })).toEqual({ type: "toggle-select" });
    expect(shortcutAction({ key: "a" })).toEqual({ type: "quick-assign" });
    expect(shortcutAction({ key: "s" })).toEqual({ type: "quick-state" });
    expect(shortcutAction({ key: "l" })).toEqual({ type: "quick-label" });
    expect(shortcutAction({ key: "e" })).toEqual({ type: "edit-card" });
    expect(shortcutAction({ key: "m" })).toEqual({ type: "mark-read" });
  });
  it("globale navigatie i/v/w", () => {
    expect(shortcutAction({ key: "i" })).toEqual({ type: "open-inbox" });
    expect(shortcutAction({ key: "v" })).toEqual({ type: "toggle-view" });
    expect(shortcutAction({ key: "w" })).toEqual({ type: "open-wiki" });
  });
  it("drawer vorige/volgende [ ]", () => {
    expect(shortcutAction({ key: "[" })).toEqual({ type: "prev-item" });
    expect(shortcutAction({ key: "]" })).toEqual({ type: "next-item" });
  });
  it("g-chord blijft werken naast de nieuwe letter-sneltoetsen", () => {
    expect(shortcutAction({ key: "a" }, { chord: "g" })).toEqual({ type: "goto-project", char: "a" });
  });
});

describe("shortcutHelp (BETON-361)", () => {
  it("elke niet-verborgen sneltoets komt precies één keer voor", () => {
    const help = shortcutHelp();
    const keys = help.flatMap((g) => g.items.map((i) => i.key));
    const visible = SHORTCUTS.filter((s) => !s.hidden).map((s) => s.key);
    for (const k of visible) {
      expect(keys.filter((x) => x === k)).toHaveLength(1);
    }
    // Geen duplicaten in de volledige lijst.
    expect(new Set(keys).size).toBe(keys.length);
  });
  it("bevat ⌘K, dat buiten de tabel om wordt afgehandeld", () => {
    const keys = shortcutHelp().flatMap((g) => g.items.map((i) => i.key));
    expect(keys).toContain("⌘K / Ctrl+K");
  });
  it("groepeert op scope (global/card/drawer)", () => {
    const help = shortcutHelp();
    expect(help.map((g) => g.scope)).toEqual(["global", "card", "drawer"]);
    const card = help.find((g) => g.scope === "card");
    expect(card.items.map((i) => i.key).sort()).toEqual(["a", "e", "l", "m", "s", "x"]);
  });
});


describe("drawer-sneltoets voor overdracht (BETON-470)", () => {
  it("activeert alleen Shift+A, niet kale a of Caps Lock", () => {
    expect(drawerShortcutAction({ key: "A", shiftKey: true })).toEqual({ type: "handoff" });
    expect(drawerShortcutAction({ key: "a" })).toBeNull();
    expect(drawerShortcutAction({ key: "A" })).toBeNull();
  });
  it("laat tekstvelden, select-menu's, modifiers en key-repeat met rust", () => {
    for (const extra of [{ target: { tagName: "TEXTAREA" } }, { target: { closest: () => ({}) } }, { ctrlKey: true }, { metaKey: true }, { altKey: true }, { repeat: true }, { defaultPrevented: true }]) {
      expect(drawerShortcutAction({ key: "A", shiftKey: true, ...extra })).toBeNull();
    }
  });
  it("blijft vorige/volgende ondersteunen en adverteert de overdracht in de help", () => {
    expect(drawerShortcutAction({ key: "[" })).toEqual({ type: "prev-item" });
    expect(drawerShortcutAction({ key: "[", repeat: true })).toEqual({ type: "prev-item" });
    expect(shortcutHelp().find((g) => g.scope === "drawer").items).toContainEqual({ key: "A", label: "Geef terug (Shift+A)" });
  });
});

it('vertaalt sneltoetshulp met dezelfde toetsen en groepen', () => {
  const en = shortcutHelp('en');
  const nl = shortcutHelp('nl');
  expect(en.map(group => ({ scope: group.scope, keys: group.items.map(item => item.key) }))).toEqual(nl.map(group => ({ scope: group.scope, keys: group.items.map(item => item.key) })));
  expect(en[0].scopeLabel).toBe('General');
  expect(en[0].items).toContainEqual({ key: 'c', label: 'New ticket' });
  expect(en.flatMap(group => group.items).every(item => !item.label.startsWith('shortcut.'))).toBe(true);
});
