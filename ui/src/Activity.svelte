<script>
  import { t, locale } from "./lib/i18n.js";
  // Activiteitenfeed per project (BETON-372): een vierde basis-view naast
  // bord/lijst/wiki. Toont events van AL de tickets van het project,
  // gegroepeerd per dag, met filters op actor/type en een "laad meer"-knop.
  //
  // Bewust géén losse repository-module: alle logica hier is fetch/DOM-bind
  // (filter-state, "laad meer", live-refresh) — de puur testbare
  // eenheden zijn `groupByDay` (lib/board.js) en `buildFeed` (lib/activity.js).
  import { api } from "./api.js";
  import { describeEvent, formatTimestamp, absoluteTime, groupByDay } from "./lib/board.js";
  import { buildFeed, DEFAULT_TYPE } from "./lib/activity.js";
  import Avatar from "./Avatar.svelte";
  import EmptyState from "./EmptyState.svelte";
  import Skeleton from "./Skeleton.svelte";
  import Select from "./Select.svelte";
  import { History, RefreshCw } from "@lucide/svelte";

  let {
    project,
    projectName = project,
    users = [],
    avatarMap = new Map(),
    liveTick = 0,
    onopenref = () => {},
  } = $props();

  // Vaste type-lijst (geen los endpoint voor "welke types bestaan er") —
  // spiegelt de cases in `describeEvent`, comment-events incluis: deze feed
  // is bewust niet de Drawer-tijdlijn (die verbergt comments, ze staan al in
  // het gesprek van het ticket) maar een projectbrede activiteitenlog.
  const TYPE_OPTIONS = $derived([
    // BETON-463: standaard zonder interne bot-events (wiki.compiled);
    // "Alle types" toont ze wel.
    { value: DEFAULT_TYPE, label: $t("activity.default") },
    { value: "", label: $t("activity.allTypes") },
    { value: "item.created", label: $t("activity.type.item.created") },
    { value: "item.updated", label: $t("activity.type.item.updated") },
    { value: "item.moved", label: $t("activity.type.item.moved") },
    { value: "item.archived", label: $t("activity.type.item.archived") },
    { value: "item.restored", label: $t("activity.type.item.restored") },
    { value: "item.deleted", label: $t("activity.type.item.deleted") },
    { value: "item.locked", label: $t("activity.type.item.locked") },
    { value: "item.unlocked", label: $t("activity.type.item.unlocked") },
    { value: "item.guardrail_set", label: $t("activity.type.item.guardrail_set") },
    { value: "item.guardrail_lifted", label: $t("activity.type.item.guardrail_lifted") },
    { value: "item.guardrail_proposed", label: $t("activity.type.item.guardrail_proposed") },
    { value: "item.guardrail_rejected", label: $t("activity.type.item.guardrail_rejected") },
    { value: "comment.created", label: $t("activity.type.comment.created") },
    { value: "relation.created", label: $t("activity.type.relation.created") },
    { value: "relation.deleted", label: $t("activity.type.relation.deleted") },
    { value: "question.answered", label: $t("activity.type.question.answered") },
    { value: "wiki.compiled", label: $t("activity.type.wiki.compiled") },
  ]);
  const DEFAULT_LIMIT = 100;
  const LOAD_MORE_STEP = 100;
  // Spiegelt de backend-cap (`Query(..., le=500)`, api/projects.py) — zonder
  // dit plafond zou een vijfde "laad meer"-klik limit=600 sturen en op een
  // 422 stuklopen terwijl de knop, door hasMore, klikbaar bleef staan.
  const MAX_LIMIT = 500;

  let events = $state([]);
  let loading = $state(true);
  let error = $state("");
  let filters = $state({ actor: "", type: DEFAULT_TYPE });
  let limit = $state(DEFAULT_LIMIT);
  // Het laatst opgehaalde aantal was gelijk aan de limiet → er kan meer zijn.
  // Bij het plafond is dat niet meer waar, ook niet als de lijst toevallig
  // exact zo lang is: er is dan sowieso geen "meer" op te vragen.
  let hasMore = $derived(events.length >= limit && limit < MAX_LIMIT);

  // Monotone volg-teller tegen races tussen overlappende load()-aanroepen
  // (filter-wissel gevolgd door een live-tik vóór de eerste respons binnen
  // is): alleen de laatst gestarte aanroep mag `events` nog zetten.
  let seq = 0;

  async function load() {
    const mine = ++seq;
    loading = true;
    error = "";
    try {
      const rows = await api.projectActivity(project, {
        actor: filters.actor || undefined,
        type: filters.type && filters.type !== DEFAULT_TYPE ? filters.type : undefined,
        limit,
      });
      if (mine !== seq) return; // een latere aanroep is al onderweg/binnen
      events = rows;
    } catch (e) {
      if (mine === seq) error = e.message || $t("activity.loadFailed");
    } finally {
      if (mine === seq) loading = false;
    }
  }

  // Filter-wissel, project-wissel of limiet-verhoging → direct herladen.
  $effect(() => {
    void project;
    void filters.actor;
    void filters.type;
    void limit;
    load();
  });

  // Live-tik (SSE, per event) → gedebounced herladen, zelfde 250ms-patroon
  // als App.svelte:refreshSideEffectsSoon — anders vuurt een triage-pass of
  // bulk-move één fetch per event i.p.v. één ná de burst. Slaat de allereerste
  // (mount-)tik over: het effect hierboven laadt al bij mount.
  let liveTimer = null;
  let sawFirstTick = false;
  $effect(() => {
    void liveTick;
    if (!sawFirstTick) {
      sawFirstTick = true;
      return;
    }
    if (liveTimer) clearTimeout(liveTimer);
    liveTimer = setTimeout(() => {
      liveTimer = null;
      load();
    }, 250);
    return () => {
      if (liveTimer) {
        clearTimeout(liveTimer);
        liveTimer = null;
      }
    };
  });

  function resetLimit() {
    limit = DEFAULT_LIMIT;
  }
  function setActor(v) {
    filters = { ...filters, actor: v };
    resetLimit();
  }
  function setType(v) {
    filters = { ...filters, type: v };
    resetLimit();
  }
  function loadMore() {
    limit = Math.min(limit + LOAD_MORE_STEP, MAX_LIMIT);
  }

  // Samenvoegen/filteren gebeurt na het ophalen; `hasMore` kijkt daarom naar
  // het ruwe aantal events, niet naar het aantal getoonde regels.
  let grouped = $derived(
    groupByDay(buildFeed(events, { showInternal: filters.type !== DEFAULT_TYPE }))
  );

  function dayLabel(day) {
    if (day === "onbekend") return $t("activity.unknown");
    const today = new Date();
    const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const yest = new Date(today);
    yest.setDate(yest.getDate() - 1);
    const yestKey = `${yest.getFullYear()}-${String(yest.getMonth() + 1).padStart(2, "0")}-${String(yest.getDate()).padStart(2, "0")}`;
    if (day === todayKey) return $t("activity.today");
    if (day === yestKey) return $t("activity.yesterday");
    return day;
  }
