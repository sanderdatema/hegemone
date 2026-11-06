/**
 * Markdown-rendering voor de hele app, op basis van markdown-it (BETON-132).
 *
 * Voorheen had de smalle drawer/chat een eigen parser in board.js, terwijl de
 * brede wiki-view al op markdown-it draaide. Sinds BETON-132 is er één
 * renderer (deze module); board.js bevat geen markdown-rendering meer.
 *
 * Twee varianten, één gedeelde pijplijn:
 *  - `renderWikiMarkdown(text, slugs, keys)` — brede wiki-view, géén
 *    heading-offset (H1=H1), met `[[slug]]`-interlinks.
 *  - `renderMarkdown(text, handles, keys)` — smalle drawer/chat, mét
 *    heading-offset +2 (`#`→`<h3>`; H5/H6 clampen op H6), met `@handle`-
 *    mention-chips. Geen `[[slug]]` (die leven alleen in de wiki).
 *
 * Beide delen dezelfde markdown-it-instantie, dezelfde URL-whitelist en
 * dezelfde ticketref-linkificatie (hergebruikt uit board.js).
 *
 * Beveiliging (gelijk aan voorheen):
 *  - `html:false` → gebruikers-HTML wordt ge-escaped, nooit als markup gelezen.
 *  - Link/afbeelding-URLs worden alleen geaccepteerd als ze http(s)://, een
 *    absoluut pad (/…, bv. de attachment-serve-URL) of een anker (#…) zijn —
 *    géén `javascript:`, `data:` e.d. (BETON-5/veilige-links).
 *  - `@handle`-mentions draaien op de veilige output-HTML en matchen alleen
 *    bekende handles (case-insensitief), zodat er nooit onveilige markup
 *    binnenkomt (BETON-60).
 *
 * Kale URL's (BETON-406): `linkify: true` laat markdown-it's ingebouwde
 * linkify-pass ook een URL zónder `[tekst](url)`-syntax omzetten naar een
 * klikbare link (`target="_blank" rel="noopener noreferrer"`, via dezelfde
 * `link_open`-regel als hierboven). Die pass loopt door dezelfde
 * `validateLink`-whitelist (`md.validateLink` geldt voor élke link, ook
 * autolinked), dus een kale `javascript:`- of `data:`-tekst wordt nooit een
 * link. In de praktijk betekent de whitelist ook dat alleen expliciete
 * `http(s)://`-URL's gelinkificeerd worden: linkify-it's fuzzy-matching van
 * kale domeinen (`www.example.com`) en e-mailadressen levert URL's zónder
 * `http(s)://`-schema op, en die vallen bewust af op dezelfde whitelist —
 * geen apart opt-out nodig. Autolinked ankers krijgen `data-autolink="1"`
 * zodat `linkifyTicketRefs` (board.js) hun ZICHTBARE tekst (de URL zelf)
 * met rust laat — anders zou een URL met een ticketref-achtig patroon erin
 * (`https://x.nl/BETON-123`) een tweede `<a>` in de eerste openen.
 */
import MarkdownIt from "markdown-it";
import { linkifyTicketRefs, escapeHtml } from "./board.js";
import { WIKILINK_RE, resolveWikiLink } from "./wikiText.js";

