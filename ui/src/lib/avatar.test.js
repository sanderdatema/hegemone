import { describe, it, expect } from "vitest";
import {
  AVATAR_COLORS,
  LABEL_HUES,
  hashString,
  avatarColor,
  labelHue,
  positionHue,
  hexToHue,
  labelHueMap,
  initials,
  avatarUrlMap,
  virtualHandleSet,
} from "./avatar.js";

describe("hashString", () => {
  it("is deterministisch", () => {
    expect(hashString("person")).toBe(hashString("person"));
  });
  it("levert een niet-negatief 32-bit getal", () => {
    const h = hashString("claude");
    expect(h).toBeGreaterThanOrEqual(0);
    expect(h).toBeLessThanOrEqual(0xffffffff);
  });
  it("verschilt voor verschillende input", () => {
    expect(hashString("person")).not.toBe(hashString("claude"));
  });
  it("behandelt leeg/undefined zonder te crashen", () => {
    expect(hashString("")).toBe(hashString(undefined));
  });
});

describe("avatarColor", () => {
  it("kiest altijd een kleur uit de palet-set", () => {
    for (const h of ["person", "claude", "jan-piet", "x", "", "AbCdEf"]) {
      expect(AVATAR_COLORS).toContain(avatarColor(h));
    }
  });
  it("is deterministisch per handle", () => {
    expect(avatarColor("person")).toBe(avatarColor("person"));
  });
});

describe("labelHue", () => {
  it("kiest altijd een hue uit de set", () => {
    for (const n of ["bug", "feature", "docs", "urgent-fix", "backend", ""]) {
      expect(LABEL_HUES).toContain(labelHue(n));
    }
  });
  it("is deterministisch per label", () => {
    expect(labelHue("feature")).toBe(labelHue("feature"));
  });
  it("verdeelt verschillende labels (niet allemaal dezelfde hue)", () => {
    const hues = new Set(["bug", "feature", "docs", "backend"].map(labelHue));
    expect(hues.size).toBeGreaterThan(1);
  });
});

describe("initials", () => {
  it("neemt eerste twee letters van een enkele handle", () => {
    expect(initials("person")).toBe("PE");
    expect(initials("claude")).toBe("CL");
  });
  it("neemt eerste letter van eerste twee delen bij scheidingstekens", () => {
    expect(initials("jan-piet")).toBe("JP");
    expect(initials("foo_bar")).toBe("FB");
    expect(initials("a.b.c")).toBe("AB");
  });
  it("werkt met een handle van één letter", () => {
    expect(initials("x")).toBe("X");
  });
  it("geeft ? bij lege input", () => {
    expect(initials("")).toBe("?");
    expect(initials(undefined)).toBe("?");
  });
});

describe("avatarUrlMap", () => {
  it("bouwt een handle→avatar_url-map uit de users-lijst", () => {
    const users = [
      { handle: "person", avatar_url: "/a/person.png" },
      { handle: "claude", avatar_url: "/a/claude.png" },
    ];
    const map = avatarUrlMap(users);
    expect(map.get("person")).toBe("/a/person.png");
    expect(map.get("claude")).toBe("/a/claude.png");
  });
  it("slaat users zonder avatar_url over", () => {
    const map = avatarUrlMap([{ handle: "triage", avatar_url: null }]);
    expect(map.has("triage")).toBe(false);
  });
  it("werkt met lege/ontbrekende input zonder te crashen", () => {
    expect(avatarUrlMap([]).size).toBe(0);
    expect(avatarUrlMap(undefined).size).toBe(0);
  });
});

describe("virtualHandleSet", () => {
  it("bevat alleen handles met is_virtual", () => {
    const set = virtualHandleSet([
      { handle: "person" },
      { handle: "coding-agent", is_virtual: 1 },
      { handle: "smid", is_virtual: 0 },
      { handle: "hermes-agent", is_virtual: true },
    ]);
    expect([...set].sort()).toEqual(["coding-agent", "hermes-agent"]);
  });
  it("is leeg zonder users", () => {
    expect(virtualHandleSet(undefined).size).toBe(0);
  });
});

describe("labelHueMap (BETON-461)", () => {
  const beton = [
    "bug", "feature", "sonnet", "opus", "research", "chore",
    "docs", "refactor", "question", "haiku", "gpt-5.5", "gpt-5.4-mini",
  ].map((name) => ({ name, color: "#95a5a6" }));

  it("geeft 12 labels van één project 12 verschillende tinten", () => {
    const hues = [...labelHueMap(beton).values()];
    expect(new Set(hues).size).toBe(12);
  });
  it("bug en feature verschillen", () => {
    const m = labelHueMap(beton);
    expect(m.get("bug")).not.toBe(m.get("feature"));
  });
  it("is onafhankelijk van de invoervolgorde", () => {
    const a = labelHueMap(beton);
    const b = labelHueMap([...beton].reverse());
    expect([...a.entries()].sort()).toEqual([...b.entries()].sort());
  });
  it("gebruikt een eigen kleur boven de positietint", () => {
    const m = labelHueMap([{ name: "a", color: "#ff0000" }, { name: "b", color: "#95a5a6" }]);
    expect(m.get("a")).toBe(0);
    expect(m.get("b")).toBe(positionHue(1));
  });
  it("behandelt de oude default en ontbrekende kleur als 'niet gezet'", () => {
    const m = labelHueMap([{ name: "a", color: null }, { name: "b", color: "#95A5A6" }]);
    expect(m.get("a")).toBe(positionHue(0));
    expect(m.get("b")).toBe(positionHue(1));
  });
});

describe("hexToHue", () => {
  it("rekent primaire kleuren om", () => {
    expect(hexToHue("#ff0000")).toBe(0);
    expect(hexToHue("#00ff00")).toBe(120);
    expect(hexToHue("#0000ff")).toBe(240);
  });
  it("geeft null voor grijs of onzin", () => {
    expect(hexToHue("#808080")).toBeNull();
    expect(hexToHue("rood")).toBeNull();
    expect(hexToHue(undefined)).toBeNull();
  });
});
