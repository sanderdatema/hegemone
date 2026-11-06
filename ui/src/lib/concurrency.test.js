import { describe, it, expect } from "vitest";
import { withPrecondition, conflictMessage } from "./concurrency.js";

describe("withPrecondition (BETON-44)", () => {
  it("voegt expected_updated_at toe uit het geladen item", () => {
    const body = withPrecondition({ title: "x" }, { updated_at: "2026-01-01T00:00:00.000Z" });
    expect(body).toEqual({ title: "x", expected_updated_at: "2026-01-01T00:00:00.000Z" });
  });

  it("laat de body ongewijzigd zonder item of updated_at", () => {
    expect(withPrecondition({ title: "x" }, null)).toEqual({ title: "x" });
    expect(withPrecondition({ title: "x" }, {})).toEqual({ title: "x" });
  });

  it("muteert de originele body niet", () => {
    const orig = { title: "x" };
    withPrecondition(orig, { updated_at: "t" });
    expect(orig).toEqual({ title: "x" });
  });
});

describe("conflictMessage (BETON-44)", () => {
  it("geeft een melding bij een 409", () => {
    expect(conflictMessage({ status: 409 })).toMatch(/gewijzigd/);
  });

  it("geeft null bij een andere of ontbrekende fout", () => {
    expect(conflictMessage({ status: 404 })).toBe(null);
    expect(conflictMessage(null)).toBe(null);
  });
});

it("vertaalt uitsluitend conflictmeldingen bij een Engelse locale", () => {
  expect(conflictMessage({ status: 409 }, "en")).toContain("latest version has been reloaded");
  expect(conflictMessage({ status: 403 }, "en")).toBe(null);
});
