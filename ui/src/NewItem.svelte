<script>
  import { t, locale } from "./lib/i18n.js";
  import PickerSuggestions from "./PickerSuggestions.svelte";
  import { textPicker, relationPicker, toggleSelection } from "./lib/inputPickers.js";
  import { tick, onDestroy } from "svelte";
  import { Dialog, Collapsible } from "bits-ui";
  import { X, ImagePlus, ChevronRight, ChevronDown } from "@lucide/svelte";
  import { api } from "./api.js";
  import { isSubmitChord } from "./lib/board.js";
  import { imageFilesFromFileList } from "./lib/drawerImages.js";
  import {
    buildPendingImage,
    resolvePlaceholder,
    removePlaceholder,
    stripPlaceholders,
  } from "./lib/newItemImages.js";
  import { newItemDefaults } from "./lib/newItemDefaults.js";
  import { insertAt, handoffTargets } from "./lib/drawerLogic.js";
  import { attachmentMarkdown } from "./lib/attachments.js";
  import { labelHueOf } from "./lib/labelPalette.svelte.js";
  import { relationLabel, RELATION_TYPES } from "./lib/labels.js";
  import SegmentedControl from "./SegmentedControl.svelte";
  import MarkdownEditor from "./MarkdownEditor.svelte";
  import Field from "./Field.svelte";
  import Chip from "./Chip.svelte";
  import AssigneeSelect from "./AssigneeSelect.svelte";
  import Select from "./Select.svelte";
  import { workloadOptions, stateOptions } from "./lib/segmentedOptions.js";

  let {
    projectKey,
    states,
    users,
    me = null,
    projectLabels = [],
    milestones = [],
    defaultState = "",
    // Het huidige project (met `triage_enabled`) — bepaalt de triage-tekst en
    // de toelichting bij het aanmaken (BETON-465).
    project = null,
    // Voorinvulling (BETON-373: "Dupliceer" vanuit de Drawer) — title/
    // description/labels/workload/milestone van duplicateDraft(item)
    // (lib/drawerLogic.js), plus de ref om een relates_to-relatie mee te
    // leggen (spiegelt het bestaande BETON-247-patroon hieronder). `parent`
    // (BETON-363) vult het parent-veld hieronder voor: bij "Dupliceer" de
    // parent van het origineel (kopie wordt een broertje), bij "Subtaak
    // toevoegen" (Drawer-rail) het item zelf.
    initial = {},
    onclose,
    oncreated,
    onerror,
  } = $props();

  // Voor de MarkdownEditor-voorbeeldweergave (BETON-365) — mentions/refs in
  // een nog niet aangemaakt ticket kunnen alleen naar dít project verwijzen.
  let knownHandles = $derived((users || []).map((u) => u.handle));
  let projectKeys = $derived([projectKey]);

  const workloadOpts = $derived(workloadOptions({ locale: $locale }));
  const stateOpts = $derived(stateOptions(states));

  let open = $state(true);
  // "Meer opties" staat bij elke opening dicht — niet onthouden tussen
  // dialogen (BETON-229, BETON-495). Het component wordt door App.svelte sowieso
  // volledig ge-unmount na sluiten, dus deze init-waarde volstaat.
  const defaults = newItemDefaults(project);
  let moreOpen = $state(defaults.moreOpen);
  let title = $state(initial.title ?? "");
  let description = $state(initial.description ?? "");
  let stateName = $state(defaultState);
  let workload = $state(initial.workload ?? "");
  let assignee = $state("");
  let assignShortcuts = $derived(handoffTargets({ assignee }, me, users));
  let dueDate = $state("");
  let deferUntil = $state("");
  let selectedLabels = $state([...(initial.labels ?? [])]);
  let milestone = $state(initial.milestone ?? "");
  let error = $state("");
  let busy = $state(false);

  // Subtaak van (BETON-363): ref-autocomplete, mirror van het bestaande
  // relTarget-patroon hieronder (api.search + pijltjes/Enter). `initial.parent`
  // vult voor (Dupliceer/"Subtaak toevoegen"); de gebruiker kan het wissen of
  // wijzigen vóórdat hij aanmaakt.
  let parentRef = $state(initial.parent ?? "");
  let parentMatches = $state([]);
  let parentActive = $state(0);
  let parentSearchTimer = null;
  let parentSearchSeq = 0; // race-guard: alleen het nieuwste zoekresultaat tonen

  function toggleLabel(name) { selectedLabels = toggleSelection(selectedLabels, name); }

  // Uitgestelde relatie (BETON-247): een relatie vereist een bestaand ref,
  // dat er bij een nieuw ticket nog niet is. We verzamelen de gekozen
  // relatie(s) lokaal en leggen ze pas ná `api.createItem` met
  // `api.addRelation(created.ref, type, target)` — zelfde uitgestelde
  // patroon als de afbeelding-upload hieronder.
  let relType = $state("relates_to");
  let relTarget = $state("");
  let relMatches = $state([]);
  let relActive = $state(0);
  let relInput = $state();
  // Duplicaat-relatie (BETON-373): "Dupliceer" legt hem meteen naar het
  // origineel, dezelfde uitgestelde-relatie-flow als een handmatig gekozen
  // relatie hieronder — de gebruiker kan hem vóór aanmaken weer intrekken.
  let nextRelId = 0;
  let pendingRelations = $state(
    initial.relatesTo ? [{ id: nextRelId++, type: "relates_to", target: initial.relatesTo }] : [],
  ); // {id, type, target}

  function onRelInput(e) { return relPicker.input(e); }

  function onRelKeydown(e) { return relPicker.keydown(e); }

  function pickRelTarget(targetRef) { return relPicker.pick(targetRef); }

  function addPendingRelation() {
    const target = relTarget.trim();
    if (!target) return;
    pendingRelations = [...pendingRelations, { id: nextRelId++, type: relType, target }];
    relTarget = "";
    relPicker.close();
  }

  function removePendingRelation(id) {
    pendingRelations = pendingRelations.filter((r) => r.id !== id);
  }

  // --- Subtaak van (BETON-363) --------------------------------------------

  function onParentInput(e) {
    parentRef = e.currentTarget.value;
    const q = parentRef.trim();
    clearTimeout(parentSearchTimer);
    if (q.length < 2) {
      parentMatches = [];
      return;
    }
    parentSearchTimer = setTimeout(() => searchParentTargets(q), 150);
  }

  async function searchParentTargets(q) {
    const seq = ++parentSearchSeq;
    try {
      const rows = await api.search(q, 6);
      if (seq !== parentSearchSeq) return; // ouder antwoord: negeren
      parentMatches = rows;
      parentActive = 0;
    } catch (e) {
      if (seq !== parentSearchSeq) return; // ouder antwoord: negeren
      parentMatches = [];
      error = $t("ticket.parentSearchFailed", {error: e.message});
    }
  }

  function onParentKeydown(e) {
    if (!parentMatches.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      parentActive = (parentActive + 1) % parentMatches.length;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      parentActive = (parentActive - 1 + parentMatches.length) % parentMatches.length;
    } else if (e.key === "Enter") {
      e.preventDefault();
      pickParentTarget(parentMatches[parentActive].ref);
    } else if (e.key === "Escape") {
      parentMatches = [];
    }
  }

  function pickParentTarget(targetRef) {
    parentRef = targetRef;
    parentMatches = [];
  }

  // @mention-autocomplete op de omschrijving (BETON-102), mirror van
  // Drawer.svelte's comment-mentions (mentionQuery/applyMention uit
  // lib/board.js, hier hergebruikt via lib/mentionAutocomplete.js).
  let descTextarea = $state();
  let caret = $state(0);
  let mentionMatches = $state([]);
  let mentionActive = $state(0);
  // #-autocomplete voor ticket-refs (BETON-254), mirror van de mention-flow:
  // los van @mentions maar op dezelfde textarea (hoogstens één actief token).
  let hashMatches = $state([]);
  let hashActive = $state(0);

  // Inline afbeelding-plakken (BETON-256), gelijkgetrokken met de Drawer: een
  // attachment hangt echter altijd aan een bestaand item (`POST
  // /items/{ref}/attachments`) en dat item bestaat pas ná `api.createItem`.
  // In plaats van de afbeelding als losse chip te tonen en de markdown pas ná
  // het aanmaken achteraan te plakken (het oude gedrag), zetten we bij
  // plakken/slepen DIRECT een placeholder-markdown-regel op de caretpositie
  // (`lib/newItemImages.js:imagePlaceholder`). Ná `api.createItem` wordt elke
  // placeholder geüpload en op precies diezelfde plek vervangen door de echte
  // `![filename](url)` (`resolvePlaceholder`) — het "inline"-gevoel blijft dus
  // ook al is de daadwerkelijke upload noodgedwongen uitgesteld.
  //
  // BETON-259 (regressie van BETON-256): de thumbnail-preview verviel omdat
  // een attachment-URL pas ná upload bestaat. Maar een LOKALE preview kan
  // wél vóór upload — via `URL.createObjectURL(file)`, exact zoals vóór
  // BETON-256. Die object-URL wordt nooit naar de server gestuurd (alleen
  // gebruikt voor de `<img>` in de pending-lijst) en moet worden gerevoked
  // zodra hij niet meer nodig is (verwijderen, of ná aanmaken/resetState) om
  // geen geheugen te lekken.
  let pendingImages = $state([]); // { id, file, placeholder, url }
  let fileInput = $state();
  let nextImgId = 0;

  async function addImagesAt(fileList, pos) {
    const files = imageFilesFromFileList(fileList);
    if (!files.length) return;
    let at = pos;
    for (const file of files) {
      const id = nextImgId++;
      const img = buildPendingImage(file, id);
      description = insertAt(description, at, img.placeholder);
      at = (at ?? description.length) + img.placeholder.length;
      pendingImages = [...pendingImages, img];
    }
    await tick();
    caret = at;
    descTextarea?.focus();
    descTextarea?.setSelectionRange(at, at);
  }

  function removePendingImage(id) {
    const img = pendingImages.find((p) => p.id === id);
    if (!img) return;
    description = removePlaceholder(description, img.placeholder);
    URL.revokeObjectURL(img.url);
    pendingImages = pendingImages.filter((p) => p.id !== id);
  }

  // Vangnet naast resetState(): na een geslaagd aanmaken sluit App.svelte de
  // overlay direct (`closeOverlayNamed("new")`), wat dit component unmount
  // zonder `onOpenChange`/`resetState` te passeren. Zonder dit zouden de
  // object-URL's van nog niet expliciet verwijderde pending-afbeeldingen
  // blijven lekken.
  onDestroy(() => {
    for (const img of pendingImages) URL.revokeObjectURL(img.url);
  });

  // Zolang de afbeeldingen ná het aanmaken nog uploaden, waarschuwt de browser
  // bij herladen/sluiten (BETON-435). App sluit de dialog pas in `oncreated`,
  // dus ná de uploads; sluit de gebruiker hem zelf eerder, dan vervalt de
  // waarschuwing met de component (de omschrijving is dan nog steeds schoon).
  let uploading = $state(false);
  $effect(() => {
    if (!uploading) return;
    const warn = (e) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  });

  function handleFileInput(e) {
    addImagesAt(e.currentTarget.files, descTextarea?.selectionStart ?? caret);
    e.currentTarget.value = ""; // zelfde bestand nog eens kunnen kiezen
  }

  // Sleep/plak op de omschrijving-textarea (mirror van Drawer.svelte's
  // imageFilesFrom): dataTransfer.files dekt slepen, clipboardData.items
  // dekt plakken van een screenshot.
  function imagesFromDataTransfer(e) {
    const dt = e.dataTransfer || e.clipboardData;
    if (!dt) return [];
    const out = imageFilesFromFileList(dt.files);
    if (!out.length && dt.items) {
      for (const it of dt.items) {
        if (it.kind === "file" && (it.type || "").startsWith("image/")) {
          const f = it.getAsFile();
          if (f) out.push(f);
        }
      }
    }
    return out;
  }

  function handleDescDrop(e) {
    const files = imagesFromDataTransfer(e);
    if (!files.length) return;
    e.preventDefault();
    addImagesAt(files, e.currentTarget?.selectionStart ?? caret);
  }

  // --- Gedeelde @mention/#ref-autocomplete (BETON-485) --------------------

  function onDescInput(e) { return descPicker.input(e); }

  function onDescKeydown(e) { return descPicker.keydown(e); }

  function pickMention(handle) { return descPicker.pickMention(handle); }

  function pickHashRef(ref) { return descPicker.pickHash(ref); }

  // Volledige lokale state terugzetten — nodig zodat een geannuleerd/gesloten
  // ticket geen restanten (autocomplete-popup, gekozen afbeeldingen, ingevoerde
  // tekst) achterlaat. Het component wordt door App.svelte weliswaar altijd
  // volledig ge-unmount na sluiten ({#if showNew}), maar de mention-popup mag
  // ook tijdens een eventuele sluit-animatie niet blijven hangen.
  function resetState() {
    title = "";
    description = "";
    stateName = defaultState;
    workload = "";
    assignee = "";
    dueDate = "";
    deferUntil = "";
    selectedLabels = [];
    milestone = "";
    error = "";
    busy = false;
    for (const img of pendingImages) URL.revokeObjectURL(img.url);
    pendingImages = [];
    mentionMatches = [];
    mentionActive = 0;
    descPicker.closeHash();
    hashMatches = [];
    hashActive = 0;
    caret = 0;
    moreOpen = defaults.moreOpen;
    relType = "relates_to";
    relTarget = "";
    relPicker.close();
    relActive = 0;
    pendingRelations = [];
    clearTimeout(parentSearchTimer);
    parentSearchSeq++;
    parentRef = "";
    parentMatches = [];
    parentActive = 0;
  }

  // Dialog dicht (Esc/overlay/close-knop/Annuleren) → alle lokale state
  // resetten en parent laten unmounten.
  function onOpenChange(v) {
    if (!v) {
      resetState();
      onclose?.();
    }
  }

  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    busy = true;
    error = "";
    // Zonder placeholders aanmaken (BETON-435): de PATCH hieronder zet de
    // afbeeldingen op hun plek. Valt die weg (pagina herladen), dan mist er
    // een afbeelding maar staat er geen dode ⏳-regel in de omschrijving.
    const createdDescription = stripPlaceholders(
      description,
      pendingImages.map((p) => p.placeholder)
    );
    const body = { title: title.trim(), description_md: createdDescription };
    if (stateName) body.state = stateName;
    if (workload) body.workload = workload;
    if (assignee) body.assignee = assignee;
    if (dueDate) body.due_date = dueDate;
    if (deferUntil) body.deferred_until = deferUntil;
    if (selectedLabels.length) body.labels = selectedLabels;
    if (milestone) body.milestone = milestone;
    if (parentRef.trim()) body.parent = parentRef.trim();
    try {
      const created = await api.createItem(projectKey, body);
      // Item bestaat nu — de gedeferreerde afbeeldingen alsnog uploaden en de
      // placeholders in de omschrijving vervangen door de echte inline
      // `![filename](url)` (BETON-256, mirror van de Drawer-flow: `resolvePlaceholder`
      // zet de markdown op precies dezelfde plek als waar geplakt/gesleept
      // werd, i.p.v. achteraan). Een upload-fout blokkeert de rest niet: het
      // ticket blijft gewoon bestaan, we melden alleen welke afbeelding(en)
      // niet meekwamen (en halen de kapotte placeholder uit de tekst).
      if (pendingImages.length) {
        uploading = true;
        let nextDescription = description;
        const failed = [];
        for (const img of pendingImages) {
          try {
            const att = await api.uploadAttachment(created.ref, img.file);
            nextDescription = resolvePlaceholder(nextDescription, img.placeholder, attachmentMarkdown(att));
          } catch {
            failed.push(img.file.name);
            nextDescription = removePlaceholder(nextDescription, img.placeholder);
          }
        }
        if (nextDescription !== createdDescription) {
          try {
            await api.updateItem(created.ref, { description_md: nextDescription });
          } catch (err) {
            failed.push($t("ticket.updateFailed", {error: err.message}));
          }
        }
        uploading = false;
        if (failed.length) {
          onerror?.(
            $t("ticket.imagesFailed", {ref: created.ref, errors: failed.join(", ")})
          );
        }
      }
      // Uitgestelde relaties (BETON-247): pas ná het aanmaken kan `type/target`
      // echt gelegd worden (relaties hangen aan een bestaand ref). Eén relatie
      // mislukt blokkeert de andere(n) niet.
      if (pendingRelations.length) {
        const relFailed = [];
        for (const rel of pendingRelations) {
          try {
            await api.addRelation(created.ref, rel.type, rel.target);
          } catch (err) {
            relFailed.push(`${relationLabel(rel.type, $locale)} → ${rel.target} (${err.message})`);
          }
        }
        if (relFailed.length) {
          onerror?.(
            $t("ticket.relationsFailed", {ref: created.ref, errors: relFailed.join(", ")})
          );
        }
      }
      oncreated?.(created);
    } catch (err) {
      error = err.message;
      busy = false;
    }
  }
  const descPicker = textPicker({
    get: () => ({ text: description, caret: caret, mentionMatches: mentionMatches, mentionActive: mentionActive, hashMatches: hashMatches, hashActive: hashActive }),
    set: (patch) => {
      if ("text" in patch) description = patch.text;
      if ("caret" in patch) caret = patch.caret;
      if ("mentionMatches" in patch) mentionMatches = patch.mentionMatches;
      if ("mentionActive" in patch) mentionActive = patch.mentionActive;
      if ("hashMatches" in patch) hashMatches = patch.hashMatches;
      if ("hashActive" in patch) hashActive = patch.hashActive;
    },
    users: () => users, project: () => projectKey, api, tick,
    textarea: () => descTextarea, localEscape: true,
  });
  const relPicker = relationPicker({
    get: () => ({ target: relTarget, matches: relMatches, active: relActive }),
    set: (patch) => {
      if ("target" in patch) relTarget = patch.target;
      if ("matches" in patch) relMatches = patch.matches;
      if ("active" in patch) relActive = patch.active;
    },
    project: () => projectKey, api, tick,
    textarea: () => relInput, add: () => addPendingRelation(),
    onerror: (e) => { error = $t("ticket.relationSearchFailed", {error: e.message}); },
    localEscape: true,
  });
  onDestroy(() => { descPicker.close(); relPicker.close(); });
