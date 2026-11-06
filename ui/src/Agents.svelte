<script>
  import { onMount } from "svelte";
  import { t, locale } from "./lib/i18n.js";
  import WebhookTest from "./WebhookTest.svelte";
  import CredentialPolicy from "./CredentialPolicy.svelte";
  import { api } from "./api.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import Avatar from "./Avatar.svelte";
  import SectionHead from "./SectionHead.svelte";
  import ErrorNote from "./ErrorNote.svelte";
  import Skeleton from "./Skeleton.svelte";
  import EmptyState from "./EmptyState.svelte";
  import { AGENT_TYPES, showsAgentType, showsWebhookFields } from "./lib/agentType.js";
  import Select from "./Select.svelte";
  import { webhookDot } from "./lib/inbox.js";
  import { formatTimestamp, absoluteTime } from "./lib/board.js";
  import {
    ArrowLeft,
    Plus,
    Trash2,
    Check,
    Copy,
    Bot,
    User,
    RotateCcw,
    ImageUp,
    ImageOff,
    Webhook,
    Pencil,
    KeyRound,
  } from "@lucide/svelte";

  let { onback, canTestWebhooks = false, ondeliveries } = $props();

  let error = $state("");
  let loading = $state(false);
  let users = $state([]);
  let health = $state({}); // handle → webhook-health (BETON-457)
  let editing = $state(null); // handle in bewerk-modus
  let draft = $state({
    display_name: "",
    description: "",
    kind: "agent",
    active: true,
    agent_type: "",
    webhook_url: "",
    webhook_secret: "",
    has_webhook: false,
  });

  // Aanmaken.
  let creating = $state(false);
  let newUser = $state({
    handle: "",
    display_name: "",
    kind: "agent",
    description: "",
    agent_type: "",
    webhook_url: "",
    webhook_secret: "",
  });
  let createdKey = $state(""); // ruwe key, één keer getoond na create
  let createdHandle = $state("");
  let keyEvent = $state("created");
  let copied = $state(false);
  let confirmAction = $state(null); // {handle, type: 'rotate'|'deactivate'} van open bevestiging

  async function load() {
    error = "";
    loading = !users.length;
    try {
      users = await api.users();
      // Statusbolletje (BETON-457): mens-only endpoint; zonder uitkomst geen bolletje.
      health = Object.fromEntries(
        (await api.webhookHealth().catch(() => [])).map((h) => [h.handle, h])
      );
    } catch (e) {
      error = $t("agents.loadFailed");
    } finally {
      loading = false;
    }
  }
  onMount(() => {
    load();
  });

  let guarding = false; // Cmd+Enter twee keer snel mag niet dubbel versturen (BETON-462)
  async function guard(fn) {
    if (guarding) return;
    guarding = true;
    error = "";
    try {
      await fn();
    } catch (e) {
      error = e.message;
    } finally {
      guarding = false;
    }
  }

  async function startEdit(u) {
    editing = u.handle;
    draft = {
      display_name: u.display_name,
      description: u.description || "",
      kind: u.kind,
      active: u.active,
      agent_type: u.agent_type || "",
      // De URL is geen geheim en wordt hieronder voorgevuld via getUser()
      // (BETON-113). Het secret blijft write-only — de server geeft 'm nooit
      // terug, dus dat veld start altijd leeg; laten staan = ongemoeid.
      webhook_url: "",
      webhook_secret: "",
      has_webhook: u.has_webhook,
    };
    if (u.has_webhook) {
      await guard(async () => {
        const detail = await api.getUser(u.handle);
        // Alleen toepassen als het formulier nog steeds deze user bewerkt
        // (niet ondertussen gesloten of naar een andere user gewisseld).
        if (editing === u.handle) draft.webhook_url = detail.webhook_url || "";
      });
    }
  }

  async function saveEdit(handle) {
    await guard(async () => {
      const body = {
        display_name: draft.display_name,
        description: draft.description,
        kind: draft.kind,
        active: draft.active,
        agent_type: draft.kind === "agent" ? draft.agent_type || null : null,
      };
      // Alleen meesturen als er iets is ingevuld — anders overschrijft een
      // PATCH van andere velden per ongeluk een bestaande webhook (de
      // backend gebruikt exclude_unset, dus weglaten = ongemoeid laten).
      if (draft.webhook_url.trim()) body.webhook_url = draft.webhook_url.trim();
      if (draft.webhook_secret.trim()) body.webhook_secret = draft.webhook_secret.trim();
      await api.updateUser(handle, body);
      editing = null;
      await load();
    });
  }

  async function removeWebhook(handle) {
    await guard(async () => {
      await api.updateUser(handle, { webhook_url: null, webhook_secret: null });
      draft.has_webhook = false;
      draft.webhook_url = "";
      draft.webhook_secret = "";
      await load();
    });
  }

  async function deactivate(handle) {
    confirmAction = null;
    await guard(async () => {
      await api.deleteUser(handle);
      await load();
    });
  }

  async function reactivate(handle) {
    await guard(async () => {
      await api.updateUser(handle, { active: true });
      await load();
    });
  }

  async function createUser() {
    const handle = newUser.handle.trim().replace(/^@/, "");
    const display_name = newUser.display_name.trim();
    if (!handle || !display_name) return;
    await guard(async () => {
      const body = {
        handle,
        display_name,
        kind: newUser.kind,
        description: newUser.description.trim() || null,
        agent_type: newUser.kind === "agent" ? newUser.agent_type || null : null,
      };
      if (newUser.webhook_url.trim()) body.webhook_url = newUser.webhook_url.trim();
      if (newUser.webhook_secret.trim()) body.webhook_secret = newUser.webhook_secret.trim();
      const created = await api.createUser(body);
      createdKey = created.api_key;
      createdHandle = created.handle;
      keyEvent = "created";
      copied = false;
      newUser = {
        handle: "",
        display_name: "",
        kind: "agent",
        description: "",
        agent_type: "",
        webhook_url: "",
        webhook_secret: "",
      };
      creating = false;
      await load();
    });
  }

  async function rotateKey(handle) {
    confirmAction = null;
    await guard(async () => {
      const rotated = await api.rotateUserKey(handle);
      createdKey = rotated.api_key;
      createdHandle = rotated.handle;
      keyEvent = "rotated";
      copied = false;
      await load();
    });
  }

  async function uploadAvatar(handle, event) {
    const file = event.target?.files?.[0];
    event.target.value = ""; // reset zodat dezelfde file opnieuw kan
    if (!file) return;
    await guard(async () => {
      await api.uploadAvatar(handle, file);
      await load();
    });
  }

  async function removeAvatar(handle) {
    await guard(async () => {
      await api.deleteAvatar(handle);
      await load();
    });
  }

  async function copyKey() {
    try {
      await navigator.clipboard.writeText(createdKey);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      /* clipboard geweigerd — de key staat zichtbaar, gebruiker kan zelf kopiëren */
    }
  }
