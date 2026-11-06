import { it, expect } from "vitest";
import { formatTimeRange } from "./board.js";
const now = Date.parse("2026-11-02T12:00:00Z");
it("toont gelijke afgeronde tijden eenmaal", () => {
  expect(formatTimeRange("2026-11-01T16:01:00Z", "2026-11-01T16:03:00Z", now)).toBe("20 u geleden");
});
it("behoudt verschillende uiteinden van een reeks", () => {
  expect(formatTimeRange("2026-11-02T10:00:00Z", "2026-11-02T11:00:00Z", now)).toBe("2 u geleden–1 u geleden");
});
