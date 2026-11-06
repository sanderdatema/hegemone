// Pure tekst-helpers voor de wiki: `[[..]]`-interlinks parsen/resolveren,
// backlinks, zoeken en `[[`-autocomplete. Losgetrokken uit board.js
// (BETON-334).

/**
 * Regex voor een wiki-interlink `[[..]]` (BETON-57, cross-scope BETON-306,
 * alias BETON-346). Optionele scope-qualifier vóór de slug: een project-key
 * (hoofdletters, bv. `BETON`) of het gereserveerde `global`. Zonder qualifier
 * = huidige scope. Optionele Obsidian-stijl alias ná de slug (`|tekst`) — de
 * weergavetekst, los van het doel (dat blijft de slug).
 *
 * Groep 1 = qualifier (of undefined), groep 2 = slug (kebab-case, veilig
 * injecteerbaar), groep 3 = aliastekst (of undefined; vrije tekst zonder `]`
 * of newline — de injectie-veiligheid zit niet in deze regex maar in de
 * aanroeper: `renderWikiMarkdown` matcht pas ná markdown-it's HTML-escaping,
 * dus alias-tekst is op dat punt al veilig). Voorbeelden: `[[slug]]`,
 * `[[BETON:slug]]`, `[[slug|Weergavetekst]]`, `[[BETON:slug|Weergavetekst]]`.
 */
export const WIKILINK_RE =
  /\[\[(?:([A-Z][A-Z0-9]*|global):)?([a-z0-9]+(?:-[a-z0-9]+)*)(?:\|([^\]\n]+))?\]\]/g;

/**
 * Resolveer een wikilink naar zijn doel-scope (BETON-306). `scope` is
 * `"global"` of een project-key.
 *
 * Een expliciete qualifier (`[[BETON:slug]]`) wint altijd. Een **kale**
 * `[[slug]]` zoekt, als de index (`knownRefs`) meegegeven is, in deze volgorde:
 *
 *   1. de huidige scope — een lokale pagina wint van elke vreemde,
 *   2. de globale wiki,
 *   3. precies één project dat de slug heeft.
 *
 * Bij meerdere kandidaat-projecten (en geen lokale/globale treffer) blijft de
 * link in de huidige scope staan en rendert dus dood — dat is ambigu en de
 * schrijver moet 'm dan expliciet kwalificeren.
 *
 * Zonder index valt hij terug op het oude gedrag (kaal = huidige scope), zodat
 * aanroepers zonder index-kennis niets stuk maken.
 *
 * Deze fallback is de kern van BETON-306: in de praktijk is élke link in de
 * wiki kaal geschreven (0 van de 75 droeg een qualifier), dus zonder deze
 * stap bleven cross-scope verwijzingen dood ondanks de qualifier-syntax.
 *
 * @param {string|undefined} rawScope de gematchte qualifier (groep 1) of undefined
 * @param {string} slug
 * @param {string} currentScope scope van de huidige weergave/bronpagina
 * @param {Set<string>|null} [knownRefs] index-keys `"<scope> <slug>"`, of null
 * @returns {{scope: string, slug: string}}
 */
export function resolveWikiLink(rawScope, slug, currentScope, knownRefs = null) {
  if (rawScope) return { scope: rawScope, slug };
  if (!knownRefs) return { scope: currentScope, slug };
  if (knownRefs.has(`${currentScope} ${slug}`)) return { scope: currentScope, slug };
  if (knownRefs.has(`global ${slug}`)) return { scope: "global", slug };
  // Scope en slug bevatten per WIKILINK_RE geen spaties, dus de eerste spatie
  // is de scheiding.
  const projects = [];
  for (const key of knownRefs) {
    const sep = key.indexOf(" ");
    if (sep === -1 || key.slice(sep + 1) !== slug) continue;
    const s = key.slice(0, sep);
    if (s !== "global" && !projects.includes(s)) projects.push(s);
  }
  if (projects.length === 1) return { scope: projects[0], slug };
  return { scope: currentScope, slug };
}

/**
 * Verzamel de unieke `[[..]]`-verwijzingen uit een stuk tekst, elk resolved naar
 * `{scope, slug}` (BETON-57, cross-scope BETON-306). Een kale `[[slug]]` erft de
 * `sourceScope` van de bronpagina; een gekwalificeerde `[[BETON:slug]]` draagt
 * zijn eigen scope.
 * @param {string} text
 * @param {string} [sourceScope] scope van de bronpagina (voor kale links)
 * @param {Set<string>|null} [knownRefs] index voor de kale-link-fallback
 * @returns {Array<{scope: string, slug: string}>} unieke refs in tekstvolgorde
 */
