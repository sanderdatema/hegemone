import { describe, it, expect } from "vitest";
import {
  groupNotifications,
  unreadGroupCount,
  summarizeGroup,
  dueLabel,
  guardrailLabel,
  INBOX_FETCH_LIMIT,
} from "./inbox.js";

// BETON-228: de platte inbox-payload groepeert client-side per ticket. Deze
// tests borgen het pure gedrag (groeperen, sorteren, tellen, samenvatten).

const mk = (event_id, ref, reason, actor, opts = {}) => ({
  event_id,
  ref,
  reason,
  actor,
  title: opts.title ?? `Titel ${ref}`,
  created_at: opts.created_at ?? `2026-07-13T00:00:${String(event_id).padStart(2, "0")}Z`,
  read: opts.read ?? false,
});

describe("groupNotifications", () => {
  it("bundelt meerdere events over hetzelfde ticket tot één groep", () => {
    const groups = groupNotifications([
      mk(3, "SOS-1", "comment", "triage"),
      mk(2, "SOS-1", "comment", "person"),
      mk(1, "SOS-1", "update", "triage"),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].ref).toBe("SOS-1");
    expect(groups[0].total).toBe(3);
    expect(groups[0].events.map((e) => e.event_id)).toEqual([3, 2, 1]);
  });

  it("sorteert groepen nieuwste-eerst op het verste event", () => {
    const groups = groupNotifications([
      mk(1, "SOS-1", "comment", "a"),
      mk(5, "SOS-2", "comment", "b"),
      mk(3, "SOS-3", "comment", "c"),
    ]);
    expect(groups.map((g) => g.ref)).toEqual(["SOS-2", "SOS-3", "SOS-1"]);
    expect(groups[0].latestEventId).toBe(5);
  });

  it("telt ongelezen events per groep en gebruikt de verste titel/tijd", () => {
    const groups = groupNotifications([
      mk(4, "SOS-1", "comment", "a", { read: false, title: "Nieuw", created_at: "2026-07-13T10:00:00Z" }),
      mk(2, "SOS-1", "comment", "b", { read: true, title: "Oud" }),
      mk(1, "SOS-1", "update", "a", { read: true }),
    ]);
    expect(groups[0].unread).toBe(1);
    expect(groups[0].total).toBe(3);
    expect(groups[0].title).toBe("Nieuw");
    expect(groups[0].latestAt).toBe("2026-07-13T10:00:00Z");
  });

  it("vat de event-typen en actoren samen", () => {
    const groups = groupNotifications([
      mk(3, "SOS-1", "comment", "triage"),
      mk(2, "SOS-1", "comment", "person"),
      mk(1, "SOS-1", "update", "triage"),
    ]);
    // comment×2, update×1; actoren nieuwste-eerst, uniek.
    expect(groups[0].reasonCounts).toEqual({ comment: 2, update: 1 });
    expect(groups[0].summary).toBe("2 reacties, 1 wijziging — @triage, @person");
  });

  it("gebruikt enkelvoud bij één event", () => {
    const groups = groupNotifications([mk(1, "SOS-1", "mention", "person")]);
    expect(groups[0].summary).toBe("1 vermelding — @person");
  });

  it("houdt gelijke seq-nummers in verschillende projecten gescheiden", () => {
    const groups = groupNotifications([
      mk(2, "SOS-42", "comment", "a"),
      mk(1, "BRAND-42", "comment", "b"),
    ]);
    expect(groups.map((g) => g.ref)).toEqual(["SOS-42", "BRAND-42"]);
    expect(groups.map((g) => g.project)).toEqual(["SOS", "BRAND"]);
  });

  it("geeft een lege array bij lege/ontbrekende invoer", () => {
    expect(groupNotifications([])).toEqual([]);
    expect(groupNotifications(undefined)).toEqual([]);
  });

  it("valt terug op 'update' bij een onbekende reason", () => {
    const groups = groupNotifications([mk(1, "SOS-1", "onzin", "a")]);
    expect(groups[0].reasonCounts).toEqual({ update: 1 });
  });

  it("negeert null-actoren in de samenvatting", () => {
    const groups = groupNotifications([mk(1, "SOS-1", "update", null)]);
    expect(groups[0].actors).toEqual([]);
    expect(groups[0].summary).toBe("1 wijziging");
  });
});

