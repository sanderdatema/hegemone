<script>
  import { onDestroy } from 'svelte';
  import { api } from './api.js';
  import { t } from './lib/i18n.js';
  import ErrorNote from './ErrorNote.svelte';
  import { canTestWebhook, webhookTestState } from './lib/webhookTest.js';
  let { user, ondeliveries } = $props();
  let delivery = $state(null);
  let busy = $state(false);
  let refreshing = $state(false);
  let error = $state('');
  let exhausted = $state(false);
  let polls = 0, timer, alive = true;
  const state = $derived(webhookTestState(delivery));
  onDestroy(() => { alive = false; clearTimeout(timer); });
  function schedule() {
    clearTimeout(timer);
    if (delivery?.status === 'pending' && polls < 60) timer = setTimeout(refresh, 1000);
    else if (delivery?.status === 'pending') exhausted = true;
  }
  async function refresh() {
    if (!delivery || !alive) return;
    clearTimeout(timer); refreshing = true;
    try {
      const next = await api.webhookTestStatus(user.handle, delivery.id);
      if (!alive) return;
      delivery = next; error = ''; polls++; schedule();
    } catch { if (alive) error = $t('webhookTest.statusFailed'); }
    finally { refreshing = false; }
  }
  async function start() {
    if (!canTestWebhook(user) || busy || delivery?.status === 'pending') return;
    busy = true; error = ''; exhausted = false; clearTimeout(timer);
    try {
      const next = await api.testWebhook(user.handle);
      if (!alive) return;
      delivery = next; polls = 0; schedule();
    } catch (e) { if (alive) error = e?.message || $t('webhookTest.requestFailed'); }
    finally { busy = false; }
  }
</script>
<div class="webhook-test">
  <div class="actions">
    <button type="button" class="sm" disabled={!canTestWebhook(user) || busy || delivery?.status === 'pending'} onclick={start}>{$t(busy ? 'webhookTest.starting' : 'webhookTest.test')}</button>
    {#if delivery}
      <button type="button" class="sm" disabled={refreshing || busy} onclick={() => { polls = 0; exhausted = false; refresh(); }}>{$t('webhookTest.refresh')}</button>
      {#if ondeliveries}<button type="button" class="sm" onclick={ondeliveries}>{$t('webhookTest.details')}</button>{/if}
    {/if}
  </div>
  <p class="hint">{$t('webhookTest.hint')}</p>
  {#if !user.active}<p class="hint">{$t('webhookTest.inactive')}</p>{/if}
  {#if state}<p role="status">{$t(`webhookTest.${state}`)}{#if delivery.http_status} · {$t('webhookTest.http', {status:delivery.http_status})}{/if}</p>{/if}
  {#if exhausted}<p class="hint">{$t('webhookTest.stillPending')}</p>{/if}
  <ErrorNote message={error} />
</div>
<style>
  .webhook-test { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-3); }
  .actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .hint { color: var(--text-tertiary); font-size: var(--text-sm); }
  p { margin: 0; }
</style>
