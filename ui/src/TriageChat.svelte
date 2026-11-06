<script>
  import { t } from "./lib/i18n.js";
  import { tick } from "svelte";
  import { api } from "./api.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import { renderMarkdown } from "./lib/markdown.js";
  import {
    needsTypedConfirm,
    typedCountValid,
    summarizePreview,
  } from "./lib/triageChat.js";
  import { MessageSquare, X, Send, Plus } from "@lucide/svelte";
  import DrawerDialog from "./DrawerDialog.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import ErrorNote from "./ErrorNote.svelte";
  import EmptyState from "./EmptyState.svelte";

  let { project, projectName, onclose, onopenref } = $props();

  // scope: 'global' of 'project'. Zonder project altijd globaal.
  let scope = $state(project ? "project" : "global");
  let messages = $state([]);
  let pending = $state(null); // openstaand voorstel-bericht
  let draft = $state("");
  let typedCount = $state("");
  let busy = $state(false); // beurt onderweg
  let acting = $state(false); // confirm/cancel onderweg
  let error = $state("");
  let listEl = $state(null);

  const scopeKey = $derived(scope === "global" ? null : project);
  const proposal = $derived(pending?.proposal ?? null);
  const requiresTyped = $derived(needsTypedConfirm(proposal));
  const canConfirm = $derived(
    !requiresTyped || typedCountValid(proposal, typedCount),
  );
  const previews = $derived(
    (proposal?.preview ?? []).map((c) => summarizePreview(c)),
  );

  const VERB_LABEL = $derived({
    archive: $t("triage.verb.archive"),
    restore: $t("triage.verb.restore"),
    set_state: $t("triage.verb.set_state"),
    set_priority: $t("triage.verb.set_priority"),
    set_assignee: $t("triage.verb.set_assignee"),
    add_label: $t("triage.verb.add_label"),
    remove_label: $t("triage.verb.remove_label"),
    set_milestone: $t("triage.verb.set_milestone"),
    add_relation: $t("triage.verb.add_relation"),
    create_item: $t("triage.verb.create_item"),
  });

  async function scrollDown() {
    await tick();
    if (listEl) listEl.scrollTop = listEl.scrollHeight;
  }

  async function load() {
    error = "";
    try {
      const s = await api.triageChat(scopeKey);
      messages = s.messages;
      pending = s.pending;
      scrollDown();
    } catch (e) {
      error = $t("triage.loadFailed");
    }
  }

  $effect(() => {
    scope; // herlaad bij scope-wissel
    typedCount = "";
    load();
  });

  async function send() {
    const msg = draft.trim();
    if (!msg || busy) return;
    busy = true;
    error = "";
    draft = "";
    try {
      const res = await api.sendTriageChat(scopeKey, msg);
      // de beurt geeft alleen het antwoord terug; herlaad de hele thread.
      await load();
      if (res.kind === "proposal") typedCount = "";
    } catch (e) {
      error = e.message;
      draft = msg; // terugzetten zodat de mens niet opnieuw hoeft te typen
    } finally {
      busy = false;
    }
  }

  async function confirmProposal() {
    if (!pending || acting || !canConfirm) return;
    acting = true;
    error = "";
    try {
      await api.confirmTriageChat(
        pending.id,
        requiresTyped ? Number(typedCount) : undefined,
      );
      typedCount = "";
      await load();
    } catch (e) {
      // bulk-rem: server kan alsnog 'confirmation_required' teruggeven
      if (e.detail && e.detail.error === "confirmation_required") {
        error = $t("triage.exactCount", {count: e.detail.total});
      } else {
        error = e.message;
      }
    } finally {
      acting = false;
    }
  }

  async function cancelProposal() {
    if (!pending || acting) return;
    acting = true;
    error = "";
    try {
      await api.cancelTriageChat(pending.id);
      await load();
    } catch (e) {
      error = e.message;
    } finally {
      acting = false;
    }
  }

  async function newConversation() {
    if (busy || acting) return;
    busy = true;
    error = "";
    try {
      const s = await api.archiveTriageChat(scopeKey);
      messages = s.messages;
      pending = s.pending;
      typedCount = "";
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }
</script>

<DrawerDialog label={$t("triage.title")} width="min(560px, 100%)" onclose={() => onclose?.()}>
  <div class="chat-panel">
    <header class="chat-head">
      <span class="chat-title"><MessageSquare size={18} /> {$t("triage.title")}</span>
      <div class="chat-head-actions">
        <button class="ghost-btn" onclick={newConversation} disabled={busy || acting} title={$t("triage.new")}>
          <Plus size={15} /> {$t("triage.new")}
        </button>
        <button class="icon-btn" title={$t("common.close")} onclick={() => onclose?.()}><X size={19} /></button>
      </div>
    </header>

    {#if project}
      <div class="scope">
        <SegmentedControl
          variant="pill"
          ariaLabel={$t("triage.scope")}
          value={scope}
          onchange={(v) => (scope = v)}
          options={[
            { value: "global", label: $t("triage.global") },
            { value: "project", label: projectName || project },
          ]}
        />
      </div>
    {/if}

    <ErrorNote message={error} onRetry={load} />

    <div class="chat-list" bind:this={listEl}>
      {#each messages as m (m.id)}
        <div class="msg" class:user={m.role === "user"} class:assistant={m.role === "assistant"}>
          <div class="msg-body">{@html renderMarkdown(m.body_md)}</div>
        </div>
      {:else}
        <EmptyState
          icon={MessageSquare}
          title={$t("triage.ask")}
          description={$t("triage.example")}
        />
      {/each}
      {#if busy}<p class="muted chat-thinking">{$t("triage.thinking")}</p>{/if}
    </div>

    {#if proposal}
      <div class="proposal" role="group" aria-label={$t("triage.proposal")}>
        <div class="proposal-summary">{proposal.summary}</div>
        <ul class="proposal-cmds">
          {#each previews as p}
            <li>
              <span class="cmd-verb">{VERB_LABEL[p.verb] ?? p.verb}</span>
              {#if p.detail}
                <span class="cmd-detail">{p.detail}</span>
              {:else}
                <span class="cmd-count">{p.count} item{p.count === 1 ? "" : "s"}</span>
                <span class="cmd-refs">
                  {#each p.shown as ref}
                    <button class="ref-chip" onclick={() => onopenref?.(ref)}>{ref}</button>
                  {/each}
                  {#if p.hidden}<span class="cmd-more">+{p.hidden}</span>{/if}
                </span>
              {/if}
            </li>
          {/each}
        </ul>
        {#if requiresTyped}
          <label class="brake">
            {$t("triage.confirmCount", {count: proposal.total_count})}
            <input class="brake-input" type="text" inputmode="numeric" bind:value={typedCount} aria-label={$t("triage.countLabel")} />
          </label>
        {/if}
        <div class="proposal-actions">
          <button class="primary" onclick={confirmProposal} disabled={acting || !canConfirm}>{$t("triage.confirm")}</button>
          <button class="ghost-btn" onclick={cancelProposal} disabled={acting}>{$t("triage.cancel")}</button>
        </div>
      </div>
    {/if}

    <div class="chat-input">
      <AutoTextarea
        bind:value={draft}
        onsubmit={send}
        placeholder={$t("triage.message")}
        rows="2"
        disabled={busy}
        aria-label={$t("triage.inputLabel")}
      />
      <button class="icon-btn send" onclick={send} disabled={busy || !draft.trim()} title={$t("triage.send")} aria-label={$t("triage.send")}>
        <Send size={18} />
      </button>
    </div>
  </div>
</DrawerDialog>

<style>
  .chat-panel {
    display: flex;
    flex-direction: column;
    /* Breedte staat nu op de DrawerDialog-content (BETON-172). */
    width: 100%;
  }
  .chat-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border);
  }
  .chat-title {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 600;
  }
  .chat-head-actions {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }
  .scope {
    display: flex;
    margin: 0.6rem 0;
  }
  .chat-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 0.75rem 0;
    min-height: 0;
  }
  .msg {
    max-width: 85%;
    padding: 0.5rem 0.75rem;
    border-radius: 12px;
    font-size: 0.92rem;
    line-height: 1.45;
  }
  .msg.user {
    align-self: flex-end;
    background: var(--accent);
    color: var(--accent-contrast, #fff);
  }
  .msg.assistant {
    align-self: flex-start;
    background: var(--surface-2, var(--surface));
    border: 1px solid var(--border);
  }
  .msg-body :global(p) {
    margin: 0.2rem 0;
  }
  .chat-thinking {
    align-self: center;
    text-align: center;
    padding: 0.5rem 1rem;
  }
  .proposal {
    border: 1px solid var(--accent);
    border-radius: 12px;
    padding: 0.75rem;
    margin-bottom: 0.6rem;
    background: var(--surface-2, var(--surface));
  }
  .proposal-summary {
    font-weight: 600;
    margin-bottom: 0.5rem;
  }
  .proposal-cmds {
    list-style: none;
    margin: 0 0 0.5rem;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .proposal-cmds li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
  }
  .cmd-verb {
    font-weight: 600;
    font-size: 0.85rem;
  }
  .cmd-count {
    color: var(--text-muted);
    font-size: 0.82rem;
  }
  .cmd-refs {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  .ref-chip {
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    padding: 0.05rem 0.35rem;
    font-size: 0.78rem;
    cursor: pointer;
    color: var(--accent);
  }
  .cmd-more,
  .cmd-detail {
    color: var(--text-muted);
    font-size: 0.82rem;
  }
  .brake {
    display: block;
    font-size: 0.85rem;
    margin-bottom: 0.5rem;
  }
  .brake-input {
    width: 5rem;
    margin-left: 0.4rem;
    padding: 0.2rem 0.4rem;
    border: 1px solid var(--border-strong, var(--border));
    border-radius: 6px;
    background: var(--surface);
    color: inherit;
  }
  .proposal-actions {
    display: flex;
    gap: 0.5rem;
  }
  .chat-input {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
    padding-top: 0.6rem;
    border-top: 1px solid var(--border);
  }
  .chat-input :global(textarea) {
    flex: 1;
    padding: 0.5rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: inherit;
    font: inherit;
  }
  .send {
    align-self: stretch;
  }
  /* Gewone actie (BETON-418): rand, vlak, tekst en :disabled uit de globale
     button-regel. De rand stond op --border (1,28 donker) en de tekst op
     --text-muted, een token dat niet bestaat. Hier alleen de maat. */
  .ghost-btn {
    gap: 0.3rem;
    padding: 0.3rem 0.6rem;
    border-radius: 8px;
    font-size: 0.85rem;
  }
</style>
