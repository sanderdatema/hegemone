<script>
  import { t as tr, locale } from "./lib/i18n.js";
  import WikiReview from "./WikiReview.svelte";
  import { tick } from "svelte";
  import { api } from "./api.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import { isSubmitChord, formatTimestamp, absoluteTime } from "./lib/board.js";
  import {
    filterWikiPages,
    wikiBacklinks,
    wikiLinkQuery,
    wikiSlugSuggestions,
  } from "./lib/wikiText.js";
  import { renderWikiMarkdown } from "./lib/markdown.js";
  import ImageLightbox from "./ImageLightbox.svelte";
  import { lightboxClicks } from "./lib/lightbox.js";
  let lightboxImage = $state(null);
  import { lineDiff, diffStat } from "./lib/diff.js";
  import {
    BookOpen,
    Plus,
    Pencil,
    Trash2,
    Search,
    ArrowLeft,
    PanelLeft,
    History,
    RotateCcw,
    X,
  } from "@lucide/svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import ConfirmBar from "./ConfirmBar.svelte";
  import DiffView from "./DiffView.svelte";

  // `onswitchproject(key)` wisselt het actieve project op app-niveau — nodig
  // om een wikilink naar een ánder project dan het geselecteerde te kunnen
  // volgen (BETON-306); zonder die callback blijft zo'n link binnen de view.
  let { project, projectName, projectArchived = false, me, onclose, onopenref, onswitchproject, liveTick = 0 } = $props();

  // Bekende project-keys, voor het klikbaar maken van ticketrefs (BETON-106).
  let projectKeys = $state([]);
  api
    .projects()
    .then((ps) => (projectKeys = ps.map((p) => p.key)))
    .catch(() => {});

  // scope: 'global' of 'project'. Zonder project altijd globaal.
  let scope = $state(project ? "project" : "global");
  let projectReadOnly = $derived(scope === "project" && projectArchived);
  let pages = $state([]);
  let selected = $state(null); // huidige slug
  let editing = $state(false);
  let creating = $state(false);
  let titleDraft = $state("");
  let bodyDraft = $state("");
  let slugDraft = $state("");
  let confirmDelete = $state(false);
  let error = $state("");
  let loading = $state(false);
  let query = $state(""); // zoekterm boven de paginalijst
  let createPrompt = $state(""); // slug uit een dode wikilink → "aanmaken?"
  let createPromptScope = $state(""); // scope van die dode link (BETON-306)
  let articleEl = $state(null); // artikel-container (focus bij openen)

  // Edit-history (BETON-209): timeline naast het artikel + diff/restore.
  let showHistory = $state(false);
  let revisions = $state([]);
  let historyLoading = $state(false);
  let revDetail = $state(null); // {revision, previous} als een revisie bekeken wordt
  let restoreConfirm = $state(false);

  // [[-autocomplete in de editor-textarea.
  let editorEl = $state(null);
  let acOpen = $state(false);
  let acItems = $state([]);
  let acIndex = $state(0);
  let acStart = $state(0);

  const scopeKey = $derived(scope === "global" ? null : project);
  // BETON-306: de scope als string ("global" of een project-key) — voor het
  // resolven van kale interlinks en het meegeven aan de renderer/navigatie.
  const currentScope = $derived(scope === "global" ? "global" : project);
  const current = $derived(pages.find((p) => p.slug === selected) || null);
  const visiblePages = $derived(filterWikiPages(pages, query));
  // Cross-scope index voor levend/dood-markering (BETON-306): keys "<scope> <slug>".
  let wikiIndex = $state([]);
  const knownRefs = $derived(new Set(wikiIndex.map((r) => `${r.scope} ${r.slug}`)));
  const backlinks = $derived(
    current ? wikiBacklinks(pages, current.slug, currentScope, knownRefs) : [],
  );
  // Diff van de bekeken revisie t.o.v. z'n voorganger (eerste revisie → alles add).
  const diffSegments = $derived(
    revDetail ? lineDiff(revDetail.previous?.body_md ?? "", revDetail.revision.body_md) : [],
  );
  const diffTotals = $derived(diffStat(diffSegments));
  // Welk paneel toont op smalle schermen: de zijbalk (lijst), het artikel/diff, of
  // de geschiedenis-timeline. Een bekeken revisie (diff) toont in het hoofdpaneel.
  const pane = $derived(
    revDetail
      ? "main"
      : showHistory && current && !creating
        ? "history"
        : current || creating
          ? "main"
          : "nav",
  );

  async function load() {
    loading = true;
    error = "";
    try {
      pages = await api.wikiList(scopeKey);
      // BETON-306: cross-scope index parallel ophalen voor de levend/dood-markering.
      wikiIndex = await api.wikiIndex().catch(() => wikiIndex);
      if (!pages.find((p) => p.slug === selected)) selected = null;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    // Herlaad bij scope-wissel én bij projectwissel (topbar-selector).
    scope;
    project;
    query = "";
    resetForm();
    load();
  });

  function resetForm() {
    editing = false;
    creating = false;
    confirmDelete = false;
    createPrompt = "";
    acOpen = false;
  }

  // Zet de geschiedenis-weergave terug (bij paginawissel/scope-wissel/edit).
  function resetHistory() {
    showHistory = false;
    revDetail = null;
    restoreConfirm = false;
    revisions = [];
  }

  async function open(slug, targetScope = currentScope) {
    // BETON-306: cross-scope navigatie. Wissel zo nodig van scope; het
    // scope-`$effect` herlaadt dan de pagina's van de nieuwe scope. Een link
    // naar een ánder project vergt een projectwissel op app-niveau
    // (`onswitchproject`) — zonder die stap landde je op een lege pagina,
    // precies de flow die vanuit de globale wiki gemeld werd.
    if (targetScope !== currentScope) {
      if (targetScope === "global") scope = "global";
      else if (targetScope === project) scope = "project";
      else if (onswitchproject) {
        await onswitchproject(targetScope);
        scope = "project";
      } else {
        error = $tr("wiki.openProject", {project: targetScope});
        return;
      }
    }
    selected = slug;
    resetForm();
    resetHistory();
    // A11y: verplaats focus naar het artikel zodat toetsenbordgebruikers
    // meteen in de gekozen pagina zitten (geen focus-trap: dit is een view).
    await tick();
    articleEl?.focus();
  }

  // Terug naar de paginalijst (vooral op smalle schermen).
  function backToList() {
    selected = null;
    resetForm();
    resetHistory();
  }

  async function loadHistory() {
    if (!current) return;
    historyLoading = true;
    try {
      revisions = await api.wikiRevisions(scopeKey, current.slug);
    } catch (e) {
      error = e.message;
    } finally {
      historyLoading = false;
    }
  }

  async function toggleHistory() {
    revDetail = null;
    restoreConfirm = false;
    showHistory = !showHistory;
    if (showHistory) await loadHistory();
  }

  async function openRevision(id) {
    restoreConfirm = false;
    try {
      revDetail = await api.wikiRevision(scopeKey, current.slug, id);
    } catch (e) {
      error = e.message;
    }
  }

  function closeRevision() {
    revDetail = null;
    restoreConfirm = false;
  }

  async function restoreRevision() {
    if (projectReadOnly) return;
    if (!revDetail) return;
    try {
      await api.wikiRestore(scopeKey, current.slug, revDetail.revision.id);
      await load(); // pagina-inhoud is nu teruggezet
      await loadHistory(); // de restore-revisie verschijnt bovenaan
      revDetail = null;
      restoreConfirm = false;
    } catch (e) {
      error = e.message;
    }
  }

  // Een wikilink activeren (klik of Enter/Space). Een dode link (naar een
  // niet-bestaande pagina) opent de "aanmaken?"-flow i.p.v. een foutmelding.
  function activateWikiLink(link) {
    const slug = link.getAttribute("data-wiki");
    if (!slug) return;
    // BETON-306: de resolved scope zit op het anker; navigeer/creëer daar.
    const linkScope = link.getAttribute("data-wiki-scope") || currentScope;
    if (link.getAttribute("data-wiki-dead") === "true") {
      createPrompt = slug;
      createPromptScope = linkScope;
    } else {
      createPrompt = "";
      open(slug, linkScope);
    }
  }

  // "Aanmaken?" vanuit een dode (mogelijk gekwalificeerde) link: maak de pagina
  // in de scope van de link, niet in de huidige weergave (BETON-306) — anders
  // ontstaat een duplicaat in de verkeerde scope. Een ánder project bereiken we
  // via de projectwissel op app-niveau, net als bij `open`.
  async function startCreateFromPrompt() {
    if (projectReadOnly) return;
    const slug = createPrompt;
    const target = createPromptScope || currentScope;
    if (target !== currentScope) {
      if (target === "global") scope = "global";
      else if (target === project) scope = "project";
      else if (onswitchproject) {
        await onswitchproject(target);
        scope = "project";
      } else {
        error = $tr("wiki.createInProject", {project: target});
        createPrompt = "";
        return;
      }
      await tick(); // laat het scope-$effect de pagina's van de nieuwe scope laden
    }
    startCreate(slug);
  }

  // Een ticketref activeren (klik of Enter/Space): laat App het ticket openen
  // (wisselt zo nodig van project + opent de drawer) en verlaat de wiki-view.
  // De app routeert op pad (/KEY/seq), niet op #hash — vandaar de callback
  // i.p.v. location.hash (BETON-106/107 fix).
  function activateTicketLink(link) {
    const ref = link.getAttribute("data-ticket");
    if (!ref) return;
    onopenref?.(ref);
    onclose?.();
  }

  function onWikiClick(e) {
    const ticket = e.target.closest?.("[data-ticket]");
    if (ticket) {
      e.preventDefault();
      activateTicketLink(ticket);
      return;
    }
    const link = e.target.closest?.("[data-wiki]");
    if (!link) return;
    e.preventDefault();
    activateWikiLink(link);
  }

  // Toegankelijkheid: een wikilink/ticketlink is focusbaar (tabindex) en met
  // Enter/Space te activeren, niet alleen met de muis.
  function onWikiKeydown(e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    const ticket = e.target.closest?.("[data-ticket]");
    if (ticket) {
      e.preventDefault();
      activateTicketLink(ticket);
      return;
    }
    const link = e.target.closest?.("[data-wiki]");
    if (!link) return;
    e.preventDefault();
    activateWikiLink(link);
  }

  function startEdit() {
    if (projectReadOnly) return;
    if (!current) return;
    // Verlaat een eventuele diff-weergave: bewerken gaat over de huidige inhoud.
    revDetail = null;
    restoreConfirm = false;
    titleDraft = current.title;
    bodyDraft = current.body_md;
    editing = true;
  }

  function startCreate(slug = "") {
    if (projectReadOnly) return;
    creating = true;
    editing = false;
    selected = null;
    createPrompt = "";
    titleDraft = slug;
    bodyDraft = "";
    slugDraft = slug;
  }

  // --- [[-autocomplete -------------------------------------------------------
  function onEditorInput() {
    const el = editorEl;
    if (!el) return;
    const q = wikiLinkQuery(bodyDraft, el.selectionStart);
    if (!q) {
      acOpen = false;
      return;
    }
    const items = wikiSlugSuggestions(pages, q.query);
    if (!items.length) {
      acOpen = false;
      return;
    }
    acItems = items;
    acIndex = 0;
    acStart = q.start;
    acOpen = true;
  }

  async function insertSuggestion(slug) {
    const el = editorEl;
    const caret = el ? el.selectionStart : bodyDraft.length;
    const before = bodyDraft.slice(0, acStart);
    const after = bodyDraft.slice(caret);
    const insert = `[[${slug}]]`;
    bodyDraft = before + insert + after;
    acOpen = false;
    const pos = before.length + insert.length;
    await tick();
    if (el) {
      el.focus();
      el.setSelectionRange(pos, pos);
    }
  }

  function onEditorKeydown(e) {
    if (acOpen && acItems.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        acIndex = (acIndex + 1) % acItems.length;
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        acIndex = (acIndex - 1 + acItems.length) % acItems.length;
        return;
      }
      if (e.key === "Enter" && !isSubmitChord(e)) {
        e.preventDefault();
        insertSuggestion(acItems[acIndex].slug);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        acOpen = false;
        return;
      }
    }
  }

  let saving = false; // dubbele Cmd+Enter mag niet dubbel opslaan (BETON-462)
  async function saveEdit() {
    if (projectReadOnly) return;
    if (saving) return;
    saving = true;
    try {
      await api.wikiUpdate(scopeKey, current.slug, {
        title: titleDraft,
        body_md: bodyDraft,
      });
      editing = false;
      await load();
      if (showHistory) await loadHistory(); // nieuwe revisie in de timeline
    } catch (e) {
      error = e.message;
    } finally {
      saving = false;
    }
  }

  async function saveCreate() {
    if (projectReadOnly) return;
    const slug = (slugDraft || titleDraft).trim();
    if (!slug || !titleDraft.trim()) {
      error = $tr("wiki.validation");
      return;
    }
    if (saving) return;
    saving = true;
    try {
      const created = await api.wikiCreate(scopeKey, {
        slug,
        title: titleDraft.trim(),
        body_md: bodyDraft,
      });
      creating = false;
      await load();
      selected = created.slug;
    } catch (e) {
      error = e.message;
    } finally {
      saving = false;
    }
  }

  async function doDelete() {
    if (projectReadOnly) return;
    try {
      await api.wikiDelete(scopeKey, current.slug);
      confirmDelete = false;
      selected = null;
      await load();
    } catch (e) {
      error = e.message;
    }
  }

  // Escape sluit de wiki-view (terug naar het bord) — tenzij je in een veld
  // typt of een sub-flow (editor/[[-autocomplete/confirm) open is; die vangen
  // Escape zelf af. Geen focus-trap: dit is een volwaardige view, geen modal.
  function onViewKeydown(e) {
    if (e.key !== "Escape") return;
    const t = e.target;
    const typing =
      t &&
      (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    if (typing || acOpen || editing || creating || confirmDelete) return;
    onclose?.();
  }
</script>

<svelte:window onkeydown={onViewKeydown} />

<section
  class="wiki-view"
  class:with-history={showHistory && current && !creating}
  aria-label="Wiki"
>
  <!-- Navigatie-zijbalk: scope, zoeken, paginalijst, nieuwe pagina. -->
  <aside class="wiki-nav" class:mobile-hidden={pane !== "nav"}>
    <header class="wiki-nav-head">
      <span class="wiki-brand"><BookOpen size={18} /> Wiki</span>
      <button class="link wiki-back" onclick={() => onclose?.()}>
        <ArrowLeft size={15} /> {$tr("wiki.board")}
      </button>
    </header>

    {#if project}
      <SegmentedControl
        variant="soft"
        itemAria="pressed"
        ariaLabel={$tr("wiki.scope")}
        value={scope}
        onchange={(v) => (scope = v)}
        options={[
          { value: "global", label: $tr("wiki.global") },
          { value: "project", label: projectName || project },
        ]}
      />
    {/if}

    <div class="wiki-search">
      <Search size={15} class="wiki-search-icon" />
      <input
        class="wiki-search-input"
        type="search"
        bind:value={query}
        placeholder={$tr("wiki.searchHint")}
        aria-label={$tr("wiki.search")}
      />
    </div>

    <button disabled={projectReadOnly} class="wiki-new" onclick={() => startCreate()}>
      <Plus size={15} /> {$tr("wiki.new")}
    </button>

    <nav class="wiki-list" aria-label={$tr("wiki.pages")}>
      {#each visiblePages as p (p.slug)}
        <button class="wiki-row" class:active={p.slug === selected} onclick={() => open(p.slug)}>
          <span class="wiki-row-title">{p.title}</span>
          <span class="wiki-row-meta">
            <span class="wiki-row-slug">{p.slug}</span>
            {#if p.updated_at}
              <span class="wiki-row-dot" aria-hidden="true">·</span>
              <span class="wiki-row-time" title={$tr("wiki.changedAt", {time: absoluteTime(p.updated_at, $locale)})}>
                {formatTimestamp(p.updated_at, Date.now(), $locale)}
              </span>
            {/if}
          </span>
        </button>
      {:else}
        {#if !loading}
          <p class="muted wiki-empty">
            {query.trim()
              ? $tr("wiki.noSearch", {query: query.trim()})
              : $tr("wiki.noPages")}
          </p>
        {/if}
      {/each}
    </nav>
  </aside>

  <!-- Hoofdinhoud: het geselecteerde artikel, de editor of een lege staat. -->
  <main class="wiki-main" class:mobile-hidden={pane !== "main"}>
    {#if projectReadOnly}<p class="project-readonly-note" role="status">{$tr("api.project_archived_readonly")}</p>{/if}
    {#if error}<p class="error wiki-error">{error}</p>{/if}
    {#if me?.kind === "human"}
      <WikiReview readOnly={projectReadOnly} project={scopeKey} {liveTick} onchanged={load} />
    {/if}

    {#if creating}
      <div class="wiki-doc">
        <div class="wiki-editor-head">
          <button class="link wiki-tolist" onclick={backToList}>
            <PanelLeft size={15} /> {$tr("wiki.pages")}
          </button>
          <h2 class="wiki-doc-title">
            {$tr("wiki.newInScope", {scope: scope === "global" ? $tr("wiki.global") : projectName || project})}
          </h2>
        </div>
        <input disabled={projectReadOnly} class="full" bind:value={titleDraft} placeholder={$tr("wiki.title")} />
        <input disabled={projectReadOnly} class="full" bind:value={slugDraft} placeholder={$tr("wiki.slugHint")} />
        <div class="ac-wrap">
          <AutoTextarea disabled={projectReadOnly}
            class="full wiki-textarea"
            bind:textareaRef={editorEl}
            bind:value={bodyDraft}
            rows="16"
            placeholder={$tr("wiki.markdownCreate")}
            oninput={onEditorInput}
            onsubmit={saveCreate}
            onkeydown={onEditorKeydown}
          />
          {@render acDropdown()}
        </div>
        <div class="btn-row">
          <button class="sm" onclick={() => (creating = false)}>{$tr("common.cancel")}</button>
          <button disabled={projectReadOnly} class="primary sm" onclick={saveCreate}>{$tr("common.create")}</button>
        </div>
      </div>
    {:else if current}
      <article class="wiki-doc" tabindex="-1" bind:this={articleEl} aria-label={current.title}>
        <div class="wiki-doc-head">
          <button class="link wiki-tolist" onclick={backToList}>
            <PanelLeft size={15} /> {$tr("wiki.pages")}
          </button>
          <div class="wiki-actions">
            {#if !editing}
              <button
                class="icon-btn sm"
                class:active={showHistory}
                title={$tr("wiki.history")}
                aria-pressed={showHistory}
                onclick={toggleHistory}
              >
                <History size={16} />
              </button>
              <button disabled={projectReadOnly} class="icon-btn sm" title={$tr("wiki.edit")} onclick={startEdit}><Pencil size={16} /></button>
              {#if me?.kind === "human"}
                <button disabled={projectReadOnly} class="icon-btn sm danger-quiet" title={$tr("wiki.delete")} onclick={() => (confirmDelete = true)}>
                  <Trash2 size={16} />
                </button>
              {/if}
            {/if}
          </div>
        </div>

        {#if !editing}
          <header class="wiki-doc-title-wrap">
            <h1 class="wiki-doc-title">{current.title}</h1>
            <p class="muted">{$tr("wiki.source")}: {current.source_kind ?? $tr("wiki.existingKnowledge")} · {$tr(current.protected ? "wiki.protected" : "wiki.ordinary")}</p>
            {#if me?.kind === "human" && scopeKey}
              <button disabled={projectReadOnly} class="sm" onclick={async () => {
                try { await api.wikiProtect(scopeKey, current.slug, !current.protected); await load(); }
                catch (e) { error = e.message; }
              }}>{$tr(current.protected ? "wiki.unprotect" : "wiki.protect")}</button>
            {/if}
            <span class="wiki-doc-meta">
              <span class="wiki-doc-slug">{current.slug}</span>
              {#if current.updated_at}
                <span title={$tr("wiki.changedAt", {time: absoluteTime(current.updated_at, $locale)})}>
                  · {$tr("wiki.changed", {time: formatTimestamp(current.updated_at, Date.now(), $locale)})}
                </span>
              {/if}
            </span>
          </header>
        {/if}

        {#if confirmDelete}
          <ConfirmBar confirmDisabled={projectReadOnly}
            cancelLabel={$tr("common.cancel")}
            danger
            message={$tr("wiki.deleteQuestion", {slug: current.slug})}
            confirmLabel={$tr("wiki.yesDelete")}
            confirmClass="danger"
            onconfirm={doDelete}
            oncancel={() => (confirmDelete = false)}
          />
        {/if}

        {#if editing}
          <input disabled={projectReadOnly} class="full" bind:value={titleDraft} placeholder={$tr("wiki.title")} />
          <div class="ac-wrap">
            <AutoTextarea disabled={projectReadOnly}
              class="full wiki-textarea"
              bind:textareaRef={editorEl}
              bind:value={bodyDraft}
              rows="18"
              placeholder={$tr("wiki.markdownEdit")}
              oninput={onEditorInput}
              onsubmit={saveEdit}
              onkeydown={onEditorKeydown}
            />
            {@render acDropdown()}
          </div>
          <div class="btn-row">
            <button class="sm" onclick={() => (editing = false)}>{$tr("common.cancel")}</button>
            <button disabled={projectReadOnly} class="primary sm" onclick={saveEdit}>{$tr("common.save")}</button>
          </div>
        {:else if revDetail}
          <div class="rev-view">
            <div class="rev-banner">
              <div class="rev-banner-info">
                <span class="rev-who">
                  {revDetail.revision.author || $tr("wiki.unknown")}
                </span>
                <span
                  class="rev-when"
                  title={absoluteTime(revDetail.revision.created_at, $locale)}
                >
                  {formatTimestamp(revDetail.revision.created_at, Date.now(), $locale)}
                </span>
                <span class="rev-stat">
                  <span class="add">+{diffTotals.added}</span>
                  <span class="del">−{diffTotals.removed}</span>
                </span>
              </div>
              <div class="rev-banner-actions">
                {#if restoreConfirm}
                  <span class="rev-confirm-q">{$tr("wiki.restoreQuestion")}</span>
                  <button disabled={projectReadOnly} class="primary sm" onclick={restoreRevision}>{$tr("wiki.yesRestore")}</button>
                  <button disabled={projectReadOnly} class="sm" onclick={() => (restoreConfirm = false)}>{$tr("common.cancel")}</button>
                {:else}
                  <button disabled={projectReadOnly} class="sm" onclick={() => (restoreConfirm = true)}>
                    <RotateCcw size={14} /> {$tr("wiki.restore")}
                  </button>
                  <button class="icon-btn sm" title={$tr("wiki.closeDiff")} onclick={closeRevision}>
                    <X size={16} />
                  </button>
                {/if}
              </div>
            </div>
            {#if diffSegments.length}
              <DiffView
                segments={diffSegments}
                variant="bordered"
                ariaLabel={$tr("wiki.changes")}
              />
            {:else}
              <p class="muted">{$tr("wiki.noDifference")}</p>
            {/if}
          </div>
        {:else if current.body_md}
          <!-- eslint-disable-next-line svelte/no-at-html-tags — renderWikiMarkdown escapet -->
          <div class="wiki-article md" use:lightboxClicks={(img) => (lightboxImage = img)} onclick={onWikiClick} onkeydown={onWikiKeydown} role="presentation">
            {@html renderWikiMarkdown(current.body_md, knownRefs, projectKeys, currentScope)}
          </div>
        {:else}
          <p class="muted">{$tr("wiki.empty")}</p>
        {/if}

        {#if createPrompt}
          <ConfirmBar confirmDisabled={projectReadOnly} cancelLabel={$tr("common.cancel")} confirmLabel={$tr("common.create")} onconfirm={startCreateFromPrompt} oncancel={() => (createPrompt = "")}>
            {#snippet message()}
              {$tr("wiki.missing", {slug: createPromptScope && createPromptScope !== currentScope ? `${createPromptScope}:${createPrompt}` : createPrompt})}
            {/snippet}
          </ConfirmBar>
        {/if}

        {#if !editing && backlinks.length}
          <div class="backlinks">
            <div class="backlinks-head">{$tr("wiki.backlinks")}</div>
            {#each backlinks as b (b.slug)}
              <button class="backlink" onclick={() => open(b.slug)}>
                <span class="wiki-row-title">{b.title}</span>
                <span class="wiki-row-slug">{b.slug}</span>
              </button>
            {/each}
          </div>
        {/if}
      </article>
    {:else}
      <div class="wiki-placeholder">
        <BookOpen size={40} strokeWidth={1.4} />
        <p class="wiki-ph-title">{$tr("wiki.choose")}</p>
        <p class="muted">
          {$tr("wiki.chooseNote")}
        </p>
      </div>
    {/if}
  </main>

  <!-- Geschiedenis-timeline (BETON-209): rechts naast het artikel; op smalle
       schermen een eigen paneel (pane === "history"). -->
  {#if showHistory && current && !creating}
    <aside class="wiki-history" class:mobile-hidden={pane !== "history"} aria-label={$tr("wiki.history")}>
      <header class="wiki-history-head">
        <button class="link wiki-tolist" onclick={() => (showHistory = false)}>
          <ArrowLeft size={15} /> {$tr("wiki.article")}
        </button>
        <span class="wiki-history-title"><History size={15} /> {$tr("wiki.history")}</span>
      </header>
      {#if historyLoading}
        <p class="muted">{$tr("wiki.loading")}</p>
      {:else if revisions.length}
        <ol class="rev-list">
          {#each revisions as r (r.id)}
            <li>
              <button
                class="rev-row"
                class:active={revDetail?.revision.id === r.id}
                onclick={() => openRevision(r.id)}
              >
                <span class="rev-row-who">{r.author || $tr("wiki.unknown")}</span>
                <span class="rev-row-when" title={absoluteTime(r.created_at, $locale)}>
                  {formatTimestamp(r.created_at, Date.now(), $locale)}
                </span>
              </button>
            </li>
          {/each}
        </ol>
      {:else}
        <p class="muted">{$tr("wiki.noRevisions")}</p>
      {/if}
    </aside>
  {/if}
</section>

<ImageLightbox image={lightboxImage} onclose={() => (lightboxImage = null)} />

{#snippet acDropdown()}
  {#if acOpen && acItems.length}
    <ul class="ac-list" role="listbox" aria-label={$tr("wiki.suggestions")}>
      {#each acItems as item, i (item.slug)}
        <li>
          <button
            class="ac-item"
            class:active={i === acIndex}
            role="option"
            aria-selected={i === acIndex}
            onmousedown={(e) => {
              e.preventDefault();
              insertSuggestion(item.slug);
            }}
          >
            <span class="ac-slug">{item.slug}</span>
            <span class="ac-title">{item.title}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
{/snippet}

<style>
  /* First-class wiki-view: navigatie-zijbalk + artikel-hoofdinhoud
     (BETON-182). Geen overlay/modal meer — dit is een volwaardige view
     naast het bord. */
  .wiki-view {
    display: grid;
    grid-template-columns: minmax(220px, 300px) 1fr;
    gap: 20px;
    align-items: start;
    padding: 16px clamp(12px, 4vw, 40px) 40px;
    min-height: 0;
  }

  /* --- Zijbalk ------------------------------------------------------------ */
  .wiki-nav {
    display: flex;
    flex-direction: column;
    gap: 12px;
    position: sticky;
    top: 12px;
  }
  .wiki-nav-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .wiki-brand {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 17px;
    font-weight: 600;
  }
  .wiki-back,
  .wiki-tolist {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .wiki-search {
    position: relative;
    display: flex;
    align-items: center;
  }
  .wiki-search :global(.wiki-search-icon) {
    position: absolute;
    left: 10px;
    color: var(--text-tertiary);
    pointer-events: none;
  }
  /* Specificity moet minstens gelijk zijn aan de globale input-basisregel
     zodat padding-left hier niet gereset wordt. */
  .wiki-search input.wiki-search-input {
    width: 100%;
    padding-left: 32px;
  }
  .wiki-new {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    justify-content: center;
    /* Gestippeld = "hier kan iets bij"; randkleur uit de globale button-regel,
       tekst van een gewone actie (BETON-418). */
    border-style: dashed;
  }
  .wiki-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    overflow-y: auto;
    /* Op desktop scrollt de lijst mee binnen de sticky zijbalk. */
    max-height: calc(100dvh - 220px);
  }
  /* BETON-204: zonder min-width:0 duwt een lange titel de flex-column-rij
     breder dan de zijbalk in plaats van te breken/afkappen — de tekst liep
     zichtbaar buiten de kaart. min-width:0 + ellipsis op titel/meta lost dat op.
     flex-shrink:0 is hier geen stijlkeuze maar een correctheidsfix: .wiki-row
     is zelf een flex-item in de scrollbare .wiki-list-kolom. Zodra title/meta
     overflow:hidden krijgen, wordt hun automatische min-height 0 (CSS-spec:
     "auto" min-size is content-based, tenzij overflow != visible), waardoor
     .wiki-list de rijen bij veel pagina's kon PLETTEN i.p.v. laten scrollen —
     titel- en metaregel renderden dan in een paar px hoge, overlappende
     tekstregels. flex-shrink:0 dwingt elke rij op z'n natuurlijke hoogte. */
  .wiki-row {
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    align-items: flex-start;
    gap: 4px;
    min-width: 0;
    width: 100%;
    text-align: left;
    border: 1px solid var(--border);
    background: var(--surface);
    border-radius: var(--radius-md);
    padding: 10px 12px;
  }
  .wiki-row.active {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .wiki-row-title {
    display: block;
    width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
  }
  .wiki-row-meta {
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    overflow: hidden;
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }
  .wiki-row-slug {
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .wiki-row-dot,
  .wiki-row-time {
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
  }
  .wiki-empty {
    padding: 8px 2px;
  }

  /* --- Hoofdinhoud -------------------------------------------------------- */
  .wiki-main {
    min-width: 0;
  }
  .wiki-error {
    margin-bottom: 12px;
  }
  .wiki-doc {
    max-width: 74ch;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .wiki-doc-head,
  .wiki-editor-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  /* "Pagina's"-terugknop alleen op smalle schermen (op desktop staat de lijst
     altijd links). */
  .wiki-tolist {
    display: none;
  }
  .wiki-actions {
    display: inline-flex;
    gap: 2px;
    margin-left: auto;
  }
  .wiki-doc-title-wrap {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }
  h1.wiki-doc-title {
    font-size: clamp(24px, 3vw, 30px);
    font-weight: 700;
    line-height: 1.2;
    margin: 0;
  }
  h2.wiki-doc-title {
    font-size: var(--text-xl);
    font-weight: 600;
    margin: 0;
  }
  .wiki-doc-meta {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 6px;
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }
  .wiki-doc-slug {
    font-variant-numeric: tabular-nums;
  }
  .wiki-article {
    line-height: 1.65;
  }
  .full {
    width: 100%;
  }
  :global(.wiki-textarea) {
    font-family: var(--font-mono, ui-monospace, monospace);
    line-height: 1.55;
  }

  /* Wiki-interlink [[slug]] (BETON-25) */
  .wiki-article :global(.wikilink) {
    color: var(--accent);
    cursor: pointer;
    text-decoration: none;
    border-bottom: 1px dotted var(--accent);
  }
  .wiki-article :global(.wikilink):hover {
    border-bottom-style: solid;
  }
  /* Dode wikilink → naar een nog-niet-bestaande pagina (BETON-57) */
  .wiki-article :global(.wikilink-dead) {
    color: var(--text-tertiary);
    border-bottom-color: var(--text-tertiary);
    border-bottom-style: dashed;
  }
  .wiki-article :global(.wikilink):focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 2px;
  }
  /* Ticketref-link zoals BETON-91 (BETON-106) */
  .wiki-article :global(.ticketlink) {
    color: var(--accent);
    cursor: pointer;
    text-decoration: none;
    border-bottom: 1px solid var(--accent);
    font-variant-numeric: tabular-nums;
  }
  .wiki-article :global(.ticketlink):hover {
    opacity: 0.8;
  }
  .wiki-article :global(.ticketlink):focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 2px;
  }

  /* Lege staat (geen pagina gekozen) */
  .wiki-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    text-align: center;
    color: var(--text-tertiary);
    padding: 64px 16px;
  }
  .wiki-ph-title {
    font-size: var(--text-lg);
    font-weight: 600;
    color: var(--text-secondary);
    margin: 8px 0 0;
  }

  /* [[-autocomplete */
  .ac-wrap {
    position: relative;
  }
  .ac-list {
    position: absolute;
    z-index: var(--z-popover);
    left: 0;
    right: 0;
    margin: 2px 0 0;
    padding: 4px;
    list-style: none;
    max-height: 220px;
    overflow-y: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
  }
  .ac-item {
    display: flex;
    align-items: baseline;
    gap: 10px;
    width: 100%;
    text-align: left;
    border: none;
    background: transparent;
    padding: 6px 10px;
    border-radius: var(--radius-sm);
  }
  .ac-item.active,
  .ac-item:hover {
    background: var(--accent-soft);
  }
  .ac-slug {
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .ac-title {
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }

  /* Backlinks-sectie */
  .backlinks {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 20px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
  }
  .backlinks-head {
    font-size: var(--text-sm);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-tertiary);
    margin-bottom: 2px;
  }
  .backlink {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    text-align: left;
    border: 1px solid var(--border);
    background: var(--surface);
    border-radius: var(--radius-md);
    padding: 6px 12px;
  }

  /* --- Edit-history (BETON-209) ------------------------------------------ */
  /* Geschiedenis komt als kolom direct TEGEN het artikel te staan (BETON-209
     her-fix): de nav-kolom houdt exact dezelfde breedte als zonder history
     (zelfde minmax → artikel verspringt niet bij openen), het artikel krijgt
     zijn eigen 74ch-cap als track zodat de geschiedenis er meteen naast valt,
     en de resterende ruimte gaat naar een lege 4e spacer-track uiterst rechts
     i.p.v. als gat tussen artikel en geschiedenis. */
  .wiki-view.with-history {
    grid-template-columns: minmax(220px, 300px) minmax(0, 74ch) minmax(220px, 300px) 1fr;
  }
  .icon-btn.active {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .wiki-history {
    display: flex;
    flex-direction: column;
    gap: 10px;
    position: sticky;
    top: 12px;
  }
  .wiki-history-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .wiki-history-title {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    font-size: var(--text-md);
    color: var(--text-secondary);
  }
  .rev-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    overflow-y: auto;
  }
  .rev-row {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 2px;
    text-align: left;
    border: 1px solid transparent;
    background: var(--surface-2);
    border-radius: var(--radius-md);
    padding: 7px 10px;
    cursor: pointer;
  }
  .rev-row:hover {
    background: var(--surface-3);
  }
  .rev-row.active {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .rev-row-who {
    font-size: var(--text-base);
    font-weight: 500;
  }
  .rev-row-when {
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }

  /* Diff-weergave in het hoofdpaneel. */
  .rev-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
    padding: 8px 12px;
    background: var(--surface-2);
    border-radius: var(--radius-md);
    margin-bottom: 12px;
  }
  .rev-banner-info,
  .rev-banner-actions {
    display: inline-flex;
    align-items: center;
    gap: 10px;
  }
  .rev-who {
    font-weight: 600;
  }
  .rev-when {
    color: var(--text-tertiary);
    font-size: var(--text-base);
  }
  .rev-stat {
    display: inline-flex;
    gap: 6px;
    font-size: var(--text-base);
    font-variant-numeric: tabular-nums;
  }
  .rev-stat .add {
    color: var(--success);
  }
  .rev-stat .del {
    color: var(--danger);
  }
  .rev-confirm-q {
    font-size: var(--text-base);
    color: var(--text-secondary);
  }
  /* --- Responsive: één paneel per keer op smalle schermen ---------------- */
  @media (max-width: 820px) {
    .wiki-view,
    .wiki-view.with-history {
      grid-template-columns: 1fr;
      gap: 0;
      padding: 12px clamp(12px, 4vw, 20px) 32px;
    }
    .wiki-nav,
    .wiki-history {
      position: static;
      max-height: none;
    }
    .wiki-list {
      max-height: none;
    }
    .wiki-tolist {
      display: inline-flex;
    }
    /* Toon of de zijbalk óf het artikel óf de geschiedenis, nooit meerdere. */
    .mobile-hidden {
      display: none;
    }
  }
</style>
