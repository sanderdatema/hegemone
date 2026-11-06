<script>
  import { setLocale } from "./lib/i18n.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import { api } from "./api.js";
  let { enabled = false, oncomplete = () => {} } = $props();
  let locale = $state("en");
  let busy = $state(false);
  let error = $state("");
  let loginKey = $state("");
  let saved = $state(false);
  const messages = {
    en: { title: "Welcome to Hegemone", intro: "Create your first administrator to start organizing work.", disabled: "Setup is disabled. Ask your server administrator to configure the setup token, then reload this page.", token: "Setup token", handle: "Username", name: "Display name", create: "Create administrator", working: "Creating…", key: "Save your login key", warning: "This key is shown once. Keep it in a password manager so you can sign in again. It is not saved in this browser.", confirm: "I have saved my login key", continue: "Open Hegemone", failed: "Setup failed. Please try again." },
    nl: { title: "Welkom bij Hegemone", intro: "Maak je eerste beheerder aan om taken te organiseren.", disabled: "Installatie staat uit. Vraag je serverbeheerder het setup-token in te stellen en herlaad deze pagina.", token: "Setup-token", handle: "Gebruikersnaam", name: "Weergavenaam", create: "Beheerder aanmaken", working: "Bezig met aanmaken…", key: "Bewaar je login-key", warning: "Deze key wordt één keer getoond. Bewaar hem in een wachtwoordmanager om later opnieuw in te loggen. Hij wordt niet in deze browser opgeslagen.", confirm: "Ik heb mijn login-key bewaard", continue: "Hegemone openen", failed: "Installatie mislukt. Probeer opnieuw." },
  };
  let text = $derived(messages[locale]);
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    busy = true; error = "";
    const form = event.currentTarget;
    const fields = new FormData(form);
    try {
      const data = await api.setup({ handle: fields.get("handle"), display_name: fields.get("display_name"), locale }, fields.get("token"));
      setLocale(locale);
      loginKey = data.api_key;
      form.reset();
    } catch (e) {
      error = e?.message || text.failed;
    } finally { busy = false; }
  }
  function finish() {
    if (!saved) return;
    loginKey = "";
    oncomplete();
  }
</script>

<main class="setup-shell">
  <section class="setup-card" aria-labelledby="setup-title">
    <div class="setup-brand">Hegemone</div>
    <div class="setup-language" aria-label="Language">
      <button type="button" aria-pressed={locale === "en"} onclick={() => locale = "en"}>English</button>
      <button type="button" aria-pressed={locale === "nl"} onclick={() => locale = "nl"}>Nederlands</button>
    </div>
    {#if loginKey}
      <h1 id="setup-title">{text.key}</h1>
      <p>{text.warning}</p>
      <label>{text.key}<AutoTextarea readonly value={loginKey} rows="3" spellcheck="false" aria-label={text.key} /></label>
      <label class="setup-confirm"><input type="checkbox" bind:checked={saved} />{text.confirm}</label>
      <button class="primary" disabled={!saved} onclick={finish}>{text.continue}</button>
    {:else}
      <h1 id="setup-title">{text.title}</h1>
      <p>{text.intro}</p>
      {#if enabled}
        <form onsubmit={submit}>
          <label>{text.token}<input name="token" type="password" required minlength="32" maxlength="256" autocomplete="off" /></label>
          <label>{text.handle}<input name="handle" required maxlength="32" pattern="[A-Za-z0-9][A-Za-z0-9_-]*" autocomplete="username" /></label>
          <label>{text.name}<input name="display_name" required maxlength="100" autocomplete="name" /></label>
          <button class="primary" type="submit" disabled={busy}>{busy ? text.working : text.create}</button>
        </form>
      {:else}
        <p role="status">{text.disabled}</p>
      {/if}
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </section>
</main>

<style>
  .setup-shell { min-height: 100dvh; display: grid; place-items: center; padding: 24px; }
  .setup-card { width: min(100%, 440px); padding: 32px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); }
  .setup-brand { font-size: 14px; font-weight: 700; color: var(--accent); margin-bottom: 16px; }
  .setup-language { display: flex; gap: 8px; margin-bottom: 24px; }
  .setup-language [aria-pressed="true"] { color: var(--accent); font-weight: 700; }
  h1 { font-size: 24px; margin-bottom: 12px; }
  p { color: var(--text-secondary); line-height: 1.6; margin-bottom: 20px; }
  form { display: grid; gap: 16px; }
  label { display: grid; gap: 6px; font-size: 14px; }
  input:not([type="checkbox"]), :global(textarea) { width: 100%; padding: 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: inherit; }
  :global(textarea) { font-family: monospace; resize: vertical; }
  .setup-confirm { display: flex; align-items: start; gap: 10px; margin: 20px 0; }
  .primary { width: 100%; padding: 12px; }
</style>
