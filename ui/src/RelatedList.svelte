<script>
  import { t as uiText } from "./lib/i18n.js";
  // Shared readable rows for subtasks and typed relations.
  import { Unlink } from "@lucide/svelte";
  import { stateColor } from "./lib/board.js";

  /** @type {{groups: Array, states?: Array, busy?: boolean, onopen?: (ref: string) => void, onremove?: (type: string, ref: string) => void}} */
  let { groups = [], states = [], busy = false, onopen, onremove } = $props();

  const isCompleted = (item) => (item.state_group ?? states.find((state) => state.name === item.state)?.group) === "completed";
</script>

<div class="related">
  {#each groups as g (g.type)}
    {#if g.label}<div class="rel-head" data-type={g.type}>{g.label}</div>{/if}
    <ul class="rel-list" data-type={g.type}>
      {#each g.items as it (it.ref)}
        <li class="rel-item" class:completed={isCompleted(it)}>
          <span class="col-dot" style:background={stateColor(states, it.state)}></span>
          <button class="rel-link" onclick={() => onopen?.(it.ref)}>
            <span class="rel-ref">{it.ref}</span>
            <span class="rel-title">{it.title}</span>
          </button>
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
  .related { width: 100%; text-align: left; }
  [data-type="blocks"] { --relation-color: var(--danger); }
  [data-type="blocked_by"] { --relation-color: light-dark(#936000, #e0a94e); }
  [data-type="duplicate_of"] { --relation-color: light-dark(#7950b0, #ba9ae5); }
  [data-type="duplicated_by"] { --relation-color: light-dark(#286ba8, #8abde9); }
  [data-type="relates_to"] { --relation-color: light-dark(#28754f, #78c69e); }
  .rel-head {
    display: inline-block;
    margin: 8px 0 3px;
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--relation-color, var(--text-secondary));
    background: color-mix(in srgb, var(--relation-color, var(--text-secondary)) 12%, transparent);
  }
  .rel-list { list-style: none; margin: 0; padding: 0; }
  .rel-item {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: start;
    gap: 6px;
    padding: 4px 0;
  }
  .rel-item :global(.col-dot) { margin-top: 7px; }
  .rel-link {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    min-width: 0;
    min-height: unset;
    padding: 0;
    border: 0;
    background: none;
    text-align: left;
    font-weight: normal;
  }
  .rel-link:hover { background: var(--surface-2); }
  .rel-ref { color: var(--relation-color, var(--accent)); font-variant-numeric: tabular-nums; }
  .rel-title { color: var(--text-secondary); white-space: normal; overflow-wrap: anywhere; }
  .completed .rel-ref, .completed .rel-title { text-decoration: line-through; }
  .rel-unlink {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: none;
    color: var(--text-secondary);
    padding: 3px;
    min-height: unset;
    border-radius: var(--radius-full);
    opacity: 0;
  }
  .rel-item:hover .rel-unlink, .rel-item:focus-within .rel-unlink { opacity: 1; }
  .rel-unlink:hover { color: var(--danger); background: var(--danger-soft); }
  @media (pointer: coarse) {
    .rel-unlink { opacity: 1; min-height: 40px; min-width: 40px; }
  }
</style>
