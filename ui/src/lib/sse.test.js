import { describe, it, expect } from "vitest";
import { parseSSE } from "./sse.js";

describe("parseSSE", () => {
  it("parset één compleet event met id + data", () => {
    const { events, rest } = parseSSE('id: 5\ndata: {"type":"item.created"}\n\n');
    expect(events).toEqual([{ id: 5, data: { type: "item.created" } }]);
    expect(rest).toBe("");
  });

  it("houdt een onvolledig laatste frame over als rest", () => {
    const { events, rest } = parseSSE('id: 1\ndata: {"a":1}\n\nid: 2\ndata: {"b":2');
    expect(events).toEqual([{ id: 1, data: { a: 1 } }]);
    expect(rest).toBe('id: 2\ndata: {"b":2');
  });

  it("slaat heartbeat-comments over", () => {
    const { events } = parseSSE(": heartbeat\n\n");
    expect(events).toEqual([]);
  });

  it("verwerkt meerdere events in één buffer", () => {
    const { events } = parseSSE(
      'id: 1\ndata: {"n":1}\n\n: heartbeat\n\nid: 2\ndata: {"n":2}\n\n'
    );
    expect(events.map((e) => e.data.n)).toEqual([1, 2]);
  });
});
