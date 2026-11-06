<script>
  import { onMount } from 'svelte';
  import { t } from './lib/i18n.js';
  import { api } from './api.js';
  import ErrorNote from './ErrorNote.svelte';
  import ConfirmBar from './ConfirmBar.svelte';
  import { MAX_CONFIGURATION_BYTES, parseConfiguration, canConfirmConfiguration, configurationDownload } from './lib/configurationTransfer.js';

  let { dirty = false, disabled = false, onapplied, onbusychange } = $props();
  let busy = $state(false);
  let preview = $state(null);
  let fileName = $state('');
  let error = $state('');
  let notice = $state('');
  let confirming = $state(false);
  let now = $state(Date.now());
  const canApply = $derived(canConfirmConfiguration(preview, now) && !dirty && !disabled && !busy);
  onMount(() => { const timer = setInterval(() => now = Date.now(), 1000); return () => clearInterval(timer); });
  $effect(() => { if (dirty) { preview = null; confirming = false; } });

  function working(value) { busy = value; onbusychange?.(value); }
  function discard() { preview = null; fileName = ''; confirming = false; }
  async function download() {
    working(true); error = ''; notice = '';
    try {
      const document = await api.exportConfiguration();
      const url = URL.createObjectURL(new Blob([configurationDownload(document)], {type:'application/json'}));
      const link = window.document.createElement('a');
      link.href = url; link.download = 'hegemone-configuration-v1.json';
      window.document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notice = 'exported';
    } catch { error = $t('configuration.exportFailed'); }
    finally { working(false); }
  }
  async function choose(event) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!file || dirty || disabled || busy) return;
    discard(); error = ''; notice = ''; working(true);
    try {
      if (file.size > MAX_CONFIGURATION_BYTES) { error = $t('configuration.tooLarge'); return; }
      let document;
      try { document = parseConfiguration(await file.text()); }
      catch { error = $t('configuration.invalidFile'); return; }
      preview = await api.previewConfiguration(document);
      fileName = file.name;
      now = Date.now();
    } catch (e) { error = e?.message || $t('configuration.previewFailed'); }
    finally { working(false); }
  }
  async function apply() {
    if (!canApply) return;
    const token = preview.preview_token;
    discard(); working(true); error = ''; notice = '';
    let applied = false;
    try {
      await api.confirmConfiguration(token);
      applied = true; notice = 'applied';
      await onapplied?.();
    } catch (e) {
      error = applied ? $t('configuration.refreshFailed') : e?.status ? `${$t('configuration.applyFailed')} ${e.message}` : $t('configuration.unknownResult');
    } finally { working(false); }
  }
</script>

<section class="configuration-transfer" aria-label={$t('configuration.title')}>
  <h3>{$t('configuration.title')}</h3>
  <p class="muted">{$t('configuration.intro')}</p>
  <ErrorNote message={error} />
  {#if notice}<p role="status">{$t(`configuration.${notice}`)}</p>{/if}
  <button type="button" disabled={busy || disabled} onclick={download}>{$t('configuration.export')}</button>
  <label>{$t('configuration.file')}<input type="file" accept="application/json,.json" disabled={dirty || disabled || busy} onchange={choose} /></label>
  {#if dirty}<p class="muted">{$t('configuration.dirty')}</p>{/if}
  {#if busy}<p role="status">{$t('configuration.busy')}</p>{/if}
  {#if preview}
    <h4>{$t('configuration.preview')}: {fileName}</h4>
    <p>{$t('configuration.previewHint')}</p>
    {#if preview.conflicts.length}
      <h4>{$t('configuration.conflicts')}</h4>
      <ul>{#each preview.conflicts as conflict}<li>{$t(`configuration.conflict.${conflict.code}`, {target:conflict.target})}</li>{/each}</ul>
    {/if}
    {#if preview.warnings.length}
      <h4>{$t('configuration.warnings')}</h4>
      <ul>{#each preview.warnings as warning}<li>{$t(`configuration.warning.${warning.code}`, {target:warning.target})}</li>{/each}</ul>
    {/if}
    {#each preview.changes as change}
      <details>
        <summary>{$t(`configuration.resource.${change.resource}`)} — {change.identity} · {$t(`configuration.${change.action}`)}</summary>
        <div class="comparison">
          <div><h5>{$t('configuration.before')}</h5><pre>{JSON.stringify(change.before, null, 2)}</pre></div>
          <div><h5>{$t('configuration.after')}</h5><pre>{JSON.stringify(change.after, null, 2)}</pre></div>
        </div>
      </details>
    {:else}<p>{$t('configuration.noChanges')}</p>{/each}
    {#if !canConfirmConfiguration(preview, now) && preview.can_apply && preview.changes.length}<p role="status">{$t('configuration.expired')}</p>{/if}
    <div class="actions"><button type="button" class="primary" disabled={!canApply} onclick={() => confirming = true}>{$t('configuration.apply')}</button><button type="button" disabled={busy || disabled} onclick={discard}>{$t('configuration.discard')}</button></div>
    {#if confirming}<ConfirmBar message={$t('configuration.confirm', {count:preview.changes.length})} confirmLabel={$t('configuration.yesApply')} confirmDisabled={!canApply} onconfirm={apply} oncancel={() => confirming = false} role="alertdialog" ariaLabel={$t('configuration.apply')} focus />{/if}
  {/if}
</section>

<style>
  .configuration-transfer { border-top: 1px solid var(--border); padding-top: var(--space-6); display: flex; flex-direction: column; gap: var(--space-3); }
  h3, h4, h5, p { margin: 0; }
  label { display: flex; flex-direction: column; gap: var(--space-2); }
  .muted { color: var(--text-tertiary); font-size: var(--text-sm); }
  .actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
  details { border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-3); }
  summary { cursor: pointer; }
  .comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); margin-top: var(--space-3); }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 320px; overflow: auto; font-size: var(--text-sm); }
  @media (max-width: 600px) { .comparison { grid-template-columns: 1fr; } }
</style>
