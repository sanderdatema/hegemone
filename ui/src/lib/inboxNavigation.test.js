import { it, expect } from "vitest";
import { openInboxGroup } from "./inbox.js";
it("opent een notificatie voordat een trage mark-read klaar is", async () => {
  const calls = []; let finish;
  const pending = openInboxGroup({ ref: "SOS-2" }, ref => calls.push(ref), () => {
    calls.push("markeren"); return new Promise(resolve => { finish = resolve; });
  });
  expect(calls).toEqual(["SOS-2", "markeren"]);
  finish(); await pending;
});
