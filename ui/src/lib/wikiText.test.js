import { describe, it, expect } from "vitest";
import {
  extractWikiLinks,
  resolveWikiLink,
  wikiBacklinks,
  filterWikiPages,
  wikiLinkQuery,
  wikiSlugSuggestions,
} from "./wikiText.js";

describe("extractWikiLinks", () => {
  it("verzamelt unieke refs (scope+slug) in volgorde; kaal erft de bronscope", () => {
    expect(extractWikiLinks("[[a]] [[b]] weer [[a]]", "global")).toEqual([
      { scope: "global", slug: "a" },
      { scope: "global", slug: "b" },
    ]);
  });

  it("resolveert een kale link naar de bronscope", () => {
    expect(extractWikiLinks("[[a]]", "BETON")).toEqual([{ scope: "BETON", slug: "a" }]);
  });

  it("draagt een expliciete qualifier als eigen scope (BETON-306)", () => {
    expect(extractWikiLinks("[[BETON:a]] [[global:b]]", "SOS")).toEqual([
      { scope: "BETON", slug: "a" },
      { scope: "global", slug: "b" },
    ]);
  });

  it("dedupt op scope+slug, niet op slug alleen", () => {
    expect(extractWikiLinks("[[BETON:a]] [[global:a]] [[BETON:a]]", "global")).toEqual([
      { scope: "BETON", slug: "a" },
      { scope: "global", slug: "a" },
    ]);
  });

  it("een alias (BETON-346) verandert het doel niet — resolveert nog altijd naar de slug", () => {
    expect(extractWikiLinks("[[plan-field-tickets|field-based expected_action]]", "BETON")).toEqual([
      { scope: "BETON", slug: "plan-field-tickets" },
    ]);
  });

  it("een gekwalificeerde link mét alias resolveert naar de qualifier-scope", () => {
    expect(extractWikiLinks("[[BETON:deploy|Deploy-stappen]]", "global")).toEqual([
      { scope: "BETON", slug: "deploy" },
    ]);
  });

  it("geeft lege lijst bij geen/lege tekst", () => {
    expect(extractWikiLinks("")).toEqual([]);
    expect(extractWikiLinks(null)).toEqual([]);
  });

  it("negeert niet-slug-achtige verwijzingen", () => {
    expect(extractWikiLinks("[[Niet Geldig]]")).toEqual([]);
  });
});

describe("resolveWikiLink (BETON-306)", () => {
  it("qualifier wint van de huidige scope", () => {
    expect(resolveWikiLink("BETON", "x", "global")).toEqual({ scope: "BETON", slug: "x" });
  });
  it("zonder qualifier erft de huidige scope", () => {
    expect(resolveWikiLink(undefined, "x", "BETON")).toEqual({ scope: "BETON", slug: "x" });
  });

  // Kale-link-fallback: huidige scope → global → uniek project. In de praktijk
  // is élke link kaal geschreven, dus hier hangt de hele cross-scope-flow aan.
  describe("kale link valt terug via de index", () => {
    const index = (...keys) => new Set(keys);

    it("een lokale pagina wint van elke vreemde", () => {
      const refs = index("BETON x", "global x", "BRAND x");
      expect(resolveWikiLink(undefined, "x", "BETON", refs)).toEqual({
        scope: "BETON",
        slug: "x",
      });
    });

    it("valt terug op global als de huidige scope hem niet heeft", () => {
      // De gemelde BETON→global-richting: `[[ticket-werkwijze]]` in een
      // BETON-pagina, bestaand in global én BRAND — global wint, dus geen ambiguïteit.
      const refs = index("global ticket-werkwijze", "BRAND ticket-werkwijze");
      expect(resolveWikiLink(undefined, "ticket-werkwijze", "BETON", refs)).toEqual({
        scope: "global",
        slug: "ticket-werkwijze",
      });
    });

    it("valt terug op een uniek project vanuit de globale wiki", () => {
      // De gemelde klacht: `[[bt-cli-afschaffing]]` in de globale wiki, de
      // pagina staat alleen in BETON.
      const refs = index("BETON bt-cli-afschaffing", "global iets-anders");
      expect(resolveWikiLink(undefined, "bt-cli-afschaffing", "global", refs)).toEqual({
        scope: "BETON",
        slug: "bt-cli-afschaffing",
      });
    });

    it("blijft dood bij meerdere kandidaat-projecten (ambigu)", () => {
      const refs = index("BETON x", "BRAND x");
      expect(resolveWikiLink(undefined, "x", "global", refs)).toEqual({
        scope: "global",
        slug: "x",
      });
    });

    it("een expliciete qualifier slaat de fallback over", () => {
      const refs = index("global x", "BETON x");
      expect(resolveWikiLink("BRAND", "x", "global", refs)).toEqual({
        scope: "BRAND",
        slug: "x",
      });
    });

    it("zonder index blijft het oude gedrag (kaal = huidige scope)", () => {
      expect(resolveWikiLink(undefined, "x", "global")).toEqual({ scope: "global", slug: "x" });
    });

    it("een nergens bestaande slug blijft in de huidige scope (dood)", () => {
      const refs = index("BETON iets-anders");
      expect(resolveWikiLink(undefined, "typo-slug", "global", refs)).toEqual({
        scope: "global",
        slug: "typo-slug",
      });
    });
  });
});

