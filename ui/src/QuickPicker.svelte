<script>
  import { t as uiText } from "./lib/i18n.js";
  // Kleine toetsenbord-picker voor de kaart-sneltoetsen a/s/l (BETON-361):
  // verankerd aan de gefocuste kaart via een DOMRect (`anchorRect`,
  // `card.getBoundingClientRect()` in App.svelte — geen bits-ui Popover omdat
  // de kaart geen Popover.Trigger is, alleen een gefocust DOM-element).
  // Filtert met dezelfde fuzzy-rangschikking als het command palette
  // (`rankItems`), pijltjes/Enter kiezen, Escape/buiten-klik sluit.
  import { rankItems, moveIndex } from "./lib/palette.js";

  let {
    title,
    items, // [{label, value}]
    anchorRect,
    onselect,
    onclose,
  } = $props();

  let query = $state("");
  let active = $state(0);
  let inputEl = $state();

  let filtered = $derived(rankItems(items || [], query));

  $effect(() => {
    filtered; // reset selectie zodra de filtering verandert
    active = 0;
  });

  function onKeydown(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      active = moveIndex(active, 1, filtered.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      active = moveIndex(active, -1, filtered.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[active]) onselect?.(filtered[active].value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onclose?.();
    }
  }

  let top = $derived((anchorRect?.bottom ?? 0) + 4);
  let left = $derived(anchorRect?.left ?? 0);
</script>

<svelte:window
  onmousedown={(e) => {
    if (!e.target.closest?.(".qp-pop")) onclose?.();
  }}
/>

<div class="qp-pop" style:top={`${top}px`} style:left={`${left}px`} role="dialog" aria-label={title}>
  <!-- svelte-ignore a11y_autofocus -->
  <input
    bind:this={inputEl}
    bind:value={query}
    placeholder={title}
    onkeydown={onKeydown}
    autofocus
  />
  <ul class="qp-list">
    {#each filtered as it, i (it.value)}
      <li role="option" aria-selected={i === active} class:active={i === active}>
        <button type="button" onclick={() => onselect?.(it.value)} onmouseenter={() => (active = i)}>
          {it.label}
        </button>
      </li>
    {/each}
    {#if !filtered.length}<li class="qp-empty muted">{$uiText("ui.noMatch")}</li>{/if}
  </ul>
</div>

<style>
  .qp-pop {
    position: fixed;
    z-index: var(--z-hints, 500);
    width: 220px;
    max-height: 260px;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.25));
    overflow: hidden;
  }
  .qp-pop input {
    border: none;
    border-bottom: 1px solid var(--border);
    padding: 8px 10px;
    font-size: var(--text-sm);
    background: transparent;
    color: inherit;
  }
  .qp-pop input:focus {
    outline: none;
  }
  .qp-list {
    list-style: none;
    margin: 0;
    padding: 4px;
    overflow-y: auto;
  }
  .qp-list li button {
    display: block;
    width: 100%;
    text-align: left;
    padding: 6px 8px;
    border: none;
    background: transparent;
    border-radius: var(--radius-sm);
    font-size: var(--text-sm);
    color: inherit;
    cursor: pointer;
  }
  .qp-list li.active button,
  .qp-list li button:hover {
    background: var(--accent-soft);
  }
  .qp-empty {
    padding: 8px;
    font-size: var(--text-sm);
  }
</style>
