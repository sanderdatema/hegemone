import { describe, it, expect } from "vitest";
import { render } from "svelte/server";
import DiffView from "./DiffView.svelte";

// Server-side render (svelte/server) — geen jsdom in dit project (node-env,
// zie vite.config.js), structurele test zoals ConfirmBar.test.js.

describe("DiffView", () => {
  it("rendert +/− tekens en tekst per segment", () => {
    const { body } = render(DiffView, {
      props: {
        segments: [
          { type: "ctx", text: "regel een" },
          { type: "del", text: "oude regel" },
          { type: "add", text: "nieuwe regel" },
        ],
      },
    });
    expect(body).toContain("regel een");
    expect(body).toContain("oude regel");
    expect(body).toContain("nieuwe regel");
    expect(body).toContain(">+<");
    expect(body).toContain(">−<");
    expect(body).toContain('class="diff-line ctx');
    expect(body).toContain('class="diff-line del');
    expect(body).toContain('class="diff-line add');
  });

  it("valt terug op een spatie voor lege regeltekst", () => {
    const { body } = render(DiffView, {
      props: { segments: [{ type: "ctx", text: "" }] },
    });
    expect(body).toContain('<span class="diff-text');
    expect(body).toMatch(/<span class="diff-text[^"]*">\s<\/span>/);
  });

  it("lege segments-lijst rendert een lege diff-container", () => {
    const { body } = render(DiffView, { props: { segments: [] } });
    expect(body).toContain('class="diff diff-surface');
  });

  it("variant bepaalt de omkaderingsklasse (surface vs bordered)", () => {
    const surface = render(DiffView, { props: { segments: [] } }).body;
    expect(surface).toContain("diff-surface");

    const bordered = render(DiffView, {
      props: { segments: [], variant: "bordered" },
    }).body;
    expect(bordered).toContain("diff-bordered");
  });

  it("zet aria-label alleen als expliciet meegegeven", () => {
    const bare = render(DiffView, { props: { segments: [] } }).body;
    expect(bare).not.toContain("aria-label=");

    const labeled = render(DiffView, {
      props: { segments: [], ariaLabel: "Wijzigingen t.o.v. de vorige versie" },
    }).body;
    expect(labeled).toContain('aria-label="Wijzigingen t.o.v. de vorige versie"');
  });
});