describe("wikiBacklinks", () => {
  const pages = [
    { slug: "deploy", title: "Deploy", body_md: "zie [[triage]] en [[wiki]]" },
    { slug: "triage", title: "Triage", body_md: "verwijst naar [[wiki]]" },
    { slug: "wiki", title: "Wiki", body_md: "geen links" },
  ];

  it("vindt pagina's die naar de slug linken", () => {
    const back = wikiBacklinks(pages, "wiki");
    expect(back.map((p) => p.slug)).toEqual(["deploy", "triage"]);
  });

  it("telt de pagina zelf niet mee", () => {
    const self = [{ slug: "x", body_md: "ik link naar [[x]]" }];
    expect(wikiBacklinks(self, "x")).toEqual([]);
  });

  it("geeft lege lijst zonder target", () => {
    expect(wikiBacklinks(pages, "")).toEqual([]);
  });

  it("is scope-bewust: een link naar een ándere scope telt niet mee (BETON-306)", () => {
    const scoped = [
      { slug: "hier", body_md: "link naar [[doel]]" }, // kaal → BETON:doel
      { slug: "ginder", body_md: "link naar [[global:doel]]" }, // andere scope
    ];
    // In scope BETON linkt alleen 'hier' naar BETON:doel; 'ginder' wijst global.
    expect(wikiBacklinks(scoped, "doel", "BETON").map((p) => p.slug)).toEqual(["hier"]);
  });
});

describe("filterWikiPages", () => {
  const pages = [
    { slug: "deploy-gotchas", title: "Deploy", body_md: "rsync naar de LXC" },
    { slug: "triage", title: "Triage-bot", body_md: "embeddings dedup" },
  ];

  it("matcht op titel, slug en body (case-insensitief)", () => {
    expect(filterWikiPages(pages, "RSYNC").map((p) => p.slug)).toEqual(["deploy-gotchas"]);
    expect(filterWikiPages(pages, "gotchas").map((p) => p.slug)).toEqual(["deploy-gotchas"]);
    expect(filterWikiPages(pages, "bot").map((p) => p.slug)).toEqual(["triage"]);
  });

  it("lege query geeft alle pagina's terug", () => {
    expect(filterWikiPages(pages, "  ")).toBe(pages);
  });
});

describe("wikiLinkQuery", () => {
  it("herkent een actief [[ met fragment", () => {
    const v = "zie [[dep";
    expect(wikiLinkQuery(v, v.length)).toEqual({ start: 4, query: "dep" });
  });

  it("herkent een leeg fragment direct na [[", () => {
    const v = "x [[";
    expect(wikiLinkQuery(v, v.length)).toEqual({ start: 2, query: "" });
  });

  it("null als de link al gesloten is", () => {
    const v = "[[af]] ";
    expect(wikiLinkQuery(v, v.length)).toBe(null);
  });

  it("null over een regeleinde heen", () => {
    const v = "[[\nnee";
    expect(wikiLinkQuery(v, v.length)).toBe(null);
  });

  it("null zonder [[", () => {
    expect(wikiLinkQuery("gewoon tekst", 5)).toBe(null);
  });
});

describe("wikiSlugSuggestions", () => {
  const pages = [
    { slug: "deploy-gotchas", title: "Deploy" },
    { slug: "triage", title: "Triage-bot" },
    { slug: "wiki", title: "Wiki" },
  ];

  it("matcht op slug én titel", () => {
    expect(wikiSlugSuggestions(pages, "dep").map((p) => p.slug)).toEqual(["deploy-gotchas"]);
    expect(wikiSlugSuggestions(pages, "bot").map((p) => p.slug)).toEqual(["triage"]);
  });

  it("leeg fragment geeft alle (gecapt)", () => {
    expect(wikiSlugSuggestions(pages, "", 2)).toHaveLength(2);
  });
});
