import { describe, it, expect } from "vitest";
import { render } from "svelte/server";
import Select from "./Select.svelte";

// Server-side render, structureel (zoals MarkdownEditor.test.js): het menu zelf
// staat in een portal en rendert pas bij openen; hier gaat het om de trigger.

const OPTS = [
  { value: "", label: "alle labels" },
  { value: "bug", label: "bug" },
  { value: "feature", label: "feature" },
];

describe("Select (BETON-439)", () => {
  it("rendert een knop i.p.v. een native select", () => {
    const { body } = render(Select, { props: { value: "bug", options: OPTS, ariaLabel: "Label" } });
    expect(body).not.toContain("<select");
    expect(body).toMatch(/<button[^>]*class="select-trigger/);
    expect(body).toContain('aria-label="Label"');
  });

  it("toont het label van de gekozen waarde", () => {
    const { body } = render(Select, { props: { value: "feature", options: OPTS } });
    expect(body).toMatch(/select-trigger-label[^>]*>feature</);
  });

  it("een lege waarde toont de lege optie", () => {
    const { body } = render(Select, { props: { value: "", options: OPTS } });
    expect(body).toMatch(/select-trigger-label[^>]*>alle labels</);
  });

  it("valt terug op de placeholder als de waarde geen optie is", () => {
    const { body } = render(Select, {
      props: { value: "", options: OPTS.slice(1), placeholder: "kies…" },
    });
    expect(body).toMatch(/select-trigger-label[^>]*>kies…</);
  });

  it("vindt het label ook in een groep", () => {
    const { body } = render(Select, {
      props: {
        value: "claude",
        options: [{ value: "", label: "niemand" }],
        groups: [{ label: "Coding-agents", options: [{ value: "claude", label: "@claude" }] }],
      },
    });
    expect(body).toMatch(/select-trigger-label[^>]*>@claude</);
  });

  it("geeft de extra klasse door aan de knop", () => {
    const { body } = render(Select, { props: { value: "", options: OPTS, class: "rail-select" } });
    expect(body).toMatch(/class="select-trigger rail-select/);
  });
});
