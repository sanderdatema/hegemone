<script>
  import { t } from "./lib/i18n.js";
  import { api } from './api.js';
  let { handle } = $props();
  let loaded = $state(false), error = $state(''), busy = $state(false), saved = $state(false);
  let restricted = $state(false), scopes = $state([]), projects = $state(''), expiry = $state('');
  const options = $derived([{value:'read',label:$t('policy.read')}, {value:'write',label:$t('policy.write')},
    {value:'memory:write',label:$t('policy.memory')}, {value:'llm',label:$t('policy.llm')},
    {value:'admin',label:$t('policy.admin')}]);
  async function load() {
    if (loaded) return;
    try {
      const user = await api.getUser(handle);
      restricted = user.api_key_scopes != null;
      scopes = user.api_key_scopes ?? options.map(o => o.value);
      projects = (user.api_key_projects ?? []).join(', ');
      expiry = user.api_key_expires_at ? new Date(user.api_key_expires_at).toISOString().slice(0,16) : '';
      loaded = true;
    } catch (e) { error = e.message; }
  }
  async function save() {
    error = ''; busy = true; saved = false;
    try {
      await api.updateUser(handle, { api_key_scopes: restricted ? scopes : null,
        api_key_projects: projects.trim() ? projects.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) : null,
        api_key_expires_at: expiry ? expiry + ':00Z' : null });
      saved = true;
    } catch (e) { error = e.message; }
    finally { busy = false; }
  }
</script>
<details ontoggle={(event) => { if (event.currentTarget.open) load(); }}>
  <summary>{$t("policy.title")}</summary>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if loaded}
    <fieldset disabled={busy} oninput={() => { saved = false; }}>
      <label><input type="checkbox" bind:checked={restricted} /> {$t("policy.restrict")}</label>
      {#if restricted}
        {#each options as option}
          <label><input type="checkbox" value={option.value} bind:group={scopes} /> {option.label}</label>
        {/each}
      {/if}
      <label>{$t("policy.projects")}<input bind:value={projects} placeholder="TEAM, DEMO" /></label>
      <label>{$t("policy.expiry")}<input type="datetime-local" bind:value={expiry} /></label>
      <p>{$t("policy.explanation")}</p>
      <button type="button" onclick={save}>{$t("policy.save")}</button>
      <button type="button" onclick={async () => {
        error = ''; busy = true;
        try { await api.resetUsage(handle); saved = true; }
        catch (e) { error = e.message; }
        finally { busy = false; }
      }}>{$t("policy.reset")}</button>
      {#if saved}<span role="status">{$t("common.saved")}</span>{/if}
    </fieldset>
  {/if}
</details>
<style>
  details { grid-column: 1 / -1; margin: var(--space-3) 0; }
  summary { cursor: pointer; }
  fieldset { border: 0; padding: var(--space-2) 0; display: flex; flex-direction: column; gap: var(--space-2); }
  label { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
  input:not([type="checkbox"]) { width: 100%; }
</style>
