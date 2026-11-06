<script>
  /**
   * Gedeelde regel-diff-weergave (BETON-329) — vervangt de dubbele
   * diff-markup/CSS in Drawer.svelte (enrich-preview, BETON-13) en
   * Wiki.svelte (revisiediff, BETON-209).
   *
   * `segments` komt uit `lib/diff.js#lineDiff`:
   *   { type: "ctx" | "add" | "del", text: string }
   *
   * De twee oorspronkelijke plekken zagen er NIET identiek uit (Drawer: een
   * gevulde surface zonder rand, kleiner lettertype; Wiki: een rand zonder
   * vulling, groter lettertype) — `variant` behoudt dat verschil zodat geen
   * van beide visueel verandert.
   *
   * @typedef {{type: "ctx" | "add" | "del", text: string}} DiffSegment
   */
  let {
    segments = /** @type {DiffSegment[]} */ ([]),
    variant = "surface",
    ariaLabel = undefined,
  } = $props();
</script>

<div class="diff diff-{variant}" aria-label={ariaLabel}>
  {#each segments as seg, i (i)}
    <div class="diff-line {seg.type}">
      <span class="diff-sign" aria-hidden="true"
        >{seg.type === "add" ? "+" : seg.type === "del" ? "−" : " "}</span
      ><span class="diff-text">{seg.text || " "}</span>
    </div>
  {/each}
</div>

<style>
  .diff {
    overflow-x: auto;
    line-height: 1.5;
  }
  .diff-line {
    display: flex;
    white-space: pre-wrap;
    word-break: break-word;
    padding: 0 8px;
  }

  /* Drawer-enrich-preview (BETON-13): gevulde surface, geen rand. */
  .diff-surface {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: var(--text-sm);
    border-radius: var(--radius-sm);
    background: var(--surface);
    padding: 6px 0;
  }
  .diff-surface .diff-line {
    gap: 8px;
  }
  .diff-surface .diff-line.add {
    background: var(--success-soft);
  }
  .diff-surface .diff-line.del {
    background: var(--danger-soft);
  }
  .diff-surface .diff-sign {
    flex: 0 0 auto;
    width: 1ch;
    user-select: none;
    color: var(--text-tertiary);
  }
  .diff-surface .diff-line.add .diff-sign {
    color: var(--success);
  }
  .diff-surface .diff-line.del .diff-sign {
    color: var(--danger);
  }
  .diff-surface .diff-text {
    flex: 1;
    min-width: 0;
  }

  /* Wiki-revisiediff (BETON-209): rand, geen vulling, groter lettertype. */
  .diff-bordered {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--text-base);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .diff-bordered .diff-line.add {
    background: color-mix(in srgb, var(--success) 14%, transparent);
  }
  .diff-bordered .diff-line.del {
    background: color-mix(in srgb, var(--danger) 14%, transparent);
  }
  .diff-bordered .diff-sign {
    flex: 0 0 1.2em;
    color: var(--text-tertiary);
    user-select: none;
  }
  .diff-bordered .diff-text {
    flex: 1 1 auto;
  }
</style>