const SAFE_URL = /^(https?:\/\/|\/|#)/i;

const md = new MarkdownIt({
  // html:true alleen om de whitelist hieronder (`beton_html_whitelist`) te
  // laten beslissen: elk html-token wordt daar óf een kale details/summary-tag
  // óf platte (ge-escapete) tekst. Er komt nooit andere markup door (BETON-458).
  html: true,
  linkify: true,
  breaks: false,
  typographer: false,
});

// Alleen URL's met een expliciet http(s)-schema linkificeren (BETON-406).
// linkify-it's fuzzy-matching herkent standaard ook kale domeinen
// (`www.example.com`) en e-mailadressen zónder schema; die normaliseert
// linkify-it zelf al naar een `http://`/`mailto:`-URL vóórdat onze
// `validateLink`-whitelist hem ziet, dus de whitelist filtert ze niet
// vanzelf weg (mailto: zou dat wel doen — dat schema staat er niet op — maar
// linkify-it's fuzzy `www.`-links krijgen intern al een `http://`-prefix en
// halen de whitelist dus gewoon). Bewuste keuze: alleen wat de gebruiker
// zelf als een volledige URL schreef wordt klikbaar; een los domein of
// e-mailadres in lopende tekst blijft platte tekst.
md.linkify.set({ fuzzyLink: false, fuzzyEmail: false, fuzzyIP: false });

// Whitelist op link- en image-URLs: alleen http(s)://, absoluut pad of anker.
// markdown-it weigert `javascript:` zelf al, maar géén `data:` of vreemde
// schema's — deze regel maakt de policy expliciet en uniform met voorheen.
const _origValidateLink = md.validateLink;
md.validateLink = (url) => SAFE_URL.test(url.trim()) && _origValidateLink(url);

// Open links in een nieuw tabblad met `noopener` (gelijk aan board.js-vóór
// BETON-132). Loopt via een render-rule, dus geldt voor álle varianten.
const _defaultLinkOpen =
  md.renderer.rules.link_open ||
  ((tokens, idx, opts, env, self) => self.renderToken(tokens, idx, opts));
md.renderer.rules.link_open = function (tokens, idx, opts, env, self) {
  if (tokens[idx].attrIndex("target") < 0) tokens[idx].attrPush(["target", "_blank"]);
  if (tokens[idx].attrIndex("rel") < 0) tokens[idx].attrPush(["rel", "noopener noreferrer"]);
  // Markeer autolinks (BETON-406, kale URL via linkify) zodat
  // linkifyTicketRefs hun zichtbare tekst — de URL zelf — met rust laat.
  if (tokens[idx].markup === "linkify" && tokens[idx].attrIndex("data-autolink") < 0) {
    tokens[idx].attrPush(["data-autolink", "1"]);
  }
  return _defaultLinkOpen(tokens, idx, opts, env, self);
};

// <details>/<summary> whitelist (BETON-458). Alleen de kale tags (en
// `<details open>`) komen door, zonder attributen; al het andere HTML-token
// wordt tekst en dus ge-escaped. Draait op de token-stream, dus code-spans en
// codeblokken (geen html-tokens) blijven altijd tekst.
const ALLOWED_TAG = /^<(\/?)(details|summary)(\s+open)?\s*>$/i;
const TAG_SPLIT = /(<\/?(?:details|summary)(?:\s+open)?\s*>)/gi;

function normalizeTag(raw) {
  const m = ALLOWED_TAG.exec(raw);
  if (!m) return null;
  const tag = m[2].toLowerCase();
  if (m[1]) return `</${tag}>`;
  return m[3] && tag === "details" ? "<details open>" : `<${tag}>`;
}

// Een html-blok mag alleen BEGINNEN met een toegestane tag. Alles wat daar niet
// mee begint (<div>, <script>, <!-- -->, <pre> …) blijft zoals vóór html:true
// gewoon een alinea met ge-escapete tekst: het kan een lopende alinea niet meer
// onderbreken en slokt geen lege regels meer op.
const _rule = md.block.ruler.__rules__[md.block.ruler.__find__("html_block")];
const _origHtmlBlock = { fn: _rule.fn, alt: _rule.alt.slice() };
const BLOCK_START = /^<\/?(?:details|summary)(?:\s+open)?\s*>/i;
md.block.ruler.at(
  "html_block",
  (state, startLine, endLine, silent) => {
    const pos = state.bMarks[startLine] + state.tShift[startLine];
    const line = state.src.slice(pos, state.eMarks[startLine]);
    if (!BLOCK_START.test(line)) return false;
    return _origHtmlBlock.fn(state, startLine, endLine, silent);
  },
  { alt: _origHtmlBlock.alt }
);

// Escape zoals in tekst, maar laat bestaande entiteiten (&nbsp;) staan: in een
// alinea zouden die ook ontleed zijn. Een entiteit blijft tekst, nooit markup.
function escapeKeepEntities(s) {
  return md.utils
    .escapeHtml(s)
    .replace(/&amp;(#\d{1,7}|#x[0-9a-f]{1,6}|[a-z][a-z0-9]{1,31});/gi, "&$1;");
}

md.core.ruler.push("beton_html_whitelist", (state) => {
  for (const tok of state.tokens) {
    if (tok.type === "html_block") {
      const parts = tok.content.split(TAG_SPLIT);
      tok.content = parts
        .map((p, i) => (i % 2 === 1 ? normalizeTag(p) ?? escapeKeepEntities(p) : escapeKeepEntities(p)))
        .join("");
    } else if (tok.type === "inline" && tok.children) {
      for (const child of tok.children) {
        if (child.type !== "html_inline") continue;
        const norm = normalizeTag(child.content.trim());
        if (norm) child.content = norm;
        else child.type = "text";
      }
    }
  }
});

// Eénmalige registratie van de heading-offset-rule; per call stuurt de
// env-variabele `headingOffset` (meegegeven aan `md.render`) of en hoeveel er
// verschoven wordt. Loopt als core-rule vóór het renderen, dus op de
// geparseerde token-stream. Offset +2 voor de smalle drawer/chat (`#`→`<h3>`
// … `###`→`<h5>`; H4–H6 clampen op H6), 0 voor de brede wiki-view (H1=H1).
md.core.ruler.push("beton_heading_offset", (state) => {
  const off = state.env && state.env.headingOffset;
  if (!off) return;
  for (const tok of state.tokens) {
    if (tok.type === "heading_open" || tok.type === "heading_close") {
      const lvl = Number(tok.tag.slice(1));
      tok.tag = "h" + Math.min(Math.max(lvl + off, 1), 6);
    }
  }
});

/**
 * Render met een gegeven heading-offset en trim de trailing newline die
 * markdown-it standaard toevoegt. `off` = 0 voor de wiki (H1=H1), 2 voor de
 * smalle drawer/chat (`#`→`<h3>`).
 *
 * @param {string} text
 * @param {number} off  heading-offset (0 of 2)
 * @returns {string} veilige HTML zonder trailing newline
 */
function renderWith(text, off) {
  return md.render(String(text ?? ""), { headingOffset: off }).replace(/\n$/, "");
}

/**
 * Vervang `@handle` van bekende users door een gestyleerde mention-chip. Draait
 * op reeds veilige markdown-it-HTML: `@` is letterlijk (geen markup), en de
 * handle matcht alleen `[A-Za-z0-9_-]+`, dus er komt nooit onveilige markup
 * binnen. Alleen bekende handles (case-insensitief) worden een chip;
 * e-mailadressen (`foo@bar`) en pad-fragmenten (`/@x`) blijven met rust.
 * Overgenomen uit board.js (BETON-60), dat sinds BETON-132 geen renderer meer
 * bevat — deze helper is de enige plek waar mentions worden aangebracht.
 *
 * @param {string} html   veilige markdown-it-output-HTML
 * @param {Set<string>} handles  bekende handles (lowercased)
 * @returns {string}
 */
// Nabewerking mag uitsluitend tekst raken, nooit bestaande HTML-attributen.
function textOnly(html, replace) {
  return html.split(/(<[^>]+>)/g).map((part, i) => i % 2 ? part : replace(part)).join("");
}

function _mentions(html, handles) {
  if (!handles || handles.size === 0) return html;
  return textOnly(html, part => part.replace(
    /(^|[^\w@/])@([A-Za-z0-9_-]+)/g,
    (m, pre, handle) =>
      handles.has(handle.toLowerCase())
        ? `${pre}<span class="mention" data-mention="${handle}">@${handle}</span>`
        : m
  ));
}

/**
 * Render markdown voor de **smalle** context (drawer-omschrijving, comments,
 * triage-chat) naar veilige HTML op basis van markdown-it (BETON-132).
 *
 * Heading-offset +2 (`#`→`<h3>` … `###`→`<h5>`, H4–H6 clampen op H6) om de
 * visuele hiërarchie in de smalle kolom te behouden — gelijk aan de oude
 * eigen parser. Ondersteunt volledige GFM-tabellen en H1–H6, die de oude
 * parser niet kon (BETON-132). `@handle`-mentions van bekende users worden
 * chips (BETON-60); ticketrefs van bekende project-keys worden klikbaar
 * (BETON-107). Geen `[[slug]]`-interlinks (die zijn wiki-only).
 *
 * @param {string} text
 * @param {Array<string>|Set<string>} [knownHandles]  handles die als chip renderen
 * @param {Iterable<string>} [knownProjectKeys] bekende project-keys (voor ticketref-links)
 * @returns {string} veilige HTML
 */
export function renderMarkdown(text, knownHandles = [], knownProjectKeys = []) {
  const handles =
    knownHandles instanceof Set
      ? new Set([...knownHandles].map((h) => String(h).toLowerCase()))
      : new Set((knownHandles || []).map((h) => String(h).toLowerCase()));
  let html = renderWith(text, 2);
  if (handles.size) html = _mentions(html, handles);
  const keys = new Set([...knownProjectKeys].map((k) => String(k).toUpperCase()));
  if (keys.size) html = linkifyTicketRefs(html, keys);
  return html;
}

/**
 * Render wiki-markdown naar veilige HTML met wiki- en ticket-interlinks
 * (brede wiki-view). Géén heading-offset (H1=H1, …, H6=H6); wél `[[..]]`-
 * interlinks (BETON-25/57) met optionele dood/levend-markering.
 *
 * Cross-scope (BETON-306): een link kan een scope-qualifier dragen
 * (`[[BETON:slug]]`, `[[global:slug]]`); een kale `[[slug]]` resolvet via
 * `resolveWikiLink` — huidige scope, dan globaal, dan een uniek project. De
 * levend/dood-check gebeurt tegen de gekwalificeerde `knownRefs`-set (keys
 * `"<scope> <slug>"`, bv. uit `GET /wiki/index`). Het anker draagt de resolved
 * scope mee in `data-wiki-scope` zodat de navigatie naar de juiste scope gaat.
 *
 * Alias (BETON-346): `[[slug|Weergavetekst]]` toont de aliastekst i.p.v. de
 * slug/qualifier; het doel blijft de slug. Zodra het zichtbare label niet meer
 * 1-op-1 de bestemming toont (alias, of een kale link die van scope sprong)
 * krijgt het anker een `title` met de echte bestemming — anders is niet meer
 * te zien waar de link heen gaat.
 *
 * @param {string} text
 * @param {Iterable<string>} [knownRefs] bestaande refs als `"<scope> <slug>"`-keys
 * @param {Iterable<string>} [knownProjectKeys] bekende project-keys (voor ticketref-links)
 * @param {string} [currentScope] scope van de huidige weergave (voor kale links)
 * @returns {string} veilige HTML (zonder trailing newline)
 */
export function renderWikiMarkdown(text, knownRefs, knownProjectKeys = [], currentScope = "global") {
  const known = knownRefs != null ? new Set(knownRefs) : null;
  const keys = new Set([...knownProjectKeys].map((k) => String(k).toUpperCase()));
  let html = renderWith(text, 0);
  if (keys.size) html = linkifyTicketRefs(html, keys);
  return textOnly(html, part => part.replace(WIKILINK_RE, (_m, rawScope, slug, alias) => {
    const { scope } = resolveWikiLink(rawScope, slug, currentScope, known);
    const dead = known != null && !known.has(`${scope} ${slug}`);
    const cls = dead ? "wikilink wikilink-dead" : "wikilink";
    const deadAttr = dead ? ' data-wiki-dead="true"' : "";
    // Label: een alias wint; anders de qualifier zoals geschreven
    // (`BETON:slug`) zodat cross-scope zichtbaar is; anders de kale slug.
    // `alias` komt uit de al door markdown-it HTML-geëscapete tekst (deze
    // functie matcht ná `renderWith`), dus onveilige tekens (`<`/`>`/`&`/`"`)
    // staan er al als entity — rechtstreeks in de HTML zetten is veilig,
    // zelfde aanname als de bestaande kale `label`.
    const label = alias || (rawScope ? `${rawScope}:${slug}` : slug);
    // Toon de bestemming in de tooltip zodra het zichtbare label 'm niet meer
    // dekt: een alias verbergt 'm altijd; een expliciete qualifier (`BETON:x`)
    // toont 'm juist al volledig in het label; een kale link laat 'm alleen
    // zien als hij niet van scope sprong.
    const showsDestination = !alias && (rawScope || scope === currentScope);
    const titleAttr = !dead && !showsDestination ? ` title="${escapeHtml(scope)}: ${slug}"` : "";
    return `<a class="${cls}" data-wiki="${slug}" data-wiki-scope="${escapeHtml(scope)}"${deadAttr}${titleAttr} role="link" tabindex="0">${label}</a>`;
  }));
}
