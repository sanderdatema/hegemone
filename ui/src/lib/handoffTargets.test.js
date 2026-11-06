import { describe, it, expect } from "vitest";
import { handoffTargets } from "./drawerLogic.js";
const me = { handle: "person", kind: "human" };
const users = [{ handle: "coding-agent", kind: "agent", is_virtual: true }, { handle: "claude", kind: "agent" }, me];
const item = { assignee: "person", previous_assignee: "claude" };

describe("snelle overdracht (BETON-470)", () => {
  it("biedt coding-queue en vorige agent in die volgorde", () => {
    expect(handoffTargets(item, me, users).map((t) => t.handle)).toEqual(["coding-agent", "claude"]);
  });
  it("toont coding-agent maar één keer en geen vorige mens", () => {
    for (const previous_assignee of [null, "coding-agent", "person"]) {
      expect(handoffTargets({ ...item, previous_assignee }, me, users).map((t) => t.handle)).toEqual(["coding-agent"]);
    }
  });
  it("toont niets voor agents en beschermde tickets", () => {
    expect(handoffTargets(item, { ...me, kind: "agent" }, users)).toEqual([]);
    for (const extra of [{ locked_at: "nu" }, { archived_at: "nu" }]) {
      expect(handoffTargets({ ...item, ...extra }, me, users)).toEqual([]);
    }
  });
  it("slaat verdwenen of inactieve agents over", () => {
    expect(handoffTargets(item, me, users.map((u) => ({ ...u, active: false })))).toEqual([]);
    expect(handoffTargets(item, me, [])).toEqual([]);
  });
});

describe("snelle coding-toewijzing (BETON-507)", () => {
  it("is beschikbaar zonder assignee en bij een andere assignee", () => {
    for (const assignee of [null, "", "claude", "ander-mens"]) {
      expect(handoffTargets({ ...item, assignee }, me, users))
        .toEqual([{ handle: "coding-agent", label: "→ coding-agent" }]);
    }
  });
  it("biedt geen dubbele toewijzing als coding-agent al gekozen is", () => {
    expect(handoffTargets({ ...item, assignee: "coding-agent" }, me, users)).toEqual([]);
  });
});

import { preferredHandoffTarget } from './drawerLogic.js';

it('biedt ingestelde coding-agents met eigen handles aan zonder vaste queue', () => {
  const roster = [
    { handle: 'builder', kind: 'agent', agent_type: 'coding', active: true },
    { handle: 'helper', kind: 'agent', agent_type: 'coding', active: true },
    { handle: 'sleeping', kind: 'agent', agent_type: 'coding', active: false },
    { handle: 'human', kind: 'human', agent_type: 'coding', active: true },
    { handle: 'receiver', kind: 'agent', agent_type: 'hermes', active: true },
  ];
  expect(handoffTargets({ assignee: null }, me, roster)).toEqual([
    { handle: 'builder', label: '→ builder' }, { handle: 'helper', label: '→ helper' },
  ]);
  expect(handoffTargets({ assignee: 'builder' }, me, roster).map(t => t.handle)).toEqual(['helper']);
  for (const extra of [{ locked_at: 'now' }, { archived_at: 'now' }]) expect(handoffTargets(extra, me, roster)).toEqual([]);
});

it('geeft de vorige configureerbare agent voorrang zonder dubbele knop', () => {
  const roster = ['builder', 'helper'].map(handle => ({ handle, kind: 'agent', agent_type: 'coding', active: true }));
  const current = { assignee: me.handle, previous_assignee: 'helper' };
  const targets = handoffTargets(current, me, roster);
  expect(targets).toEqual([{ handle: 'builder', label: '→ builder' }, { handle: 'helper', label: '↩ @helper' }]);
  expect(preferredHandoffTarget(targets, current, me).handle).toBe('helper');
  expect(preferredHandoffTarget(targets, { ...current, assignee: 'someone-else' }, me).handle).toBe('builder');
  expect(preferredHandoffTarget([], current, me)).toBeNull();
});
