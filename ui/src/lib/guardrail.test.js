import { describe, it, expect } from "vitest";
import {
  GUARDRAIL_MAX_CHARS,
  guardrailMeta,
  guardrailValidation,
  guardrailProposalMeta,
  proposalDiffSegments,
  proposalReviewLabel,
  scopeSummary,
} from "./guardrail.js";

describe("guardrailMeta", () => {
  it("leest `active` uit has_guardrail en herrekent hem niet zelf", () => {
    // De backend-definitie heeft drie termen (tekst, niet opgeheven, niet
    // gearchiveerd). Een gearchiveerd ticket houdt zijn tekst, maar de
    // guardrail is dan inactief — dat mag de UI niet anders zien.
    const item = {
      has_guardrail: false,
      guardrail_md: "Houd prompts kort.",
      guardrail_lifted_at: null,
      archived_at: "2026-09-01T10:00:00.000Z",
    };
    expect(guardrailMeta(item).active).toBe(false);
    expect(guardrailMeta({ ...item, has_guardrail: true }).active).toBe(true);
  });

  it("geeft tekst, reviewdatum, wie en wanneer terug", () => {
    const m = guardrailMeta({
      has_guardrail: true,
      guardrail_md: "Houd prompts kort.",
      guardrail_review_by: "2026-12-01",
      guardrail_set_by: "person",
      guardrail_set_at: "2026-09-01T10:00:00.000Z",
      guardrail_scope: ["prompts"],
    });
    expect(m.text).toBe("Houd prompts kort.");
    expect(m.reviewBy).toBe("2026-12-01");
    expect(m.setBy).toBe("person");
    expect(m.setAt).toBe("2026-09-01T10:00:00.000Z");
    expect(m.scope).toEqual(["prompts"]);
  });

  it("markeert een reviewdatum van vandaag of eerder als overdue", () => {
    // De review-finder draait op `guardrail_review_by <= date('now')`, dus
    // vandaag is al aan de beurt.
    const base = { has_guardrail: true, guardrail_md: "x" };
    const meta = (d) => guardrailMeta({ ...base, guardrail_review_by: d }, "2026-09-24");
    expect(meta("2026-09-25").overdue).toBe(false);
    expect(meta("2026-09-24").overdue).toBe(true);
    expect(meta("2026-09-01").overdue).toBe(true);
  });

  it("is niet overdue als de guardrail niet actief is", () => {
    const m = guardrailMeta(
      { has_guardrail: false, guardrail_md: "x", guardrail_review_by: "2026-01-01" },
      "2026-09-24",
    );
    expect(m.overdue).toBe(false);
  });

  it("verdraagt null en een leeg item", () => {
    expect(guardrailMeta(null).active).toBe(false);
    expect(guardrailMeta({}).scope).toEqual([]);
  });
});

describe("guardrailValidation", () => {
  const ok = { text: "Houd prompts kort.", reviewBy: "2026-12-01" };

  it("keurt een geldige guardrail goed", () => {
    expect(guardrailValidation(ok, "2026-09-24")).toEqual({ ok: true, error: "" });
  });

  it("weigert lege of whitespace-only tekst", () => {
    expect(guardrailValidation({ ...ok, text: "   " }, "2026-09-24").ok).toBe(false);
    expect(guardrailValidation({ ...ok, text: "" }, "2026-09-24").error).toMatch(/wat en waarom/);
  });

  it("weigert tekst boven de cap en noemt het aantal tekens", () => {
    const r = guardrailValidation(
      { ...ok, text: "x".repeat(GUARDRAIL_MAX_CHARS + 1) },
      "2026-09-24",
    );
    expect(r.ok).toBe(false);
    expect(r.error).toContain(String(GUARDRAIL_MAX_CHARS + 1));
    expect(r.error).toContain(String(GUARDRAIL_MAX_CHARS));
  });

  it("laat precies de cap toe", () => {
    expect(
      guardrailValidation({ ...ok, text: "x".repeat(GUARDRAIL_MAX_CHARS) }, "2026-09-24").ok,
    ).toBe(true);
  });

  it("eist een ISO-datum", () => {
    expect(guardrailValidation({ ...ok, reviewBy: "" }, "2026-09-24").ok).toBe(false);
    expect(guardrailValidation({ ...ok, reviewBy: "1-12-2026" }, "2026-09-24").ok).toBe(false);
  });

  it("weigert een datum in het verleden maar laat vandaag toe", () => {
    // Spiegelt de backend: die weigert op `review_by < vandaag`, dus vandaag
    // mag — en is dan meteen aan review toe.
    expect(guardrailValidation({ ...ok, reviewBy: "2026-09-23" }, "2026-09-24").ok).toBe(false);
    expect(guardrailValidation({ ...ok, reviewBy: "2026-09-24" }, "2026-09-24").ok).toBe(true);
  });
});

