import { describe, it, expect } from "vitest";
import {
  OVERVIEW_VALUE,
  projectPickerOptions,
  projectPickerGroups,
  projectPickerValue,
  projectPickerAction,
} from "./projectPicker.js";
import { isView, VIEWS } from "./viewState.js";

const projects = [
  { key: "BETON", name: "Betonning" },
  { key: "SOS", name: "Dashboard" },
];

describe("projectPicker", () => {
  it("zet Overzicht als bovenste optie, daarna de projecten", () => {
    const opts = projectPickerOptions(projects);
    expect(opts[0].value).toBe(OVERVIEW_VALUE);
    expect(opts.slice(1).map((o) => o.value)).toEqual(["BETON", "SOS"]);
    expect(opts[1].label).toBe("BETON — Betonning");
  });

  it("verdraagt een ontbrekende projectlijst", () => {
    expect(projectPickerOptions(undefined)).toHaveLength(1);
  });

  it("toont Overzicht alleen in de overzicht-view", () => {
    expect(projectPickerValue("overview", "BETON")).toBe(OVERVIEW_VALUE);
    expect(projectPickerValue("board", "BETON")).toBe("BETON");
  });

  it("Overzicht kiezen activeert de overview-view zonder project te wisselen", () => {
    expect(projectPickerAction(OVERVIEW_VALUE, "board")).toEqual({ view: "overview", project: null });
  });

  it("een project kiezen vanuit het overzicht verlaat het overzicht", () => {
    expect(projectPickerAction("SOS", "overview")).toEqual({ view: "board", project: "SOS" });
    expect(projectPickerAction("SOS", "list")).toEqual({ view: null, project: "SOS" });
  });

  it("overview blijft een geldige view voor de URL-codering", () => {
    expect(VIEWS).toContain("overview");
    expect(isView("overview")).toBe(true);
  });

  describe("stille projecten (BETON-475)", () => {
    const NOW = Date.parse("2026-10-25T12:00:00Z");
    const day = (n) => new Date(NOW - n * 86400000).toISOString();
    const ps = [
      { key: "ZED", name: "Zed", last_activity_at: day(1) },
      { key: "KT", name: "Kt", last_activity_at: day(60) },
      { key: "CLICKS", name: "Clicks", last_activity_at: day(90) },
      { key: "LEEG", name: "Leeg", last_activity_at: null },
    ];
    it("zet stille projecten onderaan in een eigen groep, op alfabet", () => {
      expect(projectPickerOptions(ps, null, NOW).slice(1).map((o) => o.value)).toEqual(["ZED"]);
      const g = projectPickerGroups(ps, null, NOW);
      expect(g).toHaveLength(1);
      expect(g[0].label).toBe("Stille projecten");
      expect(g[0].options.map((o) => o.value)).toEqual(["CLICKS", "KT", "LEEG"]);
    });
    it("laat het geopende project in de actieve groep, ook als het stil is", () => {
      expect(projectPickerOptions(ps, "KT", NOW).slice(1).map((o) => o.value)).toEqual(["ZED", "KT"]);
      expect(projectPickerGroups(ps, "KT", NOW)[0].options.map((o) => o.value)).toEqual(["CLICKS", "LEEG"]);
    });
    it("geeft geen groep als niets stil is", () => {
      expect(projectPickerGroups([ps[0]], null, NOW)).toEqual([]);
    });
  });
});

it('vertaalt projectgroepen zonder projectnamen of keuzes te veranderen', () => {
  const now = Date.parse('2026-11-05T12:00:00Z');
  const projects = [{ key: 'EIGEN', name: 'Mijn project', last_activity_at: '2020-01-01T00:00:00Z' }];
  expect(projectPickerOptions(projects, null, now, 'en')[0]).toEqual({ value: OVERVIEW_VALUE, label: 'Overview — all projects' });
  const groups = projectPickerGroups(projects, null, now, 'en');
  expect(groups[0].label).toBe('Quiet projects');
  expect(groups[0].options[0]).toMatchObject({ value: 'EIGEN', label: 'EIGEN — Mijn project' });
});
