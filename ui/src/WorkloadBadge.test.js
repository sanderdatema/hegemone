import { setLocale } from "./lib/i18n.js";
beforeEach(() => setLocale("nl"));
import { beforeEach, describe, it, expect } from "vitest";
import { render } from "svelte/server";
import WorkloadBadge from "./WorkloadBadge.svelte";

// Server-side render (svelte/server) werkt in de node-omgeving zonder DOM/jsdom.

describe("WorkloadBadge", () => {
  it("rendert het icoon + NL-titel voor light", () => {
    const { body } = render(WorkloadBadge, { props: { workload: "light" } });
    expect(body).toContain("workload-icon");
    expect(body).toContain('title="Werklast: licht (tokens)"');
    expect(body).toContain(">L<");
    expect(body).toContain("var(--workload-light)");
  });

  it("rendert het icoon + NL-titel voor medium", () => {
    const { body } = render(WorkloadBadge, { props: { workload: "medium" } });
    expect(body).toContain('title="Werklast: middel (tokens)"');
    expect(body).toContain(">M<");
    expect(body).toContain("var(--workload-medium)");
  });

  it("rendert het icoon + NL-titel voor heavy", () => {
    const { body } = render(WorkloadBadge, { props: { workload: "heavy" } });
    expect(body).toContain('title="Werklast: zwaar (tokens)"');
    expect(body).toContain(">Z<");
    expect(body).toContain("var(--workload-heavy)");
  });

  it("rendert niets bij een lege of onbekende workload", () => {
    const empty = render(WorkloadBadge, { props: { workload: "" } });
    expect(empty.body).not.toContain("workload-icon");

    const unknown = render(WorkloadBadge, { props: { workload: "mystery" } });
    expect(unknown.body).not.toContain("workload-icon");
  });

  it("schaalt het lettertype met de size-prop", () => {
    const { body } = render(WorkloadBadge, { props: { workload: "light", size: 14 } });
    expect(body).toContain("font-size: 14px");
  });
});
