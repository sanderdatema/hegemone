<script>
  import { t } from "./lib/i18n.js";
  import { onMount } from "svelte";
  import { Dialog } from "bits-ui";
  import { X, Plus, Archive, RotateCcw, Settings, FolderInput } from "@lucide/svelte";
  import { api } from "./api.js";
  import ProjectSettings from "./ProjectSettings.svelte";
  import ErrorNote from "./ErrorNote.svelte";
  import Skeleton from "./Skeleton.svelte";
  import EmptyState from "./EmptyState.svelte";

  let { onclose, onnew, onchanged } = $props();

  let settingsProject = $state(null); // {key, name, triage_enabled} of null

  let open = $state(true);
  let loading = $state(true);
  let error = $state("");
  let active = $state([]);
  let archived = $state([]);
  let confirmKey = $state(null); // project-key met open archiveer-bevestiging

  function onOpenChange(v) {
    if (!v) onclose?.();
  }

  async function load() {
    loading = true;
    error = "";
    try {
      const all = await api.projects(true);
      active = all.filter((p) => !p.archived_at);
      archived = all.filter((p) => p.archived_at);
    } catch (e) {
      error = $t("projects.loadFailed");
    } finally {
      loading = false;
    }
  }

  async function doArchive(key) {
    confirmKey = null;
    try {
      await api.archiveProject(key);
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
    }
  }

  async function doRestore(key) {
    try {
      await api.restoreProject(key);
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
    }
  }

  onMount(load);
</script>

<Dialog.Root bind:open {onOpenChange}>
  <Dialog.Portal>
    <Dialog.Overlay class="modal-overlay" />
    <Dialog.Content class="modal">
      <div class="modal-head">
        <Dialog.Title class="modal-title">{$t("projects.title")}</Dialog.Title>
        <Dialog.Close class="icon-btn" aria-label={$t("common.close")}>
          <X size={18} />
        </Dialog.Close>
      </div>

      {#if settingsProject}
        <ProjectSettings
          projectKey={settingsProject.key}
          projectName={settingsProject.name}
          projectDescription={settingsProject.description}
          triageEnabled={settingsProject.triage_enabled}
          wikiCompileEnabled={settingsProject.wiki_compile_enabled}
          onback={() => (settingsProject = null)}
          onchanged={() => { load(); onchanged?.(); }}
        />
      {:else}

      <ErrorNote message={error} onRetry={load} />

      <div class="modal-foot" style="justify-content: flex-start; margin: 0 0 .75rem">
        <button class="primary" onclick={() => onnew?.()}>
          <Plus size={15} /> {$t("project.new")}
        </button>
      </div>

      {#if loading}
        <Skeleton preset="rows" count={4} />
      {:else}
        <div class="pm-section">
          <h4 class="pm-head">{$t("projects.active")}</h4>
          {#if active.length === 0}
            <EmptyState icon={FolderInput} title={$t("projects.noActive")} />
          {:else}
            {#each active as p (p.key)}
              <div class="pm-row">
                <span class="pm-name">
                  <span class="pm-title"><strong>{p.key}</strong> — {p.name}</span>
                  {#if p.description}<span class="pm-desc">{p.description}</span>{/if}
                </span>
                {#if confirmKey === p.key}
                  <span class="pm-confirm">
                    <button class="primary sm" onclick={() => doArchive(p.key)}>
                      {$t("projects.yesArchive")}
                    </button>
                    <button class="sm" onclick={() => (confirmKey = null)}>{$t("common.cancel")}</button>
                  </span>
                {:else}
                  <span class="pm-confirm">
                    <button class="sm" title={$t("projects.settings")} onclick={() => (settingsProject = p)}>
                      <Settings size={14} /> {$t("projects.settings")}
                    </button>
                    <button class="icon-btn sm danger-quiet" title={$t("projects.archive")} onclick={() => (confirmKey = p.key)}>
                      <Archive size={15} />
                    </button>
                  </span>
                {/if}
              </div>
            {/each}
          {/if}
        </div>

        {#if archived.length > 0}
          <div class="pm-section">
            <h4 class="pm-head">{$t("projects.archived")}</h4>
            {#each archived as p (p.key)}
              <div class="pm-row pm-archived">
                <span class="pm-name"><strong>{p.key}</strong> — {p.name}</span>
                <button class="sm" title={$t("projects.restore")} onclick={() => doRestore(p.key)}>
                  <RotateCcw size={14} /> {$t("projects.restore")}
                </button>
              </div>
            {/each}
          </div>
        {/if}
      {/if}
      {/if}
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  .pm-section {
    margin-top: 0.5rem;
  }
  .pm-head {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
    margin: 0.75rem 0 0.35rem;
  }
  .pm-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.4rem 0;
    border-top: 1px solid var(--border);
  }
  .pm-name {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .pm-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pm-desc {
    font-size: 0.8rem;
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pm-archived .pm-name {
    color: var(--text-secondary);
  }
  .pm-confirm {
    display: flex;
    gap: 0.35rem;
    flex: none;
  }
</style>
