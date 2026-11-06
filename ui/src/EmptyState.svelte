<script>
  // EmptyState-primitief (BETON-226): icoon + één zin + optionele actieknop.
  // Consolideert de losse "niets hier"-teksten in de panelen (Inbox/Agents/
  // Deliveries/ProjectsManager/ListView/Drawer-subsecties) tot één
  // consistente, uitnodigende vorm. Toon: sentence case NL, zegt wat er (niet)
  // is — geen kale "Leeg".
  let { icon: Icon = undefined, title, description = "", actionLabel = "", onAction = undefined } = $props();
</script>

<div class="empty-state">
  {#if Icon}
    <span class="empty-state-icon"><Icon size={26} strokeWidth={1.5} /></span>
  {/if}
  <p class="empty-state-title">{title}</p>
  {#if description}<p class="empty-state-desc">{description}</p>{/if}
  {#if actionLabel && onAction}
    <button type="button" class="empty-state-action" onclick={() => onAction?.()}>
      {actionLabel}
    </button>
  {/if}
</div>

<style>
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: var(--space-2);
    padding: var(--space-8) var(--space-6);
    color: var(--text-tertiary);
  }
  .empty-state-icon {
    display: inline-flex;
    margin-bottom: var(--space-2);
    color: var(--text-tertiary);
  }
  .empty-state-title {
    font-size: var(--text-base);
    color: var(--text-secondary);
    margin: 0;
  }
  .empty-state-desc {
    font-size: var(--text-sm);
    color: var(--text-tertiary);
    margin: 0;
    max-width: 42ch;
  }
  .empty-state-action {
    margin-top: var(--space-2);
    font-size: var(--text-sm);
  }
</style>
