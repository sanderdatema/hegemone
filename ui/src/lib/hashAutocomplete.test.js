import { describe, it, expect } from "vitest";
import {
  hashQuery,
  parseHashQuery,
  filterTicketCandidates,
  applyHashRef,
} from "./hashAutocomplete.js";

const RESULTS = [
  { ref: "BETON-1", title: "Eerste ticket" },
  { ref: "BETON-42", title: "Antwoord" },
  { ref: "BETON-142", title: "Nog een" },
  { ref: "SOS-1", title: "Ander project, zelfde seq" },
  { ref: "SOS-24", title: "SOS-ticket" },
  { ref: "BRAND-1", title: "Weer een project met B" },
];

describe("hashQuery", () => {
  it("herkent een partieel #-token aan de caret", () => {
    expect(hashQuery("zie #B1")).toBe("B1");
    expect(hashQuery("#")).toBe("");
  });
  it("werkt ook midden in een langere tekst (caret via slice)", () => {
    // hashQuery krijgt altijd text.slice(0, caret) — caret midden in tekst
    // betekent gewoon dat de aanroeper een kortere substring doorgeeft.
    const text = "zie #42 voor details";
    const caret = 7; // net na "#42", vóór de spatie
    expect(hashQuery(text.slice(0, caret))).toBe("42");
  });
  it("geen # → null", () => {
    expect(hashQuery("gewoon tekst")).toBeNull();
  });
  it("een afgesloten token (spatie erna) telt niet meer als actief", () => {
    expect(hashQuery("zie #42 ")).toBeNull();
  });
  it("staat een koppelteken toe (volledige ref als lopende query)", () => {
    expect(hashQuery("zie #BETON-42")).toBe("BETON-42");
  });
});

describe("parseHashQuery", () => {
  it("alleen cijfers → lege letters", () => {
    expect(parseHashQuery("42")).toEqual({ letters: "", digits: "42" });
  });
  it("letters + cijfers", () => {
    expect(parseHashQuery("B1")).toEqual({ letters: "B", digits: "1" });
  });
  it("koppelteken tussen key en seq wordt genegeerd", () => {
    expect(parseHashQuery("BETON-42")).toEqual({ letters: "BETON", digits: "42" });
  });
  it("alleen letters → lege digits", () => {
    expect(parseHashQuery("SOS")).toEqual({ letters: "SOS", digits: "" });
  });
  it("lege query", () => {
    expect(parseHashQuery("")).toEqual({ letters: "", digits: "" });
  });
});

describe("filterTicketCandidates", () => {
  it("nummer-only → alleen tickets in het huidige project (seq bevat de cijfers)", () => {
    const matches = filterTicketCandidates(RESULTS, "1", "BETON");
    // BETON-142 telt ook mee: "142" bevat "1" als substring (seq-substring-match).
    expect(matches.map((r) => r.ref).sort()).toEqual(["BETON-1", "BETON-142"]);
  });
  it("#B1 → key-substring (case-insensitief) én seq bevat de cijfers", () => {
    const matches = filterTicketCandidates(RESULTS, "B1", "BETON");
    // BRAND-1 en BETON-1/142 bevatten "b" (case-insensitief) in de key en
    // hun seq bevat "1" als substring.
    expect(matches.map((r) => r.ref).sort()).toEqual(["BETON-1", "BETON-142", "BRAND-1"]);
  });
  it("#SOS → alle projecten met SOS in de key, ongeacht seq", () => {
    const matches = filterTicketCandidates(RESULTS, "SOS", "BETON");
    expect(matches.map((r) => r.ref)).toEqual(["SOS-1", "SOS-24"]);
  });
  it("query === null (geen actief token) → geen suggesties", () => {
    expect(filterTicketCandidates(RESULTS, null, "BETON")).toEqual([]);
  });
  it("lege query (net getypt #, nog niets erna) → geen suggesties", () => {
    expect(filterTicketCandidates(RESULTS, "", "BETON")).toEqual([]);
  });
  it("respecteert de limit", () => {
    const matches = filterTicketCandidates(RESULTS, "SOS", "BETON", 1);
    expect(matches).toHaveLength(1);
  });
  it("seq-substring-match: cijfers hoeven niet aan het begin te staan", () => {
    const matches = filterTicketCandidates(RESULTS, "42", "BETON");
    expect(matches.map((r) => r.ref).sort()).toEqual(["BETON-142", "BETON-42"]);
  });
  it("gaat netjes om met een ontbrekende/lege resultatenlijst", () => {
    expect(filterTicketCandidates(undefined, "42", "BETON")).toEqual([]);
    expect(filterTicketCandidates([], "42", "BETON")).toEqual([]);
  });
});

describe("applyHashRef", () => {
  it("vervangt de partial door de ref + spatie en zet de caret erna", () => {
    const { text, caret } = applyHashRef("zie #B1", 7, "BETON-1");
    expect(text).toBe("zie BETON-1 ");
    expect(caret).toBe(12);
  });
  it("laat tekst ná de caret ongemoeid", () => {
    const { text } = applyHashRef("zie #B1 voor details", 7, "BETON-1");
    expect(text).toBe("zie BETON-1  voor details");
  });
});
