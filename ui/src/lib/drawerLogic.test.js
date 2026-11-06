import { describe, it, expect } from "vitest";
import {
  triagePendingNote,
  visibleRelationGroups,
  insertAt,
  enrichQuestionsNotice,
  mergeTimeline,
  labelPickerList,
  escapeLadder,
  propertySummary,
  emptySections,
  subscriberChips,
  commentScrollTargetId,
  shouldScrollToComment,
  relSearchMode,
  filterTimeline,
  collapseEvents,
  itemToMarkdown,
  duplicateDraft,
  neighbours,
  railProperties,
  railGroupOf,
  RAIL_ACTIONS,
  RAIL_PROPERTIES,
  RAIL_META,
  shouldStartEdit,
} from "./drawerLogic.js";

describe("visibleRelationGroups", () => {
  it("neemt de parent niet meer op (staat in de kop, BETON-471)", () => {
    expect(
      visibleRelationGroups({
        parent: "BETON-100",
        relations: { relates_to: ["BETON-101"], blocks: [] },
      })
    ).toEqual([["relates_to", ["BETON-101"]]]);
  });

  it("laat lege relatiegroepen weg zonder parent", () => {
    expect(
      visibleRelationGroups({
        parent: null,
        relations: { relates_to: [], blocks: ["BETON-102"] },
      })
    ).toEqual([["blocks", ["BETON-102"]]]);
  });

  it("geeft een lege lijst zonder item", () => {
    expect(visibleRelationGroups(null)).toEqual([]);
  });
});

describe("insertAt", () => {
  it("voegt in op de caretpositie", () => {
    expect(insertAt("hallo wereld", 5, "X")).toBe("halloX wereld");
  });

  it("voegt aan het begin toe bij caret 0", () => {
    expect(insertAt("abc", 0, "Z")).toBe("Zabc");
  });

  it("voegt aan het eind toe zonder caret", () => {
    expect(insertAt("abc", null, "Z")).toBe("abcZ");
    expect(insertAt("abc", undefined, "Z")).toBe("abcZ");
  });

  it("is veilig met lege basis", () => {
    expect(insertAt(null, undefined, "hoi")).toBe("hoi");
  });
});

describe("enrichQuestionsNotice", () => {
  it("verwijst naar de comments als er een comment geplaatst is", () => {
    expect(enrichQuestionsNotice(true)).toContain("vragen gesteld in de comments");
  });

  it("meldt het als er geen comment geplaatst kon worden", () => {
    expect(enrichQuestionsNotice(false)).toContain("kon geen comment plaatsen");
  });
});

describe("mergeTimeline", () => {
  it("voegt comments en events chronologisch samen", () => {
    const comments = [
      { id: 1, created_at: "2026-01-01T10:00:00Z", body_md: "eerst" },
      { id: 2, created_at: "2026-01-01T12:00:00Z", body_md: "laatst" },
    ];
    const events = [{ id: 5, type: "item.updated", created_at: "2026-01-01T11:00:00Z" }];
    const merged = mergeTimeline(comments, events);
    expect(merged.map((e) => e.kind)).toEqual(["comment", "event", "comment"]);
    expect(merged[0].comment.body_md).toBe("eerst");
    expect(merged[1].event.type).toBe("item.updated");
  });

  it("houdt bij gelijk tijdstip de comment vóór het event (stabiel)", () => {
    const t = "2026-01-01T10:00:00Z";
    const merged = mergeTimeline(
      [{ id: 1, created_at: t }],
      [{ id: 9, type: "item.created", created_at: t }]
    );
    expect(merged.map((e) => e.kind)).toEqual(["comment", "event"]);
  });

  it("geeft unieke keys en werkt met lege input", () => {
    expect(mergeTimeline()).toEqual([]);
    const merged = mergeTimeline([{ id: 1, created_at: "2026-01-01T10:00:00Z" }], []);
    expect(merged[0].key).toBe("c1");
  });

  it("filtert historische antwoord-comments uit de tijdlijn (BETON-265)", () => {
    const comments = [
      // Een vraag met een historisch antwoord-comment (id 7).
      {
        id: 3,
        kind: "question",
        created_at: "2026-01-01T10:00:00Z",
        answer_comment_id: 7,
      },
      { id: 7, created_at: "2026-01-01T10:05:00Z", body_md: "het antwoord" },
      { id: 8, created_at: "2026-01-01T10:10:00Z", body_md: "gewone comment" },
    ];
    const merged = mergeTimeline(comments, []);
    const ids = merged.map((e) => e.comment.id);
    expect(ids).toContain(3);
    expect(ids).toContain(8);
    expect(ids).not.toContain(7);
  });
});

