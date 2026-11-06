import { describe, it, expect } from "vitest";
import {
  AGENT_TYPES,
  showsAgentType,
  showsWebhookFields,
  groupAssignees,
} from "./agentType.js";

describe("AGENT_TYPES", () => {
  it("bevat coding en hermes", () => {
    expect(AGENT_TYPES).toEqual(["coding", "hermes"]);
  });
});

describe("showsAgentType", () => {
  it("true voor agent", () => {
    expect(showsAgentType("agent")).toBe(true);
  });
  it("false voor human", () => {
    expect(showsAgentType("human")).toBe(false);
  });
});

describe("showsWebhookFields", () => {
  it("true voor agent + hermes", () => {
    expect(showsWebhookFields("agent", "hermes")).toBe(true);
  });
  it("false voor agent + coding", () => {
    expect(showsWebhookFields("agent", "coding")).toBe(false);
  });
  it("false voor agent zonder agent_type", () => {
    expect(showsWebhookFields("agent", null)).toBe(false);
    expect(showsWebhookFields("agent", undefined)).toBe(false);
  });
  it("false voor human, ook met agent_type gezet", () => {
    expect(showsWebhookFields("human", "hermes")).toBe(false);
  });
});

describe("groupAssignees", () => {
  const person = { handle: "person", kind: "human", agent_type: null, is_virtual: false, active: true };
  const smid = { handle: "smid", kind: "human", agent_type: null, is_virtual: false, active: true };
  const codingQueue = { handle: "coding-agent", kind: "agent", agent_type: "coding", is_virtual: true, active: true };
  const hermesQueue = { handle: "hermes-agent", kind: "agent", agent_type: "hermes", is_virtual: true, active: true };
  const claude = { handle: "claude", kind: "agent", agent_type: "coding", is_virtual: false, active: true };
  const lobke = { handle: "lobke", kind: "agent", agent_type: "hermes", is_virtual: false, active: true };
  const triage = { handle: "triage", kind: "agent", agent_type: null, is_virtual: false, active: true };
  const inactive = { handle: "oud-account", kind: "human", agent_type: null, is_virtual: false, active: false };
  const users = [smid, person, codingQueue, hermesQueue, claude, lobke, triage, inactive];

  it("zet 'Aan mij' vooraan met alleen de ingelogde user", () => {
    const groups = groupAssignees(users, person);
    expect(groups[0].label).toBe("Aan mij");
    expect(groups[0].options).toEqual([person]);
  });

  it("groepeert queues, mensen, coding-/hermes-agents en overig", () => {
    const groups = groupAssignees(users, person);
    const byLabel = Object.fromEntries(groups.map((g) => [g.label, g.options.map((u) => u.handle)]));
    expect(byLabel["Queues"]).toEqual(["coding-agent", "hermes-agent"]);
    expect(byLabel["Mensen"]).toEqual(["smid"]); // person zit al in "Aan mij"
    expect(byLabel["Coding-agents"]).toEqual(["claude"]);
    expect(byLabel["Hermes-agents"]).toEqual(["lobke"]);
    expect(byLabel["Overig"]).toEqual(["triage"]);
  });

  it("laat lege groepen weg", () => {
    const groups = groupAssignees([person], person);
    expect(groups.map((g) => g.label)).toEqual(["Aan mij"]);
  });

  it("sorteert binnen een groep op handle", () => {
    const groups = groupAssignees(users, null);
    const mensen = groups.find((g) => g.label === "Mensen");
    expect(mensen.options.map((u) => u.handle)).toEqual(["person", "smid"]);
  });

  it("laat inactieve users weg, behalve de huidige assignee (keep)", () => {
    const withoutKeep = groupAssignees(users, person);
    expect(withoutKeep.flatMap((g) => g.options).some((u) => u.handle === "oud-account")).toBe(false);

    const withKeep = groupAssignees(users, person, { keep: "oud-account" });
    const mensen = withKeep.find((g) => g.label === "Mensen");
    expect(mensen.options.map((u) => u.handle)).toContain("oud-account");
  });

  it("werkt zonder ingelogde user (geen 'Aan mij'-groep)", () => {
    const groups = groupAssignees(users, null);
    expect(groups.some((g) => g.label === "Aan mij")).toBe(false);
  });
});
