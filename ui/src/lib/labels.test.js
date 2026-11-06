import { describe, it, expect } from "vitest";
import {
  SignalLow,
  SignalMedium,
  SignalHigh,
  Ban,
  Hourglass,
  Copy,
  Files,
  Link2,
  CornerUpLeft,
} from "@lucide/svelte";
import {
  prioLabel,
  relationLabel,
  RELATION_TYPES,
  stateGroupLabel,
  agentTypeLabel,
  workloadMeta,
  relationMeta,
  relationHue,
  relationEntries,
  cardRelationPills,
} from "./labels.js";

describe("prioLabel", () => {
  it("vertaalt elke priority-enum-waarde naar NL", () => {
    expect(prioLabel("none")).toBe("Geen");
    expect(prioLabel("low")).toBe("Laag");
    expect(prioLabel("medium")).toBe("Middel");
    expect(prioLabel("high")).toBe("Hoog");
    expect(prioLabel("urgent")).toBe("Urgent");
  });

  it("valt terug op de ruwe waarde bij een onbekende priority", () => {
    expect(prioLabel("weird")).toBe("weird");
    expect(prioLabel(undefined)).toBe(undefined);
    expect(prioLabel(null)).toBe(null);
  });
});

describe("relationLabel", () => {
  it("vertaalt elk relatietype naar NL", () => {
    expect(relationLabel("parent")).toBe("subtaak van");
    expect(relationLabel("blocks")).toBe("blokkeert");
    expect(relationLabel("blocked_by")).toBe("geblokkeerd door");
    expect(relationLabel("duplicate_of")).toBe("duplicaat van");
    expect(relationLabel("duplicated_by")).toBe("gedupliceerd door");
    expect(relationLabel("relates_to")).toBe("gerelateerd aan");
  });

  it("valt terug op de ruwe waarde bij een onbekend relatietype", () => {
    expect(relationLabel("mystery")).toBe("mystery");
  });
});

describe("RELATION_TYPES", () => {
  it("bevat de handmatig aan te maken relatietypen, zonder 'parent' (BETON-331)", () => {
    expect(RELATION_TYPES).toEqual([
      "relates_to",
      "blocks",
      "blocked_by",
      "duplicate_of",
      "duplicated_by",
    ]);
    expect(RELATION_TYPES).not.toContain("parent");
  });

  it("heeft voor elk type een NL-label via relationLabel", () => {
    for (const t of RELATION_TYPES) {
      expect(relationLabel(t)).not.toBe(t);
    }
  });
});

describe("stateGroupLabel", () => {
  it("vertaalt elke state-group-waarde naar NL", () => {
    expect(stateGroupLabel("backlog")).toBe("Backlog");
    expect(stateGroupLabel("unstarted")).toBe("Nog niet gestart");
    expect(stateGroupLabel("started")).toBe("Gestart");
    expect(stateGroupLabel("completed")).toBe("Afgerond");
    expect(stateGroupLabel("cancelled")).toBe("Geannuleerd");
  });

  it("valt terug op de ruwe waarde bij een onbekende state-group", () => {
    expect(stateGroupLabel("onbekend")).toBe("onbekend");
  });
});

describe("agentTypeLabel", () => {
  it("vertaalt de bekende agent-types", () => {
    expect(agentTypeLabel("coding")).toBe("coding-agent");
    expect(agentTypeLabel("hermes")).toBe("Hermes-agent");
  });

  it("valt terug op de ruwe waarde bij een onbekend of ontbrekend agent-type", () => {
    expect(agentTypeLabel("robot")).toBe("robot");
    expect(agentTypeLabel(null)).toBe(null);
    expect(agentTypeLabel(undefined)).toBe(undefined);
  });
});

