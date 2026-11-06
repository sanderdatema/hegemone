import { setLocale } from "./lib/i18n.js";
beforeEach(() => setLocale("nl"));
import { beforeEach, describe, it, expect } from "vitest";
import { render } from "svelte/server";
import { createRawSnippet } from "svelte";
import MarkdownEditor from "./MarkdownEditor.svelte";

// Server-side render (svelte/server) — geen jsdom in dit project (node-env),
// structurele test zoals ConfirmBar.test.js/Chip.test.js: welke elementen
// renderen bij welke props, geen echte click-simulatie. sessionStorage
// ontbreekt in deze omgeving, dus readPreviewMode() valt terug op "write" —
// elke instantie start dus in schrijf-modus.

const dropdownSnippet = (html) =>
  createRawSnippet(() => ({
    render: () => `<!---->${html}<!---->`,
  }));

describe("MarkdownEditor", () => {
  it("groeit altijd mee met de tekst via AutoTextarea (BETON-438/462)", () => {
    const { body } = render(MarkdownEditor, { props: { value: "" } });
    expect(body).toMatch(/<textarea[^>]*class="auto-ta/);
  });

  it("rendert de textarea in schrijf-modus (default)", () => {
    const { body } = render(MarkdownEditor, {
      props: { value: "hallo @person" },
    });
    expect(body).toContain("<textarea");
    expect(body).toContain("Editor");
    expect(body).toContain("Voorbeeld");
    expect(body).not.toContain("md-editor-preview");
  });

  it("haalt de Editor/Voorbeeld-toggle uit de Tab-volgorde (BETON-408)", () => {
    // Tab ná het tekstveld moet naar wat er in het formulier op volgt (de
    // verstuurknop) gaan, niet eerst langs deze schakelaar — die blijft met
    // de muis bedienbaar (geen `disabled`), alleen niet met Tab bereikbaar.
    const { body } = render(MarkdownEditor, {
      props: { value: "" },
    });
    const buttonCount = (body.match(/class="seg-btn/g) || []).length;
    const negativeTabindexCount = (body.match(/tabindex="-1"/g) || []).length;
    expect(buttonCount).toBe(2);
    expect(negativeTabindexCount).toBe(2);
  });

  it("geeft de meegegeven waarde mee aan de textarea", () => {
    const { body } = render(MarkdownEditor, {
      props: { value: "concept-tekst" },
    });
    expect(body).toContain("concept-tekst");
  });

  it("rendert de dropdown-snippet onder de textarea in schrijf-modus", () => {
    const { body } = render(MarkdownEditor, {
      props: {
        value: "",
        dropdown: dropdownSnippet('<ul class="mention-list"><li>@person</li></ul>'),
      },
    });
    expect(body).toContain('<ul class="mention-list">');
  });

  it("respecteert rows/placeholder/ariaLabel op de textarea", () => {
    const { body } = render(MarkdownEditor, {
      props: { value: "", rows: 7, placeholder: "Schrijf hier…", ariaLabel: "Plan" },
    });
    expect(body).toContain('rows="7"');
    expect(body).toContain("Schrijf hier…");
    expect(body).toContain('aria-label="Plan"');
  });
});
