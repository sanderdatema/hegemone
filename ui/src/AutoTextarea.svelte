<script>
  // AutoTextarea (BETON-462): de enige kale <textarea> in de UI (naast
  // MarkdownEditor, dat hem gebruikt). Draagt wat elk meerregelig veld moet
  // hebben: Cmd/Ctrl+Enter = `onsubmit`, Escape = `oncancel` (alleen als die
  // meegegeven is; anders blijft Escape bij de dialog), en meegroeien met de
  // tekst tot `max-height`. Kale Enter blijft een nieuwe regel. Dit lost de
  // klasse "elk veld haakt het zelf aan" op (BETON-440/444/438); een vitest-
  // grendel (autoTextarea.guard.test.js) bewaakt dat er geen kale textarea terugkomt.
  import { textFieldAction, growToFit } from "./lib/autoTextarea.js";

  let {
    value = $bindable(""),
    textareaRef = $bindable(undefined),
    onsubmit = undefined,
    oncancel = undefined,
    onkeydown = undefined,
    class: className = "",
    ...rest
  } = $props();

  // Eerst de gedeelde toetsen, dan de handler van de aanroeper (mention-popup e.d.).
  function handleKeydown(e) {
    const action = textFieldAction(e, { canSubmit: !!onsubmit, canCancel: !!oncancel });
    if (action === "submit") {
      e.preventDefault();
      onsubmit();
      return;
    }
    if (action === "swallow") {
      e.preventDefault();
      return;
    }
    onkeydown?.(e);
    if (action === "cancel" && !e.defaultPrevented) {
      e.preventDefault();
      e.stopPropagation();
      oncancel();
    }
  }

  $effect(() => {
    value;
    growToFit(textareaRef);
  });
</script>

<textarea
  bind:this={textareaRef}
  bind:value
  class="auto-ta {className}"
  {...rest}
  onkeydown={handleKeydown}
></textarea>

<style>
  .auto-ta {
    resize: none;
    max-height: 40vh;
    overflow-y: auto;
  }
  .full {
    width: 100%;
  }
</style>
