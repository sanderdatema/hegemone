import { describe, it, expect } from "vitest";
import { mappingToRows, rowsToMapping, mappingChanged } from "./modelClasses.js";

const CLASSES = ["routine", "standaard", "complex"];

describe("modelClasses (BETON-476)", () => {
  it("zet mapping om naar alfabetische rijen", () => {
    const rows = mappingToRows({ codex: { complex: "x" }, claude: { complex: "opus" } });
    expect(rows.map((r) => r.harness)).toEqual(["claude", "codex"]);
  });
  it("rowsToMapping laat lege modellen en lege harnassen weg en trimt", () => {
    const rows = [
      { harness: " Claude ", models: { routine: "sonnet ", standaard: "", complex: "opus" } },
      { harness: "", models: { complex: "x" } },
    ];
    expect(rowsToMapping(rows, CLASSES)).toEqual({ claude: { routine: "sonnet", complex: "opus" } });
  });
  it("mappingChanged negeert sleutelvolgorde", () => {
    expect(mappingChanged({ a: { x: "1", y: "2" } }, { a: { y: "2", x: "1" } })).toBe(false);
    expect(mappingChanged({ a: { x: "1" } }, { a: { x: "2" } })).toBe(true);
  });
});
