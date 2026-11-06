import { it, expect, vi } from "vitest";
import { latestTask } from "./latestTask.js";
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
it.each([false, true])("negeert verouderd antwoord of fout na een notificatieklik (%s)", async (fails) => {
  const old = deferred(), next = deferred();
  const callbacks = { apply: vi.fn(), error: vi.fn(), settled: vi.fn() };
  const load = latestTask((ref) => ref === "A" ? old.promise : next.promise, callbacks);
  const a = load("A"), b = load("B");
  next.resolve("ticket B"); await b;
  if (fails) old.reject(new Error("oude fout")); else old.resolve("ticket A");
  await a;
  expect(callbacks.apply.mock.calls).toEqual([["ticket B"]]);
  expect(callbacks.error).not.toHaveBeenCalled();
  expect(callbacks.settled).toHaveBeenCalledTimes(1);
});
it("toont de fout van de nieuwste aanvraag", async () => {
  const error = vi.fn(), settled = vi.fn();
  await latestTask(async () => { throw new Error("offline"); }, { apply: vi.fn(), error, settled })();
  expect(error.mock.calls[0][0].message).toBe("offline");
  expect(settled).toHaveBeenCalledOnce();
});
