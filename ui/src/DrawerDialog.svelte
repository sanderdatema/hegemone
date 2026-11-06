<script>
  // Gedeelde bits-ui Dialog-wrapper voor de rechter-drawer-panelen (BETON-172).
  // Levert focus-trap, Escape, focus-return en aria-modal "gratis" (net als
  // NewItem/NewProject/CommandPalette). Eén wrapper i.p.v. per-paneel een
  // handgemaakte <div class="overlay">. De panelen leveren hun eigen inhoud via
  // de children-snippet; breedte via `width` (CSS-lengte, mobiel altijd 100dvw).
  //
  // BETON-223: optionele veto-callbacks `onEscapeKeydown`/`onInteractOutside`
  // (rechtstreeks doorgegeven aan Dialog.Content) zodat een paneel Escape/
  // buiten-klik kan onderscheppen (bv. sub-state sluiten, of waarschuwen bij een
  // onopgeslagen concept) door `e.preventDefault()` aan te roepen. Undefined =
  // bits-ui-standaardgedrag → bestaande aanroepers ongewijzigd. `open` is
  // bindable zodat een paneel programmatisch kan sluiten (X-knop) zónder de
  // sluit-veto te omzeilen — de sluiting loopt dan gewoon via onOpenChange.
  import { Dialog } from "bits-ui";

  let {
    onclose,
    label,
    width = "",
    open = $bindable(true),
    onEscapeKeydown,
    onInteractOutside,
    children,
  } = $props();

  // Esc/overlay-klik/close-knop → dicht: parent laten unmounten.
  function onOpenChange(v) {
    if (!v) onclose?.();
  }
</script>

<Dialog.Root bind:open {onOpenChange}>
  <Dialog.Portal>
    <Dialog.Overlay class="drawer-overlay" />
    <Dialog.Content
      class="drawer-dialog"
      style={width ? `--drawer-w: ${width}` : undefined}
      {onEscapeKeydown}
      {onInteractOutside}
    >
      <Dialog.Title class="sr-only">{label}</Dialog.Title>
      {@render children?.()}
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
