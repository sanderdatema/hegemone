import { describe, it, expect } from "vitest";
import { subtaskGroups, relationGroups } from "./relatedList.js";

const label = (t) => `L:${t}`;

describe("subtaskGroups", () => {
  it("één groep zonder kop, niet verbreekbaar", () => {
    const g = subtaskGroups({ children_detail: [{ ref: "A-2", title: "Kind", state: "todo" }] });
    expect(g).toEqual([
      { type: "subtasks", label: "", removable: false, items: [{ ref: "A-2", title: "Kind", state: "todo" }] },
    ]);
  });
  it("leeg zonder kinderen", () => {
    expect(subtaskGroups({})).toEqual([]);
    expect(subtaskGroups(null)).toEqual([]);
  });
});

describe("relationGroups", () => {
  it("behoudt de backend-volgorde, laat lege groepen weg, alles verbreekbaar", () => {
    const g = relationGroups(
      {
        relations_detail: {
          blocks: [],
          blocked_by: [{ ref: "A-1", title: "T", state: "done" }],
          relates_to: [{ ref: "A-3", title: "U", state: null }],
        },
      },
      label,
    );
    expect(g.map((x) => x.type)).toEqual(["blocked_by", "relates_to"]);
    expect(g.every((x) => x.removable)).toBe(true);
    expect(g[0].label).toBe("L:blocked_by");
    expect(g[0].items[0]).toEqual({ ref: "A-1", title: "T", state: "done" });
  });
  it("valt terug op kale refs zonder relations_detail", () => {
    const g = relationGroups({ relations: { relates_to: ["A-9"] } }, label);
    expect(g[0].items).toEqual([{ ref: "A-9", title: "", state: null }]);
  });
  it("parent komt er nooit in", () => {
    const g = relationGroups({ parent: "A-1", relations: { relates_to: ["A-2"] } }, label);
    expect(g.map((x) => x.type)).toEqual(["relates_to"]);
  });
});
