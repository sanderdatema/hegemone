import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { textFieldAction } from "./autoTextarea.js";

const both = { canSubmit: true, canCancel: true };

describe("textFieldAction (BETON-462)", () => {
  it("Cmd/Ctrl+Enter dient in, kale Enter niet", () => {
    expect(textFieldAction({ key: "Enter", metaKey: true }, both)).toBe("submit");
    expect(textFieldAction({ key: "Enter", ctrlKey: true }, both)).toBe("submit");
    expect(textFieldAction({ key: "Enter" }, both)).toBe(null);
    expect(textFieldAction({ key: "Enter", shiftKey: true }, both)).toBe(null);
  });
  it("niets tijdens IME-compositie", () => {
    expect(textFieldAction({ key: "Enter", metaKey: true, isComposing: true }, both)).toBe(null);
    expect(textFieldAction({ key: "Escape", isComposing: true }, both)).toBe(null);
  });
  it("zonder onsubmit/oncancel doet een toets niets", () => {
    const none = { canSubmit: false, canCancel: false };
    expect(textFieldAction({ key: "Enter", metaKey: true }, none)).toBe(null);
    expect(textFieldAction({ key: "Escape" }, none)).toBe(null);
  });
  it("vastgehouden Cmd+Enter (repeat) dient niet opnieuw in", () => {
    expect(textFieldAction({ key: "Enter", metaKey: true, repeat: true }, both)).toBe("swallow");
  });
  it("Escape annuleert alleen met oncancel", () => {
    expect(textFieldAction({ key: "Escape" }, both)).toBe("cancel");
  });
  // BETON-444: comment bewerken + Cmd+Enter moet opslaan.
  it("comment bewerken: Cmd+Enter geeft submit", () => {
    expect(textFieldAction({ key: "Enter", metaKey: true }, { canSubmit: true, canCancel: false })).toBe("submit");
  });
});

// Grendel: geen kale <textarea buiten AutoTextarea/MarkdownEditor (BETON-462).
describe("geen kale <textarea", () => {
  const src = join(dirname(fileURLToPath(import.meta.url)), "..");
  const ALLOWED = new Set(["AutoTextarea.svelte"]);
  it("alleen AutoTextarea.svelte bevat <textarea", () => {
    const offenders = readdirSync(src)
      .filter((f) => f.endsWith(".svelte") && !ALLOWED.has(f))
      .filter((f) => /<textarea[\s>]/.test(readFileSync(join(src, f), "utf8")));
    expect(offenders).toEqual([]);
  });
});
