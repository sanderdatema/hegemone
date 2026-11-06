<script>
  // WorkloadBadge.svelte (BETON-328/461): gedeelde werklast-badge. Tekst
  // L / M / Z in een neutraal-oplopende kleur (grijs → blauw → paars): werklast
  // is een tokeninschatting, geen urgentie, dus geen verkeerslicht. Geeft niets
  // terug als de workload leeg/onbekend is (`workloadMeta` → null).
  import { locale } from "./lib/i18n.js";
  import { workloadMeta } from "./lib/labels.js";

  let { workload, size = 12 } = $props();

  let meta = $derived(workloadMeta(workload, $locale));
</script>

{#if meta}
  <span
    class="workload-icon"
    style:color={meta.color}
    style:font-size="{size}px"
    title={meta.title}
    aria-label={meta.title}
  >{meta.short}</span>
{/if}

<style>
  .workload-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    min-width: 1.6em;
    padding: 0 0.3em;
    line-height: 1.5;
    font-weight: 700;
    letter-spacing: 0.02em;
    border: 1px solid currentColor;
    border-radius: var(--radius-full);
  }
</style>
