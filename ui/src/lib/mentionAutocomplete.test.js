import { describe, it, expect } from "vitest";
import { mentionQuery, applyMention, filterMentionCandidates } from "./mentionAutocomplete.js";

const USERS = [
  { handle: "person", display_name: "Person" },
  { handle: "person-two", display_name: "Person two" },
  { handle: "claude", display_name: "Claude" },
  { handle: "triage", display_name: "Triage" },
];

describe("mentionQuery (re-export)", () => {
  it("herkent een partiële mention aan de caret", () => {
    expect(mentionQuery("hoi @per")).toBe("per");
    expect(mentionQuery("@")).toBe("");
  });
  it("geen mention → null", () => {
    expect(mentionQuery("gewoon tekst")).toBeNull();
    expect(mentionQuery("mail person@")).toBeNull();
  });
});

describe("applyMention (re-export)", () => {
  it("vervangt de partial door @handle + spatie en zet de caret erna", () => {
    const { text, caret } = applyMention("hoi @per", 8, "person");
    expect(text).toBe("hoi @person ");
    expect(caret).toBe(12);
  });
});

describe("filterMentionCandidates", () => {
  it("filtert case-insensitive op handle-prefix", () => {
    const matches = filterMentionCandidates(USERS, "per");
    expect(matches.map((u) => u.handle)).toEqual(["person", "person-two"]);
  });
  it("filtert op hoofdletterongevoelige query", () => {
    const matches = filterMentionCandidates(USERS, "PER");
    expect(matches.map((u) => u.handle)).toEqual(["person", "person-two"]);
  });
  it("lege query (net getypt @) matcht iedereen, begrensd door limit", () => {
    const matches = filterMentionCandidates(USERS, "", 2);
    expect(matches).toHaveLength(2);
  });
  it("query === null (geen actieve mention) geeft lege lijst", () => {
    expect(filterMentionCandidates(USERS, null)).toEqual([]);
  });
  it("geen match → lege lijst", () => {
    expect(filterMentionCandidates(USERS, "zzz")).toEqual([]);
  });
  it("respecteert de limit", () => {
    const matches = filterMentionCandidates(USERS, "", 1);
    expect(matches).toHaveLength(1);
  });
  it("gaat netjes om met een ontbrekende/lege users-lijst", () => {
    expect(filterMentionCandidates(undefined, "per")).toEqual([]);
    expect(filterMentionCandidates([], "per")).toEqual([]);
  });
  it("sluit gedeactiveerde users uit (BETON-119)", () => {
    const users = [...USERS, { handle: "person-two-oud", display_name: "Person two (oud)", active: false }];
    const matches = filterMentionCandidates(users, "per");
    expect(matches.map((u) => u.handle)).toEqual(["person", "person-two"]);
  });
});
