import { describe, it, expect } from "vitest";
import {
  buildColumns,
  appendColumnPage,
  boardWindow,
  columnCount,
  orderColumns,
  applyMove,
  applyRead,
  filterItems,
  describeEvent,
  timelineEvents,
  formatTimestamp,
  escapeHtml,
  resolveProject,
  projectKeyOf,
  annotateSearchResults,
  groupMine,
  groupByDay,
  isSubmitChord,
  applyBulkMove,
  applyBulkAssign,
  applyBulkLabel,
  applyBulkField,
  rangeBetween,
  refsToMove,
  toggleSelection,
  nextTheme,
  sortItems,
  sortRows,
  nextSort,
  LIST_COLUMNS,
  columnToExpandFor,
  isColumnCollapsed,
  stateColor,
  pageTitle,
} from "./board.js";

const states = [{ name: "backlog" }, { name: "todo" }, { name: "done" }];

describe("buildColumns", () => {
  it("groepeert items per state in kolomvolgorde", () => {
    const items = [
      { ref: "S-1", state: "todo" },
      { ref: "S-2", state: "backlog" },
      { ref: "S-3", state: "todo" },
    ];
    const cols = buildColumns(states, items);
    expect(cols.map((c) => c.name)).toEqual(["backlog", "todo", "done"]);
    expect(cols[1].items.map((i) => i.ref)).toEqual(["S-1", "S-3"]);
    expect(cols[2].items).toEqual([]);
  });

  it("zet items met onbekende/lege state in een aparte kolom", () => {
    const cols = buildColumns(states, [{ ref: "S-1", state: null }]);
    expect(cols.at(-1).name).toBe("(geen state)");
    expect(cols.at(-1).items).toHaveLength(1);
  });

  it("draagt group/color/closed per kolom mee", () => {
    const rich = [
      { name: "todo", group: "unstarted", color: "#3498db", closed: false },
      { name: "done", group: "completed", color: "#2ecc71", closed: true },
    ];
    const cols = buildColumns(rich, []);
    expect(cols[0]).toMatchObject({ group: "unstarted", color: "#3498db", closed: false });
    expect(cols[1]).toMatchObject({ group: "completed", color: "#2ecc71", closed: true });
  });

  it("defaults voor ontbrekende metadata en de orphan-kolom", () => {
    const cols = buildColumns([{ name: "x" }], [{ ref: "S-1", state: null }]);
    expect(cols[0]).toMatchObject({ group: null, color: null, closed: false });
    expect(cols.at(-1)).toMatchObject({ name: "(geen state)", closed: false });
  });

  it("zet gearchiveerde items niet in hun normale state-kolom (BETON-100)", () => {
    const items = [
      { ref: "S-1", state: "backlog", archived_at: null },
      { ref: "S-2", state: "backlog", archived_at: "2026-01-01T00:00:00Z" },
      { ref: "S-3", state: "todo", archived_at: "2026-01-02T00:00:00Z" },
    ];
    const cols = buildColumns(states, items);
    const backlogCol = cols.find((c) => c.name === "backlog");
    const todoCol = cols.find((c) => c.name === "todo");
    expect(backlogCol.items.map((i) => i.ref)).toEqual(["S-1"]);
    expect(todoCol.items).toEqual([]);
  });

  it("verzamelt gearchiveerde items in een aparte, dichtgeklapte Archief-kolom", () => {
    const items = [
      { ref: "S-1", state: "backlog", archived_at: null },
      { ref: "S-2", state: "backlog", archived_at: "2026-01-01T00:00:00Z" },
      { ref: "S-3", state: "todo", archived_at: "2026-01-02T00:00:00Z" },
    ];
    const cols = buildColumns(states, items);
    const archiveCol = cols.at(-1);
    expect(archiveCol).toMatchObject({ name: "Archief", closed: true, archived: true });
    expect(archiveCol.items.map((i) => i.ref).sort()).toEqual(["S-2", "S-3"]);
  });

  it("voegt geen Archief-kolom toe als er niets gearchiveerd is", () => {
    const items = [{ ref: "S-1", state: "backlog", archived_at: null }];
    const cols = buildColumns(states, items);
    expect(cols.some((c) => c.archived)).toBe(false);
  });

  it("Archief-kolom komt na een eventuele orphan-kolom (geen state)", () => {
    const items = [
      { ref: "S-1", state: null },
      { ref: "S-2", state: "backlog", archived_at: "2026-01-01T00:00:00Z" },
    ];
    const cols = buildColumns(states, items);
    expect(cols.at(-2).name).toBe("(geen state)");
    expect(cols.at(-1).name).toBe("Archief");
  });

  describe("total/hasMore (BETON-359)", () => {
    it("zonder counts: total = het aantal binnengehaalde items, geen hasMore", () => {
      const items = [{ ref: "S-1", state: "done" }, { ref: "S-2", state: "done" }];
      const cols = buildColumns(states, items);
      const done = cols.find((c) => c.name === "done");
      expect(done.total).toBe(2);
      expect(done.hasMore).toBe(false);
    });

    it("met een hogere server-count: hasMore true, total = de server-count", () => {
      const items = [{ ref: "S-1", state: "done" }, { ref: "S-2", state: "done" }];
      const cols = buildColumns(states, items, { done: 40 });
      const done = cols.find((c) => c.name === "done");
      expect(done.total).toBe(40);
      expect(done.hasMore).toBe(true);
    });

    it("een count die niet hoger is dan wat al binnen is geeft geen hasMore", () => {
      const items = [{ ref: "S-1", state: "done" }];
      const cols = buildColumns(states, items, { done: 1 });
      expect(cols.find((c) => c.name === "done")).toMatchObject({ total: 1, hasMore: false });
    });

    it("een count voor een onbekende/andere kolom raakt niets anders aan", () => {
      const items = [{ ref: "S-1", state: "todo" }];
      const cols = buildColumns(states, items, { done: 40 });
      expect(cols.find((c) => c.name === "todo")).toMatchObject({ total: 1, hasMore: false });
      expect(cols.find((c) => c.name === "done")).toMatchObject({ total: 40, hasMore: true });
    });
  });
});

