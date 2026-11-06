<script>
  // Single-select knopgroep (BETON-212, uitgebreid BETON-221): vervangt losse
  // <select>'s én de her-uitgevonden segmented-controls (scope/view/mine/
  // deliveries-filter). Presentational — de opties/labels-logica zit in
  // lib/segmentedOptions.js; variant/aria-mapping in lib/segmentedControl.js.
  //
  // variant: 'accent' (gevulde selectie, default — state/prioriteit),
  //          'soft'   (pill-track, subtiele selectie — zoek/wiki-scope),
  //          'joined' (aaneengesloten, accent-soft selectie — mijn-groep),
  //          'pill'   (losse pill-knoppen, gevulde selectie — deliveries/chat).
  // itemAria: 'radio' (default, aria-checked) of 'pressed' (toggle-button).
  import {
    segmentedClass,
    containerRole,
    itemAriaProps,
    willFire,
  } from "./lib/segmentedControl.js";

  let {
    options = [],
    value,
    onchange,
    disabled = false,
    ariaLabel = undefined,
    variant = "accent",
    itemAria = "radio",
    // Standaard vólgt de knop de normale Tab-volgorde (undefined). Sommige
    // aanroepers (BETON-408: de Editor/Voorbeeld-toggle in MarkdownEditor)
    // willen 'm bewust ÚIT de Tab-volgorde — nog gewoon klikbaar, maar Tab
    // vanaf het veld erboven moet direct naar wat erna komt (de verstuurknop),
    // niet eerst langs deze schakelaar.
    tabindex = undefined,
  } = $props();

  function pick(v) {
    if (!willFire(value, v, disabled)) return;
    onchange?.(v);
  }
</script>

<div class={segmentedClass(variant)} role={containerRole(itemAria)} aria-label={ariaLabel}>
  {#each options as opt (opt.value)}
    {@const aria = itemAriaProps(itemAria, opt.value === value)}
    <button
      type="button"
      role={aria.role}
      aria-checked={aria.ariaChecked}
      aria-pressed={aria.ariaPressed}
      title={opt.title}
      class="seg-btn"
      class:selected={opt.value === value}
      class:colored={opt.color && opt.value === value}
      class:color-hint={!!opt.color}
      style:--seg-color={opt.color}
      {disabled}
      {tabindex}
      onclick={() => pick(opt.value)}
    >
      {opt.label}
    </button>
  {/each}
</div>

<style>
  .segmented {
    display: inline-flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }
  /* BETON-418: een niet-gekozen optie is een beschikbare actie, dus de look
     van een gewone knop (vlak --surface, rand --border-interactive, tekst
     --text). Was --surface-2 + --border (1,28 donker) + --text-secondary:
     grijs-op-grijs, en dat is in deze app de look van `:disabled`. De gekozen
     optie blijft vol accent (BETON-415). */
  .seg-btn {
    padding: 5px 12px;
    border: 1px solid var(--border-interactive);
    border-radius: 7px;
    background: var(--surface);
    color: var(--text);
    font-size: 0.8rem;
    line-height: 1.2;
    cursor: pointer;
    transition:
      background 0.12s ease,
      border-color 0.12s ease,
      color 0.12s ease;
  }
  .seg-btn:hover:not(:disabled):not(.selected) {
    background: var(--surface-2);
    color: var(--text);
  }
  /* BETON-443: ook niet-gekozen opties herkenbaar aan hun kolomkleur.
     De selectie blijft sterker: dubbele rand, meer tint en vetgedrukte tekst. */
  .seg-btn.color-hint:not(.selected) {
    background: color-mix(in srgb, var(--seg-color) 6%, var(--surface));
    border-color: color-mix(in srgb, var(--seg-color) 55%, var(--border-interactive));
    color: var(--text);
  }
  .seg-btn.color-hint:hover:not(:disabled):not(.selected) {
    background: color-mix(in srgb, var(--seg-color) 13%, var(--surface));
    border-color: var(--seg-color);
  }
  /* Geselecteerd = volle accent-achtergrond (BETON-212 heropening: accent-text
     op accent-soft gaf te weinig contrast — accent-text hoort op vol accent,
     zoals button.primary). */
  .seg-btn.selected {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-text);
    font-weight: 600;
  }
  /* BETON-425: optie met eigen kleur (state-groep/werklast). Tint + rand i.p.v.
     een vlak met vaste tekstkleur: de kleur kan een willekeurige per-state hex
     zijn, en --text op een 22%-mix met --surface blijft in licht én donker
     leesbaar. Specificiteit boven .variant-*-selected is niet nodig: alleen
     de accent-variant krijgt een kleur mee. */
  .seg-btn.selected.colored {
    background: color-mix(in srgb, var(--seg-color) 22%, var(--surface));
    border-color: var(--seg-color);
    box-shadow: inset 0 0 0 1px var(--seg-color);
    color: var(--text);
  }
  .seg-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .seg-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  @media (prefers-reduced-motion: reduce) {
    .seg-btn {
      transition: none;
    }
  }

  /* --- soft: pill-track met subtiele selectie (voorheen .scope) --- */
  .variant-soft {
    flex-wrap: nowrap;
    gap: 2px;
    padding: 2px;
    background: var(--surface-2);
    border-radius: var(--radius-full);
  }
  .variant-soft .seg-btn {
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--text-base);
    font-weight: 400;
    padding: var(--space-1) var(--space-4);
    border-radius: var(--radius-full);
  }
  .variant-soft .seg-btn:hover:not(:disabled):not(.selected) {
    border-color: transparent;
    color: var(--text);
  }
  .variant-soft .seg-btn.selected {
    background: var(--surface);
    color: var(--text);
    font-weight: 500;
    box-shadow: var(--shadow-sm);
    border-color: transparent;
  }

  /* --- joined: aaneengesloten met accent-soft selectie (voorheen .mine-group/.mg-btn) --- */
  .variant-joined {
    gap: 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }
  .variant-joined .seg-btn {
    border: none;
    border-radius: 0;
    background: none;
    color: var(--text-tertiary);
    font-size: var(--text-base);
    font-weight: 400;
    padding: 5px 12px;
  }
  .variant-joined .seg-btn:hover:not(:disabled):not(.selected) {
    border-color: transparent;
    color: var(--text-secondary);
  }
  .variant-joined .seg-btn.selected {
    background: var(--accent-soft);
    color: var(--accent);
    border-color: transparent;
    font-weight: 400;
  }

  /* --- pill: losse pill-knoppen, gevulde selectie (voorheen deliveries-filter) --- */
  .variant-pill {
    gap: var(--space-2);
  }
  .variant-pill .seg-btn {
    border: 1px solid var(--border-interactive);
    border-radius: var(--radius-full);
    background: var(--surface);
    color: var(--text);
    font-size: var(--text-sm);
    font-weight: 400;
    padding: 4px 12px;
  }
  .variant-pill .seg-btn:hover:not(:disabled):not(.selected) {
    background: var(--surface-2);
    color: var(--text);
  }
  .variant-pill .seg-btn.selected {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-text);
    font-weight: 400;
  }
</style>