describe("labelPickerList", () => {
  const labels = [{ name: "bug" }, { name: "backend" }, { name: "ui" }];

  it("markeert toegekende labels", () => {
    expect(labelPickerList(labels, ["ui"], "")).toEqual([
      { name: "bug", assigned: false },
      { name: "backend", assigned: false },
      { name: "ui", assigned: true },
    ]);
  });

  it("filtert op de zoekterm (case-insensitief, substring)", () => {
    expect(labelPickerList(labels, [], "ba").map((l) => l.name)).toEqual(["backend"]);
    expect(labelPickerList(labels, [], "UI").map((l) => l.name)).toEqual(["ui"]);
  });

  it("is veilig met lege input", () => {
    expect(labelPickerList()).toEqual([]);
  });
});

describe("escapeLadder", () => {
  it("kiest de binnenste actieve sub-state eerst", () => {
    expect(escapeLadder({ mention: true, editingTitle: true })).toBe("mention");
    expect(escapeLadder({ editingTitle: true, confirm: true })).toBe("editingTitle");
    expect(escapeLadder({ confirm: true, unsavedComment: true })).toBe("confirm");
  });

  it("herkent de relatie-autocomplete-rung", () => {
    expect(escapeLadder({ relMatches: true })).toBe("relMatches");
  });

  it("herkent de #-autocomplete-rung (BETON-254), vóór relMatches", () => {
    expect(escapeLadder({ hashMatches: true })).toBe("hashMatches");
    expect(escapeLadder({ hashMatches: true, relMatches: true })).toBe("hashMatches");
    expect(escapeLadder({ mention: true, hashMatches: true })).toBe("mention");
  });

  it("vangt het guardrail-formulier af vóór een bevestiging (BETON-420)", () => {
    expect(escapeLadder({ editingGuardrail: true })).toBe("editingGuardrail");
    expect(escapeLadder({ editingGuardrail: true, confirm: true })).toBe("editingGuardrail");
    expect(escapeLadder({ editingPlan: true, editingGuardrail: true })).toBe("editingPlan");
  });

  it("geeft null als niets openstaat (drawer mag sluiten)", () => {
    expect(escapeLadder({})).toBeNull();
    expect(escapeLadder()).toBeNull();
  });
});

describe("propertySummary", () => {
  const workloadOpts = [
    { value: "light", label: "Licht" },
    { value: "heavy", label: "Zwaar" },
  ];

  it("vat toegewezen/werklast/datum samen", () => {
    expect(
      propertySummary(
        { assignee: "claude", workload: "heavy", due_date: "2026-07-13T00:00:00Z" },
        { workloadOpts }
      )
    ).toMatchObject({ assignee: "@claude", workload: "Zwaar", due: "2026-07-13" });
  });

  it("toont lege-staat-teksten", () => {
    expect(propertySummary({}, { workloadOpts })).toMatchObject({
      assignee: "niet toegewezen",
      due: "geen datum",
      defer: null,
      milestone: "geen milestone",
    });
  });

  it("is veilig zonder item", () => {
    expect(propertySummary(null).assignee).toBe("niet toegewezen");
  });
});

describe("emptySections", () => {
  it("markeert alles leeg voor een kaal item", () => {
    expect(emptySections({})).toEqual({ plan: true, subtasks: true, relations: true });
  });

  it("is veilig zonder item", () => {
    expect(emptySections(null)).toEqual({ plan: true, subtasks: true, relations: true });
  });

  it("plan is niet leeg als has_plan waar is", () => {
    expect(emptySections({ has_plan: true }).plan).toBe(false);
  });

  it("subtaken tellen zowel via children als children_detail", () => {
    expect(emptySections({ children: ["BETON-2"] }).subtasks).toBe(false);
    expect(emptySections({ children_detail: [{ ref: "BETON-2" }] }).subtasks).toBe(false);
    expect(emptySections({ children: [], children_detail: [] }).subtasks).toBe(true);
  });

  it("relaties zijn niet leeg bij een gevulde relatiegroep; een parent telt niet (BETON-471)", () => {
    expect(emptySections({ parent: "BETON-1" }).relations).toBe(true);
    expect(emptySections({ relations: { blocks: ["BETON-3"] } }).relations).toBe(false);
    expect(emptySections({ relations: { blocks: [] } }).relations).toBe(true);
  });
});