describe("column pagination with hidden cards", () => {
  const loaded = [
    { ref: "S-1", state: "done", has_unread: true },
    { ref: "S-2", state: "done", has_unread: false },
    { ref: "S-3", state: "done", archived_at: "2026-01-01" },
  ];

  it("does not offer more when a quick filter hides already loaded cards", () => {
    const visible = filterItems(loaded.slice(0, 2), { unread: true });
    const done = buildColumns(states, visible, { done: 2 }, loaded).find(c => c.name === "done");
    expect(done.items).toHaveLength(1);
    expect(done).toMatchObject({ total: 2, remaining: 0, hasMore: false });
  });

  it("counts only unloaded active cards as remaining", () => {
    const cols = buildColumns(states, loaded.slice(0, 1), { done: 5 }, loaded);
    expect(cols.find(c => c.name === "done")).toMatchObject({ remaining: 3, hasMore: true });
  });

  it("does not apply state counts to the separate archive column", () => {
    const cols = buildColumns(states, loaded, { done: 2, Archief: 20 }, loaded);
    expect(cols.find(c => c.archived)).toMatchObject({ total: 1, remaining: 0, hasMore: false });
  });

  it("reconciles a stale count on an empty page instead of offering more forever", () => {
    const next = appendColumnPage(loaded, { done: 20, todo: 7 }, "done", [], 50);
    expect(next.counts).toEqual({ done: 2, todo: 7 });
    expect(buildColumns(states, next.items, next.counts).find(c => c.name === "done").hasMore).toBe(false);
  });

  it("merges short pages without duplicating cards and ends pagination", () => {
    const next = appendColumnPage(loaded, { done: 20 }, "done", [loaded[0], { ref: "S-4", state: "done" }], 50);
    expect(next.items.map(i => i.ref)).toEqual(["S-1", "S-2", "S-3", "S-4"]);
    expect(next.counts.done).toBe(3);
  });

  it("preserves the remaining count while a full page can have a successor", () => {
    const counts = { done: 100 };
    const next = appendColumnPage(loaded, counts, "done", [{ ref: "S-4", state: "done" }], 1);
    expect(next.counts).toBe(counts);
  });
});

describe("boardWindow (BETON-397)", () => {
  const serverKeys = ["assignee", "label", "workload", "milestone", "q"];

  it("zonder server-filters: het venster (closedLimit + counts) is actief", () => {
    expect(boardWindow({ assignee: "", q: "" }, serverKeys, 25)).toEqual({
      closedLimit: 25,
      wantCounts: true,
    });
  });

  it("met een actieve q: geen closedLimit en geen counts", () => {
    // BETON-397: zonder venster (geen closed_limit) kán er per definitie
    // niets bij te laden zijn — vóór de fix bleef closedLimit hier gewoon 25
    // en `wantCounts` bestond niet, dus de (ongefilterde) counts werden
    // alsnog opgehaald en tegen de gefilterde items gelegd.
    expect(boardWindow({ q: "376" }, serverKeys, 25)).toEqual({
      closedLimit: undefined,
      wantCounts: false,
    });
  });

  it("met een actief assignee-filter: ook dan geen venster", () => {
    expect(boardWindow({ assignee: "person" }, serverKeys, 25)).toEqual({
      closedLimit: undefined,
      wantCounts: false,
    });
  });
});

describe("orderColumns", () => {
  it("houdt werk-kolommen (closed: false) in hun bestaande onderlinge volgorde", () => {
    const cols = [
      { name: "todo", closed: false },
      { name: "in-progress", closed: false },
      { name: "backlog", closed: false },
    ];
    expect(orderColumns(cols).map((c) => c.name)).toEqual([
      "todo",
      "in-progress",
      "backlog",
    ]);
  });

  it("zet rust-kolommen (closed: true) achter de werk-kolommen, eigen volgorde behouden", () => {
    const cols = [
      { name: "done", closed: true },
      { name: "backlog", closed: false },
      { name: "cancelled", closed: true },
      { name: "todo", closed: false },
      { name: "deferred", closed: true },
    ];
    expect(orderColumns(cols).map((c) => c.name)).toEqual([
      "backlog",
      "todo",
      "done",
      "cancelled",
      "deferred",
    ]);
  });

  it("Archief-kolom blijft altijd absoluut laatste, ook ná de rust-rail", () => {
    const cols = [
      { name: "backlog", closed: false },
      { name: "Archief", closed: true, archived: true },
      { name: "done", closed: true },
    ];
    expect(orderColumns(cols).map((c) => c.name)).toEqual([
      "backlog",
      "done",
      "Archief",
    ]);
  });

  it("werkt met projecten die custom states/groepen hebben (geen hardcoded namen)", () => {
    const cols = [
      { name: "Wachten op klant", group: "unstarted", closed: false },
      { name: "Opgeleverd", group: "completed", closed: true },
      { name: "Ingepland", group: "started", closed: false },
      { name: "Ingetrokken", group: "cancelled", closed: true },
    ];
    expect(orderColumns(cols).map((c) => c.name)).toEqual([
      "Wachten op klant",
      "Ingepland",
      "Opgeleverd",
      "Ingetrokken",
    ]);
  });

  it("is puur: laat de invoerarray ongemoeid en geeft een nieuwe array terug", () => {
    const cols = [
      { name: "done", closed: true },
      { name: "todo", closed: false },
    ];
    const before = [...cols];
    const result = orderColumns(cols);
    expect(cols).toEqual(before);
    expect(result).not.toBe(cols);
  });

  it("lege/undefined input geeft een lege array terug", () => {
    expect(orderColumns([])).toEqual([]);
    expect(orderColumns(undefined)).toEqual([]);
  });
});

describe("applyMove", () => {
  it("wijzigt de state van het juiste item (immutable)", () => {
    const items = [
      { ref: "S-1", state: "todo" },
      { ref: "S-2", state: "backlog" },
    ];
    const moved = applyMove(items, "S-1", "done");
    expect(moved[0]).toEqual({ ref: "S-1", state: "done" });
    expect(items[0].state).toBe("todo"); // origineel ongewijzigd
    expect(moved[1]).toBe(items[1]); // ongewijzigde items behouden referentie
  });

  it("laat onbekende ref met rust", () => {
    const items = [{ ref: "S-1", state: "todo" }];
    expect(applyMove(items, "X-9", "done")).toEqual(items);
  });
});

describe("applyRead", () => {
  it("zet has_unread op false voor het gegeven ref", () => {
    const items = [
      { ref: "S-1", has_unread: true },
      { ref: "S-2", has_unread: true },
    ];
    const read = applyRead(items, "S-1");
    expect(read[0]).toEqual({ ref: "S-1", has_unread: false });
  });

  it("laat andere items ongemoeid", () => {
    const items = [
      { ref: "S-1", has_unread: true },
      { ref: "S-2", has_unread: true },
    ];
    const read = applyRead(items, "S-1");
    expect(read[1]).toBe(items[1]); // ongewijzigde items behouden referentie
  });

  it("laat een onbekend ref met rust (geen crash)", () => {
    const items = [{ ref: "S-1", has_unread: true }];
    expect(applyRead(items, "X-9")).toEqual(items);
  });

  it("is idempotent: een al-gelezen item blijft ongewijzigd", () => {
    const items = [{ ref: "S-1", has_unread: false }];
    const read = applyRead(items, "S-1");
    expect(read[0]).toBe(items[0]); // ongewijzigde referentie
  });
});

