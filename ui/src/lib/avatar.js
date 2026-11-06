// Deterministische avatar-helpers: initialen + achtergrondkleur uit een
// handle-hash. Pure functies (geen DOM) zodat ze met vitest te testen zijn en
// door Avatar.svelte, kaarten (fase 3) en de drawer (fase 4) hergebruikt worden.

// Contrast-veilige tintenset: donker genoeg voor witte tekst, en herkenbaar
// verschillend van de accent-indigo. Vaste volgorde → stabiele hashkeuze.
export const AVATAR_COLORS = [
  "#5b5bd6", // indigo (accent-familie)
  "#0e7c86", // teal
  "#b5477f", // magenta
  "#2f7d4f", // groen
  "#9a5b1f", // amber-bruin
  "#4a63c0", // blauw
  "#a23f3f", // rood-bruin
  "#6b4bb0", // paars
  "#3a7ca5", // staalblauw
  "#8a6d1f", // olijf
];

/**
 * Stabiele string-hash (djb2). Niet-cryptografisch; alleen voor kleurkeuze.
 * @param {string} s
 * @returns {number} niet-negatief geheel getal
 */
export function hashString(s) {
  let h = 5381;
  const str = String(s ?? "");
  for (let i = 0; i < str.length; i++) {
    h = (h * 33) ^ str.charCodeAt(i);
  }
  return h >>> 0; // naar unsigned 32-bit
}

/**
 * Kies deterministisch een avatarkleur voor een handle.
 * @param {string} handle
 * @returns {string} hexkleur uit AVATAR_COLORS
 */
export function avatarColor(handle) {
  return AVATAR_COLORS[hashString(handle) % AVATAR_COLORS.length];
}

// Gecureerde, visueel goed onderscheidbare tinten voor label-chips. We geven
// alleen de hue terug; de daadwerkelijke licht/donker-variant zit in CSS
// (.label-chip gebruikt --label-h in hsl()), zodat labels in beide thema's
// voldoende contrast houden.
export const LABEL_HUES = [8, 28, 45, 95, 140, 168, 192, 215, 250, 280, 315, 340];

/**
 * Deterministische hue (0–359) voor een label-naam.
 * @param {string} name
 * @returns {number} hue uit LABEL_HUES
 */
export function labelHue(name) {
  return LABEL_HUES[hashString(name) % LABEL_HUES.length];
}

// Standaardkleur van een label dat nooit een eigen kleur kreeg (BETON-461).
export const LABEL_DEFAULT_COLOR = "#95a5a6";

const GOLDEN_ANGLE = 137.508;

/**
 * Tint voor het label op positie `index` van de gesorteerde projectlabels:
 * de gouden hoek spreidt opeenvolgende posities zo ver mogelijk uit elkaar,
 * dus twee labels van één project delen geen tint (BETON-461).
 * @param {number} index
 */
export function positionHue(index) {
  return Math.round((index * GOLDEN_ANGLE) % 360) % 360;
}

/**
 * Tint (0–359) van een `#rrggbb`-kleur, of `null` als de waarde geen
 * bruikbare kleur is of grijs (grijs heeft geen tint).
 * @param {string|null|undefined} hex
 */
export function hexToHue(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex ?? "").trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const r = (n >> 16) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  if (d === 0) return null;
  let h;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return Math.round((h * 60 + 360) % 360) % 360;
}

/**
 * Naam→tint voor alle labels van één project. Een label met een eigen kleur
 * (niet de oude default) gebruikt die; de rest krijgt een tint op basis van
 * zijn positie in de op naam gesorteerde lijst.
 * @param {Array<{name: string, color?: string|null}>} labels
 * @returns {Map<string, number>}
 */
export function labelHueMap(labels) {
  const sorted = [...(labels || [])].sort((a, b) =>
    a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
  );
  const map = new Map();
  sorted.forEach((l, i) => {
    const custom =
      l.color && l.color.toLowerCase() !== LABEL_DEFAULT_COLOR ? hexToHue(l.color) : null;
    map.set(l.name, custom ?? positionHue(i));
  });
  return map;
}

/**
 * Bouw een handle→avatar_url-lookup uit de users-lijst (GET /api/v1/users).
 * Items dragen alleen een assignee-handle, geen avatar_url zelf — kaarten/
 * lijst/comments hebben deze map nodig om `avatarUrl` aan Avatar.svelte door
 * te geven (BETON-81). Users zonder avatar_url komen niet in de map, zodat
 * Avatar netjes terugvalt op initialen.
 * @param {Array<{handle: string, avatar_url?: string|null}>} users
 * @returns {Map<string, string>}
 */
export function avatarUrlMap(users) {
  const map = new Map();
  for (const u of users || []) {
    if (u?.handle && u.avatar_url) map.set(u.handle, u.avatar_url);
  }
  return map;
}

/**
 * Handles van virtuele queues (`is_virtual`, bv. coding-agent, hermes-agent)
 * als Set, zodat de lijst ze visueel van personen kan onderscheiden (BETON-460).
 */
export function virtualHandleSet(users) {
  const set = new Set();
  for (const u of users || []) {
    if (u?.handle && u.is_virtual) set.add(u.handle);
  }
  return set;
}

/**
 * Initialen (1–2 letters, uppercase) voor een handle. Bij scheidingstekens
 * (-, _, .) de eerste letter van de eerste twee delen; anders de eerste twee
 * letters van de handle.
 * @param {string} handle
 * @returns {string}
 */
export function initials(handle) {
  const h = String(handle ?? "").trim();
  if (!h) return "?";
  const parts = h.split(/[-_.\s]+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return h.slice(0, 2).toUpperCase();
}
