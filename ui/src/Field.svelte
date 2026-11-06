<script>
  // Label+control-veld (BETON-221): de terugkerende form-rij (label boven een
  // input/textarea/select). Basis-primitief dat latere formulier-tickets
  // (223/229) hergebruiken. Leunt bewust op de globale .field/.field span-
  // styling in app.css (byte-identiek aan de handgeschreven <label class="field">).
  // Het control zelf komt via de children-snippet zodat bind:value bij de
  // ouder blijft.
  let { label, style = undefined, children } = $props();
</script>

<label class="field" {style}>
  <span>{label}</span>
  {@render children?.()}
</label>
