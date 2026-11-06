<script>
  import { onMount, untrack } from 'svelte';
  import { t } from './lib/i18n.js';
  import { api } from './api.js';
  import ErrorNote from './ErrorNote.svelte';
  import ConfigurationTransfer from './ConfigurationTransfer.svelte';
  import ConfirmBar from './ConfirmBar.svelte';
  import { installationDraft, installationUpdate, managed, providerStatus, PROVIDERS } from './lib/installationSettings.js';

  let { onback, onchanged, initialData = null } = $props();
  let data = $state(untrack(() => initialData));
  let draft = $state(untrack(() => data ? installationDraft(data) : null));
  let keys = $state({ llm: '', embedding: '' });
  let clearKeys = $state({ llm: false, embedding: false });
  let busy = $state(false);
  let loading = $state(untrack(() => !data));
  let error = $state('');
  let saved = $state(false);
  let confirmReload = $state(false);
  let tests = $state({});
  let testing = $state(null);
  let transferBusy = $state(false);
  const dirty = $derived(data && draft && Object.keys(installationUpdate(data, draft, keys, clearKeys).settings).length > 0);

  function accept(value) {
    data = value;
    draft = installationDraft(value);
    keys = { llm: '', embedding: '' };
    clearKeys = { llm: false, embedding: false };
    tests = {};
  }
  async function load() {
    loading = true; error = ''; saved = false; confirmReload = false;
    try { accept(await api.installationSettings()); }
    catch (e) { error = e?.message || $t('installation.loadFailed'); }
    finally { loading = false; }
  }
  onMount(() => { if (!initialData) load(); });

  async function save() {
    if (!dirty || busy) return;
    busy = true; error = ''; saved = false;
    try {
      const result = await api.saveInstallationSettings(installationUpdate(data, draft, keys, clearKeys));
      accept(result); saved = true;
    } catch (e) { error = e?.message || $t('installation.saveFailed'); }
    finally { keys = { llm: '', embedding: '' }; busy = false; }
  }
  async function test(name) {
    if (dirty || busy || testing) return;
    testing = name; error = '';
    try {
      const result = await api.testInstallationProvider(name);
      tests = { ...tests, [name]: result.ok ? 'testOk' : 'testFailed' };
    } catch { tests = { ...tests, [name]: 'testFailed' }; }
    finally { testing = null; }
  }
  const blocked = $derived(busy || loading || !!testing || transferBusy);
  async function imported() { await load(); await onchanged?.(); }
</script>

