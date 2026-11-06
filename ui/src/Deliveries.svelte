<script>
  import { t, locale } from "./lib/i18n.js";
  // Webhook-leveringen-paneel (BETON-174): inzicht + replay voor troubleshooting.
  // Toont per delivery status/kanaal/doel-user/event-type/pogingen/tijd; filtert
  // op status en laat mislukte/geannuleerde leveringen opnieuw inplannen.
  import { api } from "./api.js";
  import { formatTimestamp } from "./lib/board.js";
  import {
    DELIVERY_STATUSES,
    statusLabel,
    statusTone,
    canReplay,
  } from "./lib/deliveries.js";
  import Avatar from "./Avatar.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import ErrorNote from "./ErrorNote.svelte";
  import Skeleton from "./Skeleton.svelte";
  import EmptyState from "./EmptyState.svelte";
  import { ArrowLeft, RotateCcw, RefreshCw, Webhook } from "@lucide/svelte";

  let { avatarMap = new Map(), onback } = $props();

  const PAGE = 50;

  let error = $state("");
  let busy = $state(false);
  let filter = $state(""); // "" = alle statussen
  let limit = $state(PAGE);
  let rows = $state([]);
  let replaying = $state(null); // id dat nu opnieuw wordt ingepland

  async function load() {
    error = "";
    busy = true;
    try {
      rows = await api.deliveries({ status: filter || undefined, limit });
    } catch (e) {
      error = $t("deliveries.loadFailed");
    }
    busy = false;
  }
  // Herlaad bij filter/limiet-wijziging.
  $effect(() => {
    filter;
    limit;
    load();
  });

  function setFilter(v) {
    if (filter === v) return;
    filter = v;
    limit = PAGE; // reset paginering
  }

  async function replay(id) {
    error = "";
    replaying = id;
    try {
      const updated = await api.replayDelivery(id);
      rows = rows.map((r) => (r.id === id ? { ...r, ...updated } : r));
    } catch (e) {
      error = e.message;
    }
    replaying = null;
  }

  // "Meer laden" = grotere limiet opvragen (de backend biedt alleen limit).
  let maybeMore = $derived(rows.length >= limit);
</script>

<div class="dl">
  <header class="dl-top">
    <button class="icon-btn" title={$t("common.back")} onclick={() => onback?.()}><ArrowLeft size={18} /></button>
    <h3 class="dl-title"><Webhook size={18} /> {$t("nav.deliveries")}</h3>
    <button class="icon-btn sm" title={$t("common.refresh")} aria-label={$t("common.refresh")} onclick={load} disabled={busy}>
      <RefreshCw size={16} />
    </button>
  </header>

  <div class="dl-filters">
    <SegmentedControl
      variant="pill"
      ariaLabel={$t("deliveries.filter")}
      value={filter}
      onchange={setFilter}
      options={[
        { value: "", label: $t("deliveries.all") },
        ...DELIVERY_STATUSES.map((s) => ({ value: s, label: statusLabel(s, $locale) })),
      ]}
    />
  </div>

  <ErrorNote message={error} onRetry={load} />

  {#if busy && !rows.length}
    <Skeleton preset="rows" count={5} />
  {:else if !rows.length}
    <EmptyState
      icon={Webhook}
      title={filter ? $t("deliveries.noStatus", {status: statusLabel(filter, $locale)}) : $t("deliveries.none")}
    />
  {:else}
    <ul class="dl-list">
      {#each rows as d (d.id)}
        <li class="dl-item">
          <span class="dl-status tone-{statusTone(d.status)}">{statusLabel(d.status, $locale)}</span>
          <div class="dl-main">
            <div class="dl-line1">
              <span class="dl-event">{d.event_type || "—"}</span>
              {#if d.channel}<span class="dl-channel">{d.channel}</span>{/if}
            </div>
            <div class="dl-line2">
              {#if d.target_handle}
                <span class="dl-target">
                  <Avatar handle={d.target_handle} avatarUrl={avatarMap.get(d.target_handle)} size={18} />
                  @{d.target_handle}
                </span>
              {/if}
              <span class="dl-meta">{$t(d.attempts === 1 ? "deliveries.attemptOne" : "deliveries.attemptMany", {count: d.attempts})}</span>
              <span class="dl-meta">{formatTimestamp(d.created_at, Date.now(), $locale)}</span>
            </div>
            {#if d.last_error}<div class="dl-err" title={d.last_error}>{d.last_error}</div>{/if}
          </div>
          {#if canReplay(d.status)}
            <button class="sm dl-replay" onclick={() => replay(d.id)} disabled={replaying === d.id}>
              <RotateCcw size={14} /> {$t("common.retry")}
            </button>
          {/if}
        </li>
      {/each}
    </ul>
    {#if maybeMore}
      <div class="dl-more">
        <button class="sm" onclick={() => (limit += PAGE)} disabled={busy}>{$t("common.loadMore")}</button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .dl-top {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }
  .dl-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-lg);
    font-weight: 600;
    margin: 0;
    flex: 1;
  }
  .dl-filters {
    margin-bottom: 12px;
  }
  .dl-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .dl-item {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }
  .dl-main {
    flex: 1;
    min-width: 0;
  }
  .dl-line1 {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .dl-event {
    font-weight: 600;
    font-size: var(--text-md);
  }
  .dl-channel {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: var(--surface-3);
    padding: 1px 7px;
    border-radius: var(--radius-full);
  }
  .dl-line2 {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 3px;
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }
  .dl-target {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--text-secondary);
  }
  .dl-meta {
    font-variant-numeric: tabular-nums;
  }
  .dl-err {
    margin-top: 4px;
    font-size: var(--text-sm);
    color: var(--danger);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Statusbadge — kleur via bestaande tokens per toon. */
  .dl-status {
    flex: 0 0 auto;
    font-size: var(--text-xs);
    font-weight: 600;
    padding: 2px 9px;
    border-radius: var(--radius-full);
    background: var(--surface-3);
    color: var(--text-secondary);
    white-space: nowrap;
  }
  .tone-ok {
    color: var(--success);
    background: var(--success-soft, color-mix(in srgb, var(--success) 16%, transparent));
  }
  .tone-bad {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 16%, transparent);
  }
  .tone-pending {
    color: var(--warning);
    background: color-mix(in srgb, var(--warning) 16%, transparent);
  }
  /* .tone-muted valt terug op de neutrale badge-basis. */
  .dl-replay {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
  }
  .dl-more {
    display: flex;
    justify-content: center;
    padding: 12px 0;
  }
</style>
