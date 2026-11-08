// API-client met intrekbare HttpOnly-sessie. Een oude opgeslagen key wordt
// eenmalig ingewisseld en uit localStorage verwijderd (BETON-505).

import { get } from "svelte/store";
import { locale } from "./lib/i18n.js";
import { apiError } from "./lib/apiError.js";
import { parseSSE } from "./lib/sse.js";

const KEY_STORAGE = "betonning_key";
const SESSION_MARKER = "betonning_session";
let transientKey = "";
let csrfToken = "";

export function getKey() {
  return transientKey || localStorage.getItem(KEY_STORAGE) ||
    (localStorage.getItem(SESSION_MARKER) === "1" ? "session" : "");
}
export function setKey(key) {
  transientKey = key;
  localStorage.removeItem(KEY_STORAGE);
}
export function clearKey() {
  transientKey = ""; csrfToken = "";
  localStorage.removeItem(KEY_STORAGE);
  localStorage.removeItem(SESSION_MARKER);
}
function authHeaders() {
  return {
    ...(transientKey ? { Authorization: `Bearer ${transientKey}` } : {}),
    ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
  };
}
async function authenticate() {
  const legacy = localStorage.getItem(KEY_STORAGE);
  const key = transientKey || legacy;
  localStorage.removeItem(KEY_STORAGE);
  const response = await fetch("/api/v1/session", {
    method: key ? "POST" : "GET",
    credentials: "same-origin",
    headers: key ? { Authorization: `Bearer ${key}` } : {},
  });
  transientKey = "";
  if (!response.ok) clearKey();
  await handleResponse(response);
  const data = await response.json();
  csrfToken = data.csrf_token || "";
  localStorage.setItem(SESSION_MARKER, "1");
  return data;
}

// Gedeelde error-afhandeling voor req() en upload(): parse de JSON `detail`,
// val terug op statusText, en gooi een Error met `.status` erop.
async function handleResponse(resp, { expireSession = true } = {}) {
  if (!resp.ok) {
    if (resp.status === 401 && expireSession) {
      clearKey();
      if (typeof window !== "undefined") window.dispatchEvent(new Event("betonning-session-expired"));
    }
    let data = {};
    try {
      data = await resp.json();
    } catch {
      /* Zonder JSON blijft de oorspronkelijke HTTP-tekst beschikbaar. */
    }
    throw apiError(resp.status, data, resp.statusText, get(locale));
  }
}