describe("filterItems", () => {
  const items = [
    { ref: "S-1", title: "Fix login", assignee: "person", workload: "heavy", labels: ["bug"] },
    { ref: "S-2", title: "Docs", assignee: "claude", workload: "light", labels: [] },
  ];

  it("filtert op assignee", () => {
    expect(filterItems(items, { assignee: "claude" }).map((i) => i.ref)).toEqual(["S-2"]);
  });
  it("filtert op label", () => {
    expect(filterItems(items, { label: "bug" }).map((i) => i.ref)).toEqual(["S-1"]);
  });
  it("filtert op workload", () => {
    expect(filterItems(items, { workload: "light" }).map((i) => i.ref)).toEqual(["S-2"]);
  });
  it("herfiltert NIET op q (BETON-396) — server matcht al op ref/omschrijving/comments, client kent alleen de titel", () => {
    // BETON-376: server matcht op de ref, de titel bevat "376" niet. Vóór de
    // fix gooide filterItems deze treffer alsnog weg.
    const serverResult = [{ ref: "BETON-376", title: "Security-audit 2026-09-02" }];
    expect(filterItems(serverResult, { q: "376" }).map((i) => i.ref)).toEqual(["BETON-376"]);
  });
  it("combineert filters met AND", () => {
    expect(filterItems(items, { assignee: "person", workload: "light" })).toEqual([]);
  });
  it("geen filters → alles", () => {
    expect(filterItems(items, {})).toHaveLength(2);
  });
});

describe("filterItems — snelfilters (BETON-357)", () => {
  const ctx = { me: "person", today: "2026-09-02" };
  const items = [
    {
      ref: "S-1",
      title: "Aan mij",
      assignee: "person",
      has_unread: true,
      has_open_question: false,
      due_date: null,
      state: "todo",
    },
    {
      ref: "S-2",
      title: "Ongelezen vraag",
      assignee: "claude",
      has_unread: false,
      has_open_question: true,
      due_date: "2026-09-01",
      state: "in-progress",
    },
    {
      ref: "S-3",
      title: "Geen assignee, deze week",
      assignee: null,
      has_unread: false,
      has_open_question: false,
      due_date: "2026-09-05",
      state: "todo",
    },
    {
      ref: "S-4",
      title: "Ver in de toekomst",
      assignee: "person",
      has_unread: false,
      has_open_question: false,
      due_date: "2026-09-20",
      state: "done",
    },
  ];

  it("mine → assignee === ctx.me", () => {
    expect(filterItems(items, { mine: true }, ctx).map((i) => i.ref)).toEqual(["S-1", "S-4"]);
  });
  it("unread → has_unread", () => {
    expect(filterItems(items, { unread: true }, ctx).map((i) => i.ref)).toEqual(["S-1"]);
  });
  it("question → has_open_question", () => {
    expect(filterItems(items, { question: true }, ctx).map((i) => i.ref)).toEqual(["S-2"]);
  });
  it("unassigned → geen assignee", () => {
    expect(filterItems(items, { unassigned: true }, ctx).map((i) => i.ref)).toEqual(["S-3"]);
  });
  it("due=overdue → te laat t.o.v. ctx.today", () => {
    expect(filterItems(items, { due: "overdue" }, ctx).map((i) => i.ref)).toEqual(["S-2"]);
  });
  it("due=week → binnen 7 dagen, niet te laat", () => {
    expect(filterItems(items, { due: "week" }, ctx).map((i) => i.ref)).toEqual(["S-3"]);
  });
  it("state → exacte state-naam", () => {
    expect(filterItems(items, { state: "todo" }, ctx).map((i) => i.ref)).toEqual(["S-1", "S-3"]);
  });
  it("combineert snelfilters met AND en met de bestaande filters", () => {
    expect(
      filterItems(items, { mine: true, state: "todo" }, ctx).map((i) => i.ref),
    ).toEqual(["S-1"]);
  });
  it("today is injecteerbaar (default = vandaag) zodat tests niet aan de klok hangen", () => {
    expect(
      filterItems([{ ref: "X-1", due_date: "2020-01-01" }], { due: "overdue" }).map(
        (i) => i.ref,
      ),
    ).toEqual(["X-1"]);
  });
});

