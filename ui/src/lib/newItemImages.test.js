import { describe, it, expect } from "vitest";
import {
  imagePlaceholder,
  resolvePlaceholder,
  removePlaceholder,
  stripPlaceholders,
  buildPendingImage,
} from "./newItemImages.js";

describe("imagePlaceholder", () => {
  it("bevat de bestandsnaam en het id, zodat gelijknamige bestanden uniek blijven", () => {
    const a = imagePlaceholder("foto.png", 0);
    const b = imagePlaceholder("foto.png", 1);
    expect(a).not.toEqual(b);
    expect(a).toContain("foto.png");
    expect(b).toContain("foto.png");
  });
});

describe("resolvePlaceholder", () => {
  it("vervangt de placeholder op precies haar eigen positie in de tekst", () => {
    const ph = imagePlaceholder("foto.png", 0);
    const text = `Voor de tekst\n\n${ph}\n\nNa de tekst`;
    const result = resolvePlaceholder(text, ph, "![foto.png](https://x/y)");
    expect(result).toBe("Voor de tekst\n\n![foto.png](https://x/y)\n\nNa de tekst");
  });

  it("valt terug op achteraan toevoegen als de placeholder niet meer bestaat", () => {
    const ph = imagePlaceholder("foto.png", 0);
    const result = resolvePlaceholder("Alleen wat tekst", ph, "![foto.png](https://x/y)");
    expect(result).toBe("Alleen wat tekst\n\n![foto.png](https://x/y)");
  });

  it("geeft alleen de vervanging terug als de omschrijving leeg was", () => {
    const ph = imagePlaceholder("foto.png", 0);
    const result = resolvePlaceholder("", ph, "![foto.png](https://x/y)");
    expect(result).toBe("![foto.png](https://x/y)");
  });

  it("behandelt null/undefined tekst als leeg", () => {
    const ph = imagePlaceholder("foto.png", 0);
    expect(resolvePlaceholder(null, ph, "X")).toBe("X");
    expect(resolvePlaceholder(undefined, ph, "X")).toBe("X");
  });
});

describe("removePlaceholder", () => {
  it("haalt de placeholder eruit en ruimt overtollige lege regels op", () => {
    const ph = imagePlaceholder("foto.png", 0);
    const text = `Voor\n\n${ph}\n\nNa`;
    expect(removePlaceholder(text, ph)).toBe("Voor\n\nNa");
  });

  it("is een no-op als de placeholder niet (meer) voorkomt", () => {
    expect(removePlaceholder("gewone tekst", "![niet aanwezig]()")).toBe("gewone tekst");
  });
});

// BETON-435: het ticket werd aangemaakt mét placeholders en pas daarna
// opgeschoond. Werd de pagina daartussen herladen, dan bleef de ⏳-regel
// voorgoed staan. De create-body gaat nu zonder placeholders de deur uit.
describe("stripPlaceholders", () => {
  it("haalt alle placeholders weg en laat de rest staan", () => {
    const a = imagePlaceholder("a.png", 0);
    const b = imagePlaceholder("b.png", 1);
    const text = `Bug:\n\n${a}\n\nen ook\n\n${b}`;
    expect(stripPlaceholders(text, [a, b])).toBe("Bug:\n\nen ook");
  });

  it("laat de tekst ongemoeid zonder placeholders", () => {
    expect(stripPlaceholders("  gewoon tekst\n", [])).toBe("  gewoon tekst\n");
  });

  it("geeft een lege string als de omschrijving alleen een placeholder was", () => {
    const a = imagePlaceholder("image.png", 0);
    expect(stripPlaceholders(a, [a])).toBe("");
  });
});

describe("buildPendingImage", () => {
  // BETON-259 (regressie van BETON-256): vóór upload bestaat er nog geen
  // attachment-URL, maar de pending-lijst moet toch een thumbnail kunnen
  // tonen — via een lokale preview-URL. `createObjectUrl` is injecteerbaar
  // zodat dit zonder een echte browser/`URL.createObjectURL` te testen is.
  it("geeft per bestand een eigen preview-URL via de geïnjecteerde createObjectUrl", () => {
    const file = { name: "foto.png" };
    const urls = new Map();
    let calls = 0;
    const createObjectUrl = (f) => {
      calls += 1;
      const url = `blob:fake-${calls}`;
      urls.set(url, f);
      return url;
    };

    const img = buildPendingImage(file, 0, createObjectUrl);

    expect(calls).toBe(1);
    expect(img.url).toBe("blob:fake-1");
    expect(urls.get(img.url)).toBe(file);
  });

  it("bevat de placeholder-markdown (voor de inline-plek) én de preview-URL", () => {
    const file = { name: "foto.png" };
    const img = buildPendingImage(file, 7, () => "blob:fake");

    expect(img).toEqual({
      id: 7,
      file,
      placeholder: imagePlaceholder("foto.png", 7),
      url: "blob:fake",
    });
  });

  it("geeft elk bestand een eigen preview-URL, ook bij gelijke bestandsnaam", () => {
    const fileA = { name: "screenshot.png" };
    const fileB = { name: "screenshot.png" };
    let calls = 0;
    const createObjectUrl = () => `blob:fake-${++calls}`;

    const imgA = buildPendingImage(fileA, 0, createObjectUrl);
    const imgB = buildPendingImage(fileB, 1, createObjectUrl);

    expect(imgA.url).not.toBe(imgB.url);
    expect(imgA.placeholder).not.toBe(imgB.placeholder);
  });
});
