<script>
  import {t} from "./lib/i18n.js";
  // ConfirmBar.svelte (BETON-319): gedeelde inline-bevestigingsbalk — dedupt de
  // ~11 copy-paste confirm-bars in Drawer.svelte/Wiki.svelte. De CSS stond
  // alleen component-scoped in Drawer.svelte, waardoor de Wiki-bars ongestyled
  // renderden; die styling zit nu hier en geldt voor beide.
  //
  // `message` mag een plain string zijn (meeste gevallen) of een snippet
  // (nodig als de boodschap opmaak bevat, bv. <strong>). `role`/`ariaLabel`/
  // `focus` zijn bewust per aanroep expliciet (geen default die stilzwijgend
  // een rol of focus-steal toevoegt aan bars die dat origineel niet hadden —
  // gedrag moet identiek blijven aan vóór de extractie). `onconfirm` is
  // optioneel: de movePicker-bar heeft geen eigen bevestigknop, de <select>
  // ís de actie (via `children`).
  let {
    message = undefined,
    danger = false,
    inline = false,
    role = undefined,
    ariaLabel = undefined,
    focus = false,
    confirmLabel = undefined,
    confirmClass = "primary",
    confirmDisabled = false,
    cancelLabel = undefined,
    onconfirm,
    oncancel,
    children,
  } = $props();

  // Toegankelijkheid (BETON-64): zet de focus op de eerste actieknop zodra een
  // inline bevestigingsbalk verschijnt (role=alertdialog kondigt aan).
  function focusFirst(node, enabled) {
    if (enabled) node.querySelector("button")?.focus();
  }
</script>

<div
  class="confirm-bar"
  class:danger
  class:inline
  {role}
  aria-label={ariaLabel}
  use:focusFirst={focus}
>
  {#if message}
    <span>{#if typeof message === "function"}{@render message()}{:else}{message}{/if}</span>
  {/if}
  {@render children?.()}
  {#if onconfirm}
    <button class="{confirmClass} sm" onclick={onconfirm} disabled={confirmDisabled}>{confirmLabel ?? $t("common.confirm")}</button>
  {/if}
  {#if oncancel}
    <button class="sm" onclick={oncancel}>{cancelLabel ?? $t("common.cancel")}</button>
  {/if}
</div>

<style>
  /* Bevestigingsbalk (verhuisd uit Drawer.svelte, BETON-319) */
  .confirm-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 8px 12px;
    margin-bottom: 12px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    font-size: var(--text-base);
  }
  .confirm-bar.inline {
    margin: 4px 0 0;
  }
  /* BETON-302: het slot is een waarschuwing, geen neutrale mededeling — vandaar
     de danger-token i.p.v. surface-2. */
  .confirm-bar.danger {
    background: var(--danger-soft);
    border-color: color-mix(in srgb, var(--danger) 40%, transparent);
  }
  .confirm-bar span {
    margin-right: auto;
  }
</style>