describe("workloadMeta", () => {
  it("geeft icon/color/label voor light", () => {
    const m = workloadMeta("light");
    expect(m.icon).toBe(SignalLow);
    expect(m.color).toBe("var(--workload-light)");
    expect(m.label).toBe("Licht");
  });

  it("geeft icon/color/label voor medium", () => {
    const m = workloadMeta("medium");
    expect(m.icon).toBe(SignalMedium);
    expect(m.color).toBe("var(--workload-medium)");
    expect(m.label).toBe("Middel");
  });

  it("geeft icon/color/label voor heavy", () => {
    const m = workloadMeta("heavy");
    expect(m.icon).toBe(SignalHigh);
    expect(m.color).toBe("var(--workload-heavy)");
    expect(m.label).toBe("Zwaar");
  });

  it("geeft null voor een lege of onbekende workload", () => {
    expect(workloadMeta("")).toBe(null);
    expect(workloadMeta(null)).toBe(null);
    expect(workloadMeta(undefined)).toBe(null);
    expect(workloadMeta("mystery")).toBe(null);
  });
});

describe("relationMeta (BETON-344)", () => {
  it("geeft icon/label voor elk van de vijf kaart-relatietypen", () => {
    expect(relationMeta("blocks")).toEqual({ icon: Ban, label: "blokkeert" });
    expect(relationMeta("blocked_by")).toEqual({ icon: Hourglass, label: "geblokkeerd door" });
    expect(relationMeta("duplicate_of")).toEqual({ icon: Copy, label: "duplicaat van" });
    expect(relationMeta("duplicated_by")).toEqual({ icon: Files, label: "gedupliceerd door" });
    expect(relationMeta("relates_to")).toEqual({ icon: Link2, label: "gerelateerd aan" });
  });

  it("duplicate_of en duplicated_by delen geen icoon (richting moet zichtbaar blijven)", () => {
    expect(relationMeta("duplicate_of").icon).not.toBe(relationMeta("duplicated_by").icon);
  });

  it("geeft icon/label voor parent ('subtaak van', BETON-344 na feedback)", () => {
    expect(relationMeta("parent")).toEqual({ icon: CornerUpLeft, label: "subtaak van" });
  });

  it("geeft null voor onbekende types", () => {
    expect(relationMeta("mystery")).toBe(null);
    expect(relationMeta(undefined)).toBe(null);
  });
});

describe("relationHue (BETON-344)", () => {
  it("geeft een vaste hue voor elk van de zes kaart-relatietypen", () => {
    expect(relationHue("parent")).toBe(150);
    expect(relationHue("blocks")).toBe(0);
    expect(relationHue("blocked_by")).toBe(30);
    expect(relationHue("relates_to")).toBe(210);
    expect(relationHue("duplicate_of")).toBe(270);
    expect(relationHue("duplicated_by")).toBe(300);
  });

  it("elk type heeft een eigen hue (geen twee gelijk)", () => {
    const types = ["parent", "blocks", "blocked_by", "relates_to", "duplicate_of", "duplicated_by"];
    const hues = types.map(relationHue);
    expect(new Set(hues).size).toBe(types.length);
  });

  it("valt terug op een neutrale hue voor een onbekend type", () => {
    expect(relationHue("mystery")).toBe(210);
    expect(relationHue(undefined)).toBe(210);
  });
});

describe("relationEntries (BETON-344)", () => {
  it("plat alle vijf typen uit tot {type, ref}-paren, in RELATION_TYPES-volgorde", () => {
    const relations = {
      relates_to: ["SOS-3"],
      blocks: ["SOS-2"],
      blocked_by: ["SOS-1"],
      duplicate_of: [],
      duplicated_by: ["BRAND-9"],
    };
    expect(relationEntries(relations)).toEqual([
      { type: "relates_to", ref: "SOS-3" },
      { type: "blocks", ref: "SOS-2" },
      { type: "blocked_by", ref: "SOS-1" },
      { type: "duplicated_by", ref: "BRAND-9" },
    ]);
  });

  it("meerdere refs voor hetzelfde type worden allebei uitgeklapt", () => {
    const relations = { relates_to: ["SOS-1", "SOS-2"] };
    expect(relationEntries(relations)).toEqual([
      { type: "relates_to", ref: "SOS-1" },
      { type: "relates_to", ref: "SOS-2" },
    ]);
  });

  it("lege of ontbrekende input geeft een lege lijst, geen crash", () => {
    expect(relationEntries({})).toEqual([]);
    expect(relationEntries(null)).toEqual([]);
    expect(relationEntries(undefined)).toEqual([]);
  });
});

