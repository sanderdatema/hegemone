import { describe, it, expect } from "vitest";
import { computeCanDrag, detectCanDrag } from "./pointer.js";

describe("computeCanDrag", () => {
  it("staat drag toe op een puur fijn-pointer-toestel (muis, geen touch)", () => {
    expect(computeCanDrag({ anyPointerCoarse: false, maxTouchPoints: 0 })).toBe(true);
  });

  it("zet drag uit op een puur touch-toestel (coarse primair)", () => {
    expect(computeCanDrag({ anyPointerCoarse: true, maxTouchPoints: 5 })).toBe(false);
  });

  it("zet drag uit op een hybride toestel: fijne primaire pointer maar wél touch", () => {
    // iPad + trackpad / touchscreen-laptop: any-pointer coarse of maxTouchPoints > 0.
    expect(computeCanDrag({ anyPointerCoarse: true, maxTouchPoints: 0 })).toBe(false);
    expect(computeCanDrag({ anyPointerCoarse: false, maxTouchPoints: 1 })).toBe(false);
  });

  it("valt veilig terug op drag-toestaan bij lege input", () => {
    expect(computeCanDrag()).toBe(true);
    expect(computeCanDrag({})).toBe(true);
  });
});

describe("detectCanDrag", () => {
  const win = (coarse, mtp) => ({
    matchMedia: (q) => ({ matches: q.includes("any-pointer: coarse") ? coarse : false }),
    navigator: { maxTouchPoints: mtp },
  });

  it("desktop-muis → drag aan", () => {
    expect(detectCanDrag(win(false, 0))).toBe(true);
  });

  it("touch-telefoon → drag uit", () => {
    expect(detectCanDrag(win(true, 5))).toBe(false);
  });

  it("touchscreen-laptop (fijne primaire pointer, maxTouchPoints>0) → drag uit", () => {
    expect(detectCanDrag(win(false, 10))).toBe(false);
  });

  it("zonder window (SSR) → drag toestaan", () => {
    expect(detectCanDrag(undefined)).toBe(true);
  });

  it("window zonder matchMedia → valt terug op maxTouchPoints", () => {
    expect(detectCanDrag({ navigator: { maxTouchPoints: 3 } })).toBe(false);
    expect(detectCanDrag({ navigator: { maxTouchPoints: 0 } })).toBe(true);
  });
});
