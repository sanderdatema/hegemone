import { describe, it, expect } from "vitest";
import { mentionQuery, applyMention } from "./mentions.js";

describe("mentionQuery", () => {
  it("herkent een partiële mention aan de caret", () => {
    expect(mentionQuery("hoi @per")).toBe("per");
    expect(mentionQuery("@")).toBe("");
  });
  it("geen mention → null", () => {
    expect(mentionQuery("gewoon tekst")).toBeNull();
    expect(mentionQuery("mail person@")).toBeNull(); // @ na woordkarakter
    expect(mentionQuery("hoi @per doe")).toBeNull(); // caret niet aan de mention
  });
});

describe("applyMention", () => {
  it("vervangt de partial door @handle + spatie en zet de caret erna", () => {
    const { text, caret } = applyMention("hoi @per", 8, "person");
    expect(text).toBe("hoi @person ");
    expect(caret).toBe(12);
  });
  it("behoudt tekst na de caret", () => {
    // before="hoi @per" → "hoi @person ", after=" einde" blijft staan.
    const { text } = applyMention("hoi @per einde", 8, "person");
    expect(text).toBe("hoi @person  einde");
  });
});
