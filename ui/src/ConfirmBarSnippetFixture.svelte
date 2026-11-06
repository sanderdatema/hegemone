<script>
  // Testfixture voor ConfirmBar.test.js — een `message`-snippet (rijke inhoud
  // met opmaak) kan alleen als echte Svelte {#snippet} geschreven worden,
  // niet als plain JS-functie vanuit een .test.js. Spiegelt de Wiki.svelte
  // create-prompt-bar (BETON-319).
  import ConfirmBar from "./ConfirmBar.svelte";

  let { onconfirm, oncancel } = $props();
</script>

<ConfirmBar confirmLabel="Aanmaken" {onconfirm} {oncancel}>
  {#snippet message()}
    Pagina <strong>foo</strong> bestaat nog niet. Aanmaken?
  {/snippet}
</ConfirmBar>
