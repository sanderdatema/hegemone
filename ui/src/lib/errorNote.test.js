import { describe, it, expect } from "vitest";
import { resolveErrorNote } from "./errorNote.js";

describe("resolveErrorNote", () => {
  it("is onzichtbaar zonder boodschap", () => {
    expect(resolveErrorNote({}).visible).toBe(false);
    expect(resolveErrorNote({ message: "" }).visible).toBe(false);
    expect(resolveErrorNote({ message: "   " }).visible).toBe(false);
  });

  it("toont de retry-knop alleen met bericht én callback", () => {
    expect(resolveErrorNote({ message: "Kon niet laden" }).showRetry).toBe(false);
    expect(
      resolveErrorNote({ message: "Kon niet laden", onRetry: () => {} }).showRetry,
    ).toBe(true);
    expect(
      resolveErrorNote({ message: "", onRetry: () => {} }).showRetry,
    ).toBe(false);
  });

  it("trimt de boodschap", () => {
    expect(resolveErrorNote({ message: "  Kon niet laden  " }).message).toBe(
      "Kon niet laden",
    );
  });

  it("gebruikt het standaard retry-label zonder override", () => {
    expect(
      resolveErrorNote({ message: "x", onRetry: () => {} }).retryLabel,
    ).toBe("Opnieuw proberen");
  });

  it("gebruikt een aangeleverd retry-label", () => {
    expect(
      resolveErrorNote({
        message: "x",
        onRetry: () => {},
        retryLabel: "Herlaad comments",
      }).retryLabel,
    ).toBe("Herlaad comments");
  });

  it("valt terug op het standaardlabel bij een leeg override", () => {
    expect(
      resolveErrorNote({ message: "x", onRetry: () => {}, retryLabel: "   " })
        .retryLabel,
    ).toBe("Opnieuw proberen");
  });
});
