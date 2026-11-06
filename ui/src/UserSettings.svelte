<script>
  import { t, locale } from "./lib/i18n.js";
  // Eigen instellingen-paneel (BETON-173): de ingelogde user beheert zijn eigen
  // webhook/telegram/subscribe/omschrijving via GET/PATCH /users/me/settings.
  // Het webhook_secret is write-only (de server geeft het nooit terug) —
  // has_webhook_secret zegt alleen òf er één staat.
  import { api } from "./api.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import Avatar from "./Avatar.svelte";
  import ErrorNote from "./ErrorNote.svelte";
  import Skeleton from "./Skeleton.svelte";
  import ModelClasses from "./ModelClasses.svelte";
  import {
    validateWebhookUrl,
    buildSettingsPatch,
    hasChanges,
  } from "./lib/userSettings.js";
  import { readPersisted, writePersisted } from "./lib/viewState.js";
  import { NOTIFY_STORAGE_KEY } from "./lib/notifications.js";
  import { ArrowLeft, Check, Webhook, Eye, EyeOff, Send, Info, Bell } from "@lucide/svelte";

  let { me, onback } = $props();

  // Browser-meldingen (BETON-368): puur client-side, geen serverveld — de
  // voorkeur staat in localStorage (spiegelt readPersisted/writePersisted uit
  // lib/viewState.js) en de browserpermissie zelf leeft in de browser, niet
  // op de server. Los van het onder liggende opslaan-flow (draft/base).
  let notifyEnabled = $state(
    readPersisted(NOTIFY_STORAGE_KEY, (v) => v === "1" || v === "0", "0") === "1",
  );
  let notifyPermission = $state(
    typeof Notification !== "undefined" ? Notification.permission : "denied",
  );

  async function toggleNotify() {
    if (!notifyEnabled) {
      // Aanzetten vanuit een expliciet klik-gebaar — de browser vraagt
      // permissie hier pas voor het eerst, nooit ongevraagd bij het laden
      // van de pagina.
      if (typeof Notification !== "undefined" && notifyPermission !== "granted") {
        try {
          notifyPermission = await Notification.requestPermission();
        } catch {
          notifyPermission = "denied";
        }
      }
      if (notifyPermission !== "granted") return; // geweigerd/genegeerd: niet aanzetten
    }
    notifyEnabled = !notifyEnabled;
    writePersisted(NOTIFY_STORAGE_KEY, notifyEnabled ? "1" : "0");
  }

  let error = $state("");
  let saved = $state(false);
  let busy = $state(false);
  let loaded = $state(false);
  let showSecret = $state(false);
  let hasSecret = $state(false); // has_webhook_secret uit de server

  // Baseline waartegen we wijzigingen bepalen. Alle velden — inclusief
  // description — komen vers uit GET /users/me/settings, zodat het paneel na
  // sluiten/heropenen niet op het bij login geladen `me`-object leunt.
  let base = $state({
    webhook_url: null,
    telegram_chat_id: null,
    description: null,
    subscribe_all: false,
  });
  let draft = $state({
    webhook_url: "",
    webhook_secret: "",
    telegram_chat_id: "",
    description: "",
    subscribe_all: false,
  });

  function norm(v) {
    const t = (v || "").trim();
    return t ? t : null;
  }

  async function load() {
    error = "";
    try {
      const s = await api.meSettings();
      hasSecret = Boolean(s.has_webhook_secret);
      base = {
        webhook_url: s.webhook_url ?? null,
        telegram_chat_id: s.telegram_chat_id ?? null,
        description: norm(s.description),
        subscribe_all: Boolean(s.subscribe_all),
      };
      draft = {
        webhook_url: s.webhook_url || "",
        webhook_secret: "",
        telegram_chat_id: s.telegram_chat_id || "",
        description: s.description || "",
        subscribe_all: Boolean(s.subscribe_all),
      };
      loaded = true;
    } catch (e) {
      error = $t("preferences.loadFailed");
    }
  }
  $effect(() => {
    load();
  });

  let dirty = $derived(loaded && hasChanges(draft, base));

  async function save() {
    error = "";
    saved = false;
    const urlErr = validateWebhookUrl(draft.webhook_url, $locale);
    if (urlErr) {
      error = urlErr;
      return;
    }
    const body = buildSettingsPatch(draft, base);
    if (!Object.keys(body).length) return;
    busy = true;
    try {
      const s = await api.updateMeSettings(body);
      // Herijk de baseline op de verse serverwaarden.
      hasSecret = Boolean(s.has_webhook_secret);
      base = {
        webhook_url: s.webhook_url ?? null,
        telegram_chat_id: s.telegram_chat_id ?? null,
        description: norm(s.description),
        subscribe_all: Boolean(s.subscribe_all),
      };
      draft.webhook_secret = "";
      draft.webhook_url = s.webhook_url || "";
      draft.telegram_chat_id = s.telegram_chat_id || "";
      draft.description = s.description || "";
      draft.subscribe_all = Boolean(s.subscribe_all);
      saved = true;
      setTimeout(() => (saved = false), 1800);
    } catch (e) {
      error = e.message;
    }
    busy = false;
  }