describe("unreadGroupCount", () => {
  it("telt groepen met minstens één ongelezen event", () => {
    const items = [
      mk(4, "SOS-1", "comment", "a", { read: false }),
      mk(3, "SOS-1", "comment", "b", { read: true }),
      mk(2, "SOS-2", "comment", "c", { read: true }),
      mk(1, "SOS-3", "update", "d", { read: false }),
    ];
    // SOS-1 (1 ongelezen) + SOS-3 (ongelezen) = 2; SOS-2 volledig gelezen.
    expect(unreadGroupCount(items)).toBe(2);
  });

  it("is 0 bij een lege lijst", () => {
    expect(unreadGroupCount([])).toBe(0);
  });
});

describe("summarizeGroup", () => {
  it("kapt de actorenlijst af met +N", () => {
    const s = summarizeGroup({ comment: 5 }, ["a", "b", "c", "d", "e"]);
    expect(s).toBe("5 reacties — @a, @b, @c +2");
  });
});

describe("INBOX_FETCH_LIMIT", () => {
  it("blijft binnen de API-klem van 200", () => {
    expect(INBOX_FETCH_LIMIT).toBeLessThanOrEqual(200);
  });
});

// --- Deadlines (BETON-367) ------------------------------------------------

describe("deadline-entries", () => {
  const due = (ref, overdue, due_date) => ({
    event_id: 0,
    type: "item.due",
    reason: "due",
    actor: null,
    ref,
    title: "Iets",
    created_at: `${due_date}T00:00:00.000Z`,
    read: false,
    due_date,
    overdue,
  });

  it("telt een deadline als eigen reason in de samenvatting", () => {
    const groups = groupNotifications([due("SOS-1", true, "2026-09-01")]);
    expect(groups[0].reasonCounts).toEqual({ due: 1 });
    expect(groups[0].summary).toBe("1 deadline");
  });

  it("noemt de deadline vóór de andere redenen", () => {
    const groups = groupNotifications([
      mk(5, "SOS-1", "comment", "claude"),
      due("SOS-1", false, "2026-09-02"),
    ]);
    expect(groups[0].summary.startsWith("1 deadline, 1 reactie")).toBe(true);
  });

  it("labelt vandaag en verstreken verschillend", () => {
    expect(dueLabel(due("SOS-1", false, "2026-09-02"))).toBe("deadline vandaag");
    expect(dueLabel(due("SOS-1", true, "2026-09-01"))).toBe(
      "deadline verstreken (2026-09-01)"
    );
  });

  it("geeft een leeg label voor een gewone entry", () => {
    expect(dueLabel(mk(1, "SOS-1", "comment", "claude"))).toBe("");
  });
});

// --- Guardrail-concept (BETON-422) -----------------------------------------

describe("guardrail-voorstellen in de inbox", () => {
  const concept = (ref, kind = "set") => ({
    // Afgeleide entry, net als `due`: geen event, dus event_id 0.
    event_id: 0,
    type: "item.guardrail_proposed",
    reason: "guardrail",
    actor: "claude",
    ref,
    title: "Iets",
    created_at: "2026-09-20T10:00:00.000Z",
    read: false,
    proposal_kind: kind,
  });

  it("telt een voorstel als eigen reason in de samenvatting", () => {
    const groups = groupNotifications([concept("SOS-1")]);
    expect(groups[0].reasonCounts).toEqual({ guardrail: 1 });
    expect(groups[0].summary).toBe("1 guardrail-voorstel — @claude");
  });

  it("noemt het voorstel vóór een vermelding en ná een deadline", () => {
    const groups = groupNotifications([
      mk(5, "SOS-1", "mention", "person"),
      concept("SOS-1"),
    ]);
    expect(groups[0].summary.startsWith("1 guardrail-voorstel, 1 vermelding")).toBe(true);
  });

  it("houdt een deadline en een voorstel op hetzelfde ticket apart", () => {
    // Beide zijn afgeleid en dragen event_id 0; ze horen bij dezelfde groep maar
    // zijn twee losse regels (de rij-key in Inbox.svelte mag dus niet alleen het
    // event-id zijn).
    const groups = groupNotifications([
      {
        event_id: 0,
        type: "item.due",
        reason: "due",
        ref: "SOS-1",
        title: "Iets",
        created_at: "2026-09-02T00:00:00.000Z",
        read: false,
        due_date: "2026-09-02",
        overdue: false,
      },
      concept("SOS-1"),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].events).toHaveLength(2);
    expect(groups[0].reasonCounts).toEqual({ due: 1, guardrail: 1 });
  });

  it("labelt voorstellen en opheffingsvoorstellen verschillend", () => {
    expect(guardrailLabel(concept("SOS-1"))).toBe("stelde een guardrail voor");
    expect(guardrailLabel(concept("SOS-1", "lift"))).toBe(
      "stelde voor de guardrail op te heffen",
    );
  });

  it("geeft een leeg label voor een gewone entry", () => {
    expect(guardrailLabel(mk(1, "SOS-1", "comment", "claude"))).toBe("");
  });
});

