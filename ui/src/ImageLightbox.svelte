<script>
  import { t as tr } from "./lib/i18n.js";
  // Lightbox (BETON-474): één afbeelding groot in een bits-ui Dialog. De Dialog
  // is een eigen laag boven de Drawer, dus Escape sluit alleen deze.
  import { Dialog } from "bits-ui";
  import { X, ExternalLink } from "@lucide/svelte";

  /** @type {{image: {src: string, alt: string}|null, onclose: () => void}} */
  let { image, onclose } = $props();
</script>

<Dialog.Root open={image != null} onOpenChange={(o) => { if (!o) onclose(); }}>
  <Dialog.Portal>
    <Dialog.Overlay class="modal-overlay lightbox-overlay" />
    <Dialog.Content class="lightbox" aria-label={image?.alt || $tr("wiki.image")}>
      <Dialog.Title class="sr-only">{image?.alt || $tr("wiki.image")}</Dialog.Title>
      {#if image}
        <img src={image.src} alt={image.alt} />
        <div class="lightbox-bar">
          <a href={image.src} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} /> {$tr("wiki.newTab")}</a>
          <Dialog.Close class="icon-btn" aria-label={$tr("common.close")}><X size={16} /></Dialog.Close>
        </div>
      {/if}
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  :global(.lightbox-overlay) {
    z-index: calc(var(--z-modal) + 10);
  }
  :global(.lightbox) {
    position: fixed;
    z-index: calc(var(--z-modal) + 11);
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    max-width: 90vw;
    max-height: 90vh;
  }
  :global(.lightbox) img {
    max-width: 90vw;
    max-height: calc(90vh - 40px);
    object-fit: contain;
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .lightbox-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--surface);
    color: var(--text);
    border-radius: var(--radius-lg);
    padding: 4px 8px;
  }
  .lightbox-bar a {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
  }
</style>