export function extractWikiLinks(text, sourceScope = "global", knownRefs = null) {
  const out = [];
  const seen = new Set();
  for (const m of (text || "").matchAll(WIKILINK_RE)) {
    const { scope, slug } = resolveWikiLink(m[1], m[2], sourceScope, knownRefs);
    // Spatie-separator, zelfde vorm als de /wiki/index-keys in markdown.js
    // (`"<scope> <slug>"`); WIKILINK_RE staat geen spaties toe in scope/slug.
    const key = `${scope} ${slug}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push({ scope, slug });
    }
  }
  return out;
}

/**
 * Backlinks bepalen (BETON-57): welke pagina's in de huidige scope linken naar de
 * opgegeven pagina. Scope-bewust (BETON-306): een link telt alleen als hij ná
 * resolutie exact naar `{currentScope, targetSlug}` wijst — een
 * `[[global:foo]]` in een projectpagina is dus géén backlink naar de
 * projectpagina `foo`. De pagina zelf telt niet mee (geen zelf-backlink).
 *
 * NB: kijkt alleen binnen de meegegeven `pages` (de huidige scope). Backlinks
 * vanuit een ándere scope vergen alle bodies over alle scopes en vallen buiten
 * deze functie.
 * @param {Array<{slug: string, title?: string, body_md?: string}>} pages
 * @param {string} targetSlug
 * @param {string} [currentScope] scope van de pagina's én de doelpagina
 * @param {Set<string>|null} [knownRefs] index voor de kale-link-fallback
 * @returns {Array<{slug: string, title?: string, body_md?: string}>}
 */
export function wikiBacklinks(pages, targetSlug, currentScope = "global", knownRefs = null) {
  if (!targetSlug) return [];
  return (pages || []).filter(
    (p) =>
      p.slug !== targetSlug &&
      extractWikiLinks(p.body_md, currentScope, knownRefs).some(
        (l) => l.scope === currentScope && l.slug === targetSlug
      )
  );
}

/**
 * Filter wiki-pagina's op een zoekterm (BETON-57): case-insensitief op titel,
 * slug én body. Lege query → alle pagina's ongewijzigd terug.
 * @param {Array<{slug: string, title?: string, body_md?: string}>} pages
 * @param {string} query
 * @returns {Array<{slug: string, title?: string, body_md?: string}>}
 */
export function filterWikiPages(pages, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return pages || [];
  return (pages || []).filter(
    (p) =>
      (p.title || "").toLowerCase().includes(q) ||
      (p.slug || "").toLowerCase().includes(q) ||
      (p.body_md || "").toLowerCase().includes(q)
  );
}

/**
 * `[[`-autocomplete-context bepalen (BETON-57). Kijkt vanaf de caret terug naar
 * de dichtstbijzijnde nog-niet-gesloten `[[`; geeft de startpositie en het al
 * getypte fragment terug, of `null` als de caret niet in een `[[`-context zit
 * (geen `[[`, al gesloten met `]]`, of een newline/ongeldig teken ertussen).
 * @param {string} value volledige textarea-inhoud
 * @param {number} caret cursorpositie (selectionStart)
 * @returns {{start: number, query: string} | null}
 */
export function wikiLinkQuery(value, caret) {
  const before = (value || "").slice(0, caret);
  const open = before.lastIndexOf("[[");
  if (open === -1) return null;
  const frag = before.slice(open + 2);
  // Al gesloten of over een regeleinde heen → geen actieve context.
  if (/[\]\n]/.test(frag)) return null;
  // Fragment moet op een slug lijken (kebab-case, mag leeg zijn direct na `[[`).
  if (!/^[a-z0-9-]*$/.test(frag)) return null;
  return { start: open, query: frag };
}

/**
 * Kies passende slug-suggesties voor `[[`-autocomplete (BETON-57): match op slug
 * óf titel, gecapt op een handzaam aantal.
 * @param {Array<{slug: string, title?: string}>} pages
 * @param {string} query
 * @param {number} [limit=8]
 * @returns {Array<{slug: string, title?: string}>}
 */
export function wikiSlugSuggestions(pages, query, limit = 8) {
  const q = (query || "").toLowerCase();
  return (pages || [])
    .filter(
      (p) =>
        p.slug.toLowerCase().includes(q) || (p.title || "").toLowerCase().includes(q)
    )
    .slice(0, limit);
}