import {
  isOptionQuestion, mergeAnswered, openCount, answeredLabel,
} from "./inbox.js";

describe("open vragen beantwoorden (BETON-456)", () => {
  const row = (id, options = ["Ja", "Nee"]) => ({ id, ref: "B-1", options });

  it("isOptionQuestion: alleen met opties", () => {
    expect(isOptionQuestion(row(1))).toBe(true);
    expect(isOptionQuestion(row(1, []))).toBe(false);
    expect(isOptionQuestion(null)).toBe(false);
  });

  it("mergeAnswered houdt een beantwoorde rij die de server niet meer levert", () => {
    const merged = mergeAnswered([row(5)], { 7: { row: row(7), index: 0 } });
    expect(merged.map((r) => [r.id, r.answeredIndex])).toEqual([[7, 0], [5, null]]);
  });

  it("mergeAnswered markeert een nog-open serverrij als beantwoord (index 0 telt)", () => {
    const merged = mergeAnswered([row(5)], { 5: { row: row(5), index: 0 } });
    expect(merged).toHaveLength(1);
    expect(merged[0].answeredIndex).toBe(0);
  });

  it("openCount telt alleen onbeantwoorde rijen", () => {
    const merged = mergeAnswered([row(5)], { 7: { row: row(7), index: 1 } });
    expect(openCount(merged)).toBe(1);
  });

  it("answeredLabel geeft de gekozen optie, leeg bij onbekende index", () => {
    expect(answeredLabel({ ...row(1), answeredIndex: 1 })).toBe("Beantwoord: Nee");
    expect(answeredLabel({ ...row(1), answeredIndex: 9 })).toBe("");
    expect(answeredLabel({ ...row(1), answeredIndex: null })).toBe("");
  });
});

import { agentAlerts, agentUnreachableLabel } from "./inbox.js";

describe("onbereikbare agents (BETON-457)", () => {
  const alert = (o = {}) => ({
    event_id: 0, reason: "agent_unreachable", ref: null, handle: "smid",
    title: "@smid", failed_count: 98, created_at: "2026-09-25T08:00:00.000Z",
    read: false, ...o,
  });

  it("label noemt aantal en d-m van de eerste mislukking", () => {
    expect(agentUnreachableLabel(alert())).toBe("98 leveringen mislukt sinds 25-9");
    expect(agentUnreachableLabel(alert({ failed_count: 1 }))).toBe("1 levering mislukt sinds 25-9");
    expect(agentUnreachableLabel(alert({ created_at: null }))).toBe("98 leveringen mislukt");
    expect(agentUnreachableLabel({ reason: "due" })).toBe("");
  });

  it("groepering slaat ticketloze entries over, tellen doet ze wel mee", () => {
    const items = [alert(), alert({ handle: "lobke" }), mk(5, "SOS-1", "comment", "a", { read: false })];
    expect(groupNotifications(items).map((g) => g.ref)).toEqual(["SOS-1"]);
    expect(agentAlerts(items)).toHaveLength(2);
    expect(unreadGroupCount(items)).toBe(3);
  });
});

import { webhookDot } from "./inbox.js";

describe("webhookDot (BETON-457)", () => {
  it("rood/groen/amber/grijs", () => {
    expect(webhookDot({ unreachable: true, failed_count: 5 })).toBe("red");
    expect(webhookDot({ unreachable: false, failed_count: 0, last_delivered_at: "x" })).toBe("green");
    expect(webhookDot({ unreachable: false, failed_count: 1, last_delivered_at: "x" })).toBe("amber");
    expect(webhookDot({ unreachable: false, failed_count: 0, last_delivered_at: null })).toBe("grey");
    expect(webhookDot(undefined)).toBe(null);
  });
});


describe("overdrachtsnotitie in inbox (BETON-469)", () => {
  it("toont de actie als groepssamenvatting wanneer de laatste entry een overdracht is", () => {
    const entry = { ...mk(50, "BETON-469", "assigned", "claude"), handover_md: "Test de knop." };
    expect(groupNotifications([entry])[0].summary).toBe("Test de knop.");
    expect(groupNotifications([entry])[0].events[0].handover_md).toBe("Test de knop.");
  });
  it("laat een nieuwere normale gebeurtenis weer de gewone samenvatting bepalen", () => {
    const entries = [{ ...mk(50, "BETON-469", "assigned", "claude"), handover_md: "Test de knop." }, mk(51, "BETON-469", "mention", "codex")];
    expect(groupNotifications(entries)[0].summary).not.toBe("Test de knop.");
  });
});
