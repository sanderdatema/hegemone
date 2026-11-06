<script>
  import { api } from "./api.js";
  import Agents from "./Agents.svelte";
  let { progress, oncomplete = () => {} } = $props();
  let busy = $state(false), error = $state(""), configure = $state(false);
  let nl = $derived(progress.locale === "nl");
  async function create(event) {
    event.preventDefault();
    if (busy) return;
    busy = true; error = "";
    const form = new FormData(event.currentTarget);
    try { progress = await api.onboardingProject({key: form.get("key").toString().toUpperCase(), name: form.get("name")}); }
    catch (e) { error = e.message; }
    finally { busy = false; }
  }
  async function finish() {
    busy = true; error = "";
    try { await api.onboardingComplete(); oncomplete(); }
    catch (e) { error = e.message; }
    finally { busy = false; }
  }
</script>

<main class="onboarding-shell">
  <section class="onboarding-card" aria-labelledby="onboarding-title">
    <div class="brand">Hegemone</div>
    <p class="progress">{nl ? "Aan de slag" : "Getting started"} · {progress.step === "project" ? "1 / 2" : "2 / 2"}</p>
    {#if progress.step === "project"}
      <h1 id="onboarding-title">{nl ? "Maak je eerste project" : "Create your first project"}</h1>
      <p>{nl ? "Groepeer je taken in een project. Je begint met zes kolommen en drie werkklassen." : "Organize your tasks in a project. You start with six columns and three work classes."}</p>
      <form onsubmit={create}>
        <label>{nl ? "Projectnaam" : "Project name"}<input name="name" required maxlength="200" /></label>
        <label>{nl ? "Projectcode" : "Project code"}<input name="key" required pattern={"[A-Za-z0-9]{1,20}"} maxlength="20" placeholder="TEAM" /></label>
        <p>{nl ? "De code verschijnt in ticketnummers, bijvoorbeeld TEAM-1." : "The code appears in ticket numbers, such as TEAM-1."}</p>
        <button class="primary" disabled={busy}>{nl ? "Project aanmaken" : "Create project"}</button>
      </form>
    {:else}
      <h1 id="onboarding-title">{nl ? "Werk samen met agents" : "Work with agents"}</h1>
      <p>{nl ? "Voeg optioneel AI-agents toe. Je kunt Hegemone ook zonder agents gebruiken en ze later instellen." : "Optionally add AI agents. You can use Hegemone without agents and configure them later."}</p>
      {#if configure}
        <Agents canTestWebhooks={true} onback={() => configure = false} />
      {:else}
        <button onclick={() => configure = true}>{nl ? "Agents instellen" : "Configure agents"}</button>
        <button class="primary" disabled={busy} onclick={finish}>{nl ? "Hegemone openen" : "Open Hegemone"}</button>
      {/if}
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </section>
</main>

<style>
  .onboarding-shell { min-height: 100dvh; display: grid; place-items: center; padding: 24px; }
  .onboarding-card { width: min(100%, 620px); padding: 32px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); }
  .brand { color: var(--accent); font-weight: 700; margin-bottom: 16px; }
  h1 { font-size: 24px; margin-bottom: 12px; }
  p { color: var(--text-secondary); margin-bottom: 20px; line-height: 1.6; }
  .progress { font-size: 12px; }
  form { display: grid; gap: 12px; }
  label { display: grid; gap: 6px; }
  input { border: 1px solid var(--border-interactive); border-radius: 6px; padding: 10px; background: var(--surface); }
  button { margin: 8px 8px 0 0; }
  .primary { padding: 12px; }
</style>
