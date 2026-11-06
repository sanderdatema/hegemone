<script>
  import { t } from "./lib/i18n.js";
  // ErrorNote-primitief (BETON-226): uniforme foutweergave in de panelen —
  // icoon + boodschap + optionele "Opnieuw"-actie. Vervangt de losse
  // `<p class="error">`-plekken (Agents/Deliveries/Inbox/ProjectSettings/
  // NewProject/ProjectsManager/UserSettings/TriageChat/Drawer). De
  // wel/geen-retry- en label-logica zit puur (en getest) in lib/errorNote.js.
  //
  // Boodschappen horen te zeggen wat misging + wat te doen (bv. "Kon
  // comments niet laden — probeer opnieuw"), nooit alleen "Fout".
  import { AlertCircle, RotateCcw } from "@lucide/svelte";
  import { resolveErrorNote } from "./lib/errorNote.js";

  let { message = "", onRetry = undefined, retryLabel = undefined } = $props();
  const note = $derived(resolveErrorNote({ message, onRetry, retryLabel: retryLabel ?? $t("common.retry") }));
</script>

{#if note.visible}
  <div class="error-note" role="alert">
    <AlertCircle size={15} />
    <span class="error-note-msg">{note.message}</span>
    {#if note.showRetry}
      <button type="button" class="error-note-retry" onclick={() => onRetry?.()}>
        <RotateCcw size={13} />
        {note.retryLabel}
      </button>
    {/if}
  </div>
{/if}

<style>
  .error-note {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-md);
    background: var(--danger-soft);
    color: var(--danger);
    font-size: var(--text-base);
  }
  .error-note :global(svg) {
    flex: none;
  }
  .error-note-msg {
    flex: 1;
  }
  .error-note-retry {
    flex: none;
    min-height: unset;
    padding: 4px 10px;
    font-size: var(--text-sm);
    color: var(--danger);
    border-color: var(--danger);
    background: transparent;
  }
  .error-note-retry:hover {
    background: color-mix(in srgb, var(--danger) 12%, transparent);
  }
</style>
