<script>
  import { t } from './lib/i18n.js';
  import { itemAction } from './lib/itemAction.js';
  let { item, virtualHandles = new Set(), detail = false } = $props();
  const action = $derived(itemAction(item, {virtualHandles}));
</script>
{#if action}
  <div class="item-action" class:detail>
    <strong>{$t(action.key, action.params)}</strong>
    {#if detail}
      {#if action.reason}<p>{action.reason}</p>{/if}
      {#if action.responsible}<p>{$t('execution.responsible')}: {action.responsible}</p>{/if}
      {#if action.condition}<p>{$t('execution.condition')}: {action.condition}</p>{/if}
    {/if}
  </div>
{/if}
<style>
  .item-action { margin-top: 6px; font-size: var(--text-sm); color: var(--text-secondary); overflow-wrap: anywhere; }
  strong { font-weight: 600; }
  .detail { margin: 10px 0; padding: 10px 12px; background: var(--surface-2); border-radius: var(--radius-sm); }
  p { margin: 4px 0 0; }
</style>