</script>

<Dialog.Root bind:open {onOpenChange}>
  <Dialog.Portal>
    <Dialog.Overlay class="modal-overlay" />
    <Dialog.Content class="modal">
      <div class="modal-head">
        <Dialog.Title class="modal-title">{$t("ticket.new")}</Dialog.Title>
        <Dialog.Close class="icon-btn" aria-label={$t("common.close")}>
          <X size={18} />
        </Dialog.Close>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
      <form onsubmit={submit}>
        <label class="field">
          <span>{$t("ticket.title")}</span>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            bind:value={title}
            placeholder={$t("ticket.short")}
            autofocus
            onkeydown={(e) => {
              // Cmd/Ctrl+Enter maakt het ticket ook vanuit de titel aan (BETON-440).
              if (isSubmitChord(e)) submit(e);
            }}
          />
        </label>
        <label class="field">
          <span>{$t("ticket.description")}</span>
          <MarkdownEditor
            bind:textareaRef={descTextarea}
            value={description}
            rows={5}
            placeholder={$t("ticket.markdown")}
            {knownHandles}
            {projectKeys}
            oninput={onDescInput}
            onsubmit={() => submit(new Event("submit"))}
            onpaste={handleDescDrop}
            ondragover={(e) => e.preventDefault()}
            ondrop={handleDescDrop}
            onkeydown={onDescKeydown}
          >
            {#snippet dropdown()}
              <PickerSuggestions mentions={mentionMatches} tickets={hashMatches} mentionActive={mentionActive} ticketActive={hashActive} onmention={pickMention} onticket={pickHashRef} />
            {/snippet}
          </MarkdownEditor>
          {#if pendingImages.length}
            <!-- De echte attachment-URL bestaat pas ná upload (BETON-256: die
                 hangt aan een item dat pas ná aanmaken bestaat), maar een
                 LOKALE preview kan wél vóór upload via
                 `URL.createObjectURL(file)` (BETON-259) — dat is deze
                 thumbnail. De placeholder-markdown in de tekst hierboven
                 blijft de inline plek voor ná aanmaken. -->
            <ul class="pending-images">
              {#each pendingImages as img (img.id)}
                <li class="pending-image">
                  <img class="pending-image-thumb" src={img.url} alt={img.file.name} />
                  <button
                    type="button"
                    class="icon-btn pending-image-remove"
                    onclick={() => removePendingImage(img.id)}
                    title={$t("common.remove")}
                    aria-label={$t("ticket.removeImage")}
                  >
                    <X size={13} />
                  </button>
                </li>
              {/each}
            </ul>
          {/if}
        </label>
        {#if assignShortcuts.length}
          <div class="quick-assign" aria-label={$t("ticket.quickAssign")}>
            {#each assignShortcuts as target (target.handle)}
              <button type="button" class="sm" disabled={busy} onclick={() => (assignee = target.handle)}>{target.label}</button>
            {/each}
          </div>
        {:else if assignee === "coding-agent"}
          <p class="quick-assign muted" role="status">{$t("ticket.assignedQueue")}</p>
        {/if}
        {#if defaults.showTriageHint}
          <p class="hint muted">{$t("ticket.triageHint")}</p>
        {/if}
        <div class="modal-foot">
          <Dialog.Close type="button" class="ghost">{$t("common.cancel")}</Dialog.Close>
          <button class="primary" type="submit" disabled={busy || !title.trim()}>
            {$t("ticket.create")}
          </button>
        </div>

        <Collapsible.Root bind:open={moreOpen} class="more-options">
          <Collapsible.Trigger type="button" class="more-toggle">
            {#if moreOpen}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}
            {$t("ticket.more")}
          </Collapsible.Trigger>
          <Collapsible.Content class="more-content">
            <div class="field-row">
              <Field label={$t("ticket.assignee")}>
                <AssigneeSelect
                  value={assignee}
                  {users}
                  {me}
                  allowNone="—"
                  onchange={(v) => (assignee = v)}
                />
              </Field>
              <Field label={$t("ticket.due")}>
                <input type="date" bind:value={dueDate} />
              </Field>
              <Field label={$t("ticket.defer")}>
                <input type="date" bind:value={deferUntil} />
              </Field>
            </div>
            <div class="field">
              <span>{$t("ticket.state")}</span>
              <SegmentedControl
                ariaLabel={$t("ticket.state")}
                options={stateOpts}
                value={stateName}
                onchange={(v) => (stateName = v)}
              />
            </div>
            <div class="field">
              <span>{$t("ticket.workload")}</span>
              <SegmentedControl
                ariaLabel={$t("ticket.workload")}
                options={workloadOpts}
                value={workload}
                onchange={(v) => (workload = v)}
              />
            </div>
            {#if milestones.length}
              <Field label={$t("ticket.milestone")}>
                <Select
                  bind:value={milestone}
                  options={[
                    { value: "", label: $t("ticket.noMilestone") },
                    ...milestones.map((m) => ({ value: m.name, label: m.name })),
                  ]}
                />
              </Field>
            {/if}
            <div class="field">
              <span>{$t("ticket.parent")}</span>
              <div class="rel-box">
                <input
                  class="rel-target"
                  placeholder={$t("ticket.refHint")}
                  value={parentRef}
                  oninput={onParentInput}
                  onkeydown={onParentKeydown}
                  role="combobox"
                  aria-expanded={parentMatches.length > 0}
                  aria-controls="parent-suggest-new"
                  autocomplete="off"
                />
                {#if parentMatches.length}
                  <ul class="mention-list" id="parent-suggest-new">
                    {#each parentMatches as m, i}
                      <li
                        role="option"
                        aria-selected={i === parentActive}
                        class:active={i === parentActive}
                        onclick={() => pickParentTarget(m.ref)}
                      >
                        <span class="rel-suggest-ref">{m.ref}</span>
                        <span class="muted">{m.title}</span>
                      </li>
                    {/each}
                  </ul>
                {/if}
              </div>
            </div>
            {#if projectLabels.length}
              <div class="field">
                <span>{$t("ticket.labels")}</span>
                <div class="label-picker">
                  {#each projectLabels as l}
                    <Chip
                      tone="label"
                      hue={labelHueOf(l.name)}
                      selected={selectedLabels.includes(l.name)}
                      onclick={() => toggleLabel(l.name)}
                    >
                      {l.name}
                    </Chip>
                  {/each}
                </div>
              </div>
            {/if}
            <div class="field">
              <span>{$t("ticket.relation")}</span>
              {#if pendingRelations.length}
                <ul class="rel-pending-list">
                  {#each pendingRelations as rel (rel.id)}
                    <li class="rel-chip">
                      <span class="rel-type-tag">{relationLabel(rel.type, $locale)}</span>
                      <span class="rel-chip-target">{rel.target}</span>
                      <button
                        type="button"
                        class="rel-x"
                        title={$t("common.remove")}
                        aria-label={$t("ticket.removeRelation")}
                        onclick={() => removePendingRelation(rel.id)}
                      >
                        <X size={12} />
                      </button>
                    </li>
                  {/each}
                </ul>
              {/if}
              <div class="rel-add">
                <Select
                  ariaLabel={$t("ticket.relationType")}
                  bind:value={relType}
                  options={RELATION_TYPES.map((t) => ({ value: t, label: relationLabel(t, $locale) }))}
                />
                <div class="rel-box">
                  <input
                    bind:this={relInput}
                    class="rel-target"
                    placeholder={$t("ticket.refHint")}
                    value={relTarget}
                    oninput={onRelInput}
                    onkeydown={onRelKeydown}
                    role="combobox"
                    aria-expanded={relMatches.length > 0}
                    aria-controls="rel-suggest-new"
                    autocomplete="off"
                  />
                  <PickerSuggestions id="rel-suggest-new" tickets={relMatches} ticketActive={relActive} onticket={pickRelTarget} />
                </div>
                <button class="sm" type="button" onclick={addPendingRelation}>{$t("common.add")}</button>
              </div>
            </div>
            <div class="field">
              <span>{$t("ticket.image")}</span>
              <input
                bind:this={fileInput}
                type="file"
                accept="image/*"
                multiple
                class="visually-hidden"
                tabindex="-1"
                onchange={handleFileInput}
              />
              <div class="upload-row">
                <button
                  class="sm img-upload-btn"
                  type="button"
                  onclick={() => fileInput?.click()}
                  title={$t("ticket.imageHint")}
                >
                  <ImagePlus size={14} /> {$t("ticket.image")}
                </button>
                {#if pendingImages.length}
                  <span class="muted upload-hint">
                    {$t("ticket.pendingImages", {count: pendingImages.length})}
                  </span>
                {/if}
              </div>
            </div>
          </Collapsible.Content>
        </Collapsible.Root>
      </form>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  .quick-assign {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
  /* .full verhuisde naar MarkdownEditor.svelte (BETON-365) — de textarea
     leeft daar nu. */
  /* Uitgestelde afbeelding-upload (BETON-78) — mirror van de visueel
     verborgen file-input + upload-knop in Drawer.svelte. */
  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
  .upload-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
  }
  .img-upload-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .upload-hint {
    font-size: var(--text-sm);
  }
  /* De afbeelding staat al inline als placeholder-markdown in de omschrijving
     (BETON-256); daarnaast een zichtbare thumbnail-galerij (BETON-259,
     `URL.createObjectURL`, de echte attachment-URL bestaat pas ná upload). */
  .pending-images {
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 8px 0 0;
    padding: 0;
  }
  .pending-image {
    position: relative;
    width: 72px;
    height: 72px;
  }
  .pending-image-thumb {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: var(--radius-md);
    border: 1px solid var(--border);
  }
  .pending-image-remove {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 20px;
    height: 20px;
    min-height: 0;
    padding: 0;
    border-radius: var(--radius-full);
    background: var(--surface);
    border: 1px solid var(--border-strong);
  }
  .label-picker {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
</style>