describe("cardRelationPills (BETON-344, na Persons feedback dat subtaken ontbraken)", () => {
  it("zet parent vooraan, dan de overige relaties", () => {
    const item = {
      parent: "SOS-1",
      relations: { blocks: ["SOS-2"], relates_to: ["SOS-3"] },
    };
    expect(cardRelationPills(item)).toEqual([
      { type: "parent", ref: "SOS-1" },
      { type: "relates_to", ref: "SOS-3" },
      { type: "blocks", ref: "SOS-2" },
    ]);
  });

  it("zonder parent alleen de gewone relaties", () => {
    const item = { parent: null, relations: { blocks: ["SOS-2"] } };
    expect(cardRelationPills(item)).toEqual([{ type: "blocks", ref: "SOS-2" }]);
  });

  it("alleen een parent, geen andere relaties", () => {
    const item = { parent: "SOS-1", relations: {} };
    expect(cardRelationPills(item)).toEqual([{ type: "parent", ref: "SOS-1" }]);
  });

  it("lege of ontbrekende input geeft een lege lijst, geen crash", () => {
    expect(cardRelationPills({})).toEqual([]);
    expect(cardRelationPills(null)).toEqual([]);
    expect(cardRelationPills(undefined)).toEqual([]);
  });

  it("laat duplicated_by weg (BETON-349): het overblijvende ticket krijgt geen duplicaat-pill", () => {
    const item = {
      parent: null,
      relations: { duplicated_by: ["SOS-9"], blocks: ["SOS-2"] },
    };
    expect(cardRelationPills(item)).toEqual([{ type: "blocks", ref: "SOS-2" }]);
  });

  it("toont duplicate_of wel: het duplicaat-ticket zelf krijgt de pill", () => {
    const item = { parent: null, relations: { duplicate_of: ["SOS-1"] } };
    expect(cardRelationPills(item)).toEqual([{ type: "duplicate_of", ref: "SOS-1" }]);
  });
});

describe("modellabels (BETON-461)", () => {
  it("herkent de drie werkklassen hoofdletterongevoelig", async () => {
    const { isModelLabel, MODEL_CLASSES } = await import("./labels.js");
    expect(MODEL_CLASSES).toEqual(["routine", "standaard", "complex"]);
    for (const n of ["routine", "Standaard", "COMPLEX"]) {
      expect(isModelLabel(n)).toBe(true);
    }
    for (const n of ["bug", "feature", "opus", "gpt-5.5", "complexer", "", undefined]) {
      expect(isModelLabel(n)).toBe(false);
    }
  });
  it("splitst labels met behoud van volgorde", async () => {
    const { splitModelLabels } = await import("./labels.js");
    expect(splitModelLabels(["bug", "complex", "docs", "routine"])).toEqual({
      plain: ["bug", "docs"],
      models: ["complex", "routine"],
    });
    expect(splitModelLabels(undefined)).toEqual({ plain: [], models: [] });
  });
  it("workloadMeta geeft korte tekst en titel", () => {
    expect(workloadMeta("heavy")).toMatchObject({ short: "Z", title: "Werklast: zwaar (tokens)" });
  });
});

describe("fitChips (BETON-479)", () => {
  it("laat alles zien als het past", async () => {
    const { fitChips } = await import("./labels.js");
    expect(fitChips([], 2)).toEqual({ shown: [], hidden: [] });
    expect(fitChips(["a", "b"], 2)).toEqual({ shown: ["a", "b"], hidden: [] });
  });
  it("knipt af en bewaart de rest", async () => {
    const { fitChips } = await import("./labels.js");
    expect(fitChips(["a", "b", "c", "d"], 2)).toEqual({ shown: ["a", "b"], hidden: ["c", "d"] });
  });
});
