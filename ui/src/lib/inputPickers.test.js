import { it, expect, vi, afterEach } from "vitest";
import { candidateSearch, pickerKey, textPicker, relationPicker, toggleSelection } from "./inputPickers.js";
afterEach(() => vi.useRealTimers());
function setupText() {
  let state = { text: "", caret: 0, mentionMatches: [], hashMatches: [], mentionActive: 0, hashActive: 0 };
  const api = { refCandidates: vi.fn(async () => [{ ref: "SOS-12", title: "Twaalf" }]) };
  const textarea = { focus: vi.fn(), setSelectionRange: vi.fn() };
  const picker = textPicker({ get: () => state, set: patch => { state = { ...state, ...patch }; }, users: () => [{ handle: "person", display_name: "Person" }], project: () => "SOS", api, tick: async () => {}, textarea: () => textarea });
  return { picker, state: () => state, api, textarea };
}
it("mention zoeken, invoegen en cursor terugzetten", async () => {
  const { picker, state, textarea } = setupText();
  picker.input({ currentTarget: { value: "Hoi @per", selectionStart: 8 } });
  expect(state().mentionMatches[0].handle).toBe("person");
  await picker.pickMention("person");
  expect(state().text).toBe("Hoi @person ");
  expect(textarea.setSelectionRange).toHaveBeenCalledWith(12, 12);
});
it("refzoekopdracht is projectgebonden, kiezen sluit en voegt in", async () => {
  vi.useFakeTimers(); const { picker, state, api } = setupText();
  picker.input({ currentTarget: { value: "Zie #12", selectionStart: 7 } });
  await vi.advanceTimersByTimeAsync(150);
  expect(api.refCandidates).toHaveBeenCalledWith("12", "SOS", 12);
  expect(state().hashMatches[0].ref).toBe("SOS-12");
  await picker.pickHash("SOS-12");
  expect(state().text).toBe("Zie SOS-12 "); expect(state().hashMatches).toEqual([]);
});
it("nieuwe invoer maakt een lopende zoekopdracht meteen ongeldig", async () => {
  vi.useFakeTimers(); let resolve; const receive = vi.fn();
  const search = candidateSearch(() => new Promise(r => { resolve = r; }), receive);
  search.input("oud"); await vi.advanceTimersByTimeAsync(150);
  search.input(null); resolve(["oud"]); await Promise.resolve();
  expect(receive.mock.calls).toEqual([[[]], [[]]]);
});
it("pijltjes wrappen, Shift+Enter blijft tekst en Tab kiest alleen refs", () => {
  const key = (key, shiftKey = false) => ({ key, shiftKey, preventDefault: vi.fn() });
  expect(pickerKey(key("ArrowUp"), 3, 0)).toEqual({ active: 2 });
  expect(pickerKey(key("ArrowDown"), 3, 2)).toEqual({ active: 0 });
  expect(pickerKey(key("Enter", true), 3, 0)).toBeNull();
  expect(pickerKey(key("Tab"), 3, 1)).toBeNull();
  expect(pickerKey(key("Tab"), 3, 1, { tab: true })).toEqual({ pick: 1 });
});
it("relatie zoekt één cijfer als ref en sluit het eigen ticket uit", async () => {
  vi.useFakeTimers(); let state = { target: "", matches: [], active: 0 };
  const api = { refCandidates: vi.fn(async () => [{ ref: "SOS-12" }, { ref: "SOS-21" }]), search: vi.fn(async () => []) };
  const picker = relationPicker({ get: () => state, set: patch => { state = { ...state, ...patch }; }, project: () => "SOS", self: () => "SOS-12", api, tick: async () => {}, textarea: () => null, add: vi.fn() });
  picker.input({ currentTarget: { value: "2" } }); await vi.advanceTimersByTimeAsync(150);
  expect(api.refCandidates).toHaveBeenCalledWith("2", "SOS", 6);
  expect(state.matches).toEqual([{ ref: "SOS-21" }]);
  await picker.pick("SOS-21"); expect(state.target).toBe("SOS-21"); expect(state.matches).toEqual([]);
  picker.input({ currentTarget: { value: "titel" } }); await vi.advanceTimersByTimeAsync(150);
  expect(api.search).toHaveBeenCalledWith("titel", 6);
});
it("labels omschakelen laat andere keuzes staan", () => {
  expect(toggleSelection(["bug"], "feature")).toEqual(["bug", "feature"]);
  expect(toggleSelection(["bug", "feature"], "bug")).toEqual(["feature"]);
});
