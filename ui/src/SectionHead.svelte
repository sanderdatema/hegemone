<script>
  // Caps-sectiekopje (BETON-221): consolideert de her-uitgevonden
  // uppercase-kopjes (voorheen .section-head in Drawer, .ag-head in Agents).
  // Presentational; content (titel + optionele acties rechts) komt via de
  // children-snippet — de flex-space-between duwt trailing knoppen naar rechts.
  let { children } = $props();
</script>

<div class="section-head">{@render children?.()}</div>

<style>
  .section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: var(--text-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-secondary);
    margin-bottom: 10px;
  }
</style>
