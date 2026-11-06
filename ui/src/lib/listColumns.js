// Zichtbare lijstkolommen (BETON-448). Ref en titel blijven altijd staan.
import { LIST_COLUMNS } from "./board.js";
export const OPTIONAL_COLUMNS = LIST_COLUMNS.filter((c) => !["ref", "title"].includes(c.key));

export function readHiddenColumns(raw) {
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return OPTIONAL_COLUMNS.map((c) => c.key).filter((key) => parsed.includes(key));
  } catch {
    return [];
  }
}

export function toggleColumn(hidden, key) {
  if (!OPTIONAL_COLUMNS.some((c) => c.key === key)) return hidden;
  return hidden.includes(key) ? hidden.filter((k) => k !== key) : [...hidden, key];
}
