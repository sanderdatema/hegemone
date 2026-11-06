// Gedeelde invoerhulp voor Drawer en Nieuw ticket (BETON-485).
// Componenten houden tekst/DOM; deze module beheert zoeken, kiezen en toetsen.
import { mentionQuery, applyMention, filterMentionCandidates } from "./mentionAutocomplete.js";
import { hashQuery, filterTicketCandidates, applyHashRef } from "./hashAutocomplete.js";
import { relSearchMode } from "./drawerLogic.js";

export function toggleSelection(values, value) {
  return values.includes(value) ? values.filter(v => v !== value) : [...values, value];
}

/** Ongeldig maken gebeurt bij invoer, dus ook tijdens de debounce van de opvolger. */
export function candidateSearch(search, receive, onerror = () => {}) {
  let timer, sequence = 0;
  function cancel() { clearTimeout(timer); sequence++; }
  function input(query) {
    cancel(); receive([]);
    if (query == null || query === "") return;
    const mine = sequence;
    timer = setTimeout(async () => {
      try { const rows = await search(query); if (mine === sequence) receive(rows); }
      catch (e) { if (mine === sequence) { receive([]); onerror(e); } }
    }, 150);
  }
  return { input, cancel };
}

/** Pijltjes wrappen; Shift+Enter blijft een nieuwe regel. */
export function pickerKey(event, count, active, { tab = false } = {}) {
  if (!count) return null;
  let action = null;
  if (event.key === "ArrowDown") action = { active: (active + 1) % count };
  if (event.key === "ArrowUp") action = { active: (active - 1 + count) % count };
  if ((event.key === "Enter" && !event.shiftKey) || (tab && event.key === "Tab")) action = { pick: active };
  if (action) event.preventDefault();
  return action;
}

export function textPicker({ get, set, users, project, api, tick, textarea, localEscape = false }) {
  const hash = candidateSearch(async q => filterTicketCandidates(await api.refCandidates(q, project(), 12), q, project(), 12), rows => set({ hashMatches: rows, hashActive: 0 }));
  function closeHash() { hash.cancel(); set({ hashMatches: [] }); }
  function close() { closeHash(); set({ mentionMatches: [] }); }
  function input(e) {
    const text = e.currentTarget.value, caret = e.currentTarget.selectionStart;
    set({ text, caret, mentionMatches: filterMentionCandidates(users(), mentionQuery(text.slice(0, caret))), mentionActive: 0 });
    hash.input(hashQuery(text.slice(0, caret)));
  }
  async function pick(kind, value) {
    const state = get();
    const result = (kind === "hash" ? applyHashRef : applyMention)(state.text, state.caret, value);
    close(); set({ text: result.text, caret: result.caret });
    await tick();
    textarea()?.focus(); textarea()?.setSelectionRange(result.caret, result.caret);
  }
  function keydown(e) {
    const state = get(), isHash = state.hashMatches.length > 0;
    const rows = isHash ? state.hashMatches : state.mentionMatches;
    const action = pickerKey(e, rows.length, isHash ? state.hashActive : state.mentionActive, { tab: isHash });
    if (action?.active != null) set({ [isHash ? "hashActive" : "mentionActive"]: action.active });
    if (action?.pick != null) pick(isHash ? "hash" : "mention", rows[action.pick][isHash ? "ref" : "handle"]);
    if (localEscape && e.key === "Escape" && rows.length) { e.preventDefault(); e.stopPropagation(); close(); }
  }
  return { input, keydown, pickMention: value => pick("mention", value), pickHash: value => pick("hash", value), close, closeHash };
}

export function relationPicker({ get, set, project, self = () => null, api, tick, textarea, add, onerror, localEscape = false }) {
  const search = candidateSearch(async q => {
    const rows = relSearchMode(q) === "ref"
      ? filterTicketCandidates(await api.refCandidates(q, project(), 6), q, project(), 6)
      : await api.search(q, 6);
    return rows.filter(row => row.ref !== self());
  }, rows => set({ matches: rows, active: 0 }), onerror);
  function close() { search.cancel(); set({ matches: [] }); }
  function input(e) {
    const target = e.currentTarget.value; set({ target });
    search.input(relSearchMode(target.trim()) == null ? null : target.trim());
  }
  async function pick(target) { close(); set({ target }); await tick(); textarea()?.focus(); }
  function keydown(e) {
    const state = get();
    if (!state.matches.length && e.key === "Enter") { e.preventDefault(); add(); return; }
    const action = pickerKey(e, state.matches.length, state.active);
    if (action?.active != null) set({ active: action.active });
    if (action?.pick != null) pick(state.matches[action.pick].ref);
    if (localEscape && e.key === "Escape" && state.matches.length) { e.preventDefault(); e.stopPropagation(); close(); }
  }
  return { input, keydown, pick, close };
}