describe("subscriberChips", () => {
  it("zet niet-gemute volgers vóór gemute en sorteert elk alfabetisch", () => {
    expect(
      subscriberChips([
        { handle: "zoe", muted: false },
        { handle: "bob", muted: true },
        { handle: "amy", muted: false },
      ])
    ).toEqual([
      { handle: "amy", muted: false, following: false },
      { handle: "zoe", muted: false, following: false },
      { handle: "bob", muted: true, following: false },
    ]);
  });

  it("ontdubbelt op handle en normaliseert muted naar boolean", () => {
    expect(
      subscriberChips([
        { handle: "amy" },
        { handle: "amy", muted: true },
      ])
    ).toEqual([{ handle: "amy", muted: false, following: false }]);
  });

  it("negeert lege invoer en items zonder handle", () => {
    expect(subscriberChips([])).toEqual([]);
    expect(subscriberChips([{ muted: true }, null])).toEqual([]);
  });

  // BETON-369: expliciete volgers zijn herkenbaar naast de afgeleide union.
  it("draagt de following-vlag mee", () => {
    expect(subscriberChips([{ handle: "mies", following: true }])).toEqual([
      { handle: "mies", muted: false, following: true },
    ]);
  });
});

describe("commentScrollTargetId", () => {
  it("gebruikt de id uit de POST-response", () => {
    expect(commentScrollTargetId({ id: 42 }, [{ id: 1 }, { id: 2 }])).toBe(42);
  });

  it("valt terug op de nieuwste comment als de response geen id heeft", () => {
    expect(commentScrollTargetId(null, [{ id: 1 }, { id: 5 }, { id: 3 }])).toBe(5);
    expect(commentScrollTargetId(undefined, [{ id: 7 }])).toBe(7);
  });

  it("geeft null als er niets is om naartoe te scrollen", () => {
    expect(commentScrollTargetId(null, [])).toBe(null);
    expect(commentScrollTargetId({}, [{}])).toBe(null);
  });
});

describe("shouldScrollToComment", () => {
  const comments = [{ id: 1 }, { id: 42 }];
  it("scrollt alleen als het item geladen is en de comment bestaat", () => {
    expect(shouldScrollToComment(42, false, comments)).toBe(true);
  });
  it("niet zolang het item nog laadt (anker bestaat nog niet)", () => {
    expect(shouldScrollToComment(42, true, comments)).toBe(false);
  });
  it("niet zonder doel", () => {
    expect(shouldScrollToComment(null, false, comments)).toBe(false);
    expect(shouldScrollToComment(undefined, false, comments)).toBe(false);
  });
  it("niet als de comment niet in de tijdlijn staat", () => {
    expect(shouldScrollToComment(99, false, comments)).toBe(false);
    expect(shouldScrollToComment(42, false, [])).toBe(false);
  });
});