describe("describeEvent", () => {
  it("beschrijft aanmaken en reageren", () => {
    expect(describeEvent({ type: "item.created", payload: { ref: "D-1" } })).toBe(
      "ticket aangemaakt"
    );
    expect(describeEvent({ type: "comment.created", payload: {} })).toBe("reageerde");
  });

  it("beschrijft een verplaatsing met herkomst én bestemming (BETON-272)", () => {
    expect(
      describeEvent({ type: "item.moved", payload: { from: "BETON-1", to: "BRAND-9" } })
    ).toBe("verplaatst van BETON-1 naar BRAND-9");
    // Oud event zonder from → alleen bestemming.
    expect(describeEvent({ type: "item.moved", payload: { to: "BRAND-9" } })).toBe(
      "verplaatst naar BRAND-9"
    );
  });

  it("beschrijft de noodstop leesbaar i.p.v. de rauwe event-type (BETON-338)", () => {
    // Vóór BETON-338 vielen deze door naar `default` en stond er letterlijk
    // "item.locked" in de tijdlijn.
    expect(
      describeEvent({ type: "item.locked", payload: { reason: "comment_limit" } })
    ).toBe("zette het ticket op slot — te veel reacties");
    expect(describeEvent({ type: "item.locked", payload: { reason: "manual" } })).toBe(
      "zette het ticket op slot (noodstop)"
    );
    expect(
      describeEvent({ type: "item.unlocked", payload: { headroom: 20 } })
    ).toBe("haalde het slot eraf — ruimte voor 20 reacties");
    // Oud event zonder headroom (van vóór BETON-338) blijft leesbaar.
    expect(describeEvent({ type: "item.unlocked", payload: {} })).toBe(
      "haalde het slot eraf"
    );
  });

  it("beschrijft guardrail-events leesbaar i.p.v. de rauwe event-type", () => {
    expect(
      describeEvent({ type: "item.guardrail_set", payload: { guardrail: { active: true } } })
    ).toBe("zette een guardrail");
    expect(
      describeEvent({ type: "item.guardrail_lifted", payload: { guardrail: { active: false } } })
    ).toBe("hief de guardrail op");
    expect(
      describeEvent({ type: "item.guardrail_proposed", payload: { guardrail: { proposal: "set" } } })
    ).toBe("stelde een guardrail voor");
    expect(
      describeEvent({ type: "item.guardrail_proposed", payload: { guardrail: { proposal: "lift" } } })
    ).toBe("stelde voor de guardrail op te heffen");
    expect(
      describeEvent({ type: "item.guardrail_rejected", payload: { guardrail: { proposal: "set" } } })
    ).toBe("wees het guardrail-voorstel af");
  });

  it("benoemt de aanleiding van een deferred-reactivatie (BETON-354)", () => {
    // Zonder de reason-branch las deze regel als een kale statuswissel — en
    // met het toenmalige actorloze event zelfs als "@? status: deferred → todo".
    expect(
      describeEvent({
        type: "item.updated",
        payload: {
          state: { from: "deferred", to: "todo" },
          deferred_until: { from: "2000-01-01", to: null },
          reason: "deferred_expired",
        },
      })
    ).toBe("uitstel verlopen, status: deferred → todo");
    // Een gewone statuswissel blijft ongewijzigd.
    expect(
      describeEvent({
        type: "item.updated",
        payload: { state: { from: "todo", to: "in-progress" } },
      })
    ).toBe("status: todo → in-progress");
  });

  it("beschrijft een beantwoorde vraag leesbaar (BETON-274)", () => {
    expect(
      describeEvent({ type: "question.answered", payload: { comment_id: 5 } })
    ).toBe("beantwoordde de vraag");
  });

  it("beschrijft state- en priority-wijziging met herkomst (from→to)", () => {
    expect(
      describeEvent({
        type: "item.updated",
        payload: { state: { from: "todo", to: "done" } },
      })
    ).toBe("status: todo → done");
    expect(
      describeEvent({
        type: "item.updated",
        payload: {
          priority: { from: "none", to: "high" },
          state: { from: "todo", to: "todo" },
        },
      })
    ).toBe("status: todo → todo, prioriteit: Geen → Hoog");
  });

  it("beschrijft een werklast-wijziging (BETON-311)", () => {
    expect(
      describeEvent({
        type: "item.updated",
        payload: { workload: { from: null, to: "heavy" } },
      })
    ).toBe("werklast: — → Zwaar");
  });

  it("beschrijft plan-wijzigingen zonder inhoud (BETON-218: marker, geen diff)", () => {
    expect(
      describeEvent({
        type: "item.updated",
        payload: { plan_md: { changed: true, cleared: false } },
      })
    ).toBe("plan bijgewerkt");
    expect(
      describeEvent({
        type: "item.updated",
        payload: { plan_md: { changed: true, cleared: true } },
      })
    ).toBe("plan gewist");
  });

  it("beschrijft labels en het wissen daarvan", () => {
    expect(
      describeEvent({
        type: "item.updated",
        payload: { labels: { from: [], to: ["bug"] } },
      })
    ).toBe("labels: bug");
    expect(
      describeEvent({
        type: "item.updated",
        payload: { labels: { from: ["bug"], to: [] } },
      })
    ).toBe("labels gewist");
  });

  it("beschrijft assignee toewijzen en wissen", () => {
    expect(
      describeEvent({
        type: "item.updated",
        payload: { assignee: { from: null, to: "person" } },
      })
    ).toBe("toegewezen aan @person");
    expect(
      describeEvent({
        type: "item.updated",
        payload: { assignee: { from: "person", to: null } },
      })
    ).toBe("toewijzing gewist");
  });

  it("beschrijft relaties leggen en verwijderen en archiveren", () => {
    expect(
      describeEvent({ type: "relation.created", payload: { type: "blocks", target: "D-2" } })
    ).toBe("relatie gelegd: blocks D-2");
    expect(
      describeEvent({ type: "relation.deleted", payload: { type: "blocks", target: "D-2" } })
    ).toBe("relatie verwijderd: blocks D-2");
    expect(describeEvent({ type: "item.archived", payload: {} })).toBe("gearchiveerd");
  });

  it("beschrijft verplaatsen en herstellen", () => {
    expect(
      describeEvent({ type: "item.moved", payload: { from: "D-1", to: "SOS-9" } })
    ).toBe("verplaatst van D-1 naar SOS-9");
    expect(describeEvent({ type: "item.restored", payload: {} })).toBe(
      "hersteld uit archief"
    );
  });

  it("valt terug op het type bij onbekende events", () => {
    expect(describeEvent({ type: "iets.raars", payload: {} })).toBe("iets.raars");
  });
});

describe("timelineEvents", () => {
  it("laat comment-events weg maar bewaart andere activiteit", () => {
    const events = [
      { type: "item.created" },
      { type: "comment.created" },
      { type: "item.updated" },
      { type: "comment.updated" },
      { type: "relation.created" },
    ];

    expect(timelineEvents(events)).toEqual([
      { type: "item.created" },
      { type: "item.updated" },
      { type: "relation.created" },
    ]);
  });
});

describe("groupByDay", () => {
  it("groepeert events per lokale kalenderdag, volgorde behouden binnen de dag", () => {
    const events = [
      { id: 3, created_at: "2026-07-04T09:00:00" },
      { id: 2, created_at: "2026-07-04T18:30:00" },
      { id: 1, created_at: "2026-07-03T08:00:00" },
    ];
    expect(groupByDay(events)).toEqual([
      { day: "2026-07-04", events: [events[0], events[1]] },
      { day: "2026-07-03", events: [events[2]] },
    ]);
  });

  it("geeft een lege lijst terug voor geen events", () => {
    expect(groupByDay([])).toEqual([]);
    expect(groupByDay(undefined)).toEqual([]);
  });

  it("vangt een onparseerbare created_at op i.p.v. te crashen", () => {
    expect(groupByDay([{ id: 1, created_at: "onzin" }])).toEqual([
      { day: "onbekend", events: [{ id: 1, created_at: "onzin" }] },
    ]);
  });
});

describe("formatTimestamp", () => {
  const now = Date.parse("2026-07-04T12:00:00.000Z");
  it("toont 'zojuist' binnen 45s", () => {
    expect(formatTimestamp("2026-07-04T11:59:30.000Z", now)).toBe("zojuist");
  });
  it("toont minuten en uren", () => {
    expect(formatTimestamp("2026-07-04T11:30:00.000Z", now)).toBe("30 min geleden");
    expect(formatTimestamp("2026-07-04T09:00:00.000Z", now)).toBe("3 u geleden");
  });
  it("valt terug op de ruwe string bij onparsebare invoer", () => {
    expect(formatTimestamp("geen-datum", now)).toBe("geen-datum");
  });
});

