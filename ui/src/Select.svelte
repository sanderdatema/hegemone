<script>
  // Eigen keuzelijst i.p.v. een native <select> (BETON-439): Safari opent het
  // native menu traag (tot een seconde, ook bij vier opties), Firefox niet.
  // Het menu staat hier in de pagina (bits-ui Select), net als de popovers die
  // wél direct openen. Toetsenbord (pijltjes, Enter, Escape, typen om te
  // springen) komt van bits-ui.
  //
  // `options` is een platte lijst `{value, label}`; `groups` (`{label, options}`)
  // geeft optgroups, getoond ná de losse `options` (zoals AssigneeSelect's
  // "niet toegewezen" boven de groepen). `value` mag "" zijn ("geen"/"alle"):
  // bits-ui leest "" als "niets gekozen", dus intern wordt het een sentinel.
  //
  // `action`: een kiezer die na elke keuze terugvalt op zijn lege waarde (de
  // bulkbalk, "verplaats naar project") — `onchange` krijgt de keuze, maar de
  // getoonde waarde blijft `value`.
  import { Select, Popover } from "bits-ui";
  import { tick } from "svelte";
  import { moveIndex } from "./lib/palette.js";
  import { t } from "./lib/i18n.js";
  import { Check, ChevronDown } from "@lucide/svelte";

  let {
    value = $bindable(""),
    options = [],
    groups = null,
    onchange,
    placeholder = "",
    ariaLabel = undefined,
    id = undefined,
    title = undefined,
    class: klass = "",
    disabled = false,
    action = false,
    searchable = false,
    searchLabel = "",
  } = $props();

  const EMPTY = "__betonning_empty__";
  const toInner = (v) => (v == null || v === "" ? EMPTY : String(v));
  const fromInner = (v) => (v === EMPTY ? "" : v);

  let flat = $derived([...options, ...(groups ?? []).flatMap((g) => g.options)]);
  let items = $derived(flat.map((o) => ({ value: toInner(o.value), label: o.label })));
  let selectedLabel = $derived(
    flat.find((o) => toInner(o.value) === toInner(value))?.label ?? placeholder
  );

  const uid = $props.id();
  let open = $state(false);
  let query = $state("");
  let active = $state(0);
  let searchInput = $state();
  const listId = `${uid}-options`;
  const optionId = (o) => `${listId}-${encodeURIComponent(String(o.value))}`;
  let searchOptions = $derived(options.filter(matches));
  let searchGroups = $derived((groups ?? []).map(g => ({ ...g, options: g.options.filter(matches) })).filter(g => g.options.length));
  let matchesFlat = $derived([...searchOptions, ...searchGroups.flatMap(g => g.options)]);

  function matches(o) {
    return `${o.value} ${o.label}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  }
  function choose(o) {
    pick(toInner(o.value));
    open = false;
  }
  async function focusSearch(event) {
    event.preventDefault();
    await tick();
    searchInput?.focus();
  }
  function searchKey(event) {
    if (event.isComposing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      active = moveIndex(active, event.key === "ArrowDown" ? 1 : -1, matchesFlat.length);
      const option = matchesFlat[active];
      if (option) document.getElementById(optionId(option))?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (matchesFlat[active]) choose(matchesFlat[active]);
    }
  }

  function pick(v) {
    const out = fromInner(v);
    if (out === value) return;
    if (!action) value = out;
    onchange?.(out);
  }
</script>

{#if searchable}
  <Popover.Root bind:open onOpenChange={(next) => { if (next) { query = ""; active = 0; } }}>
    <Popover.Trigger class={`select-trigger ${klass}`.trim()} aria-label={ariaLabel} {id} {title} {disabled}>
      <span class="select-trigger-label">{selectedLabel}</span>
      <ChevronDown size={16} aria-hidden="true" />
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Content class="select-menu searchable-select" align="start" sideOffset={4} onOpenAutoFocus={focusSearch}>
        <input
          bind:this={searchInput}
          bind:value={query}
          oninput={() => (active = 0)}
          onkeydown={searchKey}
          type="search"
          role="combobox"
          aria-label={searchLabel}
          placeholder={searchLabel}
          aria-expanded={open}
          aria-autocomplete="list"
          aria-controls={listId}
          aria-activedescendant={matchesFlat[active] ? optionId(matchesFlat[active]) : undefined}
        />
        <div class="searchable-options" id={listId} role="listbox" aria-label={ariaLabel}>
          {#snippet option(o)}
            <button
              type="button"
              class="select-item"
              class:search-active={matchesFlat[active]?.value === o.value}
              id={optionId(o)}
              role="option"
              aria-selected={toInner(o.value) === toInner(value)}
              tabindex="-1"
              onpointerdown={(event) => event.preventDefault()}
              onpointermove={() => (active = matchesFlat.findIndex(it => it.value === o.value))}
              onclick={() => choose(o)}
            >
              <span class="select-check">{#if toInner(o.value) === toInner(value)}<Check size={14} aria-hidden="true" />{/if}</span>
              {o.label}
            </button>
          {/snippet}
          {#each searchOptions as o (o.value)}{@render option(o)}{/each}
          {#each searchGroups as g (g.label)}
            <div role="group" aria-label={g.label}>
              <div class="select-heading" aria-hidden="true">{g.label}</div>
              {#each g.options as o (o.value)}{@render option(o)}{/each}
            </div>
          {/each}
        </div>
        {#if !matchesFlat.length}<p class="search-empty" role="status">{$t("ui.noMatch")}</p>{/if}
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>
{:else}

<Select.Root
  type="single"
  bind:value={() => toInner(value), pick}
  {items}
  {disabled}
>
  <Select.Trigger
    class={`select-trigger ${klass}`.trim()}
    aria-label={ariaLabel}
    {id}
    {title}
  >
    <span class="select-trigger-label">{selectedLabel}</span>
    <ChevronDown size={16} aria-hidden="true" />
  </Select.Trigger>
  <Select.Portal>
    <Select.Content class="select-menu" sideOffset={4}>
      <Select.Viewport>
        {#snippet item(o)}
          <Select.Item class="select-item" value={toInner(o.value)} label={o.label}>
            {#snippet children({ selected })}
              <span class="select-check">
                {#if selected}<Check size={14} aria-hidden="true" />{/if}
              </span>
              {o.label}
            {/snippet}
          </Select.Item>
        {/snippet}
        {#each options as o (o.value)}{@render item(o)}{/each}
        {#each groups ?? [] as g (g.label)}
          <Select.Group>
            <Select.GroupHeading class="select-heading">{g.label}</Select.GroupHeading>
            {#each g.options as o (o.value)}{@render item(o)}{/each}
          </Select.Group>
        {/each}
      </Select.Viewport>
    </Select.Content>
  </Select.Portal>
</Select.Root>

{/if}

<style>
  :global(.select-menu.searchable-select) {
    display: flex;
    flex-direction: column;
    min-width: var(--bits-popover-anchor-width);
    max-width: calc(100vw - 24px);
    max-height: min(360px, calc(100dvh - 80px));
    overflow: hidden;
  }
  input {
    flex: none;
    width: 100%;
    margin-bottom: var(--space-1);
  }
  .searchable-options { flex: 1 1 auto; overflow-y: auto; min-height: 0; }
  .searchable-options .select-item {
    justify-content: flex-start;
    width: 100%;
    text-align: left;
    border: 0;
    background: transparent;
    font-weight: 400;
  }
  .searchable-options .select-item[aria-selected="true"] { font-weight: 600; }
  .searchable-options .search-active { background: var(--surface-2); }
  .search-empty { margin: var(--space-2); color: var(--text-tertiary); }
</style>
