import {setLocale} from "./lib/i18n.js";
beforeEach(() => setLocale("nl"));
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render } from "svelte/server";
import ListView from "./ListView.svelte";

describe("lijstkolommen (BETON-446)", () => {
  it("toont de einddatum bij de titel en alleen de milestone in de milestonekolom", () => {
    const { body } = render(ListView, { props: { items: [{
      ref: "BETON-446", title: "Een titel", due_date: "2020-01-01", milestone: "v2.0.0",
    }] } });
    expect(body).toMatch(/head-btn[^>]*>\s*Milestone/);
    expect(body).not.toMatch(/head-btn[^>]*>\s*Einddatum/);
    const title = body.match(/<td class="title-cell[^"]*"[^>]*>([\s\S]*?)<\/td>/)[1];
    expect(title).toContain("2020-01-01");
    expect(title).toMatch(/class="due-badge[^\"]*overdue/);
    const milestone = body.match(/<td class="mono[^"]*"[^>]*>([\s\S]*?)<\/td>/)[1];
    expect(milestone).toContain("v2.0.0");
    expect(milestone).not.toContain("2020-01-01");
  });

  it("toont geen badge of milestone als die ontbreken", () => {
    const { body } = render(ListView, { props: { items: [{ ref: "BETON-1", title: "Leeg" }] } });
    expect(body).not.toContain('class="due-badge');
    expect(body).not.toContain('class="ms-chip');
  });
});


describe("statuskeuze in de projectlijst (BETON-447)", () => {
  const props = {
    items: [{ ref: "BETON-447", title: "Status wijzigen", state: "todo" }],
    stateOptions: [{ value: "todo", label: "todo" }, { value: "done", label: "done" }],
    onstatechange: () => {},
  };
  it("biedt een toegankelijke statuskeuze per rij", () => {
    const { body } = render(ListView, { props });
    expect(body).toContain('aria-label="Status van BETON-447"');
    expect(body).toContain("list-state-select");
  });
  it("houdt de status alleen-lezen tijdens bulkselectie en zonder wijzigcallback", () => {
    for (const extra of [{ selectMode: true }, { onstatechange: null }]) {
      const { body } = render(ListView, { props: { ...props, ...extra } });
      expect(body).not.toContain('aria-label="Status van BETON-447"');
      expect(body).toContain("state-chip");
    }
  });
  it.each([{ locked: true }, { archived_at: "2026-10-25" }])("blokkeert wijzigen van beschermde rij %j", (item) => {
    const { body } = render(ListView, { props: { ...props, items: [{ ...props.items[0], ...item }] } });
    expect(body).toMatch(/<button[^>]*disabled[^>]*aria-label="Status van BETON-447"|<button[^>]*aria-label="Status van BETON-447"[^>]*disabled/);
  });
});


describe("kolommen verbergen (BETON-448)", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("verbergt kop en cel samen, maar houdt referentie en titel", () => {
    vi.stubGlobal("localStorage", { getItem: () => '["milestone","assignee","ref","title"]' });
    const { body } = render(ListView, { props: { items: [{ ref: "BETON-448", title: "Kolomkeuze", milestone: "v2.0" }] } });
    expect(body).not.toMatch(/head-btn[^>]*>\s*Milestone/);
    expect(body).not.toContain('class="assignee-cell');
    expect(body).not.toContain("v2.0");
    expect(body).toContain("BETON-448");
    expect(body).toContain("Kolomkeuze");
    expect(body.match(/<th /g)).toHaveLength(7);
    expect(body.match(/<td /g)).toHaveLength(7);
  });
  it("past lege en laadrijen aan de kolomkeuze en bulkselectie aan", () => {
    vi.stubGlobal("localStorage", { getItem: () => '["milestone","assignee"]' });
    for (const loading of [false, true]) {
      const { body } = render(ListView, { props: { items: [], selectMode: true, loading } });
      expect(body).toContain('colspan="8"');
    }
  });
});
