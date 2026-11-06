<script>
  // Globale koppeling werkklasse → model per harnas (BETON-476). Alleen voor
  // mensen getoond (PUT is mens-only); de server geeft alleen modelnamen terug.
  import { t } from "./lib/i18n.js";
  import { api } from "./api.js";
  import ErrorNote from "./ErrorNote.svelte";
  import { mappingToRows, rowsToMapping, mappingChanged } from "./lib/modelClasses.js";
  import { Check, Cpu } from "@lucide/svelte";

  let classes = $state(["routine", "standaard", "complex"]);
  let rows = $state([]);
  let base = $state({});
  let error = $state("");
  let saved = $state(false);
  let busy = $state(false);
  let loaded = $state(false);

  async function load() {
    try {
      const d = await api.modelClasses();
      classes = d.classes;
      base = d.mapping;
      rows = mappingToRows(d.mapping);
      loaded = true;
    } catch {
      error = $t("settings.loadModelsFailed");
    }
  }
  $effect(() => {
    load();
  });

  let dirty = $derived(loaded && mappingChanged(rowsToMapping(rows, classes), base));

  function addRow() {
    rows = [...rows, { harness: "", models: {} }];
  }

  async function save() {
    error = "";
    saved = false;
    busy = true;
    try {
      const d = await api.setModelClasses(rowsToMapping(rows, classes));
      base = d.mapping;
      rows = mappingToRows(d.mapping);
      saved = true;
    } catch (e) {
      error = e?.displayDetail || e?.message || $t("settings.saveModelsFailed");
    } finally {
      busy = false;
    }
  }
</script>

<section class="mc-sec">
  <div class="mc-head"><Cpu size={14} /> {$t("settings.modelClasses")}</div>
  <p class="mc-note">
    {$t("settings.modelClassesNote")}
  </p>
  <ErrorNote message={error} />
  {#if loaded}
    <div class="mc-grid" style:--cols={classes.length}>
      <span></span>
      {#each classes as c}<span class="mc-col">{c}</span>{/each}
      {#each rows as r, i}
        <input class="mc-h" placeholder={$t("settings.harnessPlaceholder")} aria-label={$t("settings.harness")} bind:value={r.harness} />
        {#each classes as c}
          <input aria-label={`${r.harness || $t("settings.harness")} ${c}`} bind:value={r.models[c]} />
        {/each}
      {/each}
    </div>
    <div class="mc-actions">
      <button class="sm" onclick={addRow}>{$t("settings.addHarness")}</button>
      <button class="primary sm" onclick={save} disabled={!dirty || busy}>
        <Check size={14} /> {$t("common.save")}
      </button>
      {#if saved}<span class="mc-ok">{$t("common.saved")}</span>{/if}
    </div>
  {/if}
</section>

<style>
  .mc-sec {
    padding: 14px 0;
    border-top: 1px solid var(--border);
  }
  .mc-head {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    margin-bottom: 6px;
  }
  .mc-note {
    font-size: var(--text-base);
    color: var(--text-tertiary);
    margin: 0 0 10px;
  }
  .mc-grid {
    display: grid;
    grid-template-columns: minmax(70px, 0.8fr) repeat(var(--cols), minmax(0, 1fr));
    gap: 6px;
    align-items: center;
  }
  .mc-col {
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }
  .mc-grid input {
    min-width: 0;
  }
  .mc-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 10px;
  }
  .mc-ok {
    color: var(--success, var(--text-secondary));
    font-size: var(--text-base);
  }
</style>
