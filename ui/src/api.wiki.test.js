import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "./api.js";

// wikiBase() (BETON-330) is een interne helper voor het project-scope-vs-
// globaal pad; getest via het gedrag van de wiki-methodes die 'm gebruiken
// (niet de implementatie zelf), zoals de rest van api.js getest wordt.
function fakeFetch() {
  return vi.fn(() =>
    Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(null) }),
  );
}

describe("wiki-paden (wikiBase)", () => {
  beforeEach(() => {
    globalThis.localStorage = { getItem: () => "test-key" };
  });

  it("bouwt een project-scoped pad als project gezet is", async () => {
    globalThis.fetch = fakeFetch();
    await api.wikiUpdate("SOS", "mijn-pagina", { content_md: "x" });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/projects/SOS/wiki/mijn-pagina",
      expect.anything(),
    );
  });

  it("bouwt een globaal pad als project null is", async () => {
    globalThis.fetch = fakeFetch();
    await api.wikiDelete(null, "mijn-pagina");
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/wiki/mijn-pagina", expect.anything());
  });

  it("hangt subpaden (revisions) achter het juiste basispad", async () => {
    globalThis.fetch = fakeFetch();
    await api.wikiRevisions("SOS", "mijn-pagina");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/projects/SOS/wiki/mijn-pagina/revisions",
      expect.anything(),
    );

    await api.wikiRevision(null, "mijn-pagina", 7);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/wiki/mijn-pagina/revisions/7",
      expect.anything(),
    );

    await api.wikiRestore("SOS", "mijn-pagina", 7);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/projects/SOS/wiki/mijn-pagina/revisions/7/restore",
      expect.anything(),
    );
  });
});