<section class="installation-settings">
  <header>
    {#if onback}<button class="sm" onclick={onback}>{$t('installation.back')}</button>{/if}
    <h2>{$t('installation.title')}</h2>
  </header>
  <p class="muted">{$t('installation.intro')}</p>
  <ErrorNote message={error} onRetry={!data ? load : undefined} />
  {#if loading}<p role="status">{$t('installation.loading')}</p>{/if}
  {#if data && draft}
    <form onsubmit={(e) => { e.preventDefault(); save(); }}>
      <fieldset disabled={blocked}>
        <legend>{$t('installation.general')}</legend>
        <label>{$t('installation.publicUrl')}
          {#if managed(data, 'public_url')}<span class="managed">{$t('installation.managed')}</span>
          {:else}<input type="url" required bind:value={draft.public_url} placeholder="https://tickets.example.org" />{/if}
        </label>
        {#each ['language', 'ai_language'] as field}
          <label>{$t(field === 'language' ? 'installation.language' : 'installation.aiLanguage')}
            {#if managed(data, field)}<span class="managed">{$t('installation.managed')}</span>
            {:else}<select bind:value={draft[field]}><option value="en">English</option><option value="nl">Nederlands</option></select>{/if}
          </label>
        {/each}
      </fieldset>
      {#each PROVIDERS as name}
        {@const status = data.runtime?.providers?.[name]}
        <fieldset disabled={blocked}>
          <legend>{$t(`installation.${name}`)}</legend>
          <p class="provider-status" role="status">{$t(`installation.${providerStatus(status)}`)}</p>
          <label class="check-row"><input type="checkbox" disabled={managed(data, 'enabled', name)} checked={managed(data, 'enabled', name) ? !!status?.enabled : draft[name].enabled} onchange={(e) => draft[name].enabled = e.currentTarget.checked} />{$t('installation.enabled')}</label>
          {#each ['base_url', 'model', 'timeout'] as field}
            <label>{$t(field === 'base_url' ? 'installation.endpoint' : `installation.${field}`)}
              {#if managed(data, field, name)}<span class="managed">{$t('installation.managed')}</span>
              {:else if field === 'timeout'}<input type="number" min="1" max="120" step="1" bind:value={draft[name].timeout} required />
              {:else}<input type={field === 'base_url' ? 'url' : 'text'} bind:value={draft[name][field]} maxlength={field === 'base_url' ? 2048 : 100} />{/if}
            </label>
          {/each}
          {#if managed(data, 'api_key', name)}
            <p class="managed">{$t('installation.managed')}</p>
          {:else}
            <p class="muted">{$t(data.settings[name].has_api_key ? 'installation.keyPresent' : 'installation.keyAbsent')}</p>
            <label>{$t('installation.key')}
              <input type="password" autocomplete="new-password" bind:value={keys[name]} disabled={clearKeys[name] || !data.secret_storage_ready} maxlength="8192" />
            </label>
            <p class="muted">{$t('installation.keyHint')}</p>
            <label class="check-row"><input type="checkbox" bind:checked={clearKeys[name]} disabled={!data.settings[name].has_api_key || !!keys[name]} />{$t('installation.clearKey')}</label>
          {/if}
          {#if status?.overrides?.length || status?.source === 'injected'}<p class="muted">{$t('installation.managedHint')}</p>{/if}
          <button type="button" class="sm" disabled={blocked || dirty || !status?.ready} onclick={() => test(name)}>{$t(testing === name ? 'installation.testing' : 'installation.test')}</button>
          <p class="muted">{$t('installation.testHint')}</p>
          {#if tests[name]}<p role="status" class:failed={tests[name] === 'testFailed'}>{$t(`installation.${tests[name]}`)}</p>{/if}
        </fieldset>
      {/each}
      {#if !data.secret_storage_ready}<p class="storage-note" role="status">{$t('installation.encryptionUnavailable')}</p>{/if}
      <fieldset disabled={blocked}>
        <legend>{$t('installation.background')}</legend>
        {#each ['triage_enabled', 'wiki_compile_enabled'] as field}
          <label class="check-row"><input type="checkbox" disabled={managed(data, field)} checked={managed(data, field) ? !!data.runtime?.[field] : draft[field]} onchange={(e) => draft[field] = e.currentTarget.checked} />{$t(field === 'triage_enabled' ? 'installation.triage' : 'installation.wiki')}</label>
          {#if managed(data, field)}<p class="managed">{$t('installation.managed')}</p>{/if}
        {/each}
        <p class="muted">{$t('installation.optIn')}</p>
      </fieldset>
      <div class="actions">
        <button type="submit" class="primary" disabled={!dirty || blocked}>{$t(busy ? 'installation.saving' : 'installation.save')}</button>
        <button type="button" disabled={blocked} onclick={() => dirty ? confirmReload = true : load()}>{$t('installation.reload')}</button>
        <span role="status">{#if dirty}{$t('installation.unsaved')}{:else if saved}{$t('installation.saved')}{/if}</span>
      </div>
    </form>
    <ConfigurationTransfer {dirty} disabled={blocked} onbusychange={(value) => transferBusy = value} onapplied={imported} />
    {#if confirmReload}<ConfirmBar message={$t('installation.discard')} confirmLabel={$t('installation.discardYes')} onconfirm={load} oncancel={() => confirmReload = false} />{/if}
  {/if}
</section>

<style>
  .installation-settings { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-6); }
  header, .actions { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
  h2, p { margin: 0; }
  form { display: flex; flex-direction: column; gap: var(--space-6); }
  fieldset { display: flex; flex-direction: column; gap: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-4); min-width: 0; }
  legend { font-weight: 600; padding: 0 var(--space-2); }
  label { display: flex; flex-direction: column; gap: var(--space-2); }
  input:not([type='checkbox']), select { width: 100%; min-width: 0; }
  .check-row { flex-direction: row; align-items: center; }
  .check-row input { flex: 0 0 auto; }
  .muted, .managed { color: var(--text-tertiary); font-size: var(--text-sm); }
  .provider-status { font-weight: 500; }
  .failed { color: var(--danger); }
  .storage-note { color: var(--text-tertiary); }
</style>