</script>

<div class="ag">
  <header class="ag-top">
    <button class="icon-btn" title={$t("common.back")} onclick={() => onback?.()}><ArrowLeft size={18} /></button>
    <h3 class="ag-title"><Bot size={18} /> {$t("agents.title")}</h3>
    {#if !creating}
      <button class="primary sm ag-newbtn" onclick={() => { creating = true; createdKey = ""; keyEvent = "created"; }}>
        <Plus size={14} /> {$t("common.new")}
      </button>
    {/if}
  </header>
  <ErrorNote message={error} onRetry={load} />

  <!-- Ruwe key één keer tonen na create -->
  {#if createdKey}
    <div class="key-box" role="status">
      <div class="key-head">
        <Check size={15} />
        @{createdHandle} {$t(keyEvent === "rotated" ? "agents.rotated" : "agents.created")}
      </div>
      <p class="key-note">
        {$t("agents.keyNote")}
        {#if keyEvent === "rotated"}
          {$t("agents.oldKey")}
        {:else}
          {$t("agents.useKey")}
        {/if}
      </p>
      <div class="key-row">
        <code class="key-val">{createdKey}</code>
        <button class="sm" onclick={copyKey}>
          <Copy size={14} /> {$t(copied ? "common.copied" : "common.copy")}
        </button>
      </div>
      <button class="ghost sm" onclick={() => (createdKey = "")}>{$t("common.close")}</button>
    </div>
  {/if}

  <!-- Aanmaak-formulier -->
  {#if creating}
    <section class="ag-sec ag-create">
      <SectionHead>{$t("agents.new")}</SectionHead>
      <div class="form-grid">
        <label>Handle<input placeholder="worker" bind:value={newUser.handle} /></label>
        <label>{$t("agents.name")}<input placeholder={$t("agents.displayName")} bind:value={newUser.display_name} /></label>
        <label>{$t("agents.kind")}
          <Select
            bind:value={newUser.kind}
            options={[{ value: "agent", label: $t("agents.kindAgent") }, { value: "human", label: $t("agents.kindHuman") }]}
            onchange={() => (newUser.agent_type = "")}
          />
        </label>
        {#if showsAgentType(newUser.kind)}
          <label>{$t("agents.type")}
            <Select bind:value={newUser.agent_type} options={[{ value: "", label: "—" }, ...AGENT_TYPES.map((value) => ({ value, label: $t("agents.type." + value) }))]} />
          </label>
        {/if}
      </div>
      <label class="full">{$t("agents.expertise")}
        <AutoTextarea rows="2" placeholder={$t("agents.expertiseHint")}
                  bind:value={newUser.description} onsubmit={createUser} />
      </label>
      {#if showsWebhookFields(newUser.kind, newUser.agent_type)}
        <div class="webhook-fields">
          <p class="webhook-hint">
            {$t("agents.webhookHint")}
          </p>
          <div class="form-grid">
            <label>{$t("agents.webhookUrl")}
              <input placeholder="https://agent.example.org/events" bind:value={newUser.webhook_url} />
            </label>
            <label>{$t("agents.webhookSecret")}
              <input type="password" autocomplete="off" placeholder={$t("agents.hmac")} bind:value={newUser.webhook_secret} />
            </label>
          </div>
        </div>
      {/if}
      <div class="form-actions">
        <button class="primary sm" onclick={createUser}
                disabled={!newUser.handle.trim() || !newUser.display_name.trim()}>
          <Plus size={14} /> {$t("common.create")}
        </button>
        <button class="ghost sm" onclick={() => (creating = false)}>{$t("common.cancel")}</button>
      </div>
    </section>
  {/if}

  <!-- Lijst -->
  <section class="ag-sec">
    {#if loading}
      <Skeleton preset="card" count={3} />
    {:else if !users.length}
      <EmptyState icon={Bot} title={$t("agents.none")} />
    {/if}
    {#each users as u (u.handle)}
      <div class="ag-item" class:inactive={!u.active}>
        {#if editing === u.handle}
          <div class="ag-edit">
            <div class="form-grid">
              <label>{$t("agents.name")}<input bind:value={draft.display_name} /></label>
              <label>{$t("agents.kind")}
                <Select
                  bind:value={draft.kind}
                  options={[{ value: "agent", label: $t("agents.kindAgent") }, { value: "human", label: $t("agents.kindHuman") }]}
                  onchange={() => (draft.agent_type = "")}
                />
              </label>
              {#if showsAgentType(draft.kind)}
                <label>{$t("agents.type")}
                  <Select bind:value={draft.agent_type} options={[{ value: "", label: "—" }, ...AGENT_TYPES.map((value) => ({ value, label: $t("agents.type." + value) }))]} />
                </label>
              {/if}
              <label class="check-lbl"><input type="checkbox" bind:checked={draft.active} /> {$t("agents.active")}</label>
            </div>
            <label class="full">{$t("agents.expertise")}
              <AutoTextarea rows="2" bind:value={draft.description} onsubmit={() => saveEdit(u.handle)} />
            </label>
            {#if showsWebhookFields(draft.kind, draft.agent_type)}
              <div class="webhook-fields">
                <p class="webhook-hint">
                  {$t("agents.webhookHint")}
                  {#if draft.has_webhook}
                    {$t("agents.secretKeep")}
                  {/if}
                </p>
                <div class="form-grid">
                  <label>{$t("agents.webhookUrl")}
                    <input placeholder="https://agent.example.org/events" bind:value={draft.webhook_url} />
                  </label>
                  <label>{$t("agents.webhookSecret")}
                    <input type="password" autocomplete="off" placeholder={$t("agents.hmac")} bind:value={draft.webhook_secret} />
                  </label>
                </div>
                {#if draft.has_webhook}
                  <button class="ghost sm danger-quiet" onclick={() => removeWebhook(u.handle)}>
                    <Trash2 size={14} /> {$t("agents.removeWebhook")}
                  </button>
                {/if}
              </div>
            {/if}
            {#if u.kind === "agent"}<CredentialPolicy handle={u.handle} />{/if}
            <div class="form-actions">
              <button class="primary sm" onclick={() => saveEdit(u.handle)}><Check size={14} /> {$t("common.save")}</button>
              <button class="ghost sm" onclick={() => (editing = null)}>{$t("common.cancel")}</button>
            </div>
          </div>
        {:else}
          <Avatar handle={u.handle} avatarUrl={u.avatar_url} size={30} />
          <div class="ag-main">
            <div class="ag-name">
              {u.display_name}
              <span class="ag-handle">@{u.handle}</span>
              <span class="ag-kind"
                    class:ag-kind-coding={u.agent_type === "coding"}
                    class:ag-kind-hermes={u.agent_type === "hermes"}>
                {#if u.kind === "human"}<User size={12} />{:else}<Bot size={12} />{/if}
                {u.kind === "human" ? $t("agents.kindHuman") : u.agent_type ? $t("agents.type." + u.agent_type) : $t("agents.kindAgent")}
              </span>
              {#if u.has_webhook}
                {@const h = health[u.handle]}
                {@const dot = webhookDot(h)}
                <span class="ag-webhook" title={$t("agents.hasWebhook")}><Webhook size={12} /></span>
                {#if dot}
                  <span
                    class="ag-dot ag-dot-{dot}"
                    title={h.unreachable
                      ? $t("agents.unreachable", {count: h.failed_count}) + (h.last_delivered_at ? ", " + $t("agents.lastSuccess", {time: absoluteTime(h.last_delivered_at, $locale)}) : ", " + $t("agents.neverSuccess"))
                      : h.last_delivered_at ? $t("agents.lastSuccess", {time: formatTimestamp(h.last_delivered_at, Date.now(), $locale)}) : $t("agents.noTraffic")}
                  ></span>
                  {#if h.last_delivered_at}<span class="ag-last">{$t("agents.lastDelivery", {time: formatTimestamp(h.last_delivered_at, Date.now(), $locale)})}</span>{/if}
                {/if}
              {/if}
              {#if !u.active}<span class="ag-badge">{$t("agents.inactive")}</span>{/if}
            </div>
            {#if u.description}
              <div class="ag-desc">{u.description}</div>
            {:else}
              <div class="ag-desc muted">{$t("agents.noDescription")}</div>
            {/if}
            {#if canTestWebhooks && u.kind === "agent" && !u.is_virtual && u.has_webhook}
              <WebhookTest user={u} {ondeliveries} />
            {/if}
          </div>
          {#if confirmAction?.handle === u.handle && confirmAction.type === "rotate"}
            <span class="ag-confirm">
              {$t("agents.rotateConfirm", {handle: u.handle})}
              <span class="ag-confirm-actions">
                <button class="primary sm" onclick={() => rotateKey(u.handle)}>{$t("agents.yesRotate")}</button>
                <button class="sm" onclick={() => (confirmAction = null)}>{$t("common.cancel")}</button>
              </span>
            </span>
          {:else if confirmAction?.handle === u.handle && confirmAction.type === "deactivate"}
            <span class="ag-confirm">
              {$t("agents.deactivateConfirm", {handle: u.handle})}
              <span class="ag-confirm-actions">
                <button class="primary sm" onclick={() => deactivate(u.handle)}>{$t("agents.yesDeactivate")}</button>
                <button class="sm" onclick={() => (confirmAction = null)}>{$t("common.cancel")}</button>
              </span>
            </span>
          {:else}
            <span class="ag-actions">
              <label class="icon-btn sm avatar-up" title={$t("agents.uploadAvatar")}>
                <ImageUp size={15} />
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  onchange={(e) => uploadAvatar(u.handle, e)}
                />
              </label>
              {#if u.avatar_url}
                <button class="icon-btn sm" title={$t("agents.removeAvatar")} onclick={() => removeAvatar(u.handle)}>
                  <ImageOff size={15} />
                </button>
              {/if}
              <button class="icon-btn sm" title={$t("common.edit")} onclick={() => startEdit(u)}>
                <Pencil size={15} />
              </button>
              <button class="icon-btn sm" title={$t("agents.rotate")}
                      onclick={() => (confirmAction = { handle: u.handle, type: "rotate" })}>
                <KeyRound size={15} />
              </button>
              {#if u.active}
                <button class="icon-btn sm" title={$t("agents.deactivate")}
                        onclick={() => (confirmAction = { handle: u.handle, type: "deactivate" })}>
                  <Trash2 size={15} />
                </button>
              {:else}
                <button class="icon-btn sm" title={$t("agents.reactivate")} onclick={() => reactivate(u.handle)}>
                  <RotateCcw size={15} />
                </button>
              {/if}
            </span>
          {/if}
        {/if}
      </div>
    {:else}
      <span class="muted">{$t("agents.noUsers")}</span>
    {/each}
  </section>
</div>

<style>
  .ag-top {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }
  .ag-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-lg);
    font-weight: 600;
    margin: 0;
    flex: 1;
  }
  .ag-newbtn {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
  }
  .ag-sec {
    padding: 12px 0;
    border-top: 1px solid var(--border);
  }
  .ag-item {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }
  .ag-item.inactive {
    opacity: 0.55;
  }
  .ag-main {
    flex: 1;
    min-width: 0;
  }
  .ag-name {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    font-weight: 600;
  }
  .ag-handle {
    font-weight: 400;
    color: var(--text-tertiary);
    font-size: var(--text-base);
  }
  .ag-kind {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: var(--surface-3);
    padding: 1px 7px;
    border-radius: var(--radius-full);
  }
  .ag-badge {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    background: var(--surface-3);
    padding: 1px 7px;
    border-radius: var(--radius-full);
  }
  /* Eén badge (icoon + human/coding/hermes/agent); coding & hermes krijgen een
     eigen kleur, human en type-loze agents blijven neutraal. */
  .ag-kind-coding {
    color: var(--success);
    background: var(--success-soft);
  }
  .ag-kind-hermes {
    color: var(--warning);
    background: color-mix(in srgb, var(--warning) 18%, transparent);
  }
  .ag-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    display: inline-block;
    background: var(--text-tertiary);
  }
  .ag-dot-green { background: var(--success); }
  .ag-dot-amber { background: var(--warning); }
  .ag-dot-red { background: var(--danger); }
  .ag-last {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }
  .ag-webhook {
    display: inline-flex;
    align-items: center;
    color: var(--text-tertiary);
  }
  .webhook-fields {
    border: 1px dashed var(--border);
    border-radius: var(--radius);
    padding: 8px 10px;
    margin-bottom: 8px;
  }
  .webhook-hint {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    margin: 0 0 8px;
    line-height: 1.4;
  }
  .ag-desc {
    font-size: var(--text-base);
    color: var(--text-secondary);
    line-height: 1.4;
    margin-top: 2px;
  }
  .ag-desc.muted {
    font-style: italic;
    color: var(--text-tertiary);
  }
  .ag-actions {
    display: inline-flex;
    gap: 2px;
    flex: 0 0 auto;
  }
  .ag-confirm {
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: flex-end;
    flex: 0 0 auto;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    max-width: 220px;
    text-align: right;
  }
  .ag-confirm-actions {
    display: flex;
    gap: 0.35rem;
  }
  .avatar-up {
    cursor: pointer;
  }
  .avatar-up input[type="file"] {
    display: none;
  }
  .ag-edit,
  .ag-create {
    width: 100%;
  }
  .form-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 8px;
  }
  .form-grid label,
  label.full {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    flex: 1 1 120px;
    min-width: 0;
  }
  label.full {
    display: flex;
  }
  label.full :global(textarea) {
    width: 100%;
  }
  .check-lbl {
    flex-direction: row;
    align-items: center;
    gap: 5px;
    flex: 0 0 auto;
    align-self: flex-end;
    padding-bottom: 8px;
  }
  .form-actions {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }
  /* Ruwe-key-box */
  .key-box {
    border: 1px solid var(--accent);
    border-radius: var(--radius);
    padding: 12px;
    margin: 10px 0;
    background: var(--surface-2);
  }
  .key-head {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    color: var(--success);
    margin-bottom: 4px;
  }
  .key-note {
    font-size: var(--text-base);
    color: var(--text-secondary);
    margin: 0 0 8px;
    line-height: 1.4;
  }
  .key-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }
  .key-val {
    flex: 1;
    min-width: 0;
    overflow-x: auto;
    white-space: nowrap;
    font-family: var(--font-mono, monospace);
    font-size: var(--text-sm);
    background: var(--surface-3);
    padding: 6px 8px;
    border-radius: var(--radius-sm);
  }
</style>
