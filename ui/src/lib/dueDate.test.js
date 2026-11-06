import { describe, it, expect } from "vitest";
import { todayISO, dueMeta } from "./dueDate.js";

describe("todayISO", () => {
  it("geeft de lokale kalenderdag als YYYY-MM-DD", () => {
    // Midden op de dag (12:00) — geen tijdzone-flip naar buurdag.
    const d = new Date(2026, 6, 12, 12, 0, 0); // 12 juli 2026, lokaal
    expect(todayISO(d)).toBe("2026-07-12");
  });
});

describe("dueMeta", () => {
  const today = "2026-07-12";

  it("null zonder einddatum", () => {
    expect(dueMeta(null, today)).toBeNull();
    expect(dueMeta("", today)).toBeNull();
  });

  it("overdue voor een dag in het verleden", () => {
    expect(dueMeta("2026-07-10", today)).toEqual({
      kind: "overdue",
      title: "Te laat: 2026-07-10",
    });
  });

  it("today voor vandaag", () => {
    expect(dueMeta("2026-07-12T09:00:00Z", today)).toEqual({
      kind: "today",
      title: "Vandaag: 2026-07-12",
    });
  });

  it("future voor een dag in de toekomst", () => {
    expect(dueMeta("2026-07-20", today)).toEqual({
      kind: "future",
      title: "Einddatum: 2026-07-20",
    });
  });
});

it('vertaalt datumlabels met behoud van de dagvergelijking', () => {
  expect(dueMeta('2026-11-01', '2026-11-05', 'en')).toEqual({kind:'overdue',title:'Overdue: 2026-11-01'});
  expect(dueMeta('2026-11-05', '2026-11-05', 'en').kind).toBe('today');
});
