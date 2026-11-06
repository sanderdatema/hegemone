<script>
  import { t, locale } from "./lib/i18n.js";
  // Overzicht over ÁLLE projecten (BETON-371): de vijfde basis-view naast
  // bord/lijst/wiki/activiteit. Eén kaart per levend project met de tellers
  // die bepalen waar je vandaag heen moet — open werk, wat er loopt, wat
  // klemt, wat niemand heeft, en wat er persoonlijk op jou wacht (open vragen
  // en ongelezen activiteit).
  //
  // Eén backend-call (`GET /overview`, gebatcht) — bewust géén fetch per
  // project, want dat is precies de lus die dit scherm duur maakt.
  //
  // Geen losse repository-module: alles hier is fetch/DOM-bind. De enige puur
  // testbare eenheid (`hidesProjectFilters`) staat in lib/viewState.js.
  import { api } from "./api.js";
  import { countParts, splitProjects } from "./lib/overview.js";
  import EmptyState from "./EmptyState.svelte";
  import Skeleton from "./Skeleton.svelte";
  import {
    Boxes,
    RefreshCw,
    CircleDot,
    Ban,
    UserX,
    MessageCircleQuestion,
    Mail,
  } from "@lucide/svelte";

  let { liveTick = 0, onopen = () => {} } = $props();

  let rows = $state([]);
  let loading = $state(true);
  let error = $state("");

  // Monotone volg-teller tegen races tussen overlappende load()-aanroepen
  // (zelfde patroon als Activity.svelte).
  let seq = 0;

  async function load() {
    const mine = ++seq;
    loading = true;
    error = "";
    try {
      const data = await api.overview();
      if (mine !== seq) return;
      rows = data;
    } catch (e) {
      if (mine === seq) error = e.message || $t("overview.loadFailed");
    } finally {
      if (mine === seq) loading = false;
    }
  }

  $effect(() => {
    load();
  });

  // Live-tik → gedebounced herladen (250ms), anders vuurt een triage-pass één
  // fetch per event. Slaat de mount-tik over: het effect hierboven laadt al.
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

  let groups = $derived(splitProjects(rows));

  function pct(ms) {
    if (!ms || !ms.items_total) return 0;
    return Math.round((ms.items_done / ms.items_total) * 100);
  }
</script>

<section class="ov-view" aria-label={$t("overview.title")}>
  <header class="ov-head">
    <h2><Boxes size={18} /> {$t("overview.allProjects")}</h2>
    <button class="icon-btn" title={$t("overview.refresh")} aria-label={$t("overview.refresh")} onclick={load}>
      <RefreshCw size={15} />
    </button>
  </header>

  {#if error}
    <p class="ov-error" role="alert">{error}</p>
  {/if}

  {#if loading && !rows.length}
    <div class="ov-grid" aria-busy="true">
      {#each Array(4) as _, i (i)}
        <div class="ov-card"><Skeleton preset="card" count={1} /></div>
      {/each}
    </div>
  {:else if !rows.length}
    <EmptyState
      icon={Boxes}
      title={$t("overview.none")}
      description={$t("overview.emptyNote")}
    />
  {:else}
    <div class="ov-grid">
      {#each groups.active as p (p.key)}
        <button class="ov-card ov-card-btn" onclick={() => onopen(p.key)}>
          <span class="ov-title">
            <span class="ov-name">{p.name}</span>
            <span class="ov-key">{p.key}</span>
          </span>

          <span class="ov-counts">
            <span class="ov-count" title={$t("overview.openCount", {count:p.open})}>
              <strong>{p.open}</strong> {$t("overview.open")}
            </span>
          </span>

          {#if countParts(p, $locale).length}
            <span class="ov-mine">
              {#each countParts(p, $locale) as c, i (c.key)}
                {#if i > 0}<span class="ov-sep" aria-hidden="true">·</span>{/if}
                <span class="ov-count" class:alert={c.mine} title={c.title}>
                  {#if c.key === "in_progress"}<CircleDot size={13} />
                  {:else if c.key === "blocked"}<Ban size={13} />
                  {:else if c.key === "unassigned"}<UserX size={13} />
                  {:else if c.key === "open_questions"}<MessageCircleQuestion size={13} />
                  {:else}<Mail size={13} />{/if}
                  {c.text}
                </span>
              {/each}
            </span>
          {/if}

          {#if p.next_milestone}
            <span class="ov-ms">
              <span class="ov-ms-head">
                <span class="ov-ms-name">{p.next_milestone.name}</span>
                <span class="ov-ms-count"
                  >{p.next_milestone.items_done}/{p.next_milestone.items_total}</span
                >
              </span>
              <span class="ov-bar" aria-hidden="true">
                <span class="ov-bar-fill" style:width="{pct(p.next_milestone)}%"></span>
              </span>
              {#if p.next_milestone.due_date}
                <span class="ov-ms-due">{p.next_milestone.due_date.slice(0, 10)}</span>
              {/if}
            </span>
          {/if}
        </button>
      {/each}
    </div>

    {#if groups.quiet.length}
      <details class="ov-quiet">
        <summary>{$t("overview.quiet")} ({groups.quiet.length})</summary>
        <ul>
          {#each groups.quiet as p (p.key)}
            <li>
              <button class="ov-quiet-row" onclick={() => onopen(p.key)}>
                <span class="ov-name">{p.name}</span>
                <span class="ov-key">{p.key}</span>
              </button>
            </li>
          {/each}
        </ul>
      </details>
    {/if}
  {/if}
</section>

<style>
  .ov-view {
    padding: var(--space-4);
    max-width: 1100px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .ov-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .ov-head h2 {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 1.05rem;
    margin: 0;
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
  .ov-error {
    color: var(--danger);
  }
  .ov-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr));
    gap: var(--space-3);
  }
  .ov-card {
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    /* de globale button-reset zet justify-content:center; in een kolom
       centreert dat de inhoud verticaal (BETON-473) */
    justify-content: flex-start;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface);
    text-align: left;
  }
  .ov-card-btn:hover {
    border-color: var(--accent);
  }
  .ov-title {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .ov-name {
    white-space: normal;
    min-width: 0;
    overflow-wrap: anywhere;
    font-weight: 600;
  }
  .ov-key {
    flex-shrink: 0;
    font-size: var(--text-sm);
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
  }
  .ov-counts,
  .ov-mine {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .ov-count {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-variant-numeric: tabular-nums;
  }
  .ov-count.zero {
    color: var(--text-tertiary);
  }
  .ov-count.alert {
    color: var(--accent);
    font-weight: 600;
  }
  .ov-sep {
    color: var(--text-tertiary);
  }
  .ov-quiet summary {
    cursor: pointer;
    color: var(--text-secondary);
    font-size: var(--text-sm);
  }
  .ov-quiet ul {
    list-style: none;
    margin: var(--space-2) 0 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr));
    gap: var(--space-1) var(--space-3);
  }
  .ov-quiet-row {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-1) var(--space-2);
    background: transparent;
    border: 0;
    text-align: left;
    color: var(--text-secondary);
  }
  .ov-quiet-row:hover {
    color: var(--text);
  }
  .ov-ms {
    margin-top: auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .ov-ms-name {
    white-space: normal;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .ov-ms-count {
    flex-shrink: 0;
  }
  .ov-ms-head {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .ov-ms-count {
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
  }
  .ov-bar {
    display: block;
    height: 4px;
    border-radius: 2px;
    background: var(--border);
    overflow: hidden;
  }
  .ov-bar-fill {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .ov-ms-due {
    color: var(--text-tertiary);
    font-size: var(--text-xs);
  }
</style>
