import { afterEach, describe, expect, it } from "vitest";
import { render } from "svelte/server";
import ProjectSettings from "./ProjectSettings.svelte";
import { setLocale } from "./lib/i18n.js";

afterEach(() => setLocale("en"));

describe("project automatic ticket locks", () => {
  it.each([
    ["en", "Automatic ticket lock", "existing locks"],
    ["nl", "Automatisch ticketslot", "bestaande sloten"],
  ])("explains and renders the enabled switch in %s", (locale, label, note) => {
    setLocale(locale);
    const { body } = render(ProjectSettings, {
      props: { projectKey: "DEMO", projectName: "Demo", canSetAutoLock: true },
    });
    expect(body).toContain(note);
    expect(body).toMatch(new RegExp(`aria-checked="true"[^>]*aria-label="${label}"`));
  });

  it("shows a disabled policy without granting agents permission to change it", () => {
    setLocale("en");
    const { body } = render(ProjectSettings, {
      props: { projectKey: "DEMO", autoLockEnabled: false, canSetAutoLock: false },
    });
    expect(body).toMatch(/aria-checked="false"[^>]*aria-label="Automatic ticket lock"[^>]*disabled/);
  });
});
