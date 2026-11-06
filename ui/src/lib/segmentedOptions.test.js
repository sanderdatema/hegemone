import { describe, it, expect } from "vitest";
import {
  WORKLOAD_VALUES,
  workloadOptions,
  stateOptions,
} from "./segmentedOptions.js";

describe("workloadOptions", () => {
  it("levert alle werklasten in vaste licht→zwaar-volgorde met NL-labels", () => {
    const opts = workloadOptions();
    expect(opts.map((o) => o.value)).toEqual(WORKLOAD_VALUES);
    expect(opts.map((o) => o.value)).toEqual(["light", "medium", "heavy"]);
    expect(opts[0]).toEqual({ value: "light", label: "Licht" });
    expect(opts.at(-1)).toEqual({ value: "heavy", label: "Zwaar" });
    expect(opts.every((o) => o.label)).toBe(true);
  });
});

describe("stateOptions", () => {
  const states = [{ name: "Todo" }, { name: "In Progress" }, { name: "Done" }];

  it("mapt projectstates naar {value,label}", () => {
    expect(stateOptions(states)).toEqual([
      { value: "Todo", label: "Todo" },
      { value: "In Progress", label: "In Progress" },
      { value: "Done", label: "Done" },
    ]);
  });

  it("heeft geen (default)-pseudo-optie meer (BETON-229)", () => {
    const opts = stateOptions(states);
    expect(opts).toHaveLength(3);
    expect(opts.some((o) => o.value === "")).toBe(false);
    expect(opts.some((o) => o.label === "(default)")).toBe(false);
  });

  it("is veilig bij ontbrekende states", () => {
    expect(stateOptions(undefined)).toEqual([]);
    expect(stateOptions(null)).toEqual([]);
  });

  it("null/lege waarde matcht geen enkele optie — dat is het default-pad", () => {
    // Een SegmentedControl met value="" (niets gekozen) laat geen knop actief
    // zien; de create-call stuurt dan geen `state` mee en de server valt terug
    // op de projectdefault.
    const opts = stateOptions(states);
    expect(opts.find((o) => o.value === "")).toBeUndefined();
    expect(opts.find((o) => o.value === null)).toBeUndefined();
  });
});

describe("kleur per optie (BETON-425)", () => {
  it("geeft standaard geen kleur mee", () => {
    expect(stateOptions([{ name: "Todo", color: "#123456" }])[0]).not.toHaveProperty("color");
    expect(workloadOptions()[0]).not.toHaveProperty("color");
  });

  it("state: per-state kleur wint, anders de groep-token, anders neutraal", () => {
    const opts = stateOptions(
      [
        { name: "Todo", group: "unstarted", color: "#3366ff" },
        { name: "Doing", group: "started" },
        { name: "Weird" },
      ],
      { colored: true },
    );
    expect(opts.map((o) => o.color)).toEqual([
      "#3366ff",
      "var(--accent)",
      "var(--border-strong)",
    ]);
  });

  it("werklast: kleur van de workload-badge", () => {
    const opts = workloadOptions({ colored: true });
    expect(opts.map((o) => o.color)).toEqual([
      "var(--workload-light)",
      "var(--workload-medium)",
      "var(--workload-heavy)",
    ]);
  });
});
