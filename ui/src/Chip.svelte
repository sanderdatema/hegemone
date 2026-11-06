<script>
  import { t as uiText } from "./lib/i18n.js";
  // Chip-primitief (BETON-221): één home voor de her-uitgevonden pill-chips.
  // Presentational — de class/element-keuze zit in lib/chip.js. In gebruik voor
  // de label-chips (statische weergave op board/lijst én de interactieve toggle
  // in de Drawer) en de neutrale ref-chip (Drawer-kop).
  //
  // tone: 'neutral' | 'label' (label kleurt via `hue`, uit
  //       lib/avatar.js → labelHue).
  // Interactief zodra `onclick`/`href` gezet is (→ button/a); `selected`
  // markeert een aan-staande toggle. `removable` toont een sluit-x (onremove).
  import { chipClass, chipElement, chipInteractive } from "./lib/chip.js";
  import { X } from "@lucide/svelte";

  let {
    tone = "neutral",
    hue = 0,
    selected = false,
    removable = false,
    onremove,
    href,
    onclick,
    disabled = false,
    title = undefined,
    ariaLabel = undefined,
    children,
  } = $props();

  const el = $derived(chipElement({ href, onclick }));
  const cls = $derived(
    chipClass(tone, { interactive: chipInteractive({ href, onclick }), selected }),
  );
</script>

<svelte:element
  this={el}
  class={cls}
  style:--label-h={tone === "label" ? hue : undefined}
  href={el === "a" ? href : undefined}
  type={el === "button" ? "button" : undefined}
  disabled={el === "button" ? disabled : undefined}
  aria-pressed={onclick && tone === "label" ? selected : undefined}
  {title}
  aria-label={ariaLabel}
  role={onclick && el !== "button" ? "button" : undefined}
  onclick={onclick}
>
  {@render children?.()}
  {#if removable}
    <button
      type="button"
      class="chip-x"
      aria-label={$uiText("ui.remove")}
      onclick={(e) => {
        e.stopPropagation();
        onremove?.();
      }}
    >
      <X size={12} />
    </button>
  {/if}
</svelte:element>

<style>
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
    font: inherit;
    /* BETON-238: neutraliseer de globale <button>-box (border/achtergrond/
       min-height: 34px) zodat een button-chip (onclick) exact even hoog is als
       een span-chip. De tone-regels hieronder zetten hun eigen rand/vulling. */
    min-height: 0;
    border: 0;
    background: none;
    color: inherit;
  }
  .chip.interactive {
    cursor: pointer;
  }
  .chip:disabled {
    cursor: default;
  }

  /* --- neutral: surface-2 pill (voorheen Drawer .ref-chip) --- */
  .tone-neutral {
    gap: 5px;
    padding: 3px 10px;
    font-size: var(--text-sm);
    font-variant-numeric: tabular-nums;
    color: var(--text-secondary);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-full);
  }
  /* BETON-418: klikbaar = rand en tekst van een gewone actie; de statische
     span-chip houdt de stille --border/--text-secondary. */
  .tone-neutral.interactive {
    color: var(--text);
    border-color: var(--border-interactive);
  }
  .tone-neutral.interactive:hover {
    background: var(--surface-3);
    color: var(--text);
  }

  /* --- label: hue-gekleurd. Statische weergave = zacht gevulde pill
     (voorheen .label-chip); interactief = outline-toggle die gevuld wordt
     bij .selected (voorheen .dlabel). light-dark() volgt de color-scheme,
     dus flipt mee met systeem én de handmatige thema-toggle (BETON-61). --- */
  .tone-label {
    border-radius: var(--radius-full);
    gap: 4px;
  }
  /* statische weergave (span). BETON-238/240: zelfde compacte pill-maat als de
     neutrale chip (font-sm, ~2px 9px) zodat alle pills één designtaal delen en
     de tekst-tot-padding-verhouding klopt; kleur (soft-fill hue) is het enige
     onderscheid. */
  .tone-label:not(.interactive) {
    font-size: var(--text-sm);
    line-height: 1.4;
    padding: 2px 9px;
    background: light-dark(hsl(var(--label-h) 62% 90%), hsl(var(--label-h) 28% 26%));
    color: light-dark(hsl(var(--label-h) 42% 32%), hsl(var(--label-h) 68% 78%));
  }
  /* interactieve toggle — uit */
  .tone-label.interactive {
    padding: 3px 10px;
    font-size: var(--text-sm);
    border: 1px solid light-dark(hsl(var(--label-h) 45% 76%), hsl(var(--label-h) 30% 42%));
    background: transparent;
    color: light-dark(hsl(var(--label-h) 40% 42%), hsl(var(--label-h) 50% 68%));
  }
  .tone-label.interactive:hover:not(.selected) {
    border-color: hsl(var(--label-h) 50% 58%);
    background: light-dark(hsl(var(--label-h) 62% 94%), hsl(var(--label-h) 26% 22%));
  }
  /* interactieve toggle — aan */
  .tone-label.interactive.selected {
    border-color: transparent;
    background: light-dark(hsl(var(--label-h) 55% 45%), hsl(var(--label-h) 55% 55%));
    color: light-dark(var(--on-solid), hsl(var(--label-h) 30% 12%));
    font-weight: 600;
  }

  /* Touch: interactieve chips krijgen een volwaardig tap-target (voorheen de
     .dlabel- en .ref-chip-overrides in Drawer). */
  @media (pointer: coarse) {
    .tone-label.interactive {
      min-height: 40px;
      padding: 8px 12px;
    }
    .tone-neutral.interactive {
      min-height: 40px;
    }
  }

  .chip-x {
    display: inline-flex;
    border: none;
    background: none;
    /* BETON-418: de tekstkleur van de chip zelf. --text-tertiary haalde op een
       gekleurde label-chip 2,69 (licht) en 1,78 (donker). */
    color: inherit;
    padding: 0;
    /* BETON-238: ook de sluit-x is een <button> — reset de globale min-height
       zodat de x de chip niet naar 34px oprekt. */
    min-height: 0;
    cursor: pointer;
  }
  .chip-x:hover {
    color: var(--text);
  }
</style>
