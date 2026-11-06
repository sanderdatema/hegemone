import { describe, it, expect } from "vitest";
import { errorCause, loadErrorMessage } from "./loadError.js";

const BASE = "Kon dit ticket niet laden — probeer opnieuw.";

describe("errorCause", () => {
  it("geeft niets terug zonder fout", () => {
    expect(errorCause(null)).toBe("");
    expect(errorCause(undefined)).toBe("");
  });

  it("gebruikt status + detail van een API-fout", () => {
    const err = new Error("404: Item niet gevonden");
    err.status = 404;
    err.detail = "Item niet gevonden";
    expect(errorCause(err)).toBe("404: Item niet gevonden");
  });

  it("gebruikt de kale status als het detail geen string is", () => {
    const err = new Error("409: ");
    err.status = 409;
    err.detail = { error: "conflict", total: 3 };
    expect(errorCause(err)).toBe("409");
  });

  it("valt bij een netwerkfout terug op de message", () => {
    expect(errorCause(new TypeError("Failed to fetch"))).toBe("Failed to fetch");
  });

  it("accepteert een kale string", () => {
    expect(errorCause("  stuk  ")).toBe("stuk");
  });

  it("geeft niets terug bij een fout zonder status én zonder message", () => {
    expect(errorCause({})).toBe("");
  });
});

describe("loadErrorMessage", () => {
  it("zet de oorzaak achter de basisregel", () => {
    const err = new Error("404: Item niet gevonden");
    err.status = 404;
    err.detail = "Item niet gevonden";
    expect(loadErrorMessage(BASE, err)).toBe(`${BASE} (404: Item niet gevonden)`);
  });

  it("laat de basisregel kaal zonder bruikbare oorzaak", () => {
    expect(loadErrorMessage(BASE, {})).toBe(BASE);
    expect(loadErrorMessage(BASE, null)).toBe(BASE);
  });
});