async function req(method, path, body) {
  const resp = await fetch(`/api/v1${path}`, {
    method,
    headers: {
      ...authHeaders(),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  await handleResponse(resp);
  return resp.status === 204 ? null : resp.json();
}

// Multipart-upload los van req() (die zet Content-Type: application/json).
// Laat de browser zelf de multipart-boundary zetten door géén Content-Type mee
// te geven.
async function upload(path, file) {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`/api/v1${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  await handleResponse(resp);
  return resp.json();
}

// Wiki-pad: project-scope of globaal (BETON-24). project=null → globale wiki.
function wikiBase(project, slug) {
  return project ? `/projects/${project}/wiki/${slug}` : `/wiki/${slug}`;
}

export const api = {
  authenticate,
  onboarding: () => req("GET", "/onboarding"),
  onboardingProject: (body) => req("POST", "/onboarding/project", body),
  onboardingComplete: () => req("POST", "/onboarding/complete"),
  setupStatus: () => req("GET", "/setup"),
  setup: async (body, token) => {
    const response = await fetch("/api/v1/setup", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Setup-Token": token },
      body: JSON.stringify(body),
    });
    // Een verkeerd setup-token is geen verlopen gewone browsersessie.
    await handleResponse(response, { expireSession: false });
    return response.json();
  },
  resetUsage: (handle) => req("POST", `/security-usage/${encodeURIComponent(handle)}/reset`),
  projectTemplate: () => req("GET", "/settings/project-template"),
  setProjectTemplate: (states) => req("PUT", "/settings/project-template", { states }),
  me: () => req("GET", "/me"),
  // Media-toegangscookie (BETON-202): schermt de auth-loze attachment-/avatar-
  // serve-routes af. Bij boot aanroepen zodat <img>-tags (same-origin) de bytes
  // mogen ophalen; de cookie is HttpOnly en gaat automatisch mee.
  mediaCookie: () => req("POST", "/media-cookie"),
  // Uitloggen (BETON-383): de key wissen we lokaal, maar het media-cookie is
  // HttpOnly — alleen de server kan het weghalen.
  logout: () => req("POST", "/logout"),
  users: () => req("GET", "/users"),
  // Werkklasse → model per harnas (BETON-476); PUT is mens-only.
  exportConfiguration: () => req("GET", "/settings/configuration/export"),
  previewConfiguration: (document) => req("POST", "/settings/configuration/preview", document),
  confirmConfiguration: (previewToken) => req("POST", "/settings/configuration/confirm", { preview_token: previewToken, confirmed: true }),
  installationSettings: () => req("GET", "/settings/installation"),
  saveInstallationSettings: (body) => req("PATCH", "/settings/installation", body),
  testInstallationProvider: (provider) => req("POST", `/settings/installation/providers/${encodeURIComponent(provider)}/test`),
  modelClasses: () => req("GET", "/settings/model-classes"),
  setModelClasses: (mapping) => req("PUT", "/settings/model-classes", { mapping }),
  // Agent-/user-beheer (BETON-72) — alleen voor mensen (current_human → 403).
  // createUser geeft de ruwe api_key ÉÉN keer terug (voor de Hermes-config).
  createUser: (body) => req("POST", "/users", body),
  // Detail incl. webhook_url (BETON-113, mens-only) — voor het voorinvullen
  // van het bewerkformulier. webhook_secret blijft write-only, komt hier niet in.
  getUser: (handle) => req("GET", `/users/${encodeURIComponent(handle)}`),
  updateUser: (handle, body) =>
    req("PATCH", `/users/${encodeURIComponent(handle)}`, body),
  rotateUserKey: (handle) =>
    req("POST", `/users/${encodeURIComponent(handle)}/api-key/rotate`),
  deleteUser: (handle) => req("DELETE", `/users/${encodeURIComponent(handle)}`),
  // Avatar (BETON-71) — human-only upload/delete; serve is een auth-loze
  // capability-URL (staat in user.avatar_url).
  uploadAvatar: (handle, file) =>
    upload(`/users/${encodeURIComponent(handle)}/avatar`, file),
  deleteAvatar: (handle) =>
    req("DELETE", `/users/${encodeURIComponent(handle)}/avatar`),
  // Eigen instellingen (BETON-49/173): webhook/telegram/subscribe van de
  // ingelogde user. GET geeft geen ruw secret terug (has_webhook_secret).
  meSettings: () => req("GET", "/users/me/settings"),
  updateMeSettings: (body) => req("PATCH", "/users/me/settings", body),
  // Webhook-leveringen (BETON-52/174): inzicht + replay voor troubleshooting.
  deliveries: (params = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.limit != null) qs.set("limit", params.limit);
    const q = qs.toString();
    return req("GET", `/webhook-deliveries${q ? `?${q}` : ""}`);
  },
  testWebhook: (handle) => req("POST", `/users/${encodeURIComponent(handle)}/webhook-test`),
  webhookTestStatus: (handle, id) => req("GET", `/users/${encodeURIComponent(handle)}/webhook-test/${id}`),
  webhookHealth: () => req("GET", "/webhook-health"), // BETON-457
  replayDelivery: (id) => req("POST", `/webhook-deliveries/${id}/replay`),
  // My Issues (BETON-55): cross-project open items van de ingelogde user.
  myIssues: () => req("GET", "/me/issues"),
  // Inbox (BETON-55): events die jou raken + ongelezen-teller.
  inbox: (limit) => req("GET", `/inbox${limit != null ? `?limit=${limit}` : ""}`),
  inboxSeen: (event_id) => req("POST", "/inbox/seen", { event_id }),
  projects: (archived = false) =>
    req("GET", archived ? "/projects?archived=true" : "/projects"),
  createProject: (body) => req("POST", "/projects", body),
  updateProject: (key, body) => req("PATCH", `/projects/${key}`, body),
  archiveProject: (key) => req("DELETE", `/projects/${key}`),
  restoreProject: (key) => req("POST", `/projects/${key}/restore`),
  states: (key) => req("GET", `/projects/${key}/states`),
  createState: (key, body) => req("POST", `/projects/${key}/states`, body),
  updateState: (key, name, body) =>
    req("PATCH", `/projects/${key}/states/${encodeURIComponent(name)}`, body),
  deleteState: (key, name) =>
    req("DELETE", `/projects/${key}/states/${encodeURIComponent(name)}`),
  labels: (key) => req("GET", `/projects/${key}/labels`),
  createLabel: (key, body) => req("POST", `/projects/${key}/labels`, body),
  updateProjectLabel: (key, name, body) =>
    req("PATCH", `/projects/${key}/labels/${encodeURIComponent(name)}`, body),
  deleteProjectLabel: (key, name) =>
    req("DELETE", `/projects/${key}/labels/${encodeURIComponent(name)}`),
  milestones: (key) => req("GET", `/projects/${key}/milestones`),
  createMilestone: (key, body) => req("POST", `/projects/${key}/milestones`, body),
  updateMilestone: (key, name, body) =>
    req("PATCH", `/projects/${key}/milestones/${encodeURIComponent(name)}`, body),
  deleteMilestone: (key, name) =>
    req("DELETE", `/projects/${key}/milestones/${encodeURIComponent(name)}`),
  setTriage: (key, enabled) => req("PUT", `/projects/${key}/triage`, { enabled }),
  backfillTriage: (key) => req("POST", `/projects/${key}/triage/backfill`),
  setWikiCompile: (key, enabled) =>
    req("PUT", `/projects/${key}/wiki-compile`, { enabled }),
  backfillWikiCompile: (key) => req("POST", `/projects/${key}/wiki-compile/backfill`),
  // Per-project agent-toegang (BETON-123). level=null bij setAgentAccess = inherit.
  access: (key) => req("GET", `/projects/${key}/access`),
  setTypeAccess: (key, type, level) =>
    req("PUT", `/projects/${key}/access/type/${type}`, { level }),
  setAgentAccess: (key, handle, level) =>
    req("PUT", `/projects/${key}/access/agent/${encodeURIComponent(handle)}`, { level }),
  items: (key, params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null && v !== "")
    ).toString();
    return req("GET", `/projects/${key}/items${qs ? `?${qs}` : ""}`);
  },
  // Aantal items per state (BETON-359) — voedt "toon meer (N)" op begrensde
  // (closed_limit) kolommen zonder dat de items-lijst zelf breder wordt.
  stateCounts: (key, { archived } = {}) =>
    req("GET", `/projects/${key}/state-counts${archived ? "?archived=true" : ""}`),
  // Activiteitenfeed van een héel project (BETON-372), spiegelt `items()`.
  projectActivity: (key, params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null && v !== "")
    ).toString();
    return req("GET", `/projects/${key}/activity${qs ? `?${qs}` : ""}`);
  },
  // Stand van zaken over álle projecten (BETON-371): tellers per project,
  // in één gebatchte backend-call — nooit een fetch per project.
  overview: () => req("GET", "/overview"),
  // Cross-project full-text zoek (FTS + fuzzy fallback). Voor de relatie-
  // autocomplete (BETON-12) en de zoek-scope 'alle projecten' (BETON-7).
  search: (q, limit) => {
    const qs = new URLSearchParams({ q });
    if (limit != null) qs.set("limit", String(limit));
    return req("GET", `/search?${qs.toString()}`);
  },
  // Ticket-ref-autocomplete voor het #-menu (BETON-254): substring-match op
  // project-key + seq met ref-first ordening. `project` bepaalt de scope bij
  // een query van alleen cijfers (dan alleen het huidige project).
  refCandidates: (q, project, limit) => {
    const qs = new URLSearchParams({ q });
    if (project) qs.set("project", project);
    if (limit != null) qs.set("limit", String(limit));
    return req("GET", `/ref-candidates?${qs.toString()}`);
  },
  item: (ref) => req("GET", `/items/${ref}`),
  // Plan/handover (BETON-218): apart, lazy — zit niet in de item-serialisatie.
  getPlan: (ref) => req("GET", `/items/${ref}/plan`),
  // Volgers + per-item mute (BETON-245): afgeleide subscribers-union (assignee +
  // eerdere participants + subscribe_all) elk met een muted-vlag; muten haalt een
  // user uit de fanout van dít item.
  subscribers: (ref) => req("GET", `/items/${ref}/subscribers`),
  muteSubscriber: (ref, handle) =>
    req("POST", `/items/${ref}/subscribers/${encodeURIComponent(handle)}/mute`),
  unmuteSubscriber: (ref, handle) =>
    req("DELETE", `/items/${ref}/subscribers/${encodeURIComponent(handle)}/mute`),
  // Ticket volgen/ontvolgen (BETON-369): mens-only tegenhanger van de mute —
  // zet je in de fanout en geeft de inbox-reden "following".
  follow: (ref) => req("POST", `/items/${ref}/follow`),
  unfollow: (ref) => req("DELETE", `/items/${ref}/follow`),
  activity: (ref) => req("GET", `/items/${ref}/activity`),
  // Per-item read-state (BETON-294/286): "ik heb dit ticket geopend/gezien",
  // los van de globale inbox-watermark (inboxSeen).
  markItemRead: (ref) => req("POST", `/items/${ref}/read`),
  createItem: (key, body) => req("POST", `/projects/${key}/items`, body),
  updateItem: (ref, body) => req("PATCH", `/items/${ref}`, body),
  archiveItem: (ref) => req("DELETE", `/items/${ref}`),
  restoreItem: (ref) => req("POST", `/items/${ref}/restore`),
  deleteItem: (ref) => req("DELETE", `/items/${ref}?hard=true`),
  moveItem: (ref, project) => req("POST", `/items/${ref}/move`, { project }),
  // Noodstop (BETON-302): mens-only — de backend geeft een agent hier 403.
  lockItem: (ref) => req("POST", `/items/${ref}/lock`),
  // BETON-338: `headroom` = hoeveel reacties er ruimte is vóór het opnieuw
  // dichtklapt (5/10/20; backend weigert de rest met 422).
  unlockItem: (ref, headroom = 5) => req("POST", `/items/${ref}/unlock`, { headroom }),
  // Guardrail (BETON-420): zetten/wijzigen en opheffen zijn mens-only — de
  // backend geeft een agent hier 403. Body: {guardrail_md, review_by,
  // scope_labels}; lege scope = projectbreed en telt mee in het plafond van
  // vijf (409 als dat vol zit). Geen precondition-header: guardrail_md staat
  // bewust niet in het PATCH-pad, dus er is hier geen updated_at-contract.
  setGuardrail: (ref, body) => req("POST", `/items/${ref}/guardrail`, body),
  liftGuardrail: (ref) => req("POST", `/items/${ref}/guardrail/lift`),
  // Guardrail-concept (BETON-422): een agent stelt voor, een mens beslist —
  // allebei mens-only (403 voor een agent). Zonder openstaand concept geven ze
  // 409; goedkeuren geeft bovendien 409 als het concept projectbreed is en het
  // plafond van vijf vol staat. "Goedkeuren met wijzigingen" gaat NIET hier
  // langs maar via `setGuardrail`: die zet de bewerkte versie meteen actief en
  // wist het concept. Beide geven het verse item terug.
  approveGuardrail: (ref) => req("POST", `/items/${ref}/guardrail/approve`),
  rejectGuardrail: (ref) => req("POST", `/items/${ref}/guardrail/reject`),
  comment: (ref, body_md) => req("POST", `/items/${ref}/comments`, { body_md }),
  // Vraagmodule (BETON-219). Beantwoorden: body = precies één van {text} of
  // {option_index}. Open vragen gericht aan de ingelogde user.
  answerQuestion: (commentId, body) => req("POST", `/comments/${commentId}/answer`, body),
  withdrawQuestion: (commentId, reason) => req("POST", `/comments/${commentId}/withdraw`, { reason }),
  resumeExecution: (ref, executionId, body) => req("POST", `/items/${ref}/executions/${executionId}/resume`, body),
  updateAnswer: (commentId, body) => req("PATCH", `/comments/${commentId}/answer`, body),
  openQuestions: () => req("GET", "/questions?open=true"),
  updateComment: (ref, id, body_md) =>
    req("PATCH", `/items/${ref}/comments/${id}`, { body_md }),
  deleteComment: (ref, id) => req("DELETE", `/items/${ref}/comments/${id}`),
  addLabel: (ref, name) => req("POST", `/items/${ref}/labels/${encodeURIComponent(name)}`),
  removeLabel: (ref, name) =>
    req("DELETE", `/items/${ref}/labels/${encodeURIComponent(name)}`),
  uploadAttachment: (ref, file) => upload(`/items/${ref}/attachments`, file),
  attachments: (ref) => req("GET", `/items/${ref}/attachments`),
  enrich: (ref) => req("POST", `/items/${ref}/enrich`),
  decompose: (ref) => req("POST", `/items/${ref}/decompose`),
  decomposeApply: (ref, body) => req("POST", `/items/${ref}/decompose/apply`, body),
  addRelation: (ref, type, target) =>
    req("POST", `/items/${ref}/relations`, { type, target }),
  deleteRelation: (ref, type, target) =>
    req("DELETE", `/items/${ref}/relations`, { type, target }),
  // Wiki / memory-provider (BETON-24). project=null → globale wiki.
  wikiProposals: (project) => req("GET", `/wiki-proposals${project ? `?project=${encodeURIComponent(project)}` : ""}`),
  wikiReview: (id, approve) => req("POST", `/wiki-proposals/${id}/review`, { approve }),
  wikiProtect: (project, slug, protectedValue) => req("PUT", "/wiki-protection", {project, slug, protected: protectedValue}),
  wikiList: (project) => req("GET", project ? `/projects/${project}/wiki` : "/wiki"),
  // Cross-scope index [{scope, slug}] voor levend/dood-markering (BETON-306).
  wikiIndex: () => req("GET", "/wiki/index"),
  wikiCreate: (project, body) =>
    req("POST", project ? `/projects/${project}/wiki` : "/wiki", body),
  wikiUpdate: (project, slug, body) => req("PATCH", wikiBase(project, slug), body),
  wikiDelete: (project, slug) => req("DELETE", wikiBase(project, slug)),
  // Edit-history (BETON-209).
  wikiRevisions: (project, slug) => req("GET", `${wikiBase(project, slug)}/revisions`),
  wikiRevision: (project, slug, id) =>
    req("GET", `${wikiBase(project, slug)}/revisions/${id}`),
  wikiRestore: (project, slug, id) =>
    req("POST", `${wikiBase(project, slug)}/revisions/${id}/restore`),
  // Chat-met-triage (BETON-120). project=null → globale thread.
  triageChat: (project) =>
    req("GET", project ? `/projects/${project}/triage-chat` : "/triage-chat"),
  sendTriageChat: (project, message) =>
    req("POST", project ? `/projects/${project}/triage-chat` : "/triage-chat", { message }),
  archiveTriageChat: (project) =>
    req("POST", project ? `/projects/${project}/triage-chat/archive` : "/triage-chat/archive"),
  confirmTriageChat: (id, typedCount) =>
    req("POST", `/triage-chat/${id}/confirm`, typedCount == null ? undefined : { typed_count: typedCount }),
  cancelTriageChat: (id) => req("POST", `/triage-chat/${id}/cancel`),
};

// Server stuurt gegarandeerd elke ~1s bytes (event óf heartbeat-comment). Als
// er langer dan dit venster niets binnenkomt, beschouwen we de verbinding als
// stilgevallen (bv. half-open door een proxy) en forceren we een reconnect.
const STALL_TIMEOUT = 12000;

// Hoe vaak de wachter (BETON-405) kijkt of er nog bytes binnenkomen. Bewust
// onafhankelijk van `visibilitychange`: een scherm dat in slaap valt terwijl het
// tabblad op de voorgrond blijft verandert `document.hidden` niet, dus die
// trigger vuurt daar nooit.
const WATCHDOG_INTERVAL = 5000;

// Sprong in de wandklok die groter is dan dit veelvoud van de intervallengte
// betekent dat de machine geslapen heeft: het interval vuurde niet op tijd.
const CLOCK_JUMP_FACTOR = 3;

// SSE-abonnement via fetch+ReadableStream (EventSource kan geen Authorization-
// header sturen en we willen de key niet in de URL). Roept onEvent aan per
// geparsed event; herverbindt met backoff vanaf het laatst geziene event-id.
// Geeft een stop-functie terug. `deps` is een test-seam (fetch/setTimeout/
// clearTimeout/setInterval/clearInterval/now/document injecteerbaar, default =
// globals) — bestaande callers hoeven niets aan te passen.
//
// `onResync` (BETON-402) vuurt bij élke geslaagde verbinding die niet de eerste
// verbindingspoging is: na een drop is er per definitie een gat dat de stream
// zelf niet meer dicht kan garanderen, dus de aanroeper moet een volledige
// herlaad doen. Precies één keer per herverbinding (mislukte pogingen vuren
// niets — de fetch gooit vóór het signaal).
export function subscribe(onEvent, { onStatus, onResync } = {}, deps = {}) {
  const doFetch = deps.fetch ?? fetch;
  const setTimer = deps.setTimeout ?? setTimeout;
  const clearTimer = deps.clearTimeout ?? clearTimeout;
  const setInterv = deps.setInterval ?? setInterval;
  const clearInterv = deps.clearInterval ?? clearInterval;
  const stallTimeout = deps.stallTimeout ?? STALL_TIMEOUT;
  const watchdogInterval = deps.watchdogInterval ?? WATCHDOG_INTERVAL;
  // Alleen voor de visibility-trigger; null-guard omdat de vitest-omgeving
  // geen jsdom heeft (er is dus geen `document`).
  const doc = deps.document ?? (typeof document === "undefined" ? null : document);
  const now = deps.now ?? (() => Date.now());

  let stopped = false;
  let controller = null;
  let since = 0;
  let backoff = 1000;
  let attempts = 0;
  // Wandkloktijd van de laatste ontvangen bytes (event óf heartbeat). De
  // stall-watchdog draait op timers en die staan stil in een slapend tabblad;
  // dit is de klok-kant van hetzelfde signaal.
  let lastByteAt = null;

  async function run() {
    while (!stopped) {
      attempts += 1;
      controller = new AbortController();
      let stallTimer = null;
      const resetStall = () => {
        lastByteAt = now();
        if (stallTimer != null) clearTimer(stallTimer);
        stallTimer = setTimer(() => controller?.abort(), stallTimeout);
      };
      try {
        // Eerste verbinding (nog geen event gezien): start bij het huidige
        // laatste event i.p.v. de hele historie opnieuw af te spelen (BETON-186).
        // De UI heeft net een volledige loadBoard() gedaan; backlog-replay is
        // onnodig en zou de incrementele reducer met duizenden upserts belasten.
        // Zodra we een event zagen (since > 0) hervatten we normaal vanaf dat id.
        //
        // BETON-402: is `since` na een drop nóg 0 (er kwam nooit een event
        // langs), dan blijft dit `from=latest` — `?since=0` kaal zou de héle
        // historie afspelen, precies wat BETON-186 wegnam. Er is dan geen
        // betrouwbaar hervatpunt, dus het gat wordt gedicht door de
        // onResync-herlaad hieronder, niet door de stream.
        const url =
          since === 0
            ? `/api/v1/events/stream?since=0&from=latest`
            : `/api/v1/events/stream?since=${since}`;
        const resp = await doFetch(url, {
          headers: authHeaders(),
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) throw new Error(`stream ${resp.status}`);
        onStatus?.("live");
        // Een herverbinding is geen eerste verbinding: alles tussen de drop en
        // nu is niet geleverd (of, met from=latest, per definitie overgeslagen).
        if (attempts > 1) onResync?.();
        backoff = 1000;
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        resetStall();
        while (!stopped) {
          const { value, done } = await reader.read();
          if (done) break;
          resetStall();
          buffer += decoder.decode(value, { stream: true });
          const parsed = parseSSE(buffer);
          buffer = parsed.rest;
          for (const ev of parsed.events) {
            if (ev.id != null) since = ev.id;
            if (ev.data) onEvent(ev.data);
          }
        }
      } catch {
        onStatus?.("offline");
      } finally {
        if (stallTimer != null) clearTimer(stallTimer);
        // Tussen twee verbindingen is er geen stream om te beoordelen: de
        // wachter moet niet op een oude `lastByteAt` blijven aborten terwijl de
        // backoff loopt.
        lastByteAt = null;
      }
      if (stopped) break;
      await new Promise((r) => setTimer(r, backoff));
      backoff = Math.min(backoff * 2, 15000);
    }
  }

  // Een tabblad dat uit de achtergrond komt (laptop uit slaap) is het
  // waarschijnlijkste praktijkgeval: de timers stonden stil, dus de
  // stall-watchdog heeft nog niets gemerkt terwijl de stream al dood kan zijn.
  // De poort is niet "hoe lang was je weg" maar "kwamen er recent nog bytes":
  // een tabblad dat op de achtergrond heartbeats bleef krijgen is gezond en
  // wordt niet aangeraakt (een abort zou een offline-flikker + onnodige herlaad
  // kosten), een stil geworden stream wél.
  function onVisibility() {
    if (stopped) return;
    if (doc.visibilityState !== "visible") return;
    if (lastByteAt == null || now() - lastByteAt > stallTimeout) controller?.abort();
  }
  doc?.addEventListener?.("visibilitychange", onVisibility);

  // De wachter (BETON-405). Twee dingen die `visibilitychange` en de
  // stall-`setTimeout` samen niet dekken:
  //
  // 1. Een scherm dat in slaap valt met het tabblad op de voorgrond laat
  //    `document.hidden` ongemoeid, dus de visibility-trigger vuurt nooit.
  // 2. De stall-`setTimeout` staat stil zolang de machine slaapt, en of de
  //    browser hem na het ontwaken alsnog laat vuren is niets om op te bouwen.
  //    Vuurt hij niet, dan blijft `reader.read()` hangen op een dode socket:
  //    geen `catch`, geen herverbinding, geen `onResync` — en een groen
  //    bolletje boven stilstaande data.
  //
  // Het oordeel gaat daarom over bytes, niet over zichtbaarheid: de server
  // stuurt elke seconde een heartbeat, dus `lastByteAt` ouder dan
  // `stallTimeout` betekent dood. Daarnaast een sprong in de wandklok
  // (`Date.now()`, níet `performance.now()` — die telt in slaap niet altijd
  // door) als extra ingang voor het slaapgeval.
  //
  // Trippen = `onStatus("offline")` + `controller.abort()`; de abort zet de
  // bestaande herverbindingslus met zijn backoff in gang (en daarmee
  // `onResync`). Geen tweede stream, geen polling.
  let lastTickAt = now();
  function onWatchdogTick() {
    const t = now();
    const jumped = t - lastTickAt > watchdogInterval * CLOCK_JUMP_FACTOR;
    lastTickAt = t;
    if (stopped) return;
    // Geen actieve stream (nog aan het verbinden of in de backoff): niets te
    // beoordelen — de herverbindingslus is daar zelf al mee bezig.
    if (lastByteAt == null) return;
    // Een late tick is niet alléén een slaapstand: een verborgen tabblad wordt
    // door de browser afgeknepen (Firefox rekt timers tot ~15s, Chrome naar
    // ~1/min). Netwerklevering wordt niet zo afgeknepen, dus daar komen de
    // bytes gewoon door. Een sprong mag daarom niet de byte-poort omzeilen —
    // hij verscherpt hem alleen: verse bytes betekent een gezonde stream, ook
    // na een sprong. Anders kost elke afgeknepen tick een offline-flikker plus
    // een volledige herlaad, precies wat BETON-402 wegnam.
    if (t - lastByteAt <= (jumped ? watchdogInterval : stallTimeout)) return;
    // De indicator hoort de waarheid te vertellen op het moment dat wij de
    // stream dood verklaren, niet pas als de `catch` er ooit komt.
    onStatus?.("offline");
    // Eén keer per dode stream: de abort loopt normaal via de `catch` naar de
    // herverbindingslus, die `lastByteAt` opnieuw zet. Zou de socket zich niets
    // van de abort aantrekken, dan blijft de wachter hier anders elke tick
    // opnieuw op vallen.
    lastByteAt = null;
    controller?.abort();
  }
  const watchdog = setInterv(onWatchdogTick, watchdogInterval);

  run();
  return () => {
    stopped = true;
    doc?.removeEventListener?.("visibilitychange", onVisibility);
    clearInterv(watchdog);
    controller?.abort();
  };
}
