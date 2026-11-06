import { describe, it, expect } from "vitest";
import { markUpTo } from "./Inbox.svelte";

// BETON-125: klikken op een inbox-entry moet 'm als gelezen markeren.
// De read-marker is één watermark op event_id (repo/inbox.py:mark_seen) —
// markUpTo spiegelt dat gedrag lokaal zodat de UI direct bijwerkt.

const ENTRIES = [
  { event_id: 3, read: false },
  { event_id: 2, read: false },
  { event_id: 1, read: true },
];

describe("markUpTo", () => {
  it("markeert alleen entries met event_id <= watermark als gelezen", () => {
    const result = markUpTo(ENTRIES, 2);
    expect(result.map((e) => e.read)).toEqual([false, true, true]);
  });

  it("laat entries boven de watermark ongelezen", () => {
    const result = markUpTo(ENTRIES, 1);
    expect(result.map((e) => [e.event_id, e.read])).toEqual([
      [3, false],
      [2, false],
      [1, true],
    ]);
  });

  it("markeert alles als de watermark de hoogste event_id is", () => {
    const result = markUpTo(ENTRIES, 3);
    expect(result.every((e) => e.read)).toBe(true);
  });

  it("muteert de invoer niet (nieuwe objecten/array)", () => {
    const result = markUpTo(ENTRIES, 2);
    expect(result).not.toBe(ENTRIES);
    expect(ENTRIES[1].read).toBe(false); // origineel ongemoeid
  });

  it("gaat netjes om met een ontbrekende/lege lijst", () => {
    expect(markUpTo(undefined, 5)).toEqual([]);
    expect(markUpTo([], 5)).toEqual([]);
  });
});
