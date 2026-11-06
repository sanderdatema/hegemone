<script>
  import { t as tr } from "./lib/i18n.js";
  import { api } from './api.js';
  import DiffView from './DiffView.svelte';
  import { lineDiff } from './lib/diff.js';
  let { project = null, liveTick = 0, onchanged = () => {} } = $props();
  let proposals = $state([]), error = $state(''), busy = $state(false);
  let seq = 0;
  async function load() {
    const mine = ++seq;
    try { const rows = await api.wikiProposals(project); if (mine === seq) proposals = rows; }
    catch (e) { if (mine === seq) error = e.message; }
  }
  $effect(() => { void project; void liveTick; load(); });
  async function review(id, approve) {
    busy = true; error = '';
    try { await api.wikiReview(id, approve); await load(); onchanged(); }
    catch (e) { error = e.message; }
    finally { busy = false; }
  }
</script>
{#if error}<p role="alert">{error}</p>{/if}
{#if proposals.length}
  <aside aria-label={$tr("wiki.review")} class="wiki-review">
    <strong>{$tr(proposals.length === 1 ? "wiki.reviewOne" : "wiki.reviewMany", {count: proposals.length})}</strong>
    {#each proposals as proposal (proposal.id)}
      <details>
        <summary>{proposal.title} — {$tr("wiki.by")} @{proposal.author}</summary>
        <p>{$tr("wiki.reviewNote", {slug: proposal.slug})}</p>
        <DiffView segments={lineDiff(proposal.current_body, proposal.body_md)} variant="bordered" ariaLabel={$tr("wiki.reviewChange")} />
        <button class="primary" disabled={busy} onclick={() => review(proposal.id, true)}>{$tr("wiki.approve")}</button>
        <button disabled={busy} onclick={() => review(proposal.id, false)}>{$tr("wiki.reject")}</button>
      </details>
    {/each}
  </aside>
{/if}
<style>
  .wiki-review { padding: var(--space-3); margin-bottom: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-sm); }
  details { padding: var(--space-2) 0; }
  summary { cursor: pointer; }
  button { margin-top: var(--space-2); }
</style>
