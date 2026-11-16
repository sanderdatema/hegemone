import { writable } from "svelte/store";

// Account-scoped browser preference shared by creation and detail views.
export const quickAssignmentPreferences = writable({});
export const quickAssignmentKey = (handle) => `hegemone_quick_assignment:${handle}`;

export function quickAssignmentSelection(handle, preferences = {}, storage) {
  if (!handle) return null;
  if (Object.hasOwn(preferences, handle)) return preferences[handle];
  try {
    const value = JSON.parse((storage ?? globalThis.localStorage)?.getItem(quickAssignmentKey(handle)) ?? "null");
    return Array.isArray(value) && value.every((entry) => typeof entry === "string") ? value : null;
  } catch {
    return null;
  }
}

export function setQuickAssignmentSelection(handle, selection) {
  if (!handle) return;
  const value = selection === null ? null : [...new Set(selection)];
  try {
    if (value === null) localStorage.removeItem(quickAssignmentKey(handle));
    else localStorage.setItem(quickAssignmentKey(handle), JSON.stringify(value));
  } catch { /* Keep the preference for this session if storage is unavailable. */ }
  quickAssignmentPreferences.update((preferences) => ({ ...preferences, [handle]: value }));
}

export function activeAssignmentAgents(users = []) {
  return users.filter((user) => user.kind === "agent" && user.active !== false && user.active !== 0);
}

export function defaultQuickAssignmentAgent(user) {
  return user.agent_type === "coding" || user.handle === "coding-agent";
}
