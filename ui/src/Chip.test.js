import {setLocale} from "./lib/i18n.js";
beforeEach(() => setLocale("nl"));
import { beforeEach, describe, it, expect } from "vitest";
import { render } from "svelte/server";
import { createRawSnippet } from "svelte";
import Chip from "./Chip.svelte";

// Server-side render (svelte/server) — geen jsdom in dit project (node-env,
// zie vite.config.js), structurele test zoals ConfirmBar.test.js/DiffView.test.js.
// Chip.svelte is de gedeelde primitive achter de label-chips en -pickers in
// ProjectSettings/Drawer/NewItem (BETON-221/331) — deze test dekt het
// template zelf; lib/chip.test.js dekt de pure class/element-helpers.

const textSnippet = (text) =>
  createRawSnippet(() => ({
    render: () => `<!---->${text}<!---->`,
  }));

describe("Chip", () => {
  it("rendert een span met tone-klasse voor niet-interactieve chips", () => {
    const { body } = render(Chip, {
      props: { tone: "label", hue: 120, children: textSnippet("bug") },
    });
    expect(body).toContain("bug");
    expect(body).toContain("tone-label");
    expect(body).toContain("<span");
    expect(body).not.toContain("<button");
  });

  it("rendert een button + 'selected'-klasse voor een interactieve, aan-staande toggle", () => {
    const { body } = render(Chip, {
      props: {
        tone: "label",
        hue: 30,
        selected: true,
        onclick: () => {},
        children: textSnippet("feature"),
      },
    });
    expect(body).toContain("<button");
    expect(body).toContain("interactive");
    expect(body).toContain("selected");
    expect(body).toContain('aria-pressed="true"');
  });

  it("toont géén 'selected' als de toggle uit staat", () => {
    const { body } = render(Chip, {
      props: { tone: "label", onclick: () => {}, children: textSnippet("x") },
    });
    expect(body).not.toContain("selected");
    expect(body).toContain('aria-pressed="false"');
  });

  it("rendert de sluit-x als removable, met de eigen aria-label", () => {
    const { body } = render(Chip, {
      props: { tone: "label", removable: true, children: textSnippet("x") },
    });
    expect(body).toContain("chip-x");
    expect(body).toContain('aria-label="Verwijderen"');
    // removable alleen (geen onclick/href) blijft een span, de x is de enige button.
    expect(body).not.toContain("<button\n");
  });

  it("laat de sluit-x weg zonder removable", () => {
    const { body } = render(Chip, {
      props: { tone: "label", children: textSnippet("x") },
    });
    expect(body).not.toContain("chip-x");
  });

  it("valt terug op tone-neutral bij een onbekende/ontbrekende tone", () => {
    const { body } = render(Chip, {
      props: { children: textSnippet("ref") },
    });
    expect(body).toContain("tone-neutral");
  });

  it("zet title en aria-label alleen als expliciet meegegeven", () => {
    const bare = render(Chip, { props: { children: textSnippet("x") } }).body;
    expect(bare).not.toContain("title=");
    expect(bare).not.toContain("aria-label=");

    const labeled = render(Chip, {
      props: { title: "Verwijder label", ariaLabel: "Label x", children: textSnippet("x") },
    }).body;
    expect(labeled).toContain('title="Verwijder label"');
    expect(labeled).toContain('aria-label="Label x"');
  });
});

it('vertaalt het verwijderlabel als de browsertaal Engels is', () => {
  setLocale('en');
  expect(render(Chip, {props:{removable:true}}).body).toContain('aria-label="Remove"');
});
