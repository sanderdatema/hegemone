import { describe, it, expect } from "vitest";
import { parsePath, parseHashRef, buildPath } from "./routing.js";

describe("parsePath", () => {
  it("wortelpad → geen route", () => {
    expect(parsePath("/")).toEqual({ project: null, ref: null, query: {} });
    expect(parsePath("")).toEqual({ project: null, ref: null, query: {} });
  });

  it("project-pad → alleen project", () => {
    expect(parsePath("/SOS")).toEqual({ project: "SOS", ref: null, query: {} });
  });

  it("project + seq → project + ref", () => {
    expect(parsePath("/SOS/42")).toEqual({ project: "SOS", ref: "SOS-42", query: {} });
  });

  it("uppercaset de project-key (case-insensitief pad)", () => {
    expect(parsePath("/sos/42")).toEqual({ project: "SOS", ref: "SOS-42", query: {} });
  });

  it("negeert trailing slash en lege segmenten", () => {
    expect(parsePath("/SOS/42/")).toEqual({ project: "SOS", ref: "SOS-42", query: {} });
  });

  it("niet-numerieke of te diepe paden → geen ref", () => {
    expect(parsePath("/SOS/abc")).toEqual({ project: "SOS", ref: null, query: {} });
    expect(parsePath("/SOS/42/extra")).toEqual({ project: "SOS", ref: null, query: {} });
  });

  it("geen search-arg → lege query", () => {
    expect(parsePath("/SOS").query).toEqual({});
  });
});

describe("parsePath — querystring (BETON-358)", () => {
  it("parset bekende filtervelden + view/scope/sort", () => {
    const r = parsePath("/SOS", "?assignee=person&view=list&scope=all&sort=workload");
    expect(r.query).toEqual({ assignee: "person", view: "list", scope: "all", sort: "workload" });
  });

  it("werkt met of zonder leidend ?", () => {
    expect(parsePath("/SOS", "assignee=person").query).toEqual({ assignee: "person" });
    expect(parsePath("/SOS", "?assignee=person").query).toEqual({ assignee: "person" });
  });

  it("negeert onbekende keys", () => {
    expect(parsePath("/SOS", "?assignee=person&foo=bar").query).toEqual({ assignee: "person" });
  });

  it("vertaalt boolean-filtervelden ('1' → true); ontbrekend → geen key", () => {
    const r = parsePath("/SOS", "?mine=1&unread=0");
    expect(r.query).toEqual({ mine: true, unread: false });
    expect(parsePath("/SOS", "").query).toEqual({});
  });

  it("lege of ontbrekende search → lege query", () => {
    expect(parsePath("/SOS", "").query).toEqual({});
    expect(parsePath("/SOS", "?").query).toEqual({});
  });

  it("ref + query komen samen terug", () => {
    expect(parsePath("/SOS/42", "?view=board")).toEqual({
      project: "SOS",
      ref: "SOS-42",
      query: { view: "board" },
    });
  });
});

describe("parseHashRef", () => {
  it("geldige hash-deeplink → project + ref (geüppercased)", () => {
    expect(parseHashRef("#sos-42")).toEqual({ project: "SOS", ref: "SOS-42" });
  });

  it("werkt met of zonder leidend #", () => {
    expect(parseHashRef("SOS-42")).toEqual({ project: "SOS", ref: "SOS-42" });
  });

  it("onbekende/lege vorm → null-route", () => {
    expect(parseHashRef("")).toEqual({ project: null, ref: null });
    expect(parseHashRef("#/board")).toEqual({ project: null, ref: null });
    expect(parseHashRef(null)).toEqual({ project: null, ref: null });
  });
});

describe("buildPath", () => {
  it("niets → wortelpad", () => {
    expect(buildPath(null, null)).toBe("/");
  });

  it("alleen project", () => {
    expect(buildPath("SOS", null)).toBe("/SOS");
  });

  it("ref bepaalt het pad, ook cross-project", () => {
    expect(buildPath("SOS", "SOS-42")).toBe("/SOS/42");
    expect(buildPath("SOS", "BETON-7")).toBe("/BETON/7");
  });

  it("uppercaset de key en is een round-trip met parsePath", () => {
    expect(buildPath("sos", "sos-42")).toBe("/SOS/42");
    expect(parsePath(buildPath("SOS", "SOS-42"))).toEqual({
      project: "SOS",
      ref: "SOS-42",
      query: {},
    });
  });
});

describe("buildPath — querystring (BETON-358)", () => {
  it("serialiseert alleen niet-lege query-velden", () => {
    expect(buildPath("SOS", null, { assignee: "person", label: "" })).toBe(
      "/SOS?assignee=person",
    );
  });

  it("laat false/null/undefined/lege string weg", () => {
    expect(
      buildPath("SOS", null, { mine: false, due: null, q: undefined, label: "" }),
    ).toBe("/SOS");
  });

  it("serialiseert booleans als '1'", () => {
    expect(buildPath("SOS", null, { mine: true })).toBe("/SOS?mine=1");
  });

  it("negeert onbekende query-keys", () => {
    expect(buildPath("SOS", null, { onzin: "iets" })).toBe("/SOS");
  });

  it("view=list&scope=all", () => {
    expect(buildPath("SOS", null, { view: "list", scope: "all" })).toBe(
      "/SOS?view=list&scope=all",
    );
  });

  it("ref + query samen", () => {
    expect(buildPath("SOS", "SOS-42", { view: "board" })).toBe("/SOS/42?view=board");
  });

  it("geen query-arg → gelijk aan de oude 2-arg call", () => {
    expect(buildPath("SOS", "SOS-42")).toBe("/SOS/42");
  });

  it("round-trip met parsePath", () => {
    const path = buildPath("SOS", null, { assignee: "person", view: "list", mine: true });
    const [pathname, search] = path.split("?");
    expect(parsePath(pathname, search ? `?${search}` : "")).toEqual({
      project: "SOS",
      ref: null,
      query: { assignee: "person", view: "list", mine: true },
    });
  });
});
