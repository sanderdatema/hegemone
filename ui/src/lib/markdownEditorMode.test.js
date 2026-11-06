import { describe, it, expect } from "vitest";
import { readPreviewMode, writePreviewMode } from "./markdownEditorMode.js";

// node-testomgeving, geen jsdom → geen globale sessionStorage. Beide helpers
// guarden daarop (try/catch resp. een impliciete throw op de ontbrekende
// global) en vallen terug op "write" — nooit stilzwijgend een voorbeeld tonen.
describe("readPreviewMode/writePreviewMode (BETON-365)", () => {
  it('valt terug op "write" zonder sessionStorage', () => {
    expect(readPreviewMode()).toBe("write");
  });

  it("writePreviewMode gooit niet zonder sessionStorage", () => {
    expect(() => writePreviewMode("preview")).not.toThrow();
  });
});