describe("scopeSummary", () => {
  it("noemt een lege scope projectbreed", () => {
    expect(scopeSummary([])).toBe("Projectbreed");
    expect(scopeSummary(null)).toBe("Projectbreed");
  });

  it("somt de labelnamen op", () => {
    expect(scopeSummary(["prompts", "llm"])).toBe("prompts, llm");
  });
});

// --- Concept naast de actieve versie (BETON-422) ---------------------------

describe("guardrailProposalMeta", () => {
  const proposal = {
    kind: "set",
    guardrail_md: "Houd prompts kort.",
    review_by: "2099-01-01",
    reason: null,
    scope: ["prompts"],
    proposed_by: "claude",
    proposed_at: "2026-09-20T10:00:00.000Z",
  };

  it("geeft null zonder concept", () => {
    expect(guardrailProposalMeta(null)).toBe(null);
    expect(guardrailProposalMeta({})).toBe(null);
    expect(guardrailProposalMeta({ guardrail_proposal: null })).toBe(null);
  });

  it("leest het concept los van de actieve versie", () => {
    // Een concept bindt niets: het mag nooit met de actieve velden samenvallen.
    const m = guardrailProposalMeta({
      has_guardrail: true,
      guardrail_md: "De geldende tekst.",
      guardrail_proposal: proposal,
    });
    expect(m.kind).toBe("set");
    expect(m.isLift).toBe(false);
    expect(m.text).toBe("Houd prompts kort.");
    expect(m.reviewBy).toBe("2099-01-01");
    expect(m.scope).toEqual(["prompts"]);
    expect(m.proposedBy).toBe("claude");
    expect(m.proposedAt).toBe("2026-09-20T10:00:00.000Z");
  });

  it("herkent een opheffingsvoorstel met zijn reden", () => {
    const m = guardrailProposalMeta({
      guardrail_proposal: { ...proposal, kind: "lift", guardrail_md: null, reason: "achterhaald" },
    });
    expect(m.isLift).toBe(true);
    expect(m.reason).toBe("achterhaald");
  });
});

describe("proposalReviewLabel", () => {
  it("toont de voorgestelde datum als hij nog geldt", () => {
    expect(proposalReviewLabel("2026-09-25", "2026-09-24")).toBe("Review op 2026-09-25");
  });

  it("zegt dat de datum bij goedkeuren volgt als er geen is", () => {
    // `approve` vult dan zelf de default-horizon in.
    expect(proposalReviewLabel(null, "2026-09-24")).toBe("Reviewdatum volgt bij goedkeuren");
  });

  it("behandelt een verstreken voorgestelde datum als afwezig", () => {
    // De backend vervangt hem door vandaag + 90; een datum tonen die de server
    // niet gaat gebruiken is liegen.
    expect(proposalReviewLabel("2026-09-01", "2026-09-24")).toBe(
      "Reviewdatum volgt bij goedkeuren",
    );
  });
});

