<script>
  import { t, locale } from "./lib/i18n.js";
  import { api } from "./api.js";
  import Select from "./Select.svelte";
  import { stateGroupLabel } from "./lib/labels.js";
  let { editable = false } = $props();
  let states = $state([]);
  let error = $state("");
  let busy = $state(false);
  let loaded = $state(false);
  let saved = $state(false);
  const groups = $derived(["backlog", "unstarted", "started", "completed", "cancelled"].map(value => ({ value, label: stateGroupLabel(value, $locale) })));
  async function load() {
    if (loaded) return;
    try { states = (await api.projectTemplate()).states; loaded = true; }
    catch (e) { error = e.message; }
  }
  function move(index, step) {
    const next = [...states];
    [next[index], next[index + step]] = [next[index + step], next[index]];
    states = next; saved = false;
  }
  async function save() {
    busy = true; error = ""; saved = false;
    try { states = (await api.setProjectTemplate(states)).states; saved = true; }
    catch (e) { error = e.message; }
    finally { busy = false; }
  }
</script>
<details ontoggle={(e) => { if (e.currentTarget.open) load(); }} class="template">
  <summary>{$t(editable ? "template.edit" : "template.view")}</summary>
  <p>{$t("template.note")}</p>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if loaded}
    <fieldset disabled={!editable || busy} oninput={() => { saved = false; }}>
      {#each states as state, index}
        <div class="template-row">
          <label>{$t("template.columnName")}<input maxlength="100" bind:value={state.name} oninput={() => { saved = false; }} /></label>
          <label>{$t("projectSettings.group")}<Select options={groups} value={state.group} onchange={(value) => { state.group = value; saved = false; }} /></label>
          <label>{$t("projectSettings.color")}<input type="color" bind:value={state.color} /></label>
          <div class="template-options">
          <label><input type="radio" name="template-default" checked={state.is_default} onchange={() => { states = states.map((s, i) => ({ ...s, is_default: i === index })); saved = false; }} /> {$t("template.default")}</label>
          <label><input type="checkbox" bind:checked={state.closed} /> {$t("template.collapsed")}</label>
          <label><input type="checkbox" bind:checked={state.blocks_work} /> {$t("template.blocksWork")}</label>
          </div>
          <div class="template-actions">
          <button type="button" aria-label={$t("template.up")} disabled={index === 0} onclick={() => move(index, -1)}>↑</button>
          <button type="button" aria-label={$t("template.down")} disabled={index === states.length - 1} onclick={() => move(index, 1)}>↓</button>
          <button type="button" onclick={() => { states = states.filter((_, i) => i !== index); saved = false; }}>{$t("common.remove")}</button>
          </div>
        </div>
      {/each}
      <button type="button" onclick={() => { states = [...states, { name: "", group: "unstarted", color: "#3498db", is_default: false, closed: false, blocks_work: false }]; saved = false; }}>{$t("template.addColumn")}</button>
      <button type="button" class="primary" onclick={save}>{$t("template.save")}</button>
    </fieldset>
    {#if saved}<p role="status">{$t("template.saved")}</p>{/if}
  {/if}
</details>
<style>
  .template { margin-top: var(--space-3); font-size: var(--text-sm); }
  summary { cursor: pointer; }
  p { margin: var(--space-2) 0; }
  fieldset { border: 0; padding: 0; min-width: 0; }
  .template-row { display: grid; grid-template-columns: minmax(0, 1fr) 134px 48px; align-items: end; gap: var(--space-2); padding: var(--space-3) 0; border-top: 1px solid var(--border); }
  .template-options, .template-actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
  .template-options label { flex-direction: row; align-items: center; }
  .template-row input[type="color"] { width: 48px; height: 34px; }
  label { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  input:not([type="radio"]):not([type="checkbox"]):not([type="color"]) { width: 100%; }
</style>