describe("escapeHtml", () => {
  it("is los bruikbaar (BETON-132: bleef in board.js)", () => {
    expect(escapeHtml('a & b < c > "d"')).toBe("a &amp; b &lt; c &gt; &quot;d&quot;");
  });
});

describe("resolveProject", () => {
  const projects = [{ key: "SOS" }, { key: "BETON" }];

  it("matcht een gewenste key case-insensitief", () => {
    expect(resolveProject(projects, "BETON")).toBe("BETON");
  });

  it("valt terug op het eerste project bij onbekende/lege wens", () => {
    expect(resolveProject(projects, "NOPE")).toBe("SOS");
    expect(resolveProject(projects, null)).toBe("SOS");
  });

  it("null als er geen projecten zijn", () => {
    expect(resolveProject([], "SOS")).toBeNull();
    expect(resolveProject(undefined, null)).toBeNull();
  });
});

describe("groupMine", () => {
  const rows = [
    { ref: "SOS-1", state: "Todo" },
    { ref: "BETON-2", state: "Todo" },
    { ref: "SOS-3", state: "Done" },
  ];

  it("groepeert op state met behoud van volgorde", () => {
    expect(groupMine(rows, "state")).toEqual([
      { label: "Todo", items: [rows[0], rows[1]] },
      { label: "Done", items: [rows[2]] },
    ]);
  });

  it("groepeert op project via de ref-key", () => {
    expect(groupMine(rows, "project")).toEqual([
      { label: "SOS", items: [rows[0], rows[2]] },
      { label: "BETON", items: [rows[1]] },
    ]);
  });

  it("valt terug op restlabels bij ontbrekende state/ref", () => {
    expect(groupMine([{ ref: "x", state: "" }], "state")).toEqual([
      { label: "(geen state)", items: [{ ref: "x", state: "" }] },
    ]);
    expect(groupMine([{ ref: "x" }], "project")).toEqual([
      { label: "(overig)", items: [{ ref: "x" }] },
    ]);
  });

  it("lege/ontbrekende invoer → lege lijst", () => {
    expect(groupMine(null, "state")).toEqual([]);
    expect(groupMine([], "project")).toEqual([]);
  });
});

describe("projectKeyOf", () => {
  it("haalt de key uit een ref", () => {
    expect(projectKeyOf("BRAND-14")).toBe("BRAND");
    expect(projectKeyOf("sos-1")).toBe("SOS");
  });
  it("null bij onzin", () => {
    expect(projectKeyOf("garbage")).toBeNull();
    expect(projectKeyOf("")).toBeNull();
  });
});

describe("annotateSearchResults", () => {
  const projects = [
    { key: "SOS", name: "sos" },
    { key: "BRAND", name: "brandaris" },
  ];
  it("voegt project-key en -naam toe per resultaat", () => {
    const rows = [{ ref: "BRAND-14", title: "x" }];
    expect(annotateSearchResults(rows, projects)).toEqual([
      { ref: "BRAND-14", title: "x", project: "BRAND", projectName: "brandaris" },
    ]);
  });
  it("valt terug op de key als de naam onbekend is", () => {
    const rows = [{ ref: "OTHER-3", title: "y" }];
    expect(annotateSearchResults(rows, projects)[0].projectName).toBe("OTHER");
  });
  it("robuust bij lege input", () => {
    expect(annotateSearchResults(null, projects)).toEqual([]);
    expect(annotateSearchResults([{ ref: "SOS-1" }], null)[0].projectName).toBe("SOS");
  });
});

describe("applyBulkMove", () => {
  const items = [
    { ref: "A-1", state: "todo" },
    { ref: "A-2", state: "todo" },
    { ref: "A-3", state: "done" },
  ];

  it("zet alleen de geselecteerde refs op de nieuwe state", () => {
    const out = applyBulkMove(items, ["A-1", "A-3"], "in-progress");
    expect(out.map((i) => i.state)).toEqual(["in-progress", "todo", "in-progress"]);
  });

  it("accepteert een Set en laat de rest ongemoeid", () => {
    const out = applyBulkMove(items, new Set(["A-2"]), "done");
    expect(out.find((i) => i.ref === "A-2").state).toBe("done");
    expect(out.find((i) => i.ref === "A-1").state).toBe("todo");
  });

  it("muteert de invoer niet", () => {
    applyBulkMove(items, ["A-1"], "done");
    expect(items[0].state).toBe("todo");
  });
});

describe("refsToMove", () => {
  const items = [
    { ref: "A-1", state: "todo" },
    { ref: "A-2", state: "todo" },
    { ref: "A-3", state: "done" },
  ];

  it("laat refs vallen die al in de doelstate staan", () => {
    expect(refsToMove(items, ["A-1", "A-3"], "done")).toEqual(["A-1"]);
  });

  it("laat onbekende refs vallen en behoudt de volgorde", () => {
    expect(refsToMove(items, ["A-2", "X-9", "A-1"], "done")).toEqual(["A-2", "A-1"]);
  });

  it("lege lijst als niets hoeft te verplaatsen", () => {
    expect(refsToMove(items, ["A-3"], "done")).toEqual([]);
    expect(refsToMove(items, [], "todo")).toEqual([]);
  });
});

describe("applyBulkAssign", () => {
  const items = [
    { ref: "A-1", assignee: null },
    { ref: "A-2", assignee: "claude" },
    { ref: "A-3", assignee: "person" },
  ];

  it("zet de assignee op alleen de geselecteerde refs", () => {
    const out = applyBulkAssign(items, ["A-1", "A-3"], "zcode");
    expect(out.map((i) => i.assignee)).toEqual(["zcode", "claude", "zcode"]);
  });

  it("lege string = unassign (wordt null)", () => {
    const out = applyBulkAssign(items, ["A-2"], "");
    expect(out.find((i) => i.ref === "A-2").assignee).toBeNull();
  });

  it("accepteert een Set en laat de rest ongemoeid", () => {
    const out = applyBulkAssign(items, new Set(["A-1"]), "zcode");
    expect(out.find((i) => i.ref === "A-1").assignee).toBe("zcode");
    expect(out.find((i) => i.ref === "A-2").assignee).toBe("claude");
  });

  it("muteert de invoer niet", () => {
    applyBulkAssign(items, ["A-1"], "zcode");
    expect(items[0].assignee).toBeNull();
  });
});

