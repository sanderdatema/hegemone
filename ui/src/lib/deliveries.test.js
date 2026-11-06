import { describe, it, expect } from "vitest";
import {
  DELIVERY_STATUSES,
  statusLabel,
  statusTone,
  canReplay,
} from "./deliveries.js";

describe("deliveries pure logic", () => {
  it("kent de vier migratie-010-statussen", () => {
    expect(DELIVERY_STATUSES).toEqual([
      "pending",
      "delivered",
      "failed",
      "cancelled",
    ]);
  });

  it("labelt bekende statussen in het Nederlands", () => {
    expect(statusLabel("delivered")).toBe("geleverd");
    expect(statusLabel("failed")).toBe("mislukt");
    expect(statusLabel("cancelled")).toBe("geannuleerd");
    expect(statusLabel("pending")).toBe("in wachtrij");
  });

  it("valt terug op de ruwe waarde voor onbekende status", () => {
    expect(statusLabel("weird")).toBe("weird");
    expect(statusLabel("")).toBe("onbekend");
  });

  it("mapt status naar een toon-token", () => {
    expect(statusTone("delivered")).toBe("ok");
    expect(statusTone("failed")).toBe("bad");
    expect(statusTone("cancelled")).toBe("muted");
    expect(statusTone("pending")).toBe("pending");
    expect(statusTone("weird")).toBe("muted");
  });

  it("staat replay alleen toe voor mislukt en geannuleerd", () => {
    expect(canReplay("failed")).toBe(true);
    expect(canReplay("cancelled")).toBe(true);
    expect(canReplay("pending")).toBe(false);
    expect(canReplay("delivered")).toBe(false);
  });
});

it('vertaalt statussen zonder API-waarden of replaybeleid te wijzigen', () => {
  expect(statusLabel('pending', 'en')).toBe('queued');
  expect(statusLabel('failed', 'en')).toBe('failed');
  expect(statusLabel('', 'en')).toBe('unknown');
  expect(canReplay('failed')).toBe(true);
  expect(canReplay('delivered')).toBe(false);
});
