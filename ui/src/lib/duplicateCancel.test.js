import { describe, it, expect } from "vitest";
import { duplicateRefForRelation, resolveDuplicateCancelAction } from "./duplicateCancel.js";

describe("duplicateRefForRelation", () => {
  it("duplicate_of: het huidige item is het duplicaat", () => {
    expect(duplicateRefForRelation("duplicate_of", "BETON-1", "BETON-2")).toBe("BETON-1");
  });

  it("duplicated_by: het doel is het duplicaat", () => {
    expect(duplicateRefForRelation("duplicated_by", "BETON-1", "BETON-2")).toBe("BETON-2");
  });

  it("andere relatietypen hebben geen duplicaat-semantiek", () => {
    expect(duplicateRefForRelation("relates_to", "BETON-1", "BETON-2")).toBeNull();
    expect(duplicateRefForRelation("blocks", "BETON-1", "BETON-2")).toBeNull();
    expect(duplicateRefForRelation("blocked_by", "BETON-1", "BETON-2")).toBeNull();
  });
});

describe("resolveDuplicateCancelAction", () => {
  it("cancelt wanneer er een cancelled-state is en het item nog open is", () => {
    expect(
      resolveDuplicateCancelAction({ stateGroup: "started", cancelledStateName: "Cancelled" })
    ).toEqual({ action: "cancel", stateName: "Cancelled" });
  });

  it("slaat over als het duplicaat al cancelled is (idempotent)", () => {
    expect(
      resolveDuplicateCancelAction({ stateGroup: "cancelled", cancelledStateName: "Cancelled" })
    ).toEqual({ action: "skip", reason: "already-closed" });
  });

  it("slaat over als het duplicaat al done/completed is (idempotent)", () => {
    expect(
      resolveDuplicateCancelAction({ stateGroup: "completed", cancelledStateName: "Cancelled" })
    ).toEqual({ action: "skip", reason: "already-closed" });
  });

  it("slaat over als het project geen cancelled-state heeft", () => {
    expect(
      resolveDuplicateCancelAction({ stateGroup: "started", cancelledStateName: null })
    ).toEqual({ action: "skip", reason: "no-cancelled-state" });
  });
});