describe("mergeTimeline — wachtende comment (BETON-338)", () => {
  const held = { id: 7, author: "lobke", body_md: "in de wacht", created_at: "2026-01-01T00:00:00Z" };

  it("zet de wachtende comment onderaan, ook al is hij ouder", () => {
    const comments = [{ id: 1, created_at: "2026-06-01T00:00:00Z" }];
    const out = mergeTimeline(comments, [], held);
    expect(out.at(-1).kind).toBe("held");
    expect(out.at(-1).held.body_md).toBe("in de wacht");
  });

  it("laat de tijdlijn ongemoeid zonder wachtende comment (regressie)", () => {
    const comments = [{ id: 1, created_at: "2026-06-01T00:00:00Z" }];
    const events = [{ id: 2, type: "item.locked", created_at: "2026-06-02T00:00:00Z" }];
    expect(mergeTimeline(comments, events)).toEqual(mergeTimeline(comments, events, null));
    expect(mergeTimeline(comments, events).every((e) => e.kind !== "held")).toBe(true);
  });

  it("geeft de held-entry een eigen sleutel die niet met comments botst", () => {
    const out = mergeTimeline([{ id: 7, created_at: "2026-06-01T00:00:00Z" }], [], held);
    const keys = out.map((e) => e.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("collapseEvents (BETON-364)", () => {
  function ev(id, type = "item.updated") {
    return { kind: "event", key: `e${id}`, at: `2026-06-01T00:00:0${id}Z`, event: { id, type, actor: `u${id}`, created_at: `2026-06-01T00:00:0${id}Z` } };
  }
  function cm(id) {
    return { kind: "comment", key: `c${id}`, at: `2026-06-01T00:00:0${id}Z`, comment: { id } };
  }

  it("klapt 3 opeenvolgende events samen tot één groep", () => {
    const timeline = [ev(1), ev(2), ev(3)];
    const out = collapseEvents(timeline);
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("event-group");
    expect(out[0].events).toHaveLength(3);
    expect(out[0].actors).toEqual(["u1", "u2", "u3"]);
    expect(out[0].first).toBe(timeline[0].event);
    expect(out[0].last).toBe(timeline[2].event);
  });

  it("laat 2 opeenvolgende events los staan (onder de drempel van 3)", () => {
    const timeline = [ev(1), ev(2)];
    const out = collapseEvents(timeline);
    expect(out).toEqual(timeline);
  });

  it("een comment breekt de reeks", () => {
    const timeline = [ev(1), ev(2), ev(3), cm(4), ev(5), ev(6), ev(7)];
    const out = collapseEvents(timeline);
    expect(out.map((e) => e.kind)).toEqual(["event-group", "comment", "event-group"]);
  });

  it("laat een lege of ontbrekende tijdlijn ongemoeid", () => {
    expect(collapseEvents([])).toEqual([]);
    expect(collapseEvents(undefined)).toEqual([]);
  });
});

describe("filterTimeline (BETON-364)", () => {
  const comment = { kind: "comment", key: "c1", at: "t", comment: { id: 1 } };
  const held = { kind: "held", key: "h1", at: "t", held: { id: 2 } };
  const questionAnswered = {
    kind: "event",
    key: "e1",
    at: "t",
    event: { id: 3, type: "question.answered" },
  };
  const stateChanged = {
    kind: "event",
    key: "e2",
    at: "t",
    event: { id: 4, type: "item.updated" },
  };
  const timeline = [comment, held, questionAnswered, stateChanged];

  it('mode "all" geeft de tijdlijn ongewijzigd terug', () => {
    expect(filterTimeline(timeline, "all")).toEqual(timeline);
  });

  it('mode "comments" houdt comments, held én question.answered — gewone events vallen weg', () => {
    const out = filterTimeline(timeline, "comments");
    expect(out).toContain(comment);
    expect(out).toContain(held);
    expect(out).toContain(questionAnswered);
    expect(out).not.toContain(stateChanged);
  });
});

describe("relSearchMode (BETON-347)", () => {
  it("een pure cijferquery is een ref-lookup, al bij 1 teken", () => {
    expect(relSearchMode("1")).toBe("ref");
    expect(relSearchMode("12")).toBe("ref");
  });

  it("tekst blijft een text-lookup, met de drempel van 2 tekens", () => {
    expect(relSearchMode("a")).toBe(null);
    expect(relSearchMode("ab")).toBe("text");
    expect(relSearchMode("wikilinks")).toBe("text");
  });

  it("cijfers mét letters (bv. een ref-fragment 'B1') zijn een text-lookup, geen ref-lookup", () => {
    expect(relSearchMode("B1")).toBe("text");
    expect(relSearchMode("BETON-12")).toBe("text");
  });

  it("lege of te korte tekstquery zoekt niet (null)", () => {
    expect(relSearchMode("")).toBe(null);
    expect(relSearchMode(null)).toBe(null);
    expect(relSearchMode(undefined)).toBe(null);
  });
});

describe("itemToMarkdown (BETON-373)", () => {
  const item = {
    ref: "BETON-373",
    title: "Voorbeeld ticket",
    state: "in-progress",
    workload: "medium",
    assignee: "person",
    labels: ["ui", "bug"],
    milestone: "v1.4.0",
    due_date: "2026-07-01T00:00:00Z",
    description_md: "Een omschrijving.",
  };

  it("bevat de kop, metadata-regel en omschrijving", () => {
    const out = itemToMarkdown(item, { comments: [] });
    expect(out).toContain("# BETON-373 — Voorbeeld ticket");
    expect(out).toContain("**Status:** in-progress");
    expect(out).toContain("**Werklast:**");
    expect(out).toContain("**Toegewezen:** @person");
    expect(out).toContain("**Labels:** ui, bug");
    expect(out).toContain("**Milestone:** v1.4.0");
    expect(out).toContain("**Due:** 2026-07-01");
    expect(out).toContain("## Omschrijving");
    expect(out).toContain("Een omschrijving.");
  });

  it("laat de Plan-sectie weg zonder plan", () => {
    expect(itemToMarkdown(item, { comments: [] })).not.toContain("## Plan");
  });

  it("neemt het plan op als het gegeven is", () => {
    const out = itemToMarkdown(item, { comments: [], plan: "Stap 1: doe X." });
    expect(out).toContain("## Plan");
    expect(out).toContain("Stap 1: doe X.");
  });

  it("rendert gewone comments als kop + body", () => {
    const out = itemToMarkdown(item, {
      comments: [{ id: 1, author: "claude", body_md: "Zie PR.", created_at: "2026-07-01T10:00:00Z" }],
    });
    expect(out).toContain("### @claude · 2026-07-01 10:00");
    expect(out).toContain("Zie PR.");
  });

  it("rendert een vraag als citaat en het antwoord als losse regel", () => {
    const out = itemToMarkdown(item, {
      comments: [
        {
          id: 2,
          author: "triage",
          kind: "question",
          body_md: "Welke aanpak?",
          question_options: ["A", "B"],
          created_at: "2026-07-01T10:00:00Z",
          answered_at: "2026-07-01T11:00:00Z",
          answered_by: "person",
          answer_option_index: 1,
        },
      ],
    });
    expect(out).toContain("> Vraag: Welke aanpak?");
    expect(out).toContain("Antwoord: B");
  });

  it("slaat historische antwoord-comments over (answer_comment_id-koppeling)", () => {
    const out = itemToMarkdown(item, {
      comments: [
        { id: 3, author: "triage", kind: "question", body_md: "Vraag?", created_at: "t", answer_comment_id: 4 },
        { id: 4, author: "person", body_md: "Antwoord-comment (oud).", created_at: "t" },
      ],
    });
    expect(out).not.toContain("Antwoord-comment (oud).");
  });

  it("toont een placeholder zonder reacties", () => {
    expect(itemToMarkdown(item, { comments: [] })).toContain("_geen reacties_");
  });
});

describe("duplicateDraft (BETON-373)", () => {
  it("zet de kopie-suffix en neemt labels/werklast/milestone/parent over", () => {
    const item = {
      title: "Origineel",
      description_md: "Body.",
      labels: ["ui"],
      workload: "light",
      milestone: "v1.4.0",
      parent: "BETON-100",
    };
    expect(duplicateDraft(item)).toEqual({
      title: "Origineel (kopie)",
      description: "Body.",
      labels: ["ui"],
      workload: "light",
      milestone: "v1.4.0",
      parent: "BETON-100",
    });
  });

  it("laat comments/relaties/subtaken weg (geeft alleen het draft-veldenset)", () => {
    const out = duplicateDraft({ title: "X", comments: [{ id: 1 }], children: ["Y-1"] });
    expect(Object.keys(out).sort()).toEqual(
      ["description", "labels", "milestone", "parent", "title", "workload"].sort(),
    );
  });

  it("geeft veilige defaults zonder item", () => {
    expect(duplicateDraft(null)).toEqual({
      title: " (kopie)",
      description: "",
      labels: [],
      workload: "",
      milestone: "",
      parent: null,
    });
  });

  it("labels-array is een kopie, geen referentie naar het origineel", () => {
    const original = { title: "X", labels: ["a"] };
    const out = duplicateDraft(original);
    out.labels.push("b");
    expect(original.labels).toEqual(["a"]);
  });
});

describe("neighbours (BETON-362)", () => {
  const refs = ["SOS-1", "SOS-2", "SOS-3"];

  it("geeft prev/next in het midden", () => {
    expect(neighbours(refs, "SOS-2")).toEqual({ prev: "SOS-1", next: "SOS-3", index: 2, total: 3 });
  });

  it("geen prev aan het begin", () => {
    expect(neighbours(refs, "SOS-1")).toEqual({ prev: null, next: "SOS-2", index: 1, total: 3 });
  });

  it("geen next aan het eind", () => {
    expect(neighbours(refs, "SOS-3")).toEqual({ prev: "SOS-2", next: null, index: 3, total: 3 });
  });

  it("ref niet in de lijst → geen prev/next, index -1, total blijft de lijstgrootte", () => {
    expect(neighbours(refs, "SOS-99")).toEqual({ prev: null, next: null, index: -1, total: 3 });
  });

  it("lege lijst", () => {
    expect(neighbours([], "SOS-1")).toEqual({ prev: null, next: null, index: -1, total: 0 });
  });

  it("enkel item: geen prev, geen next", () => {
    expect(neighbours(["SOS-1"], "SOS-1")).toEqual({ prev: null, next: null, index: 1, total: 1 });
  });
});

describe("railProperties (BETON-414)", () => {
  const full = {
    milestone: "v1.4.0",
    due_date: "2026-09-20",
    deferred_until: "2026-09-15",
    labels: ["bug"],
    children_detail: [{ ref: "BETON-2", state: "todo" }],
    relations: { blocks: ["BETON-3"] },
  };
  const milestones = [{ name: "v1.4.0" }];
  const subs = [{ handle: "person" }];

  function byKey(rows) {
    return Object.fromEntries(rows.map((r) => [r.key, r]));
  }

  it("de drie mutaties zitten in de actiegroep, niet in de lijst", () => {
    expect(RAIL_ACTIONS).toEqual(["state", "workload", "assignee"]);
    for (const key of RAIL_ACTIONS) {
      expect(railGroupOf(key)).toBe("actions");
      expect(RAIL_PROPERTIES).not.toContain(key);
    }
  });

  it("de tijdstempels zijn read-only meta, geen bewerkbare eigenschap", () => {
    expect(RAIL_META).toEqual(["created", "updated"]);
    expect(railGroupOf("created")).toBe("meta");
    expect(railGroupOf("updated")).toBe("meta");
  });

  it("samen dekken de drie lagen de twaalf groepen van de oude rail", () => {
    expect(RAIL_ACTIONS.length + RAIL_PROPERTIES.length + RAIL_META.length).toBe(12);
  });

  it("onbekende sleutel hoort nergens", () => {
    expect(railGroupOf("onzin")).toBe(null);
  });

  it("gevulde eigenschappen zijn niet leeg en dragen hun waarde", () => {
    const rows = byKey(railProperties(full, { subscribers: subs, milestones }));
    expect(rows.milestone).toEqual({
      key: "milestone",
      label: "Milestone",
      text: "v1.4.0",
      empty: false,
    });
    expect(rows.due.text).toBe("2026-09-20");
    expect(rows.defer.text).toBe("2026-09-15");
    expect(rows.labels.empty).toBe(false);
    expect(rows.subtasks.empty).toBe(false);
    expect(rows.relations.empty).toBe(false);
    expect(rows.followers.empty).toBe(false);
  });

  it("een eigenschap zonder waarde verdwijnt niet: hij krijgt een stille regel", () => {
    const rows = byKey(railProperties({}, { milestones }));
    expect(rows.milestone).toMatchObject({ empty: true, text: "geen milestone" });
    expect(rows.due).toMatchObject({ empty: true, text: "geen datum" });
    expect(rows.defer).toMatchObject({ empty: true, text: "niet uitgesteld" });
    expect(rows.labels).toMatchObject({ empty: true, text: "geen labels" });
    expect(rows.subtasks).toMatchObject({ empty: true, text: "geen subtaken" });
    expect(rows.relations).toMatchObject({ empty: true, text: "geen relaties" });
    expect(rows.followers).toMatchObject({ empty: true, text: "geen volgers" });
  });

  it("zonder milestones in het project valt die regel weg", () => {
    const keys = railProperties(full, { milestones: [] }).map((r) => r.key);
    expect(keys).not.toContain("milestone");
    expect(keys).toEqual(["due", "defer", "labels", "subtasks", "relations", "followers"]);
  });

  it("vaste volgorde, met milestone vooraan", () => {
    const keys = railProperties(full, { milestones }).map((r) => r.key);
    expect(keys).toEqual(RAIL_PROPERTIES);
  });

  it("subtaken tellen ook als alleen de rauwe children-lijst gevuld is", () => {
    const rows = byKey(railProperties({ children: ["BETON-9"] }, { milestones: [] }));
    expect(rows.subtasks.empty).toBe(false);
  });

  it("een parent telt niet als relatie (staat in de kop, BETON-471)", () => {
    const rows = byKey(railProperties({ parent: "BETON-1" }, { milestones: [] }));
    expect(rows.relations.empty).toBe(true);
  });

  it("null-item geeft alle regels leeg terug", () => {
    const rows = railProperties(null, { milestones: [] });
    expect(rows.every((r) => r.empty)).toBe(true);
  });
});

describe("shouldStartEdit (BETON-415)", () => {
  const plainTarget = { closest: () => null };
  function ticketTarget() {
    return { closest: (sel) => (sel === "[data-ticket]" ? {} : null) };
  }
  function linkTarget() {
    return { closest: (sel) => (sel === "a" ? {} : null) };
  }

  it("lege selectie: gewone klik start de edit", () => {
    expect(shouldStartEdit(plainTarget, "")).toBe(true);
  });

  it("geen selectie meegegeven (default) start de edit", () => {
    expect(shouldStartEdit(plainTarget)).toBe(true);
  });

  it("niet-lege selectie voorkomt de edit", () => {
    expect(shouldStartEdit(plainTarget, "een gekopieerde regel")).toBe(false);
  });

  it("een ticketref houdt zijn eigen actie, ook zonder selectie", () => {
    expect(shouldStartEdit(ticketTarget(), "")).toBe(false);
  });

  it("een link houdt zijn eigen actie, ook zonder selectie", () => {
    expect(shouldStartEdit(linkTarget(), "")).toBe(false);
  });

  it("null-target zonder selectie start gewoon de edit", () => {
    expect(shouldStartEdit(null, "")).toBe(true);
  });
});

import {
  commentAlwaysOpen,
  commentCollapse,
  commentLineCount,
  COMMENT_COLLAPSE_ABOVE,
} from "./drawerLogic.js";

describe("comment inklappen (BETON-458)", () => {
  it("klapt alleen in boven de gemeten drempel", () => {
    expect(commentCollapse({ height: COMMENT_COLLAPSE_ABOVE }).collapsible).toBe(false);
    expect(commentCollapse({ height: COMMENT_COLLAPSE_ABOVE + 1 })).toMatchObject({ collapsible: true, collapsed: true });
  });
  it("nog niet gemeten = nooit inklappen", () => {
    expect(commentCollapse({})).toMatchObject({ collapsible: false, collapsed: false });
  });
  it("uitgeklapt of altijd-open klapt niet in", () => {
    expect(commentCollapse({ height: 900, expanded: true })).toMatchObject({ collapsible: true, collapsed: false });
    expect(commentCollapse({ height: 900, alwaysOpen: true })).toMatchObject({ collapsible: false, collapsed: false });
  });
  it("de eerste alinea blijft zichtbaar: maxHeight volgt het eerste blok", () => {
    expect(commentCollapse({ height: 900, firstBlockHeight: 300 }).maxHeight).toBe(300);
    expect(commentCollapse({ height: 900, firstBlockHeight: 50 }).maxHeight).toBe(240);
    // net boven de drempel maar nauwelijks winst → niet inklappen
    expect(commentCollapse({ height: 330, firstBlockHeight: 300 }).collapsible).toBe(false);
  });
  it("nieuwste, eigen en vastgepinde comment staan altijd open", () => {
    const ctx = { lastCommentId: 9, meHandle: "person", pinnedId: 4 };
    expect(commentAlwaysOpen({ id: 9, author: "claude" }, ctx)).toBe(true);
    expect(commentAlwaysOpen({ id: 1, author: "person" }, ctx)).toBe(true);
    expect(commentAlwaysOpen({ id: 4, author: "claude" }, ctx)).toBe(true);
    expect(commentAlwaysOpen({ id: 1, author: "claude" }, ctx)).toBe(false);
    expect(commentAlwaysOpen({ id: 1, author: null }, { meHandle: null })).toBe(false);
  });
  it("telt regels", () => {
    expect(commentLineCount("a\nb\nc\n\n")).toBe(3);
    expect(commentLineCount(null)).toBe(1);
  });
});

import { followerAvatars, selfFollowState, followChoiceOps } from "./drawerLogic.js";
import { emptyAddLinks } from "./guardrail.js";

describe("volgersrail (BETON-459)", () => {
  it("avatarrij: max 5 en +N, ontdubbeld", () => {
    const subs = ["a", "b", "c", "d", "e", "f", "g", "a"].map((handle) => ({ handle, muted: handle === "b" }));
    const r = followerAvatars(subs);
    expect(r.shown).toHaveLength(5);
    expect(r.extra).toBe(2);
    expect(followerAvatars([]).extra).toBe(0);
  });
  it("eigen status: gedempt wint van volgend", () => {
    expect(selfFollowState({ following: true, muted: true }).label).toBe("Gedempt");
    expect(selfFollowState({ following: true }).label).toBe("Volgend");
    expect(selfFollowState({}).label).toBe("Volgen");
  });
  it("keuze → calls", () => {
    expect(followChoiceOps("follow", { muted: true })).toEqual(["unmute", "follow"]);
    expect(followChoiceOps("follow", { following: true })).toEqual([]);
    expect(followChoiceOps("mute", { following: true })).toEqual(["mute"]);
    expect(followChoiceOps("mute", { muted: true })).toEqual([]);
    expect(followChoiceOps("normal", { following: true, muted: true })).toEqual(["unmute", "unfollow"]);
  });
});

describe("emptyAddLinks (BETON-459)", () => {
  it("leeg ticket, mens: Plan en Guardrail", () => {
    expect(emptyAddLinks({ isHuman: true })).toEqual(["plan", "guardrail"]);
  });
  it("agent ziet geen Guardrail-link", () => {
    expect(emptyAddLinks({ isHuman: false })).toEqual(["plan"]);
  });
  it("sectie met inhoud of in bewerking krijgt geen link", () => {
    expect(emptyAddLinks({ isHuman: true, hasPlan: true, guardrailVisible: true })).toEqual([]);
    expect(emptyAddLinks({ isHuman: true, planEditing: true })).toEqual(["guardrail"]);
  });
});

describe("triagePendingNote (BETON-478)", () => {
  it("toont de regel bij een openstaande toewijzing aan triage", () => {
    expect(triagePendingNote({ assignee: "triage", triage_pending: true })).toBe("triage reageert zo");
  });
  it("zwijgt als triage klaar is, het ticket elders staat of er geen item is", () => {
    expect(triagePendingNote({ assignee: "triage", triage_pending: false })).toBeNull();
    expect(triagePendingNote({ assignee: "person", triage_pending: true })).toBeNull();
    expect(triagePendingNote(null)).toBeNull();
  });
});

describe("gelokaliseerde ticketexport en meldingen", () => {
  it("exporteert een leeg ticket zonder ontbrekende locale en behoudt Nederlandse defaults", () => {
    const out = itemToMarkdown({ ref: "TEST-1", title: "Eigen titel" });
    expect(out).toContain("niet toegewezen");
    expect(out).toContain("geen milestone");
    expect(out).toContain("## Omschrijving");
  });

  it("vertaalt Engelse exportmetadata en behoudt inhoud en refs", () => {
    const item = { ref: "TEST-1", title: "Eigen titel", description_md: "Mijn inhoud", state: "eigen-status", labels: ["privé"], workload: "medium" };
    const comments = [{ id: 1, author: "voorbeeld", body_md: "Eigen reactie", created_at: "2026-11-05T12:00:00Z" }];
    const before = JSON.stringify({ item, comments });
    const out = itemToMarkdown(item, { locale: "en", comments, plan: "Eigen plan" });
    for (const text of ["## Description", "## Comments", "**Assignee:** unassigned", "**Workload:**", "TEST-1", "Eigen titel", "Mijn inhoud", "eigen-status", "privé", "Eigen reactie", "Eigen plan"]) expect(out).toContain(text);
    expect(out).not.toContain("geen milestone");
    expect(JSON.stringify({ item, comments })).toBe(before);
    expect(itemToMarkdown({}, { locale: "en" })).toContain("_no comments_");
    expect(duplicateDraft(item, "en").title).toBe("Eigen titel (copy)");
  });

  it("vertaalt beide vraagmeldingen", () => {
    expect(enrichQuestionsNotice(true, "en")).toContain("posted questions");
    expect(enrichQuestionsNotice(false, "en")).toContain("could not post a comment");
  });
});

it('vertaalt de triagewachtmelding met behoud van de statuspoort', () => {
  expect(triagePendingNote({ assignee: 'triage', triage_pending: true }, 'en')).toBe('triage will respond shortly');
  expect(triagePendingNote({ assignee: 'builder', triage_pending: true }, 'en')).toBeNull();
});
