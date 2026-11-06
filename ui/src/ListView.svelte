<script>
  import { t, locale } from "./lib/i18n.js";
  // Lijst/tabel-view naast de kanban (BETON-54). Toont de reeds gefilterde
  // items als sorteerbare tabel; klik op een kolomkop sorteert, rij-klik opent
  // de drawer. Bulk-select werkt hier net als op het board. Herbruikt door de
  // My-Issues-view (BETON-55) via `groupLabel`.
  import { LIST_COLUMNS, sortRows, nextSort, formatTimestamp, absoluteTime } from "./lib/board.js";
  import { labelHueOf, projectKeyOfRef } from "./lib/labelPalette.svelte.js";
  import { OPTIONAL_COLUMNS, readHiddenColumns, toggleColumn } from "./lib/listColumns.js";
  import { readPersisted, writePersisted } from "./lib/viewState.js";
  import Select from "./Select.svelte";
  import DueBadge from "./DueBadge.svelte";
  import Avatar from "./Avatar.svelte";
  import Chip from "./Chip.svelte";
  import Skeleton from "./Skeleton.svelte";
  import EmptyState from "./EmptyState.svelte";
  import { Cpu, Flag, Archive, List, MessageCircleQuestion, MessageSquareDot } from "@lucide/svelte";
  import { splitModelLabels, fitChips } from "./lib/labels.js";
  import WorkloadBadge from "./WorkloadBadge.svelte";

  let {
    items = [],
    preferenceKey = "betonning-list-columns",
    selectMode = false,
    selectedRefs = [],
    onopen = () => {},
    ontoggle = () => {},
    // BETON-360: "alles op deze pagina" (de header-checkbox) — krijgt de
    // huidige gesorteerde refs mee, de aanroeper bepaalt aan/uit.
    ontoggleall = () => {},
    // BETON-362: meldt de effectief gerenderde volgorde terug — ListView
    // sorteert lokaal (klik op kolomkop), dus de aanroeper kan de volgorde
    // niet zelf herberekenen voor "vorige/volgende" in de drawer.
    onorder = () => {},
    // Optioneel: extra kolom-prefix per rij (bv. project-key in My Issues).
    showProject = false,
    // State-naam → kleur (BETON-70), zelfde bron als de kolomstip op het board.
    stateColors = new Map(),
    // Alleen de projectlijst geeft bewerkbare statussen mee (BETON-447).
    stateOptions = [],
    onstatechange = null,
    // Handle → avatar_url (BETON-81), zelfde bron als het board.
    avatarMap = new Map(),
    // Handles van virtuele queues (BETON-460): anders weergegeven dan personen.
    virtualHandles = new Set(),
    // Optioneel: toont skeleton-rijen i.p.v. de tabelinhoud tijdens het laden
    // (BETON-226). Default false — bestaande aanroepen (App.svelte) blijven
    // ongewijzigd werken zonder deze prop mee te geven.
    loading = false,
  } = $props();

  function loadHidden() {
    return readHiddenColumns(readPersisted(preferenceKey, () => true, null));
  }
  let hiddenColumns = $state(loadHidden());
  let visibleColumns = $derived(LIST_COLUMNS.filter((c) => !hiddenColumns.includes(c.key)));
  $effect(() => { hiddenColumns = loadHidden(); });

  function toggleVisibleColumn(key) {
    hiddenColumns = toggleColumn(hiddenColumns, key);
    writePersisted(preferenceKey, JSON.stringify(hiddenColumns));
    if (hiddenColumns.includes(sort.key)) sort = { key: "ref", dir: "asc" };
  }

  let sort = $state({ key: "last_activity_at", dir: "desc" });
  let sorted = $derived(sortRows(items, sort.key, sort.dir));

  $effect(() => {
    // Vorige/volgende in de drawer (BETON-362) volgt de VOLLE sortering,
    // ongeacht paginering hieronder — navigeren mag over paginagrenzen heen.
    onorder(sorted.map((i) => i.ref));
  });

  // Paginering boven 200 rijen (BETON-359): een grote project-lijst maakt de
  // tabel traag om te renderen. Geen virtualisatie-lib — de rij-hoogte
  // varieert door labels, wat de meeste virtualisatie-libs juist lastig
  // vinden — gewoon 50 per pagina met knoppen onderaan.
  // Eén regel per rij (BETON-460/479): meer gewone labels dan dit worden +N.
  const MAX_LIST_CHIPS = 2;
  const PAGE_SIZE = 50;
  const PAGINATE_THRESHOLD = 200;
  let page = $state(0);
  let paginated = $derived(sorted.length > PAGINATE_THRESHOLD);
  let pageCount = $derived(paginated ? Math.max(1, Math.ceil(sorted.length / PAGE_SIZE)) : 1);
  let visibleRows = $derived(
    paginated ? sorted.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE) : sorted,
  );

  $effect(() => {
    // Nieuwe items (filter/project-wissel) of een nieuwe sortering → terug
    // naar pagina 1, anders kan een filter je op een lege pagina achterlaten.
    items;
    sort;
    page = 0;
  });

  function clickHead(key) {
    sort = nextSort(sort, key);
  }
  function ariaSort(key) {
    if (sort.key !== key) return "none";
    return sort.dir === "asc" ? "ascending" : "descending";
  }
  function onRowClick(e, ref) {
    // Een statuskeuze opent niet tegelijkertijd de drawer.
    if (e.target.closest("button, [role=combobox]")) return;
    selectMode ? ontoggle(ref, e) : onopen(ref);
  }
  function onRowKey(e, ref) {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      selectMode ? ontoggle(ref, e) : onopen(ref);
    }
  }
