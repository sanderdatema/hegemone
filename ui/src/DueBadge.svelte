<script>
  import {t,locale} from "./lib/i18n.js";
  // Gedeelde einddatumbadge voor bord en lijst (BETON-446).
  import { Calendar } from "@lucide/svelte";
  import { dueMeta } from "./lib/dueDate.js";

  let { due = null, card = false } = $props();
  let meta = $derived(dueMeta(due, undefined, $locale));
</script>

{#if meta}
  <span class="due-badge" class:card class:overdue={meta.kind === "overdue"} class:today={meta.kind === "today"} title={meta.title}>
    <Calendar size={11} aria-hidden="true" />
    {meta.kind === "overdue" ? $t("due.overdue") : meta.kind === "today" ? $t("due.today") : ""}{due.slice(0, 10)}
  </span>
{/if}

<style>
  .due-badge {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    flex-shrink: 0;
    white-space: nowrap;
    font-size: var(--text-xs);
    padding: 1px 7px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--text-tertiary) 15%, transparent);
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
  }
  .card { margin-top: 6px; margin-left: 6px; }
  .today {
    background: color-mix(in srgb, var(--warning) 15%, transparent);
    color: var(--warning);
    font-weight: 600;
  }
  .overdue {
    background: color-mix(in srgb, var(--danger) 15%, transparent);
    color: var(--danger);
    font-weight: 600;
  }
</style>
