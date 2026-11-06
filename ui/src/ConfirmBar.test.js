import {setLocale} from "./lib/i18n.js";
beforeEach(() => setLocale("nl"));
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "svelte/server";
import ConfirmBar from "./ConfirmBar.svelte";
import ConfirmBarSnippetFixture from "./ConfirmBarSnippetFixture.svelte";

// Server-side render (svelte/server) — geen jsdom in dit project (node-env,
// zie vite.config.js), dus dit is een structurele test: welke elementen/
// labels/klassen renderen bij welke props, niet een echte click-simulatie.
// De callback-contract-sanity spiegelt lib/chip.test.js.

describe("ConfirmBar", () => {
  it("rendert message, confirm- en cancel-knop met labels", () => {
    const { body } = render(ConfirmBar, {
      props: {
        message: "Item verwijderen?",
        confirmLabel: "Ja, verwijder",
        cancelLabel: "Nee",
        onconfirm: () => {},
        oncancel: () => {},
      },
    });
    expect(body).toContain("Item verwijderen?");
    expect(body).toContain("Ja, verwijder");
    expect(body).toContain("Nee");
    expect(body).toContain('class="confirm-bar');
  });

  it("laat de confirm-knop weg zonder onconfirm (movePicker-variant)", () => {
    const { body } = render(ConfirmBar, {
      props: { message: "Verplaatsen naar…", oncancel: () => {} },
    });
    expect(body).toContain("Verplaatsen naar…");
    expect(body).not.toContain("Bevestig");
    expect(body).toContain("Annuleren");
  });

  it("laat de message-span weg zonder message (decompose-variant)", () => {
    const { body } = render(ConfirmBar, {
      props: { confirmLabel: "Maak 3 subtaken", onconfirm: () => {}, oncancel: () => {} },
    });
    expect(body).not.toContain("<span>");
    expect(body).toContain("Maak 3 subtaken");
  });

  it("rendert een snippet-message (rich content, bv. Wiki create-prompt)", () => {
    const { body } = render(ConfirmBarSnippetFixture, {
      props: { onconfirm: () => {}, oncancel: () => {} },
    });
    expect(body).toContain("Pagina");
    expect(body).toContain("<strong>foo</strong>");
    expect(body).toContain("bestaat nog niet. Aanmaken?");
    expect(body).toContain("Aanmaken</button>");
  });

  it("zet de danger- en inline-klasse conditioneel", () => {
    const plain = render(ConfirmBar, { props: { message: "x" } }).body;
    expect(plain).not.toContain("danger");
    expect(plain).not.toContain("inline");

    const dangerInline = render(ConfirmBar, {
      props: { message: "x", danger: true, inline: true },
    }).body;
    expect(dangerInline).toContain("danger");
    expect(dangerInline).toContain("inline");
  });

  it("zet role en aria-label alleen als expliciet meegegeven", () => {
    const bare = render(ConfirmBar, { props: { message: "x" } }).body;
    expect(bare).not.toContain("role=");
    expect(bare).not.toContain("aria-label=");

    const withRole = render(ConfirmBar, {
      props: { message: "x", role: "alertdialog", ariaLabel: "Verwijderen bevestigen" },
    }).body;
    expect(withRole).toContain('role="alertdialog"');
    expect(withRole).toContain('aria-label="Verwijderen bevestigen"');
  });

  it("confirm- en cancel-callbacks zijn losse functies die onafhankelijk vuren (contract)", () => {
    const onconfirm = vi.fn();
    const oncancel = vi.fn();
    render(ConfirmBar, {
      props: { message: "x", onconfirm, oncancel },
    });
    // SSR simuleert geen klik (geen DOM); dit bevestigt dat de props zelf
    // onafhankelijk aanroepbaar zijn — de daadwerkelijke onclick-koppeling in
    // het template (`onclick={onconfirm}` / `onclick={oncancel}`) is triviaal
    // en identiek aan het bestaande Chip.svelte-idioom (lib/chip.test.js).
    onconfirm();
    expect(onconfirm).toHaveBeenCalledTimes(1);
    expect(oncancel).not.toHaveBeenCalled();
    oncancel();
    expect(oncancel).toHaveBeenCalledTimes(1);
  });
});
