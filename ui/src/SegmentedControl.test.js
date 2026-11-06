import { describe, it, expect } from "vitest";
import { render } from "svelte/server";
import SegmentedControl from "./SegmentedControl.svelte";
import { stateOptions } from "./lib/segmentedOptions.js";

describe("kleurherkenning van statusknoppen (BETON-443)", () => {
  it("geeft alle opties hun statekleur en slechts één optie de selectiestijl", () => {
    const options = stateOptions([{ name: "todo", color: "#123456" }, { name: "done", color: "#00aa00" }], { colored: true });
    const { body } = render(SegmentedControl, { props: { options, value: "done" } });
    const buttons = [...body.matchAll(/<button[^>]*>/g)].map((m) => m[0]);
    expect(buttons).toHaveLength(2);
    expect(buttons.every((b) => b.includes("color-hint"))).toBe(true);
    expect(buttons[0]).toContain("#123456");
    expect(buttons[1]).toContain("#00aa00");
    expect(buttons[0]).toContain('aria-checked="false"');
    expect(buttons[0]).not.toMatch(/class="[^"]*selected/);
    expect(buttons[1]).toMatch(/class="[^"]*selected/);
  });
  it("laat controles zonder kleurcontext ongemoeid", () => {
    const { body } = render(SegmentedControl, { props: { options: [{ value: "all", label: "Alles" }], value: "all" } });
    expect(body).not.toMatch(/class="[^"]*color-hint/);
  });
});
