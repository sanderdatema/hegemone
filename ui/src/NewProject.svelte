<script>
  import { t } from "./lib/i18n.js";
  import ProjectTemplate from "./ProjectTemplate.svelte";
  import { Dialog } from "bits-ui";
  import { X } from "@lucide/svelte";
  import { api } from "./api.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import Field from "./Field.svelte";
  import ErrorNote from "./ErrorNote.svelte";

  let { onclose, oncreated, me = null } = $props();

  let open = $state(true);
  let key = $state("");
  let name = $state("");
  let description = $state("");
  let error = $state("");
  let busy = $state(false);

  // Dialog dicht (Esc/overlay/close-knop) → parent laten unmounten.
  function onOpenChange(v) {
    if (!v) onclose?.();
  }

  // Key normaliseren: uppercase, alleen A–Z/0–9, max 20.
  function onKeyInput(e) {
    key = e.currentTarget.value
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, "")
      .slice(0, 20);
  }

  async function submit(e) {
    e.preventDefault();
    if (!key.trim() || !name.trim() || busy) return;
    busy = true;
    error = "";
    try {
      const created = await api.createProject({
        key: key.trim(),
        name: name.trim(),
        description,
      });
      oncreated?.(created);
    } catch (err) {
      error = $t("projects.createFailed", {error: err.message});
      busy = false;
    }
  }
</script>

<Dialog.Root bind:open {onOpenChange}>
  <Dialog.Portal>
    <Dialog.Overlay class="modal-overlay" />
    <Dialog.Content class="modal">
      <div class="modal-head">
        <Dialog.Title class="modal-title">{$t("project.new")}</Dialog.Title>
        <Dialog.Close class="icon-btn" aria-label={$t("common.close")}>
          <X size={18} />
        </Dialog.Close>
      </div>
      <ErrorNote message={error} />
      <form onsubmit={submit}>
        <div class="field-row">
          <Field label={$t("projects.key")}>
            <!-- svelte-ignore a11y_autofocus -->
            <input
              value={key}
              oninput={onKeyInput}
              placeholder="TEAM"
              maxlength="20"
              autofocus
            />
          </Field>
          <Field label={$t("agents.name")} style="flex: 2">
            <input bind:value={name} placeholder={$t("projects.nameHint")} />
          </Field>
        </div>
        <Field label={$t("ticket.description")}>
          <AutoTextarea bind:value={description} rows="3" placeholder={$t("projects.optional")} onsubmit={() => submit(new Event("submit"))} />
        </Field>
        <div class="modal-foot">
          <button type="button" class="ghost" onclick={() => (open = false)}>{$t("common.cancel")}</button>
          <button class="primary" type="submit" disabled={busy || !key.trim() || !name.trim()}>
            {$t("common.create")}
          </button>
        </div>
      </form>
      <ProjectTemplate editable={me?.kind === "human"} />
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