describe("applyBulkLabel", () => {
  const items = [
    { ref: "A-1", labels: ["bug"] },
    { ref: "A-2", labels: [] },
    { ref: "A-3", labels: ["bug", "ui"] },
  ];

  it("voegt een label toe aan de geselecteerde refs die het nog niet hebben", () => {
    const out = applyBulkLabel(items, ["A-1", "A-2"], "ui", true);
    expect(out.find((i) => i.ref === "A-1").labels).toEqual(["bug", "ui"]);
    expect(out.find((i) => i.ref === "A-2").labels).toEqual(["ui"]);
  });

  it("laat items die het label al hebben ongewijzigd (zelfde referentie)", () => {
    const out = applyBulkLabel(items, ["A-1"], "bug", true);
    expect(out.find((i) => i.ref === "A-1")).toBe(items[0]);
  });

  it("verwijdert een label van de geselecteerde refs", () => {
    const out = applyBulkLabel(items, ["A-3"], "bug", false);
    expect(out.find((i) => i.ref === "A-3").labels).toEqual(["ui"]);
  });

  it("laat items zonder het label ongewijzigd bij verwijderen", () => {
    const out = applyBulkLabel(items, ["A-2"], "bug", false);
    expect(out.find((i) => i.ref === "A-2")).toBe(items[1]);
  });

  it("accepteert een Set en laat niet-geselecteerde refs ongemoeid", () => {
    const out = applyBulkLabel(items, new Set(["A-2"]), "ui", true);
    expect(out.find((i) => i.ref === "A-1").labels).toEqual(["bug"]);
  });

  it("muteert de invoer niet", () => {
    applyBulkLabel(items, ["A-2"], "ui", true);
    expect(items[1].labels).toEqual([]);
  });
});

describe("applyBulkField", () => {
  const items = [
    { ref: "A-1", milestone: null, workload: "light" },
    { ref: "A-2", milestone: "v1.0", workload: null },
  ];

  it("zet het gevraagde veld op de geselecteerde refs", () => {
    const out = applyBulkField(items, ["A-1"], "milestone", "v1.0");
    expect(out.find((i) => i.ref === "A-1").milestone).toBe("v1.0");
    expect(out.find((i) => i.ref === "A-2").milestone).toBe("v1.0");
  });

  it("werkt ook voor workload en laat niet-geselecteerde refs ongemoeid", () => {
    const out = applyBulkField(items, ["A-2"], "workload", "heavy");
    expect(out.find((i) => i.ref === "A-2").workload).toBe("heavy");
    expect(out.find((i) => i.ref === "A-1").workload).toBe("light");
  });

  it("muteert de invoer niet", () => {
    applyBulkField(items, ["A-1"], "milestone", "v2.0");
    expect(items[0].milestone).toBeNull();
  });
});

describe("rangeBetween", () => {
  const ordered = ["A-1", "A-2", "A-3", "A-4", "A-5"];

  it("geeft het bereik inclusief anchor en target, anchor vóór target", () => {
    expect(rangeBetween(ordered, "A-2", "A-4")).toEqual(["A-2", "A-3", "A-4"]);
  });

  it("werkt ook in omgekeerde richting (target vóór anchor)", () => {
    expect(rangeBetween(ordered, "A-4", "A-2")).toEqual(["A-2", "A-3", "A-4"]);
  });

  it("een enkele ref als anchor === target", () => {
    expect(rangeBetween(ordered, "A-3", "A-3")).toEqual(["A-3"]);
  });

  it("valt terug op alleen target als anchor niet (meer) bestaat", () => {
    expect(rangeBetween(ordered, "X-9", "A-3")).toEqual(["A-3"]);
  });

  it("lege lijst als target niet bestaat", () => {
    expect(rangeBetween(ordered, "A-1", "X-9")).toEqual([]);
  });
});

describe("toggleSelection", () => {
  it("voegt een ontbrekende ref toe", () => {
    expect(toggleSelection(["A-1"], "A-2")).toEqual(["A-1", "A-2"]);
  });

  it("haalt een aanwezige ref eruit", () => {
    expect(toggleSelection(["A-1", "A-2"], "A-1")).toEqual(["A-2"]);
  });

  it("geeft een nieuwe array terug (muteert niet)", () => {
    const sel = ["A-1"];
    const out = toggleSelection(sel, "A-2");
    expect(out).not.toBe(sel);
    expect(sel).toEqual(["A-1"]);
  });
});

describe("board.js — geen NUL-bytes in broncode (BETON-317)", () => {
  it("het bestand bevat geen letterlijke NUL-byte (regressie op de dedup-key)", async () => {
    const { readFile } = await import("node:fs/promises");
    const { fileURLToPath } = await import("node:url");
    const path = fileURLToPath(new URL("./board.js", import.meta.url));
    const source = await readFile(path, "utf-8");
    expect(source).not.toContain("\0");
  });
});

describe("isSubmitChord", () => {
  it("Cmd+Enter (Mac) is de submit-chord", () => {
    expect(isSubmitChord({ key: "Enter", metaKey: true })).toBe(true);
  });

  it("Ctrl+Enter (Windows/Linux) is de submit-chord", () => {
    expect(isSubmitChord({ key: "Enter", ctrlKey: true })).toBe(true);
  });

  it("NumpadEnter met modifier telt ook", () => {
    expect(isSubmitChord({ key: "NumpadEnter", metaKey: true })).toBe(true);
  });

  it("kale Enter is géén submit (blijft een regeleinde in de textarea)", () => {
    expect(isSubmitChord({ key: "Enter" })).toBe(false);
  });

  it("Cmd zonder Enter is niets", () => {
    expect(isSubmitChord({ key: "a", metaKey: true })).toBe(false);
  });

  it("negeert IME-compositie", () => {
    expect(isSubmitChord({ key: "Enter", metaKey: true, isComposing: true })).toBe(false);
  });

  it("is veilig bij ontbrekend event", () => {
    expect(isSubmitChord(null)).toBe(false);
  });
});