</script>

<div class="activity-view">
  <header class="activity-head">
    <h2><History size={18} /> {$t("activity.title")} — {projectName}</h2>
    <div class="activity-filters">
      <Select
        ariaLabel="Actor"
        value={filters.actor}
        options={[
          { value: "", label: $t("activity.everyone") },
          ...users.map((u) => ({ value: u.handle, label: `@${u.handle}` })),
        ]}
        onchange={(v) => setActor(v)}
      />
      <Select
        ariaLabel="Type"
        value={filters.type}
        options={TYPE_OPTIONS}
        onchange={(v) => setType(v)}
      />
      <button class="icon-btn" title={$t("activity.refresh")} onclick={load} disabled={loading}>
        <RefreshCw size={15} />
      </button>
    </div>
  </header>

  {#if error}
    <p class="activity-error" role="alert">{error}</p>
  {/if}

  {#if loading && !events.length}
    <Skeleton preset="rows" count={6} />
  {:else if !events.length}
    <EmptyState icon={History} title={$t("activity.none")} />
  {:else}
    <div class="activity-days">
      {#each grouped as g (g.day)}
        <section class="activity-day">
          <h3 class="activity-daylabel">{dayLabel(g.day)}</h3>
          <ul class="activity-list">
            {#each g.events as e (e.id)}
              <li class="activity-row">
                <Avatar handle={e.actor ?? "?"} avatarUrl={avatarMap.get(e.actor)} size={20} />
                <button class="activity-line" onclick={() => e.ref && onopenref(e.ref)} disabled={!e.ref}>
                  <span class="activity-actor">@{e.actor ?? $t("activity.system")}</span>
                  {describeEvent(e, $locale)}{#if e.count > 1}<span class="activity-count"> ({e.count}×)</span>{/if}
                  {#if e.ref}<span class="activity-ref">{e.ref}</span>{/if}
                  <span class="activity-time" title={absoluteTime(e.created_at, $locale)}>
                    · {formatTimestamp(e.created_at, Date.now(), $locale)}
                  </span>
                </button>
              </li>
            {/each}
          </ul>
        </section>
      {/each}
    </div>
    {#if hasMore}
      <button class="load-more" onclick={loadMore} disabled={loading}>{$t("activity.more")}</button>
    {/if}
  {/if}
</div>

<style>
  .activity-count {
    color: var(--text-secondary);
  }
  .activity-view {
    padding: var(--space-4);
    max-width: 860px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .activity-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .activity-head h2 {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 1.05rem;
    margin: 0;
  }
  .activity-filters {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .activity-filters :global(.select-trigger) {
    font-size: 0.85rem;
  }
  /* Omlijnde icoonknop = gewone actie (BETON-418): --border haalde 1,21/1,42. */
  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    background: transparent;
    border: 1px solid var(--border-interactive);
    color: var(--text);
  }
  .activity-error {
    color: var(--danger);
  }
  .activity-days {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .activity-daylabel {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.02em;
    margin: 0 0 var(--space-2) 0;
  }
  .activity-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .activity-row {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
  }
  .activity-line {
    display: flex;
    align-items: baseline;
    gap: var(--space-1);
    flex-wrap: wrap;
    background: none;
    border: none;
    padding: 0;
    text-align: left;
    color: var(--text);
    font-size: 0.88rem;
    cursor: pointer;
  }
  .activity-line:disabled {
    cursor: default;
  }
  .activity-actor {
    font-weight: 600;
  }
  .activity-ref {
    color: var(--text-secondary);
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 0.82rem;
  }
  .activity-time {
    color: var(--text-secondary);
    font-size: 0.8rem;
  }
  .load-more {
    align-self: center;
    padding: var(--space-2) var(--space-4);
    /* Rand, vlak en tekst uit de globale button-regel (BETON-418). */
    border-radius: var(--radius-md);
  }
</style>
