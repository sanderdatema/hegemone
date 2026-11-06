import { describe, it, expect } from "vitest";
import {
  validateWebhookUrl,
  buildSettingsPatch,
  hasChanges,
} from "./userSettings.js";

const initial = {
  webhook_url: null,
  telegram_chat_id: null,
  description: null,
  subscribe_all: false,
};

describe("validateWebhookUrl", () => {
  it("staat leeg toe (wist de webhook)", () => {
    expect(validateWebhookUrl("")).toBe("");
    expect(validateWebhookUrl("   ")).toBe("");
  });
  it("accepteert http en https", () => {
    expect(validateWebhookUrl("http://host:8644/webhooks/smid")).toBe("");
    expect(validateWebhookUrl("https://example.test/hook")).toBe("");
  });
  it("weigert niet-http(s)", () => {
    expect(validateWebhookUrl("ftp://x")).not.toBe("");
    expect(validateWebhookUrl("host/hook")).not.toBe("");
  });
});

describe("buildSettingsPatch", () => {
  it("is leeg zonder wijzigingen", () => {
    expect(buildSettingsPatch({ ...initial }, initial)).toEqual({});
  });

  it("stuurt alleen gewijzigde velden mee", () => {
    const draft = { ...initial, webhook_url: "https://x.test/h" };
    expect(buildSettingsPatch(draft, initial)).toEqual({
      webhook_url: "https://x.test/h",
    });
  });

  it("wist een veld met leeg → null", () => {
    const withUrl = { ...initial, webhook_url: "https://x.test/h" };
    const draft = { ...withUrl, webhook_url: "  " };
    expect(buildSettingsPatch(draft, withUrl)).toEqual({ webhook_url: null });
  });

  it("stuurt subscribe_all als boolean bij wijziging", () => {
    const draft = { ...initial, subscribe_all: true };
    expect(buildSettingsPatch(draft, initial)).toEqual({ subscribe_all: true });
  });

  it("stuurt het secret alleen mee als het is ingevuld", () => {
    expect(buildSettingsPatch({ ...initial, webhook_secret: "" }, initial)).toEqual(
      {},
    );
    expect(
      buildSettingsPatch({ ...initial, webhook_secret: "  s3cret " }, initial),
    ).toEqual({ webhook_secret: "s3cret" });
  });

  it("negeert een ongewijzigde description die al gevuld was", () => {
    const withDesc = { ...initial, description: "hallo" };
    expect(buildSettingsPatch({ ...withDesc }, withDesc)).toEqual({});
  });
});

describe("hasChanges", () => {
  it("false zonder wijzigingen", () => {
    expect(hasChanges({ ...initial }, initial)).toBe(false);
  });
  it("true bij een nieuw secret", () => {
    expect(hasChanges({ ...initial, webhook_secret: "x" }, initial)).toBe(true);
  });
});

it('geeft dezelfde URL-validatie in het Engels zonder de patch te veranderen', () => {
  expect(validateWebhookUrl('invalid', 'en')).toBe('Webhook URL must start with http:// or https://.');
  expect(validateWebhookUrl('https://receiver.example.org/events', 'en')).toBe('');
});
