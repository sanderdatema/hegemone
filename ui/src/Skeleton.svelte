<script>
  // Skeleton-primitief (BETON-226): vervangt de kale "Laden…"-teksten in de
  // panelen door dezelfde `.skel`-shimmer die het bord al gebruikt (app.css).
  // De preset/telling-keuze is puur en getest in lib/skeleton.js — dit
  // component rendert alleen wat die functie teruggeeft.
  //
  // preset: 'title' (kopregel) | 'lines' (N tekstregels) | 'rows' (N rijen
  //         met avatar-cirkel + regel, voor lijst/inbox/tijdlijn) | 'card'
  //         (N kaarten met korte + volle + halve regel, voor Agents).
  // count: overschrijft het standaardaantal rijen van de preset.
  import { skeletonRows } from "./lib/skeleton.js";

  let { preset = "lines", count = undefined } = $props();
  const rows = $derived(skeletonRows(preset, count));
</script>

<div class="skeleton skeleton-{preset}" aria-hidden="true">
  {#each rows as row, i (i)}
    {#if row.kind === "head"}
      <span class="skel skel-head"></span>
    {:else if row.kind === "row"}
      <div class="skel-row">
        <span class="skel skel-avatar"></span>
        <span class="skel skel-line"></span>
      </div>
    {:else if row.kind === "card"}
      <div class="skel-card-block">
        <span class="skel skel-line short"></span>
        <span class="skel skel-line"></span>
        <span class="skel skel-line med"></span>
      </div>
    {:else}
      <span class="skel skel-line" style:width={row.width}></span>
    {/if}
  {/each}
</div>

<style>
  .skeleton {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .skeleton-rows,
  .skeleton-card {
    gap: var(--space-4);
  }
</style>
