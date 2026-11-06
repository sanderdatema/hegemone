import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// BETON-353: de antwoordmodule toonde de default "Bevestig" i.p.v. "Ja,
// antwoord" op de bevestigknop van een gekozen meerkeuze-optie. Oorzaak:
// role/ariaLabel/confirmLabel op die <ConfirmBar> gebruikten typografische
// aanhalingstekens (” “) als attribuut-scheidingsteken i.p.v. gewone
// aanhalingstekens — geen geldige Svelte/HTML-attribuutsyntax, waardoor
// confirmLabel niet als prop doorkwam en de component op zijn default terugviel.
// Structurele bron-scan (geen component-render: Drawer.svelte heeft een grote
// prop-oppervlakte en side-effecting mounted-logica die dat onpraktisch maakt).
const drawerSource = readFileSync(
  fileURLToPath(new URL("./Drawer.svelte", import.meta.url)),
  "utf-8",
);

describe("Drawer.svelte — antwoordmodule confirm-bar markup", () => {
  it("gebruikt gewone aanhalingstekens als attribuut-delimiter (geen typografische)", () => {
    const block = drawerSource.slice(
      drawerSource.indexOf('ariaLabel={$uiText("ui.confirmAnswer")}'),
    );
    const confirmBarBlock = block.slice(0, block.indexOf("/>") + 2);
    expect(confirmBarBlock).not.toContain("“");
    expect(confirmBarBlock).not.toContain("”");
  });

  it('geeft de bevestigknop het label "Ja, antwoord" mee', () => {
    const idx = drawerSource.indexOf('ariaLabel={$uiText("ui.confirmAnswer")}');
    expect(idx).toBeGreaterThan(-1);
    const block = drawerSource.slice(idx, idx + 400);
    expect(block).toContain('confirmLabel={$uiText("ui.yesAnswer")}');
  });
});

// BETON-403: het bewerken van een bestaande reactie gebruikte een kale
// <textarea bind:value={editCommentText}> zonder ondrop/onpaste — slepen of
// plakken van een afbeelding deed daar dus niets. Structurele bron-scan,
// zelfde reden als hierboven (Drawer.svelte is niet praktisch te renderen).
describe("Drawer.svelte — afbeelding slepen naar een reactie in bewerkmodus", () => {
  it("hangt ondrop/onpaste aan de edit-comment-textarea, gericht op editComment", () => {
    const idx = drawerSource.indexOf("bind:value={editCommentText}");
    expect(idx).toBeGreaterThan(-1);
    const block = drawerSource.slice(idx - 50, idx + 400);
    expect(block).toContain('handleImageDrop(e, "editComment")');
    expect(block).toMatch(/ondrop=\{.*handleImageDrop/);
    expect(block).toMatch(/onpaste=\{.*handleImageDrop/);
  });
});

// BETON-420: een guardrail bindt élke agent, dus zetten/wijzigen/opheffen is
// mens-only — een agent stelt hem voor via de MCP-tool. De backend weigert een
// agent met 403; deze scan is de grendel op de UI-kant, zodat de knoppen niet
// per ongeluk buiten de mens-poort belanden. Structurele bron-scan, zelfde
// reden als hierboven.
describe("Drawer.svelte — guardrail-sectie", () => {
  const section = drawerSource.slice(
    drawerSource.indexOf("<!-- Guardrail (BETON-420)"),
    drawerSource.indexOf("<!-- Plan/handover (BETON-218)"),
  );

  it("knipt de sectie goed uit de bron (anker blijft bestaan)", () => {
    expect(section.length).toBeGreaterThan(200);
  });

  // De sectiekop apart, want de buitenste {#if} van de sectie noemt de
  // mens-poort óók (voor de "of hij is actief"-tak). Zou je die meenemen, dan
  // slaagt de assertie ook als de knoppen buiten de poort staan.
  const head = section.slice(
    section.indexOf("<SectionHead>"),
    section.indexOf("</SectionHead>"),
  );

  it("zet de zet-/wijzig-knop in de kop achter de mens-poort", () => {
    expect(head).toContain("startGuardrailEdit");
    const gate = head.indexOf('me?.kind === "human"');
    expect(gate).toBeGreaterThan(-1);
    // De poort opent vóór de knoppen, niet erna.
    expect(gate).toBeLessThan(head.indexOf("startGuardrailEdit"));
    expect(gate).toBeLessThan(head.indexOf("confirmLiftGuardrail = true"));
  });

  it("zet de opheffen-knop achter dezelfde poort en achter een bevestiging", () => {
    expect(section).toContain("confirmLiftGuardrail = true");
    expect(section).toContain("onconfirm={doLiftGuardrail}");
    expect(section).toContain('confirmLabel={$uiText("ui.yesLift")}');
  });

  it("toont een actieve guardrail óók zonder mens-poort (agents lezen mee)", () => {
    // BETON-422: een openstaand concept opent dezelfde poort — een agent moet
    // kunnen lezen dat er een wijziging aankomt, ook als er (nog) niets geldt.
    expect(section).toContain(
      "{#if guardrail.active || guardrailProposal || editingGuardrail}",
    );
  });

  // BETON-422: het conceptblok is leesbaar voor iedereen, maar bedienen is
  // mens-only — de backend geeft een agent 403 op approve/reject.
  const concept = section.slice(
    section.indexOf("{#if guardrailProposal && !editingGuardrail}"),
    section.indexOf("{#if confirmLiftGuardrail}"),
  );

  it("knipt het conceptblok goed uit de bron", () => {
    expect(concept.length).toBeGreaterThan(200);
  });

  it("zet goedkeuren, wijzigen en afwijzen achter de mens-poort", () => {
    const gate = concept.indexOf('me?.kind === "human"');
    expect(gate).toBeGreaterThan(-1);
    for (const marker of [
      "doApproveGuardrail",
      "startGuardrailEditFromProposal",
      "confirmRejectGuardrail = true",
    ]) {
      expect(concept.indexOf(marker)).toBeGreaterThan(gate);
    }
  });

  it("toont de inhoud van het concept vóór (en dus buiten) die poort", () => {
    const gate = concept.indexOf('me?.kind === "human"');
    expect(concept.indexOf("guardrailProposalDiff")).toBeLessThan(gate);
    expect(concept.indexOf("guardrailProposal.reason")).toBeLessThan(gate);
  });

  it("zet afwijzen achter een bevestiging", () => {
    expect(section).toContain("onconfirm={doRejectGuardrail}");
    expect(section).toContain('confirmLabel={$uiText("ui.yesReject")}');
  });

  it("gebruikt gewone aanhalingstekens als attribuut-delimiter (BETON-353)", () => {
    expect(section).not.toContain("“");
    expect(section).not.toContain("”");
  });
});