describe("sortItems (BETON-58, BETON-141)", () => {
  const items = [
    { ref: "A-1", workload: "light", created_at: "2026-01-01T00:00:00Z", last_activity_at: "2026-01-01T00:00:00Z" },
    { ref: "A-2", workload: "heavy", created_at: "2026-01-03T00:00:00Z", last_activity_at: "2026-01-03T12:00:00Z" },
    { ref: "A-3", workload: "medium", created_at: "2026-01-02T00:00:00Z", last_activity_at: "2026-01-05T00:00:00Z" },
  ];

  it("sorteert op laatst gewijzigd nieuwste eerst (default, BETON-141)", () => {
    expect(sortItems(items).map((i) => i.ref)).toEqual(["A-3", "A-2", "A-1"]);
  });

  it("sorteert op werklast zwaar→licht", () => {
    expect(sortItems(items, "workload").map((i) => i.ref)).toEqual(["A-2", "A-3", "A-1"]);
  });

  it("sorteert op aanmaakdatum nieuwste eerst", () => {
    expect(sortItems(items, "created-desc").map((i) => i.ref)).toEqual(["A-2", "A-3", "A-1"]);
  });

  it("sorteert op aanmaakdatum oudste eerst", () => {
    expect(sortItems(items, "created-asc").map((i) => i.ref)).toEqual(["A-1", "A-3", "A-2"]);
  });

  it("activity-desc valt terug op 0 bij ontbrekend last_activity_at", () => {
    const noActivity = [
      { ref: "D-1", last_activity_at: null },
      { ref: "D-2", last_activity_at: "2026-06-01T00:00:00Z" },
    ];
    // D-2 heeft activiteit, D-1 niet (0) → D-2 eerst.
    expect(sortItems(noActivity, "activity-desc").map((i) => i.ref)).toEqual(["D-2", "D-1"]);
  });

  it("is stabiel bij gelijke werklast (behoudt serverorde)", () => {
    const eq = [
      { ref: "B-1", workload: "heavy" },
      { ref: "B-2", workload: "heavy" },
      { ref: "B-3", workload: "heavy" },
    ];
    expect(sortItems(eq, "workload").map((i) => i.ref)).toEqual(["B-1", "B-2", "B-3"]);
  });

  it("behandelt ontbrekende werklast als onderaan", () => {
    const mixed = [{ ref: "C-1" }, { ref: "C-2", workload: "heavy" }];
    expect(sortItems(mixed, "workload").map((i) => i.ref)).toEqual(["C-2", "C-1"]);
  });

  it("muteert de invoer niet en is robuust bij lege input", () => {
    sortItems(items, "workload");
    expect(items.map((i) => i.ref)).toEqual(["A-1", "A-2", "A-3"]);
    expect(sortItems(null)).toEqual([]);
  });

  it("onbekende sleutel → serverorde ongemoeid", () => {
    expect(sortItems(items, "onzin").map((i) => i.ref)).toEqual(["A-1", "A-2", "A-3"]);
  });
});

describe("nextTheme (BETON-61)", () => {
  it("cyclus systeem → licht → donker → systeem", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });

  it("onbekende invoer valt terug op 'system'", () => {
    expect(nextTheme("paars")).toBe("system");
    expect(nextTheme(undefined)).toBe("system");
  });
});

describe("columnToExpandFor (BETON-200)", () => {
  const closedStates = [
    { name: "todo", closed: false },
    { name: "done", closed: true },
    { name: "cancelled", closed: true },
  ];
  const closedItems = [
    { ref: "SOS-1", state: "todo" },
    { ref: "SOS-2", state: "done" },
    { ref: "SOS-3", state: "cancelled" },
  ];

  it("geeft de kolomnaam als het item in een gesloten kolom zit", () => {
    expect(columnToExpandFor(closedItems, closedStates, "SOS-2")).toBe("done");
    expect(columnToExpandFor(closedItems, closedStates, "SOS-3")).toBe("cancelled");
  });

  it("geeft ook een werk-kolom terug voor navigatie", () => {
    expect(columnToExpandFor(closedItems, closedStates, "SOS-1")).toBe("todo");
  });

  it("geeft null bij een onbekende ref of item zonder state", () => {
    expect(columnToExpandFor(closedItems, closedStates, "SOS-999")).toBe(null);
    expect(
      columnToExpandFor([{ ref: "SOS-4", state: null }], closedStates, "SOS-4")
    ).toBe(null);
  });
});

describe("isColumnCollapsed (BETON-230)", () => {
  const openCol = { name: "todo", closed: false, items: [{ ref: "SOS-1" }] };
  const closedColWithMatch = { name: "done", closed: true, items: [{ ref: "SOS-2" }] };
  const closedColEmpty = { name: "cancelled", closed: true, items: [] };

  it("een werk-kolom start uitgeklapt", () => {
    expect(isColumnCollapsed(openCol, new Set(), false)).toBe(false);
    expect(isColumnCollapsed(openCol, new Set(), true)).toBe(false);
  });

  it("een werk-kolom kan dicht en toont zoekresultaten tijdelijk", () => {
    const collapsed = new Set(["todo"]);
    expect(isColumnCollapsed(openCol, new Set(), false, collapsed)).toBe(true);
    expect(isColumnCollapsed(openCol, new Set(), true, collapsed)).toBe(false);
    expect(isColumnCollapsed({ ...openCol, items: [] }, new Set(), true, collapsed)).toBe(true);
    expect(isColumnCollapsed(openCol, new Set(), false, collapsed)).toBe(true);
    expect(isColumnCollapsed(openCol, new Set(), false, new Set())).toBe(false);
  });

  it("een gesloten kolom is standaard ingeklapt zonder actieve filter", () => {
    expect(isColumnCollapsed(closedColWithMatch, new Set(), false)).toBe(true);
  });

  it("de gebruiker kan een gesloten kolom handmatig uitklappen", () => {
    const expanded = new Set(["done"]);
    expect(isColumnCollapsed(closedColWithMatch, expanded, false)).toBe(false);
  });

  it("een actieve zoek/filter klapt een gesloten kolom mét treffers uit", () => {
    expect(isColumnCollapsed(closedColWithMatch, new Set(), true)).toBe(false);
  });

  it("een actieve zoek/filter laat een gesloten kolom zonder treffers dicht", () => {
    expect(isColumnCollapsed(closedColEmpty, new Set(), true)).toBe(true);
  });
});

describe("stateColor (BETON-203)", () => {
  const states = [
    { name: "todo", group: "unstarted" },
    { name: "done", group: "completed" },
    { name: "review", group: "started", color: "#9b59b6" },
  ];

  it("gebruikt de per-state kleur als die is ingesteld", () => {
    expect(stateColor(states, "review")).toBe("#9b59b6");
  });

  it("valt terug op de groep-token zonder eigen kleur", () => {
    expect(stateColor(states, "todo")).toBe("var(--prio-low)");
    expect(stateColor(states, "done")).toBe("var(--success)");
  });

  it("valt terug op een neutrale kleur bij een onbekende state", () => {
    expect(stateColor(states, "weg")).toBe("var(--border-strong)");
    expect(stateColor(states, null)).toBe("var(--border-strong)");
  });
});

