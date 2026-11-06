import { describe, it, expect } from "vitest";
import { shouldNotify, notificationText, titleWithUnread } from "./notifications.js";

describe("shouldNotify", () => {
  const base = { enabled: true, permission: "granted", hidden: true, delta: 1 };

  it("waar als alles klopt: opt-in, permissie, tab op de achtergrond, nieuwe items", () => {
    expect(shouldNotify(base)).toBe(true);
  });

  it("niet als de opt-in uitstaat", () => {
    expect(shouldNotify({ ...base, enabled: false })).toBe(false);
  });

  it("niet zonder browserpermissie", () => {
    expect(shouldNotify({ ...base, permission: "denied" })).toBe(false);
    expect(shouldNotify({ ...base, permission: "default" })).toBe(false);
  });

  it("niet als het tabblad zichtbaar is (je ziet het al op het scherm)", () => {
    expect(shouldNotify({ ...base, hidden: false })).toBe(false);
  });

  it("niet zonder nieuwe items (delta 0 of ontbrekend)", () => {
    expect(shouldNotify({ ...base, delta: 0 })).toBe(false);
    expect(shouldNotify({ enabled: true, permission: "granted", hidden: true })).toBe(false);
  });

  it("werkt zonder argumenten (alles ontbreekt → false)", () => {
    expect(shouldNotify()).toBe(false);
  });
});

describe("notificationText", () => {
  it("gebruikt de ref als titel", () => {
    const { title } = notificationText({ ref: "SOS-42", reason: "comment", actor: "claude" });
    expect(title).toBe("SOS-42");
  });

  it("mention: @actor + label", () => {
    const { body } = notificationText({ ref: "SOS-1", reason: "mention", actor: "person" });
    expect(body).toBe("@person noemde je");
  });

  it("assigned: @actor + label", () => {
    const { body } = notificationText({ ref: "SOS-1", reason: "assigned", actor: "triage" });
    expect(body).toBe("@triage wees je toe");
  });

  it("comment: @actor + label", () => {
    const { body } = notificationText({ ref: "SOS-1", reason: "comment", actor: "claude" });
    expect(body).toBe("@claude reageerde op je item");
  });

  it("onbekende reason valt terug op update", () => {
    const { body } = notificationText({ ref: "SOS-1", reason: "geheim", actor: "claude" });
    expect(body).toBe("@claude wijzigde je item");
  });

  it("zonder actor blijft het label zonder @-prefix", () => {
    const { body } = notificationText({ ref: "SOS-1", reason: "update", actor: null });
    expect(body).toBe("wijzigde je item");
  });

  it("due: gebruikt dueLabel (vandaag vs. verstreken), geen actor-prefix", () => {
    const today = notificationText({
      ref: "SOS-1",
      reason: "due",
      actor: null,
      due_date: "2026-09-02",
      overdue: false,
    });
    expect(today.body).toBe("deadline vandaag");
    const overdue = notificationText({
      ref: "SOS-1",
      reason: "due",
      actor: null,
      due_date: "2026-09-01",
      overdue: true,
    });
    expect(overdue.body).toBe("deadline verstreken (2026-09-01)");
  });
});

describe("titleWithUnread", () => {
  it("zonder ongelezen items blijft de titel ongewijzigd", () => {
    expect(titleWithUnread("SOS · Betonning", 0)).toBe("SOS · Betonning");
  });

  it("met ongelezen items komt de teller vooraan", () => {
    expect(titleWithUnread("SOS · Betonning", 3)).toBe("(3) SOS · Betonning");
  });

  it("negatief telt als geen ongelezen items", () => {
    expect(titleWithUnread("Betonning", -1)).toBe("Betonning");
  });
});

it('vertaalt browsermeldingen met behoud van actor, ref en datum', () => {
  const entry={ref:'OWN-1',reason:'mention',actor:'eigen-naam'};
  expect(notificationText(entry,'en')).toEqual({title:'OWN-1',body:'@eigen-naam mentioned you'});
  expect(notificationText({...entry,reason:'due',overdue:true,due_date:'2026-11-05'},'en').body).toBe('overdue (2026-11-05)');
  expect(notificationText(entry,'nl').body).toBe('@eigen-naam noemde je');
  expect(entry.actor).toBe('eigen-naam');
});
