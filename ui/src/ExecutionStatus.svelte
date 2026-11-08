<script>
  import { t } from "./lib/i18n.js";
  import { api } from "./api.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import ErrorNote from "./ErrorNote.svelte";
  let { value, ref, me, readOnly = false, onchanged } = $props();
  let confirming = $state(false);
  let stopped = $state(false);
  let reviewed = $state(false);
  let reason = $state("");
  let busy = $state(false);
  let error = $state("");
  let recovery = $derived(value.status === "stopping" || value.block_kind === "recovery");
  let canResume = $derived(!readOnly && me?.kind === "human" && ["blocked", "stopping"].includes(value.status));
  async function resume() {
    if (!canResume || busy || !reason.trim() || (recovery && (!stopped || !reviewed))) return;
    busy = true; error = "";
    try {
      await api.resumeExecution(ref, value.id, {
        reason: reason.trim(), previous_worker_stopped: stopped, previous_effects_reviewed: reviewed,
      });
      confirming = false;
      await onchanged?.();
    } catch (e) { error = e.message; }
    finally { busy = false; }
  }
</script>
<section class="execution-status" aria-label={$t("execution.title")}>
  <div class="execution-heading">
    <strong>{$t(`execution.state.${value.status}`)}</strong>
    {#if value.fence}<span>{$t("execution.attempt", {count: value.fence})}</span>{/if}
  </div>
  <p>{$t("execution.profile")}: <code>{value.profile}</code></p>
  {#if value.reason}<p>{value.reason}</p>{/if}
  {#if value.missing_requirements?.length}<p>{$t("execution.missing")}: {value.missing_requirements.join(", ")}</p>{/if}
  {#if value.responsible}<p>{$t("execution.responsible")}: {value.responsible}</p>{/if}
  {#if value.resume_condition}<p>{$t("execution.condition")}: {value.resume_condition}</p>{/if}
  {#if value.transport_attempts}<p>{$t("execution.transport", {count: value.transport_attempts})}</p>{/if}
  {#if value.run?.evidence?.length}
    <details><summary>{$t("execution.evidence")}</summary>
      <ul>{#each value.run.evidence as item}<li><code>{item.reference}</code>{#if item.sha256} — <code>{item.sha256}</code>{/if}</li>{/each}</ul>
    </details>
  {/if}
  {#if recovery}<p>{$t("execution.recovery")}</p>{/if}
  <ErrorNote message={error} />
  {#if canResume}
    {#if confirming}
      <form onsubmit={(e) => { e.preventDefault(); resume(); }}>
        <AutoTextarea rows={2} aria-label={$t("execution.reason")} placeholder={$t("execution.reason")} bind:value={reason} disabled={busy} />
        {#if recovery}
          <label><input type="checkbox" bind:checked={stopped} disabled={busy} /> {$t("execution.stopped")}</label>
          <label><input type="checkbox" bind:checked={reviewed} disabled={busy} /> {$t("execution.reviewed")}</label>
        {/if}
        <div class="btn-row">
          <button type="submit" class="primary sm" disabled={busy || !reason.trim() || (recovery && (!stopped || !reviewed))}>{$t("execution.resume")}</button>
          <button type="button" class="sm" disabled={busy} onclick={() => (confirming = false)}>{$t("common.cancel")}</button>
        </div>
      </form>
    {:else}
      <button class="sm" onclick={() => { confirming = true; stopped = false; reviewed = false; reason = ""; }}>{$t("execution.resume")}</button>
    {/if}
  {/if}
</section>
<style>
  .execution-status { margin-bottom: var(--space-4); padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-2); }
  .execution-heading { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-2); }
  .execution-heading span { color: var(--text-secondary); font-size: var(--text-sm); }
  p { margin: var(--space-2) 0; }
  code { overflow-wrap: anywhere; }
  label { display: flex; gap: var(--space-2); margin: var(--space-2) 0; align-items: start; }
  form { margin-top: var(--space-3); }
</style>
