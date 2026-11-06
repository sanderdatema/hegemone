import { describe, it, expect } from "vitest";
import { OPTIONAL_COLUMNS, readHiddenColumns, toggleColumn } from "./listColumns.js";

describe("lijstkolomvoorkeuren (BETON-448)", () => {
  it("herstelt alleen bekende optionele kolommen en verwijdert duplicaten", () => {
    expect(readHiddenColumns('["ref","title","milestone","oud","milestone"]')).toEqual(["milestone"]);
  });
  it("valt bij ontbrekende of beschadigde opslag terug op alle kolommen", () => {
    for (const raw of [null, "", "kapot", "{}", "null", "42"]) expect(readHiddenColumns(raw)).toEqual([]);
  });
  it("kan alle optionele kolommen verbergen zonder referentie of titel te raken", () => {
    let hidden = [];
    for (const c of OPTIONAL_COLUMNS) hidden = toggleColumn(hidden, c.key);
    expect(hidden).toHaveLength(7);
    expect(toggleColumn(hidden, "ref")).toBe(hidden);
    expect(toggleColumn(hidden, "title")).toBe(hidden);
    expect(toggleColumn(hidden, "milestone")).not.toContain("milestone");
  });
});
