import { describe, it, expect, vi } from "vitest";
import { lightboxTarget, lightboxClicks } from "./lightbox.js";

const img = (attrs = {}, inLink = false) => ({
  tagName: "IMG",
  getAttribute: (k) => attrs[k] ?? null,
  closest: (sel) => (sel === "a" && inLink ? {} : null),
});

describe("lightboxTarget", () => {
  it("geeft src en alt van een afbeelding", () => {
    expect(lightboxTarget(img({ src: "/a.png", alt: "x" }))).toEqual({ src: "/a.png", alt: "x" });
  });
  it("negeert een afbeelding binnen een link", () => {
    expect(lightboxTarget(img({ src: "/a.png" }, true))).toBeNull();
  });
  it("negeert andere elementen en lege input", () => {
    expect(lightboxTarget({ tagName: "P", closest: () => null })).toBeNull();
    expect(lightboxTarget(null)).toBeNull();
    expect(lightboxTarget(img({}))).toBeNull();
  });
});

describe("lightboxClicks", () => {
  function mount() {
    let h, capture;
    const node = {
      addEventListener: (_t, fn, c) => ((h = fn), (capture = c)),
      removeEventListener: vi.fn(),
    };
    const onopen = vi.fn();
    const act = lightboxClicks(node, onopen);
    return { h: () => h, capture: () => capture, onopen, act, node };
  }
  it("opent bij een afbeeldingsklik en stopt de klik (capture)", () => {
    const m = mount();
    const e = { target: img({ src: "/a.png" }), preventDefault: vi.fn(), stopPropagation: vi.fn() };
    m.h()(e);
    expect(m.capture()).toBe(true);
    expect(m.onopen).toHaveBeenCalledWith({ src: "/a.png", alt: "" });
    expect(e.stopPropagation).toHaveBeenCalled();
  });
  it("laat een klik naast de afbeelding ongemoeid", () => {
    const m = mount();
    const e = { target: { tagName: "P", closest: () => null }, preventDefault: vi.fn(), stopPropagation: vi.fn() };
    m.h()(e);
    expect(m.onopen).not.toHaveBeenCalled();
    expect(e.stopPropagation).not.toHaveBeenCalled();
  });
});