</script>

<div class="list-toolbar">
  <details class="column-picker">
    <summary>{$t("list.columns")}</summary>
    <div class="column-options">
      <p>{$t("list.fixed")}</p>
      {#each OPTIONAL_COLUMNS as col (col.key)}
        <label><input type="checkbox" checked={!hiddenColumns.includes(col.key)} onchange={() => toggleVisibleColumn(col.key)} />{$t("list.column." + col.key)}</label>
      {/each}
    </div>
  </details>
</div>
<div class="list-wrap">
  <table class="list-table">
    <thead>
      <tr>
        {#if selectMode}
          <th class="sel-col" scope="col">
            <span class="sr-only">{$t("list.select")}</span>
            <button
              class="row-check-all"
              title={$t("list.selectPage")}
              aria-label={$t("list.selectPage")}
              onclick={() => ontoggleall(visibleRows.map((i) => i.ref))}
            >
              <span
                class="row-check"
                class:on={visibleRows.length > 0 && visibleRows.every((i) => selectedRefs.includes(i.ref))}
                aria-hidden="true"
              ></span>
            </button>
          </th>
        {/if}
        {#each visibleColumns as col (col.key)}
          <th scope="col" aria-sort={ariaSort(col.key)} class:num={col.key === "workload"}>
            <button class="head-btn" onclick={() => clickHead(col.key)}>
              {$t("list.column." + col.key)}
              {#if sort.key === col.key}
                <span class="head-arrow" aria-hidden="true">{sort.dir === "asc" ? "▲" : "▼"}</span>
              {/if}
            </button>
          </th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#if loading}
        {#each Array(6) as _, i (i)}
          <tr class="skel-row-tr">
            <td colspan={visibleColumns.length + (selectMode ? 1 : 0)}><Skeleton preset="lines" count={1} /></td>
          </tr>
        {/each}
      {:else}
      {#each visibleRows as item (item.ref)}
        <tr
          class="list-row"
          class:selected={selectMode && selectedRefs.includes(item.ref)}
          class:archived={item.archived_at}
          tabindex="0"
          role="button"
          data-ref={item.ref}
          aria-label={$t("list.openItem", {ref:item.ref,title:item.title})}
          onclick={(e) => onRowClick(e, item.ref)}
          onkeydown={(e) => onRowKey(e, item.ref)}
        >
          {#if selectMode}
            <td class="sel-col">
              <span class="row-check" class:on={selectedRefs.includes(item.ref)} aria-hidden="true"></span>
            </td>
          {/if}
          <td class="ref-cell">
            <span class="ref">{item.ref}</span>
            {#if item.archived_at}<Archive size={11} class="arch-ico" />{/if}
          </td>
          <td class="title-cell">
            <!-- BETON-460: iconen inline achter de titel; alleen de titel kapt af. -->
            <div class="title-line">
              <span class="title-text" title={item.title}>{item.title}</span>
              <DueBadge due={item.due_date} />
              {#if item.has_open_question}
                <!-- BETON-275: open-vraag-markering. -->
                <MessageCircleQuestion size={13} class="q-ico" aria-label={$t("list.openQuestion")} />
              {/if}
              {#if item.has_unread}
                <!-- BETON-281: ongelezen-comments-markering, naast een eventuele open vraag. -->
                <MessageSquareDot size={13} class="unread-ico" aria-label={$t("list.unread")} />
              {/if}
            </div>
          </td>
          {#if !hiddenColumns.includes("state")}
          <td class="state-cell" style:--state-color={stateColors.get(item.state) || "var(--border-strong)"}>
            {#if onstatechange && stateOptions.length && !selectMode}
              <Select
                value={item.state}
                options={stateOptions}
                ariaLabel={$t("list.stateFor", {ref:item.ref})}
                class="list-state-select"
                action
                disabled={!!item.locked || !!item.archived_at}
                onchange={(value) => onstatechange(item.ref, value)}
              />
            {:else if item.state}
              <span class="state-chip">
                <span class="state-dot" style:background={stateColors.get(item.state) || "var(--border-strong)"}></span>
                {item.state}
              </span>
            {/if}
          </td>
          {/if}
          {#if !hiddenColumns.includes("workload")}
          <td class="prio-cell">
            <WorkloadBadge workload={item.workload} />
          </td>
          {/if}
          {#if !hiddenColumns.includes("assignee")}
          <td class="assignee-cell">
            {#if item.assignee}
              <span class="assignee" class:queue={virtualHandles.has(item.assignee)} title={virtualHandles.has(item.assignee) ? `Queue @${item.assignee}` : `@${item.assignee}`}>
                <Avatar handle={item.assignee} avatarUrl={avatarMap.get(item.assignee)} size={20} />
                <span class="assignee-handle">@{item.assignee}</span>
              </span>
            {/if}
          </td>
          {/if}
          {#if !hiddenColumns.includes("labels")}
          {@const split = splitModelLabels(item.labels)}
          {@const fit = fitChips(split.plain, MAX_LIST_CHIPS)}
          <td>
            <span class="labels">
              {#each fit.shown as l}
                <Chip tone="label" hue={labelHueOf(l, projectKeyOfRef(item.ref))}>{l}</Chip>
              {/each}
              {#if fit.hidden.length}
                <span class="more-labels" title={split.plain.join(", ")}>+{fit.hidden.length}</span>
              {/if}
              {#each split.models as m}
                <span class="model-label" title={$t("list.workClass")}><Cpu size={11} />{m}</span>
              {/each}
            </span>
          </td>
          {/if}
          {#if !hiddenColumns.includes("milestone")}
          <td class="mono">
            {#if item.milestone}<span class="ms-chip" title="Milestone {item.milestone}"><Flag size={10} />{item.milestone}</span>{/if}
          </td>
          {/if}
          {#if !hiddenColumns.includes("last_activity_at")}
          <td class="mono date-cell" title={absoluteTime(item.last_activity_at, $locale)}>{formatTimestamp(item.last_activity_at, Date.now(), $locale)}</td>
          {/if}
          {#if !hiddenColumns.includes("created_at")}
          <td class="mono date-cell" title={absoluteTime(item.created_at, $locale)}>{formatTimestamp(item.created_at, Date.now(), $locale)}</td>
          {/if}
        </tr>
      {:else}
        <tr>
          <td colspan={visibleColumns.length + (selectMode ? 1 : 0)} class="empty-cell">
            <EmptyState icon={List} title={$t("list.noItems")} />
          </td>
        </tr>
      {/each}
      {/if}
    </tbody>
  </table>
  {#if paginated}
    <!-- BETON-359: alleen zichtbaar boven de 200-rijen-drempel. -->
    <div class="list-pager">
      <button disabled={page === 0} onclick={() => (page = Math.max(0, page - 1))}>{$t("list.previous")}</button>
      <span class="list-pager-info">{$t("list.page", {page:page+1,total:pageCount,rows:sorted.length})}</span>
      <button
        disabled={page >= pageCount - 1}
        onclick={() => (page = Math.min(pageCount - 1, page + 1))}
      >
        {$t("list.next")}
      </button>
    </div>
  {/if}
</div>

<style>
  .list-toolbar { display: flex; justify-content: flex-end; margin: var(--space-3) clamp(12px, 3vw, 28px) 0; }
  .column-picker { position: relative; font-size: var(--text-sm); }
  .column-picker summary { cursor: pointer; padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
  .column-options { position: absolute; right: 0; z-index: var(--z-overlay); min-width: 200px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--shadow-lg); }
  .column-options p { margin: 0 0 8px; color: var(--text-tertiary); }
  .column-options label { display: flex; align-items: center; gap: 8px; padding: 5px 0; white-space: nowrap; }
  .list-wrap {
    margin: var(--space-5) clamp(12px, 3vw, 28px) 28px;
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--surface);
  }
  /* Paginering boven 200 rijen (BETON-359). */
  .list-pager {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    padding: 10px;
    border-top: 1px solid var(--border);
    background: var(--surface-2);
  }
  .list-pager-info {
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .list-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-base);
  }
  thead th {
    position: sticky;
    top: 0;
    background: var(--surface-2);
    text-align: left;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    z-index: var(--z-raised);
  }
  .head-btn {
    all: unset;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 9px 12px;
    width: 100%;
    box-sizing: border-box;
    cursor: pointer;
    font-weight: 600;
    color: var(--text-secondary);
    font-size: var(--text-sm);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .head-btn:hover {
    color: var(--text-primary);
  }
  .head-arrow {
    font-size: 9px;
    color: var(--accent);
  }
  .list-row {
    cursor: pointer;
    border-bottom: 1px solid var(--border);
  }
  .list-row:last-child {
    border-bottom: none;
  }
  .list-row:hover {
    background: color-mix(in srgb, var(--accent) 6%, transparent);
  }
  .list-row.selected {
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }
  .list-row.archived {
    opacity: 0.55;
  }
  td {
    padding: 8px 12px;
    vertical-align: middle;
  }
  .ref-cell {
    white-space: nowrap;
  }
  .ref {
    font-family: ui-monospace, monospace;
    font-size: var(--text-sm);
    color: var(--text-tertiary);
    font-weight: 600;
  }
  /* Titelkolom neemt de resterende breedte (BETON-460): width:100% + max-width:0
     laat een tabelcel krimpen zodat de ellipsis in .title-text werkt. */
  .title-cell {
    color: var(--text);
    width: 100%;
    max-width: 0;
    min-width: 12ch;
  }
  .title-line {
    display: flex;
    align-items: center;
    gap: 4px;
    min-width: 0;
  }
  .title-text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Open-vraag-markering (BETON-275). */
  .title-line :global(.q-ico) {
    color: var(--accent);
    flex-shrink: 0;
  }
  /* Ongelezen-comments-markering (BETON-281) — ander token dan .q-ico zodat
     beide naast elkaar te onderscheiden zijn. */
  .title-line :global(.unread-ico) {
    color: var(--warning);
    flex-shrink: 0;
  }
  .assignee-cell {
    white-space: nowrap;
  }
  .assignee {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 18ch;
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .assignee-handle {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* Virtuele queue (coding-agent, hermes-agent): cursief en gedempt, geen persoon. */
  .assignee.queue {
    font-style: italic;
    color: var(--text-tertiary);
  }
  .state-cell :global(.list-state-select) {
    min-height: unset;
    padding: 2px 6px;
    font-size: var(--text-xs);
    white-space: nowrap;
  }
  .state-cell :global(.list-state-select)::before {
    content: "";
    width: 7px;
    height: 7px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--state-color);
  }
  .state-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 1px 8px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--text-tertiary) 14%, transparent);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    white-space: nowrap;
  }
  .state-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .prio-cell {
    text-align: center;
  }
  .labels {
    display: inline-flex;
    gap: 4px;
    flex-wrap: nowrap;
    overflow: hidden;
    align-items: center;
    white-space: nowrap;
  }
  .more-labels {
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }
  .mono {
    font-variant-numeric: tabular-nums;
    color: var(--text-tertiary);
    font-size: var(--text-sm);
    white-space: nowrap;
  }
  .ms-chip {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    color: var(--accent);
  }
  .date-cell {
    color: var(--text-tertiary);
  }
  .empty-cell {
    padding: 0;
  }
  .skel-row-tr td {
    padding: 12px;
  }
  .row-check {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 1.5px solid var(--border-strong);
    border-radius: 4px;
  }
  .row-check.on {
    background: var(--accent);
    border-color: var(--accent);
  }
  .sel-col {
    width: 34px;
    text-align: center;
  }
  .row-check-all {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: unset;
    padding: 0;
    border: none;
    background: none;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
  .model-label {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: var(--text-sm);
    color: var(--text-tertiary);
    white-space: nowrap;
  }
</style>
