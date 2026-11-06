<script>
  import { t as tr, locale } from "./lib/i18n.js";
  // Command palette (Cmd+K) — fuzzy zoeken over tickets + acties (BETON-56).
  // Twee niveaus: de wortel toont acties + ticket-treffers; kies een ticket en
  // je krijgt snelacties (open / status / werklast / toewijzen) voor dat item.
  import { Dialog } from "bits-ui";
  import { Search, Plus, BookOpen, LayoutGrid, List, FolderInput, Ticket, ChevronRight } from "@lucide/svelte";
  import { api } from "./api.js";
  import { rankItems, moveIndex } from "./lib/palette.js";
  import { WORKLOAD_VALUES, workloadLabel } from "./lib/labels.js";
  import { groupAssignees } from "./lib/agentType.js";

  let {
    projects = [],
    states = [],
    users = [],
    me = null,
    view = "board",
    onclose = () => {},
    onnew = () => {},
    onview = () => {},
    onwiki = () => {},
    ongoto = () => {},
    onopen = () => {},
    onpatch = () => {},
  } = $props();

  let open = $state(true);
  let query = $state("");
  let tickets = $state([]);
  let index = $state(0);
  let error = $state("");
  let selectedTicket = $state(null); // {ref, title} of null → wortelniveau
  let searchTimer = null;
  let searchSeq = 0;

  function onOpenChange(v) {
    if (!v) onclose();
  }

  // --- Ticket-zoek (debounced, race-guard) ---------------------------------
  function scheduleSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 160);
  }
  async function runSearch() {
    const q = query.trim();
    if (!q) {
      tickets = [];
      return;
    }
    const seq = ++searchSeq;
    try {
      const rows = await api.search(q, 8);
      if (seq === searchSeq) {
        tickets = rows;
        error = "";
      }
    } catch (e) {
      if (seq !== searchSeq) return; // ouder antwoord: negeren
      tickets = [];
      error = $tr("palette.searchFailed", {error:e.message});
    }
  }

  // --- Wortel-acties --------------------------------------------------------
  let rootActions = $derived([
    { label: $tr("palette.new"), keywords: ["new", "create", "add"], icon: Plus, run: () => act(onnew) },
    {
      label: $tr(view === "board" ? "palette.toList" : "palette.toBoard"),
      keywords: ["view", "list", "board", "kanban"],
      icon: view === "board" ? List : LayoutGrid,
      run: () => act(() => onview(view === "board" ? "list" : "board")),
    },
    { label: $tr("palette.wiki"), keywords: ["memory", "notes", "kennis"], icon: BookOpen, run: () => act(onwiki) },
    ...projects.map((p) => ({
      label: $tr("palette.project", {key:p.key,name:p.name}),
      keywords: ["goto", "project", p.key, p.name],
      icon: FolderInput,
      run: () => act(() => ongoto(p.key)),
    })),
  ]);

  // Zichtbare lijst op het wortelniveau: gefilterde acties + ticket-treffers.
  let matchedActions = $derived(rankItems(rootActions, query));
  let ticketRows = $derived(
    tickets.map((t) => ({
      // BETON-370: een treffer die alleen in een reactie zit krijgt een suffix
      // en opent straks op die reactie.
      label: `${t.ref}  ${t.title}${t.matched_in === "comment" ? "  · " + $tr("search.comment") : ""}`,
      ref: t.ref,
      title: t.title,
      icon: Ticket,
      isTicket: true,
      run: () =>
        selectTicket({ ref: t.ref, title: t.title, commentId: t.comment_id ?? null }),
    }))
  );
  let rootList = $derived([...matchedActions, ...ticketRows]);

  // --- Ticket-snelacties ----------------------------------------------------
  let ticketActions = $derived(
    selectedTicket
      ? [
          { label: $tr("palette.open",{ref:selectedTicket.ref}), icon: Ticket, run: () => act(() => onopen(selectedTicket.ref, selectedTicket.commentId ?? null)) },
          ...states.map((s) => ({
            label: $tr("palette.state",{value:s.name}),
            keywords: ["state", "status", s.name],
            run: () => act(() => onpatch(selectedTicket.ref, { state: s.name })),
          })),
          ...WORKLOAD_VALUES.map((w) => ({
            label: $tr("palette.workload",{value:workloadLabel(w,$locale)}),
            keywords: ["workload", "werklast", w, workloadLabel(w,$locale)],
            run: () => act(() => onpatch(selectedTicket.ref, { workload: w })),
          })),
          ...groupAssignees(users, me).flatMap((g) => g.options).map((u) => ({
            label: $tr("palette.assign",{handle:u.handle}),
            keywords: ["assign", u.handle],
            run: () => act(() => onpatch(selectedTicket.ref, { assignee: u.handle })),
          })),
          { label: $tr("palette.unassign"), keywords: ["unassign"], run: () => act(() => onpatch(selectedTicket.ref, { assignee: "" })) },
        ]
      : []
  );
  let list = $derived(selectedTicket ? rankItems(ticketActions, query) : rootList);

  function selectTicket(t) {
    selectedTicket = t;
    query = "";
    index = 0;
  }
  function act(fn) {
    fn();
    open = false;
  }

  // Reset selectie-index als de lijst kleiner wordt.
  $effect(() => {
    if (index >= list.length) index = 0;
  });

  function onInput() {
    index = 0;
    if (!selectedTicket) scheduleSearch();
  }

  function onKeydown(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      index = moveIndex(index, 1, list.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      index = moveIndex(index, -1, list.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      list[index]?.run?.();
    } else if (e.key === "Escape" && selectedTicket) {
      // Eerst terug naar het wortelniveau, dan pas sluiten (dat doet de Dialog).
      e.preventDefault();
      e.stopPropagation();
      selectedTicket = null;
      query = "";
      index = 0;
    }
  }
</script>

<Dialog.Root bind:open {onOpenChange}>
  <Dialog.Portal>
    <Dialog.Overlay class="modal-overlay" />
    <Dialog.Content class="cmd" aria-label={$tr("palette.title")}>
      <div class="cmd-input">
        <Search size={17} />
        {#if selectedTicket}
          <button class="cmd-crumb" onclick={() => { selectedTicket = null; query = ""; }}>
            {selectedTicket.ref} <ChevronRight size={13} />
          </button>
        {/if}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          autofocus
          bind:value={query}
          placeholder={$tr(selectedTicket ? "palette.ticketAction" : "palette.hint")}
          oninput={onInput}
          onkeydown={onKeydown}
          aria-label={$tr("palette.search")}
        />
      </div>
      {#if error}<p class="error cmd-error">{error}</p>{/if}
      <ul class="cmd-list" role="listbox">
        {#each list as row, i (row.label)}
          {@const Icon = row.icon}
          <li>
            <button
              class="cmd-row"
              class:active={i === index}
              role="option"
              aria-selected={i === index}
              onmouseenter={() => (index = i)}
              onclick={() => row.run?.()}
            >
              {#if Icon}<span class="cmd-ico"><Icon size={15} /></span>{:else}<span class="cmd-ico"></span>{/if}
              <span class="cmd-label">{row.label}</span>
              {#if row.isTicket}<ChevronRight size={14} class="cmd-more" />{/if}
            </button>
          </li>
        {:else}
          <li class="cmd-none">{$tr("search.none")}</li>
        {/each}
      </ul>
      <div class="cmd-foot">
        <span><kbd>↑</kbd><kbd>↓</kbd> {$tr("palette.navigate")}</span>
        <span><kbd>↵</kbd> {$tr("palette.choose")}</span>
        <span><kbd>esc</kbd> {$tr(selectedTicket ? "palette.back" : "palette.close")}</span>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  :global(.cmd) {
    position: fixed;
    top: 12vh;
    left: 50%;
    transform: translateX(-50%);
    width: min(560px, 92vw);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow: 0 24px 60px -12px rgba(0, 0, 0, 0.45);
    z-index: var(--z-palette);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    max-height: 70vh;
  }
  .cmd-input {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    color: var(--text-tertiary);
  }
  .cmd-input input {
    flex: 1;
    border: none;
    background: none;
    outline: none;
    font-size: 15px;
    color: var(--text);
  }
  .cmd-crumb {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    background: var(--surface-2);
    border: none;
    border-radius: 6px;
    padding: 2px 6px;
    font-size: var(--text-sm);
    font-family: ui-monospace, monospace;
    color: var(--text-secondary);
    cursor: pointer;
  }
  .cmd-error {
    margin: 0;
    padding: 8px 16px;
    border-bottom: 1px solid var(--border);
  }
  .cmd-list {
    list-style: none;
    margin: 0;
    padding: 6px;
    overflow-y: auto;
  }
  .cmd-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    border-radius: 8px;
    padding: 9px 10px;
    cursor: pointer;
    color: var(--text);
    font-size: var(--text-md);
  }
  .cmd-row.active {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .cmd-ico {
    display: inline-flex;
    width: 16px;
    color: var(--text-tertiary);
  }
  .cmd-row.active .cmd-ico {
    color: var(--accent);
  }
  .cmd-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cmd-none {
    padding: 20px;
    text-align: center;
    color: var(--text-tertiary);
    font-size: var(--text-md);
  }
  .cmd-foot {
    display: flex;
    gap: 14px;
    padding: 9px 16px;
    border-top: 1px solid var(--border);
    color: var(--text-tertiary);
    font-size: var(--text-sm);
  }
  kbd {
    font-family: ui-monospace, monospace;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0 4px;
    margin-right: 2px;
  }
</style>
