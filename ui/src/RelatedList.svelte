<script>
  import { t as uiText } from "./lib/i18n.js";
  // Eén lijstvorm voor subtaken en relaties (BETON-471): statusstip · ref ·
  // titel (afgekapt, volledige titel in `title`), gegroepeerd met het type als
  // kleine kop. De verbreek-knop ligt OVER de regel (absoluut, geen gereserveerde
  // ruimte): zichtbaar bij hover/focus, op touch altijd (BETON-415).
  import { Unlink } from "@lucide/svelte";
  import { stateColor } from "./lib/board.js";

  /** @type {{groups: Array, states?: Array, busy?: boolean, onopen?: (ref: string) => void, onremove?: (type: string, ref: string) => void}} */
  let { groups = [], states = [], busy = false, onopen, onremove } = $props();
</script>

<div class="related">
  {#each groups as g (g.type)}
    {#if g.label}<div class="rel-head">{g.label}</div>{/if}
    <ul class="rel-list">
      {#each g.items as it (it.ref)}
        <li class="rel-item">
          <span class="col-dot" style:background={stateColor(states, it.state)}></span>
          <button class="ref-link" onclick={() => onopen?.(it.ref)}>{it.ref}</button>
          <span class="rel-title" title={it.title}>{it.title}</span>
          {#if onremove && g.removable}
            <button
              class="rel-unlink"
              title={$uiText("ui.unlink")}
              aria-label={$uiText("detail.unlinkRef", {ref: it.ref})}
              disabled={busy}
              onclick={() => onremove(g.type, it.ref)}
            >
              <Unlink size={12} />
            </button>
          {/if}
        </li>
      {/each}
    </ul>
  {/each}
</div>

<style>
  .related {
    width: 100%;
    text-align: left;
  }
  .rel-head {
    margin-top: 4px;
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }
  .rel-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .rel-item {
    position: relative;
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-width: 0;
    padding: 1px 0;
  }
  .rel-item :global(.col-dot) {
    flex: none;
    align-self: center;
  }
  .rel-item .ref-link {
    flex: none;
    border: none;
    background: none;
    color: var(--accent);
    padding: 2px 4px;
    min-height: unset;
    font-variant-numeric: tabular-nums;
    border-radius: var(--radius-sm);
  }
  .rel-item .ref-link:hover {
    background: var(--accent-soft);
  }
  .rel-title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-secondary);
  }
  /* Over de regel, geen gereserveerde ruimte: de titel loopt eronder door. */
  .rel-unlink {
    position: absolute;
    right: 0;
    top: 50%;
    transform: translateY(-50%);
    display: inline-flex;
    border: none;
    background: var(--surface);
    color: var(--text-secondary);
    padding: 3px;
    min-height: unset;
    border-radius: var(--radius-full);
    opacity: 0;
    transition: opacity var(--dur-fast) var(--ease);
  }
  .rel-item:hover .rel-unlink,
  .rel-item:focus-within .rel-unlink {
    opacity: 1;
  }
  .rel-unlink:hover {
    color: var(--danger);
    background: var(--danger-soft);
  }
  /* Hover bestaat niet op touch: daar altijd zichtbaar (BETON-415). */
  @media (pointer: coarse) {
    .rel-unlink {
      opacity: 1;
      min-height: 40px;
      min-width: 40px;
      justify-content: center;
    }
  }
</style>
