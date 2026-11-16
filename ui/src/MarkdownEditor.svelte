<script>
  import { tick } from "svelte";
  import { textFieldAction } from "./lib/autoTextarea.js";
  import { t } from "./lib/i18n.js";
  // MarkdownEditor.svelte (BETON-365): bundelt de textarea + een
  // Editor/Voorbeeld-schakelaar voor de drie markdown-velden (reactie,
  // omschrijving, plan). De @mention-/#hash-autocomplete-state (matches,
  // actieve index, pick-functies) blijft bewust in de aanroeper — die state
  // voedt Drawer.svelte's Escape-ladder (`escapeLadder`/`ESCAPE_ORDER` in
  // drawerLogic.js); zou die state hierheen verhuizen, dan kan de ladder 'm
  // niet meer lezen/wissen en sluit Escape de hele drawer terwijl een
  // dropdown nog open staat (de BETON-289-regressieklasse). De aanroeper
  // geeft de dropdown-<ul> daarom mee als `dropdown`-snippet; deze component
  // is alleen verantwoordelijk voor schrijven-vs-voorbeeld.
  import { renderMarkdown } from "./lib/markdown.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import { readPreviewMode, writePreviewMode } from "./lib/markdownEditorMode.js";

  let {
    value = "",
    rows = 3,
    placeholder = "",
    ariaLabel = undefined,
    autofocus = false,
    knownHandles = [],
    projectKeys = [],
    textareaRef = $bindable(undefined),
    oninput,
    onsubmit,
    oncancel,
    onkeydown,
    onpaste,
    ondragover,
    ondrop,
    onblur,
    dropdown,
  } = $props();

  // Gedeeld over reactie/omschrijving/plan (BETON-365: "onthouden per sessie,
  // niet per veld") — elke instantie leest bij het opzetten en schrijft bij
  // elke wissel; instanties die op hetzelfde moment open staan synchroniseren
  // niet live met elkaar, alleen de volgende keer opnieuw opzetten.
  const helpId = $props.id();
  let previewRef = $state();
  let mode = $state(readPreviewMode());

  async function handleModeKeydown(e) {
    if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && e.code === "KeyP") {
      e.preventDefault();
      e.stopPropagation();
      setMode(mode === "write" ? "preview" : "write");
      await tick();
      (mode === "write" ? textareaRef : previewRef)?.focus({ preventScroll: true });
      return;
    }
    if (e.target !== previewRef) return;
    const action = textFieldAction(e, { canSubmit: !!onsubmit, canCancel: !!oncancel });
    if (action === "submit" || action === "swallow") {
      e.preventDefault();
      if (action === "submit") onsubmit();
      return;
    }
    onkeydown?.(e);
    if (action === "cancel" && !e.defaultPrevented) {
      e.preventDefault();
      e.stopPropagation();
      oncancel();
    }
  }
  function setMode(v) {
    mode = v;
    writePreviewMode(v);
  }

  // Meegroeien (BETON-438), Cmd+Enter en Escape (BETON-462) zitten in
  // AutoTextarea; hier alleen doorgeven.

  const MODE_OPTS = $derived([
    { value: "write", label: "Editor" },
    { value: "preview", label: $t("editor.preview") },
  ]);
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions — delegated mode shortcut for the field and its preview -->
<div class="md-editor" role="group" aria-label={ariaLabel || $t("editor.view")} onkeydown={handleModeKeydown}>
  {#if mode === "preview"}
    <!-- eslint-disable-next-line svelte/no-at-html-tags — renderMarkdown escapet -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex — preview replaces the editable field in the same keyboard position -->
    <div class="md-editor-preview md" bind:this={previewRef} tabindex="0" role="region" aria-label={ariaLabel || $t("editor.preview")} aria-describedby={helpId} aria-keyshortcuts="Alt+Shift+P">{@html renderMarkdown(value, knownHandles, projectKeys)}</div>
  {:else}
    <div class="mention-box">
      <!-- svelte-ignore a11y_autofocus -->
      <AutoTextarea
        class="full"
        bind:textareaRef
        {onsubmit}
        {oncancel}
        {rows}
        {placeholder}
        aria-label={ariaLabel}
        aria-describedby={helpId}
        aria-keyshortcuts="Alt+Shift+P"
        {value}
        {oninput}
        {onkeydown}
        {onpaste}
        {ondragover}
        {ondrop}
        {onblur}
        {autofocus}
      />
      {@render dropdown?.()}
    </div>
  {/if}
  <!-- DOM ná het veld, visueel via `order` er vóór (BETON-408): zo gaat Tab
       vanaf het titelveld naar de textarea/preview i.p.v. eerst deze
       schakelaar te moeten passeren, zonder de layout te wijzigen.
       `tabindex="-1"` (BETON-408 heropening) haalt de knoppen ook zelf uit
       de Tab-volgorde: Tab ná de textarea moet direct naar wat er in het
       formulier op volgt (de verstuurknop), niet eerst langs deze toggle.
       De zichtbare sneltoets wisselt de modus vanuit het veld of voorbeeld. -->
  <div class="md-editor-toggle">
    <span id={helpId} class="mode-help">{$t("editor.modeShortcut")}</span>
    <!-- BETON-415: soft i.p.v. pill — Editor/Voorbeeld wisselt alleen de
         WEERGAVE van hetzelfde veld, geen mutatie, dus geen volle accent. -->
    <SegmentedControl
      ariaLabel={$t("editor.view")}
      variant="soft"
      options={MODE_OPTS}
      value={mode}
      onchange={setMode}
      tabindex={-1}
    />
  </div>
</div>

<style>
  .md-editor {
    display: flex;
    flex-direction: column;
  }
  .md-editor-toggle {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    order: -1;
    margin-bottom: 6px;
  }
  .mode-help {
    color: var(--text-secondary);
    font-size: var(--text-xs);
  }
  .md-editor-preview:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .md-editor-preview {
    min-height: 3em;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-2);
  }
  .md-editor-preview:empty::before {
    content: "Niets om te tonen.";
    color: var(--text-tertiary);
  }
</style>