</script>

<div class="us">
  <header class="us-top">
    <button class="icon-btn" title={$t("drawer.back")} onclick={() => onback?.()}><ArrowLeft size={18} /></button>
    <h3 class="us-title">{$t("nav.mySettings")}</h3>
  </header>

  {#if me}
    <div class="us-id">
      <Avatar handle={me.handle} avatarUrl={me.avatar_url} size={34} />
      <div class="us-id-main">
        <div class="us-name">{me.display_name}</div>
        <div class="us-handle">@{me.handle}</div>
      </div>
    </div>
  {/if}

  <ErrorNote message={error} onRetry={load} />

  {#if loaded}
    <!-- Omschrijving -->
    <section class="us-sec">
      <div class="us-head"><Info size={14} /> {$t("ticket.description")}</div>
      <span class="us-note">{$t("preferences.descriptionNote")}</span>
      <AutoTextarea rows="2" bind:value={draft.description} placeholder={$t("preferences.descriptionHint")} onsubmit={() => { if (dirty && !busy) save(); }} />
    </section>

    <!-- Webhook -->
    <section class="us-sec">
      <div class="us-head"><Webhook size={14} /> Webhook</div>
      <span class="us-note">
        {$t("preferences.webhookNote")}
      </span>
      <label class="us-field">{$t("agents.webhookUrl")}
        <input placeholder="https://receiver.example.org/events" bind:value={draft.webhook_url} />
      </label>
      <label class="us-field">{$t("preferences.webhookSecret")}
        <span class="secret-row">
          <input
            type={showSecret ? "text" : "password"}
            placeholder={$t(hasSecret ? "preferences.keepSecret" : "preferences.optionalSecret")}
            bind:value={draft.webhook_secret}
            autocomplete="off"
          />
          <button
            type="button"
            class="icon-btn sm"
            title={$t(showSecret ? "preferences.hide" : "preferences.show")}
            aria-label={$t(showSecret ? "preferences.hideSecret" : "preferences.showSecret")}
            onclick={() => (showSecret = !showSecret)}
          >
            {#if showSecret}<EyeOff size={15} />{:else}<Eye size={15} />{/if}
          </button>
        </span>
      </label>
      <span class="us-hint">
        {$t("preferences.secretNeverReturned")} {$t(hasSecret ? "preferences.secretSet" : "preferences.secretUnset")}
      </span>
    </section>

    <!-- Telegram -->
    <section class="us-sec">
      <div class="us-head"><Send size={14} /> Telegram</div>
      <span class="us-note">{$t("preferences.telegramNote")}</span>
      <label class="us-field">{$t("preferences.chatId")}
        <input placeholder="123456789" bind:value={draft.telegram_chat_id} />
      </label>
    </section>

    <!-- Subscribe all -->
    <section class="us-sec">
      <div class="us-head">{$t("preferences.followAll")}</div>
      <div class="us-row">
        <span class="us-note">
          {$t("preferences.followAllNote")}
        </span>
        <button
          class="switch"
          class:on={draft.subscribe_all}
          role="switch"
          aria-checked={draft.subscribe_all}
          aria-label={$t("preferences.followAll")}
          onclick={() => (draft.subscribe_all = !draft.subscribe_all)}
        >
          <span class="knob"></span>
        </button>
      </div>
    </section>

    <!-- Browser-meldingen (BETON-368) -->
    <section class="us-sec">
      <div class="us-head"><Bell size={14} /> {$t("preferences.browserNotifications")}</div>
      <div class="us-row">
        <span class="us-note">
          {$t("preferences.browserNote")}
          {#if notifyPermission === "denied"}
            {$t("preferences.browserDenied")}
          {/if}
        </span>
        <button
          class="switch"
          class:on={notifyEnabled}
          role="switch"
          aria-checked={notifyEnabled}
          aria-label={$t("preferences.browserNotifications")}
          disabled={notifyPermission === "denied" && !notifyEnabled}
          onclick={toggleNotify}
        >
          <span class="knob"></span>
        </button>
      </div>
    </section>

    {#if me?.kind === "human"}<ModelClasses />{/if}

    <div class="us-actions">
      <button class="primary sm" onclick={save} disabled={!dirty || busy}>
        <Check size={14} /> {$t("common.save")}
      </button>
      {#if saved}<span class="us-ok">{$t("common.saved")}</span>{/if}
    </div>
  {:else if !error}
    <div class="us-loading"><Skeleton preset="lines" count={5} /></div>
  {/if}
</div>

<style>
  .us-top {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }
  .us-title {
    font-size: var(--text-lg);
    font-weight: 600;
    margin: 0;
  }
  .us-id {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 0 12px;
  }
  .us-loading {
    padding: 14px 0;
  }
  .us-name {
    font-weight: 600;
  }
  .us-handle {
    font-size: var(--text-base);
    color: var(--text-tertiary);
  }
  .us-sec {
    padding: 14px 0;
    border-top: 1px solid var(--border);
  }
  .us-head {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-sm);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
    margin-bottom: 8px;
  }
  .us-note {
    display: block;
    font-size: var(--text-base);
    color: var(--text-secondary);
    line-height: 1.4;
    flex: 1;
  }
  .us-hint {
    display: block;
    font-size: var(--text-sm);
    color: var(--text-tertiary);
    margin-top: 6px;
    line-height: 1.4;
  }
  .us-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    margin-top: 10px;
  }
  .us-field input {
    width: 100%;
  }
  .us-sec :global(textarea) {
    width: 100%;
    margin-top: 8px;
  }
  .secret-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .secret-row input {
    flex: 1;
    min-width: 0;
  }
  .us-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .us-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
    margin-top: 4px;
  }
  .us-ok {
    font-size: var(--text-base);
    color: var(--success);
  }
  /* Toggle-switch (zelfde vorm als ProjectSettings). */
  .switch {
    flex: 0 0 auto;
    width: 42px;
    height: 24px;
    min-height: 0;
    padding: 0;
    border-radius: var(--radius-full);
    background: var(--surface-3);
    border: 1px solid var(--border-strong);
    position: relative;
    transition: background var(--dur-fast) var(--ease);
  }
  .switch .knob {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--surface);
    box-shadow: var(--shadow-sm);
    transition: transform var(--dur-fast) var(--ease);
  }
  .switch.on {
    background: var(--accent);
    border-color: var(--accent);
  }
  .switch.on .knob {
    transform: translateX(18px);
  }
</style>
