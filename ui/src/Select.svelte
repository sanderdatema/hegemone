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
  import { Select } from "bits-ui";
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
  } = $props();

  const EMPTY = "__betonning_empty__";
  const toInner = (v) => (v == null || v === "" ? EMPTY : String(v));
  const fromInner = (v) => (v === EMPTY ? "" : v);

  let flat = $derived([...options, ...(groups ?? []).flatMap((g) => g.options)]);
  let items = $derived(flat.map((o) => ({ value: toInner(o.value), label: o.label })));
  let selectedLabel = $derived(
    flat.find((o) => toInner(o.value) === toInner(value))?.label ?? placeholder
  );

  function pick(v) {
    const out = fromInner(v);
    if (out === value) return;
    if (!action) value = out;
    onchange?.(out);
  }
</script>

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
