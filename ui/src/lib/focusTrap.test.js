import { describe, it, expect } from "vitest";
import { trapTarget, FOCUSABLE_SELECTOR } from "./focusTrap.js";

// De trap-volgorde testen we puur met stand-in "nodes" (strings): de functie
// werkt op referentie-gelijkheid, niet op echte DOM.
describe("trapTarget", () => {
  const nodes = ["a", "b", "c"];

  it("wrap van laatste naar eerste bij Tab", () => {
    expect(trapTarget(nodes, "c", false)).toBe("a");
  });

  it("wrap van eerste naar laatste bij Shift+Tab", () => {
    expect(trapTarget(nodes, "a", true)).toBe("c");
  });

  it("laat de browser tabben in het midden (geen override)", () => {
    expect(trapTarget(nodes, "b", false)).toBe(null);
    expect(trapTarget(nodes, "b", true)).toBe(null);
  });

  it("trekt focus terug naar binnen als die buiten het paneel zit", () => {
    expect(trapTarget(nodes, "buiten", false)).toBe("a");
    expect(trapTarget(nodes, "buiten", true)).toBe("c");
  });

  it("geen tabbare elementen → null", () => {
    expect(trapTarget([], "a", false)).toBe(null);
  });

  it("één element blijft op zichzelf (wrap naar zichzelf)", () => {
    expect(trapTarget(["solo"], "solo", false)).toBe("solo");
    expect(trapTarget(["solo"], "solo", true)).toBe("solo");
  });
});

describe("FOCUSABLE_SELECTOR", () => {
  it("dekt de gangbare tabbare elementen en sluit tabindex=-1 uit", () => {
    expect(FOCUSABLE_SELECTOR).toContain("button:not([disabled])");
    expect(FOCUSABLE_SELECTOR).toContain('[tabindex]:not([tabindex="-1"])');
    expect(FOCUSABLE_SELECTOR).toContain("a[href]");
  });
});