describe("proposalDiffSegments", () => {
  const active = (over = {}) =>
    guardrailMeta({
      has_guardrail: true,
      guardrail_md: "Oude tekst.",
      guardrail_review_by: "2099-01-01",
      guardrail_scope: ["prompts"],
      ...over,
    });
  const concept = (over = {}) =>
    guardrailProposalMeta({
      guardrail_proposal: {
        kind: "set",
        guardrail_md: "Nieuwe tekst.",
        review_by: "2099-06-01",
        scope: ["ui"],
        proposed_by: "claude",
        proposed_at: "2026-09-20T10:00:00.000Z",
        ...over,
      },
    });

  it("geeft null zonder actieve guardrail (dan valt er niets te vergelijken)", () => {
    expect(proposalDiffSegments(active({ has_guardrail: false }), concept())).toBe(null);
  });

  it("geeft null voor een opheffingsvoorstel", () => {
    expect(proposalDiffSegments(active(), concept({ kind: "lift", reason: "weg" }))).toBe(
      null,
    );
  });

  it("geeft null zonder concept", () => {
    expect(proposalDiffSegments(active(), null)).toBe(null);
  });

  it("zet tekst, scope en reviewdatum als regels tegenover elkaar", () => {
    const segs = proposalDiffSegments(active(), concept(), "2026-09-24");
    const del = segs.filter((s) => s.type === "del").map((s) => s.text);
    const add = segs.filter((s) => s.type === "add").map((s) => s.text);
    expect(del).toContain("Oude tekst.");
    expect(add).toContain("Nieuwe tekst.");
    expect(del).toContain("Scope: prompts");
    expect(add).toContain("Scope: ui");
    expect(del).toContain("Review op 2099-01-01");
    expect(add).toContain("Review op 2099-06-01");
  });

  it("houdt een ongewijzigde regel als context", () => {
    const segs = proposalDiffSegments(
      active(),
      concept({ scope: ["prompts"] }),
      "2026-09-24",
    );
    expect(segs.filter((s) => s.type === "ctx").map((s) => s.text)).toContain(
      "Scope: prompts",
    );
  });
});

describe("guardrailpresentatie per taal", () => {
  it("vertaalt validatie zonder de regels te wijzigen", () => {
    const today = "2026-11-05";
    const cases = [
      [{}, "text cannot be empty"],
      [{ text: "x".repeat(1001) }, "maximum 1000"],
      [{ text: "Bewaar deze tekst" }, "Choose a review date"],
      [{ text: "Bewaar deze tekst", reviewBy: "2026-11-04" }, "cannot be in the past"],
    ];
    for (const [input, message] of cases) {
      expect(guardrailValidation(input, today, "en").error).toContain(message);
      expect(guardrailValidation(input, today, "en").ok).toBe(guardrailValidation(input, today, "nl").ok);
    }
    expect(guardrailValidation({ text: "Bewaar deze tekst", reviewBy: today }, today, "en")).toEqual({ ok: true, error: "" });
  });

  it("behoudt inhoud en scopes en voorkomt vertaalverschillen in de diff", () => {
    const text = "Bewaar de Nederlandse invoer.";
    const scope = ["privé-label"];
    expect(scopeSummary(scope, "en")).toBe("privé-label");
    expect(scopeSummary([], "en")).toBe("Project-wide");
    expect(proposalReviewLabel(null, "2026-11-05", "en")).toBe("Review date set on approval");
    const active = { active: true, text, scope, reviewBy: "2099-01-01" };
    const proposal = { text, scope, reviewBy: "2099-01-01" };
    const snapshot = JSON.stringify({ active, proposal });
    const segments = proposalDiffSegments(active, proposal, "2026-11-05", "en");
    expect(segments.some(s => s.type === "add" || s.type === "del")).toBe(false);
    expect(segments.map(s => s.text).join("\n")).toContain(text);
    expect(segments.map(s => s.text).join("\n")).toContain("Review on 2099-01-01");
    expect(JSON.stringify({ active, proposal })).toBe(snapshot);
  });
});