describe("sortRows (BETON-54)", () => {
  const rows = [
    { ref: "SOS-2", title: "Beta", workload: "light", assignee: "person", state: "todo", labels: ["x"], due_date: "2026-07-10", created_at: "2026-07-02T10:00:00Z", last_activity_at: "2026-07-02T12:00:00Z" },
    { ref: "SOS-10", title: "alpha", workload: "heavy", assignee: null, state: "done", labels: [], due_date: null, created_at: "2026-07-01T10:00:00Z", last_activity_at: "2026-07-06T00:00:00Z" },
    { ref: "SOS-1", title: "gamma", workload: "medium", assignee: "claude", state: "backlog", labels: ["a", "b"], due_date: "2026-07-05", created_at: "2026-07-03T10:00:00Z", last_activity_at: "2026-07-04T00:00:00Z" },
  ];

  it("sorteert op ref numeriek binnen project (asc)", () => {
    expect(sortRows(rows, "ref", "asc").map((r) => r.ref)).toEqual(["SOS-1", "SOS-2", "SOS-10"]);
  });

  it("sorteert op ref desc", () => {
    expect(sortRows(rows, "ref", "desc").map((r) => r.ref)).toEqual(["SOS-10", "SOS-2", "SOS-1"]);
  });

  it("sorteert op titel case-insensitief", () => {
    expect(sortRows(rows, "title", "asc").map((r) => r.title)).toEqual(["alpha", "Beta", "gamma"]);
  });

  it("sorteert op werklast (asc = licht→zwaar)", () => {
    expect(sortRows(rows, "workload", "asc").map((r) => r.workload)).toEqual(["light", "medium", "heavy"]);
    expect(sortRows(rows, "workload", "desc").map((r) => r.workload)).toEqual(["heavy", "medium", "light"]);
  });

  it("sorteert op last_activity_at als timestamp (BETON-141)", () => {
    expect(sortRows(rows, "last_activity_at", "desc").map((r) => r.ref)).toEqual(["SOS-10", "SOS-1", "SOS-2"]);
    expect(sortRows(rows, "last_activity_at", "asc").map((r) => r.ref)).toEqual(["SOS-2", "SOS-1", "SOS-10"]);
  });

  it("zet lege waarden achteraan, ongeacht richting", () => {
    expect(sortRows(rows, "assignee", "asc").map((r) => r.assignee)).toEqual(["claude", "person", null]);
    expect(sortRows(rows, "assignee", "desc").map((r) => r.assignee)).toEqual(["person", "claude", null]);
    expect(sortRows(rows, "due_date", "asc").map((r) => r.due_date)).toEqual(["2026-07-05", "2026-07-10", null]);
  });

  it("is immutable en stabiel", () => {
    const input = [...rows];
    const out = sortRows(input, "state", "asc");
    expect(input).toEqual(rows);
    expect(out).not.toBe(input);
  });

  it("onbekende sleutel → serverorde", () => {
    expect(sortRows(rows, "").map((r) => r.ref)).toEqual(["SOS-2", "SOS-10", "SOS-1"]);
  });
});

describe("nextSort (BETON-54)", () => {
  it("nieuwe kolom → asc", () => {
    expect(nextSort({ key: "title", dir: "desc" }, "state")).toEqual({ key: "state", dir: "asc" });
  });
  it("zelfde kolom → richting omdraaien", () => {
    expect(nextSort({ key: "state", dir: "asc" }, "state")).toEqual({ key: "state", dir: "desc" });
    expect(nextSort({ key: "state", dir: "desc" }, "state")).toEqual({ key: "state", dir: "asc" });
  });
  it("zonder huidige sort → asc", () => {
    expect(nextSort(null, "ref")).toEqual({ key: "ref", dir: "asc" });
  });
});

describe("LIST_COLUMNS (BETON-54)", () => {
  it("bevat de verwachte kolommen in volgorde", () => {
    expect(LIST_COLUMNS.map((c) => c.key)).toEqual([
      "ref", "title", "state", "workload", "assignee", "labels", "milestone", "last_activity_at", "created_at",
    ]);
  });
});

describe("pageTitle (BETON-345)", () => {
  it("zet het projectnaam vóóraan", () => {
    expect(pageTitle("Betonning")).toBe("Betonning · Hegemone");
    expect(pageTitle("SOS")).toBe("SOS · Hegemone");
  });

  it("valt terug op kaal 'Betonning' zonder projectnaam", () => {
    expect(pageTitle(null)).toBe("Hegemone");
    expect(pageTitle(undefined)).toBe("Hegemone");
    expect(pageTitle("")).toBe("Hegemone");
  });

  it("BETON-368: ongelezen-teller komt vooraan", () => {
    expect(pageTitle("SOS", 3)).toBe("(3) SOS · Hegemone");
    expect(pageTitle(null, 2)).toBe("(2) Hegemone");
  });

  it("BETON-368: geen teller zonder ongelezen items", () => {
    expect(pageTitle("SOS", 0)).toBe("SOS · Hegemone");
    expect(pageTitle("SOS")).toBe("SOS · Hegemone");
  });
});

describe("columnCount (BETON-451)", () => {
  const col = { items: [{}, {}], total: 40 };
  it("toont het totaal zonder filters", () => {
    expect(columnCount(col, false)).toBe(40);
  });
  it("toont het geladen aantal met een actief filter", () => {
    expect(columnCount(col, true)).toBe(2);
  });
  it("valt zonder total terug op het geladen aantal", () => {
    expect(columnCount({ items: [{}, {}, {}] }, false)).toBe(3);
  });
});


describe("milestone-sortering (BETON-446)", () => {
  it("sorteert op naam, hoofdletterongevoelig, met lege waarden altijd onderaan", () => {
    const rows = [{ milestone: null }, { milestone: "v2.0" }, { milestone: "Alpha" }, { milestone: "" }];
    expect(sortRows(rows, "milestone").map(r => r.milestone)).toEqual(["Alpha", "v2.0", null, ""]);
    expect(sortRows(rows, "milestone", "desc").map(r => r.milestone)).toEqual(["v2.0", "Alpha", null, ""]);
    expect(rows[0].milestone).toBeNull();
  });
});

describe("describeEvent wiki.compiled (BETON-463)", () => {
  it("noemt de pagina's, of dat het overgeslagen is", () => {
    expect(describeEvent({ type: "wiki.compiled", payload: { pages: ["sessies"] } })).toBe("wiki bijgewerkt: sessies");
    expect(describeEvent({ type: "wiki.compiled", payload: { skipped: true, pages: [] } })).toBe("wiki-compilatie overgeslagen");
  });
});


it("prefers an active project by default while retaining explicit archive deep links", () => {
  const projects = [{ key: "OLD", archived_at: "2026-01-01" }, { key: "LIVE" }];
  expect(resolveProject(projects, null)).toBe("LIVE");
  expect(resolveProject(projects, "OLD")).toBe("OLD");
});
