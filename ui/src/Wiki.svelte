<script>
  import { t as tr, locale } from "./lib/i18n.js";
  import WikiReview from "./WikiReview.svelte";
  import { tick, onDestroy } from "svelte";
  import { api } from "./api.js";
  import MarkdownEditor from "./MarkdownEditor.svelte";
  import ErrorNote from "./ErrorNote.svelte";
  import Select from "./Select.svelte";
  import { isSubmitChord, formatTimestamp, absoluteTime } from "./lib/board.js";
  import {
    wikiReadingBody,
    wikiSearchSnippet,
    sortWikiPages,
    filterWikiPages,
    wikiBacklinks,
    wikiLinkQuery,
    wikiSlugSuggestions,
  } from "./lib/wikiText.js";
  import { renderWikiDocument } from "./lib/markdown.js";
  import ImageLightbox from "./ImageLightbox.svelte";
  import { lightboxClicks } from "./lib/lightbox.js";
  let lightboxImage = $state(null);
  import { lineDiff } from "./lib/diff.js";
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
    Shield,
    ChevronRight,
    MoreHorizontal,
    List,
    FileText,
  } from "@lucide/svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import ConfirmBar from "./ConfirmBar.svelte";
  import DiffView from "./DiffView.svelte";

  // `onswitchproject(key)` wisselt het actieve project op app-niveau — nodig
  // om een wikilink naar een ánder project dan het geselecteerde te kunnen
  // volgen (BETON-306); zonder die callback blijft zo'n link binnen de view.
  let { project, projectName, projectArchived = false, me, onclose, onopenref, onswitchproject, liveTick = 0, routePage = null, routeScope = null, onroute, onleaveguard } = $props();

  // Bekende project-keys, voor het klikbaar maken van ticketrefs (BETON-106).
  let projectKeys = $state([]);
  api
    .projects()
    .then((ps) => (projectKeys = ps.map((p) => p.key)))
    .catch(() => {});

  // scope: 'global' of 'project'. Zonder project altijd globaal.
  let scope = $state(routeScope || "project");
  let projectReadOnly = $derived(scope === "project" && projectArchived);
  let pages = $state([]);
  let loadedScope = $state(null);
  let loadPending = Promise.resolve();
  const scopedPages = $derived(loadedScope === currentScope ? pages : []);
  let selected = $state(routePage); // huidige slug
  let editing = $state(false);
  let creating = $state(false);
  let titleDraft = $state("");
  let bodyDraft = $state("");
  let slugDraft = $state("");
  let confirmDelete = $state(false);
  let error = $state("");
  let notice = $state("");
  let loading = $state(true);
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

  const scopeKey = $derived(scope === "global" || !project ? null : project);
  // BETON-306: de scope als string ("global" of een project-key) — voor het
  // resolven van kale interlinks en het meegeven aan de renderer/navigatie.
  const currentScope = $derived(scope === "global" || !project ? "global" : project);
  const current = $derived(scopedPages.find((p) => p.slug === selected) || null);
  let sort = $state("alphabetical");
  let navOpen = $state(false);
  let contextOpen = $state(false);
  let showAllBacklinks = $state(false);
  let menuOpen = $state(false);
  let pendingLeave = $state(null);
  let leaveFocus = null;
  let editBase = $state(null);
  let conflictPage = $state(null);
  let showConflict = $state(false);
  const dirty = $derived((editing || creating) && (creating
    ? !!(titleDraft || bodyDraft || slugDraft)
    : titleDraft !== editBase?.title || bodyDraft !== editBase?.body_md));
  const visiblePages = $derived(sortWikiPages(filterWikiPages(scopedPages, query), sort, $locale));
  const recentPages = $derived(sortWikiPages(scopedPages, "recent", $locale).slice(0, 6));
  const scopeLabel = $derived(scope === "global" ? $tr("wiki.global") : projectName || project || $tr("wiki.global"));
  // Cross-scope index voor levend/dood-markering (BETON-306): keys "<scope> <slug>".
  let wikiIndex = $state([]);
  const knownRefs = $derived(new Set(wikiIndex.map((r) => `${r.scope} ${r.slug}`)));
  const backlinks = $derived(
    current ? wikiBacklinks(scopedPages, current.slug, currentScope, knownRefs) : [],
  );
  const pageTitles = $derived(new Map([
    ...wikiIndex.filter(p => p.title).map(p => [`${p.scope} ${p.slug}`, p.title]),
    ...scopedPages.map(p => [`${currentScope} ${p.slug}`, p.title]),
  ]));
  const document = $derived(renderWikiDocument(wikiReadingBody(current?.body_md, current?.title), knownRefs, projectKeys, currentScope, pageTitles));
  // Diff van de bekeken revisie t.o.v. z'n voorganger (eerste revisie → alles add).
  const diffSegments = $derived(
    revDetail ? lineDiff(revDetail.previous?.body_md ?? "", revDetail.revision.body_md) : [],
  );
  let loadSequence = 0;
  async function load() {
    const seq = ++loadSequence;
    const target = scopeKey;
    loading = true;
    error = "";
    try {
      const [nextPages, index] = await Promise.all([api.wikiList(target), api.wikiIndex().catch(() => wikiIndex)]);
      if (seq !== loadSequence) return;
      pages = nextPages;
      loadedScope = target || "global";
      wikiIndex = index;
      if (selected && !pages.some(p => p.slug === selected)) error = $tr("wiki.pageUnavailable");
    } catch (e) {
      if (seq === loadSequence) error = e.message;
    } finally {
      if (seq === loadSequence) loading = false;
    }
  }

  $effect(() => {
    void scopeKey;
    void liveTick;
    loadPending = load();
  });
  $effect(() => {
    if (routePage === selected && (!routeScope || routeScope === scope)) return;
    requestLeave(() => {
      scope = routeScope || "project";
      selected = routePage;
      resetForm(); resetHistory();
    });
  });
  $effect(() => { onleaveguard?.(requestLeave); });
  onDestroy(() => onleaveguard?.(null));

  function requestLeave(action) {
    if (dirty) { leaveFocus = window.document.activeElement; pendingLeave = action; return false; }
    action(); return true;
  }
  function cancelLeave() {
    pendingLeave = null;
    if (leaveFocus?.isConnected) leaveFocus.focus({preventScroll:true});
    else editorEl?.focus({preventScroll:true});
  }
  function discardLeave() {
    const action = pendingLeave;
    pendingLeave = null;
    resetForm();
    action?.();
  }
  function beforeUnload(event) {
    if (!dirty) return;
    event.preventDefault(); event.returnValue = "";
  }
  function publishRoute() { onroute?.({page:selected, scope}); }
  function changeScope(value) {
    requestLeave(() => {
      scope = value; selected = null; query = ""; navOpen = false;
      resetForm(); resetHistory(); publishRoute();
    });
  }

  function resetForm() {
    editing = false;
    creating = false;
    confirmDelete = false;
    createPrompt = "";
    acOpen = false;
    menuOpen = false;
    conflictPage = null;
    showConflict = false;
  }

  // Zet de geschiedenis-weergave terug (bij paginawissel/scope-wissel/edit).
  function resetHistory() {
    showHistory = false;
    revDetail = null;
    restoreConfirm = false;
    revisions = [];
  }

  function open(slug, targetScope = currentScope) {
    requestLeave(() => openPage(slug, targetScope));
  }
  async function openPage(slug, targetScope = currentScope) {
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
    navOpen = false; contextOpen = false; showAllBacklinks = false;
    publishRoute();
    // A11y: verplaats focus naar het artikel zodat toetsenbordgebruikers
    // meteen in de gekozen pagina zitten (geen focus-trap: dit is een view).
    await tick();
    await loadPending;
    await tick();
    articleEl?.focus({preventScroll:true});
  }

  // Terug naar de paginalijst (vooral op smalle schermen).
  function backToList() {
    requestLeave(() => {
      selected = null; resetForm(); resetHistory(); navOpen = false; publishRoute();
    });
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
      const restored = await api.wikiRestore(scopeKey, current.slug, revDetail.revision.id);
      if (restored.status === "pending") notice = $tr("wiki.proposalSaved");
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
    requestLeave(() => onopenref?.(ref));
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
    editBase = {...current};
    conflictPage = null;
    showHistory = false; menuOpen = false;
    notice = "";
    editing = true;
  }

  function startCreate(slug = "") {
    requestLeave(() => createPage(slug));
  }
  function createPage(slug = "") {
    if (projectReadOnly) return;
    creating = true;
    editing = false;
    selected = null;
    createPrompt = "";
    titleDraft = slug;
    bodyDraft = "";
    slugDraft = slug;
    notice = "";
    navOpen = false; menuOpen = false;
    resetHistory();
    publishRoute();
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
    const items = wikiSlugSuggestions(scopedPages, q.query);
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

  let saving = $state(false); // dubbele Cmd+Enter mag niet dubbel opslaan (BETON-462)
  async function saveEdit() {
    if (projectReadOnly) return;
    if (!titleDraft.trim()) { error = $tr("wiki.validation"); return; }
    if (saving) return;
    saving = true;
    try {
      const result = await api.wikiUpdate(scopeKey, selected, {
        title: titleDraft.trim(),
        body_md: bodyDraft,
        expected_revision: editBase.revision,
      });
      if (result.status === "pending") notice = $tr("wiki.proposalSaved");
      editing = false; conflictPage = null;
      await load();
      if (showHistory) await loadHistory(); // nieuwe revisie in de timeline
    } catch (e) {
      error = e.message;
      if (e.status === 409) {
        conflictPage = await api.wikiGet(scopeKey, selected).catch(() => null);
        error = $tr("wiki.editConflict");
      }
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
      selected = created.slug || null;
      if (created.status === "pending") notice = $tr("wiki.proposalSaved");
      publishRoute();
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
      publishRoute();
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
    if (pendingLeave) { e.preventDefault();e.stopPropagation();cancelLeave();return; }
    if (menuOpen) { e.preventDefault();e.stopPropagation();menuOpen=false;return; }
    const t = e.target;
    const typing =
      t &&
      (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    if (typing || acOpen || editing || creating || confirmDelete) return;
    requestLeave(() => onclose?.());
  }
  async function jumpTo(id) {
    contextOpen = false;
    await tick();
    const heading = articleEl?.querySelector(`[id="${CSS.escape(id)}"]`);
    heading?.scrollIntoView({block:"start", behavior:"auto"});
    heading?.focus({preventScroll:true});
  }
  async function protectPage() {
    if (projectReadOnly) return;
    try { await api.wikiProtect(scopeKey, current.slug, !current.protected); menuOpen = false; await load(); }
    catch (e) { error = e.message; }
  }
</script>

<svelte:window onkeydown={onViewKeydown} onbeforeunload={beforeUnload} />

<section class="wiki-view" class:overview={!current && !editing && !creating} aria-label="Wiki">
  <header class="wiki-mobile-bar">
    <button class="sm" aria-expanded={navOpen} aria-controls="wiki-navigation" onclick={() => navOpen = !navOpen}><PanelLeft size={16} /> {$tr("wiki.pages")}</button>
    <span>{scopeLabel}</span>
    {#if current && !editing}<button class="sm" aria-expanded={contextOpen} aria-controls="wiki-context" onclick={() => contextOpen = !contextOpen}><List size={16} /> {$tr("wiki.onPage")}</button>{/if}
  </header>
  <aside id="wiki-navigation" class="wiki-nav" class:nav-open={navOpen} aria-label={$tr("wiki.pages")}>
    <div class="wiki-nav-head"><BookOpen size={20} /><strong>{$tr("wiki.knowledge")}</strong></div>
    {#if project}
      <SegmentedControl variant="soft" itemAria="pressed" ariaLabel={$tr("wiki.scope")} value={scope}
        onchange={changeScope} options={[{value:"project",label:projectName || project},{value:"global",label:$tr("wiki.global")}]} />
    {/if}
    <button class="wiki-home-link" class:active={!selected && !creating} onclick={backToList}><BookOpen size={15} /> {$tr("wiki.overview")}</button>
    <div class="wiki-search">
      <Search size={16} />
      <input type="search" bind:value={query} aria-label={$tr("wiki.search")} placeholder={$tr("wiki.searchHint")} />
      {#if query}<button class="icon-btn" aria-label={$tr("wiki.clearSearch")} onclick={() => query = ""}><X size={14} /></button>{/if}
    </div>
    <div class="wiki-list-tools">
      <span>{query ? $tr("wiki.results",{count:visiblePages.length}) : $tr("wiki.pageCount",{count:scopedPages.length})}</span>
      <Select value={sort} ariaLabel={$tr("wiki.sort")} options={[{value:"alphabetical",label:$tr("wiki.alphabetical")},{value:"recent",label:$tr("wiki.recent")}]} onchange={(value) => sort=value} />
    </div>
    <nav class="wiki-list" aria-label={$tr("wiki.pages")}>
      {#each visiblePages as page (page.slug)}
        <button class="wiki-row" class:active={page.slug===selected} aria-current={page.slug===selected ? "page" : undefined} onclick={() => open(page.slug)}>
          <FileText size={15} /><span><span class="wiki-row-title" title={page.title}>{page.title}</span>
          {#if query}<span class="wiki-row-snippet">{wikiSearchSnippet(page,query)}</span>{/if}</span>
        </button>
      {:else}
        {#if !loading}<p class="wiki-nav-empty">{$tr(query ? "wiki.noSearch" : "wiki.noPages",{query})}</p>{/if}
      {/each}
    </nav>
    <button class="primary sm wiki-new" disabled={projectReadOnly} onclick={() => startCreate()}><Plus size={16} /> {$tr("wiki.new")}</button>
    <button class="link wiki-board" onclick={() => requestLeave(() => onclose?.())}><ArrowLeft size={14} /> {$tr("wiki.board")}</button>
  </aside>

  <main class="wiki-main">
    {#if pendingLeave}
      <div class="wiki-leave"><ConfirmBar role="alertdialog" ariaLabel={$tr("wiki.unsavedTitle")} focus message={$tr("wiki.unsaved")}
        confirmLabel={$tr("wiki.discard")} cancelLabel={$tr("wiki.keepEditing")} onconfirm={discardLeave} oncancel={cancelLeave} /></div>
    {/if}
    <ErrorNote message={error} onRetry={!editing && !creating ? load : undefined} />
    {#if notice}<p class="wiki-notice" role="status">{notice}</p>{/if}
    {#if projectReadOnly}<p class="readonly-note">{$tr("api.project_archived_readonly")}</p>{/if}
    {#if me?.kind === "human"}<WikiReview project={scopeKey} {liveTick} readOnly={projectReadOnly} onchanged={load} />{/if}
    {#if loading && !scopedPages.length}<p role="status">{$tr("wiki.loading")}</p>
    {:else if creating || editing}
      <article class="wiki-doc wiki-editor" aria-label={$tr(creating ? "wiki.new" : "wiki.edit")}>
        <div class="wiki-breadcrumb"><button class="link" onclick={backToList}>{scopeLabel}</button><ChevronRight size={13} /><span>{$tr(creating ? "wiki.new" : "wiki.edit")}</span></div>
        <div class="wiki-editor-head"><h1>{$tr(creating ? "wiki.new" : "wiki.edit")}</h1><span>{$tr("wiki.unsavedLabel")}</span></div>
        <label class="wiki-field">{$tr("wiki.title")}<input class="full" bind:value={titleDraft} disabled={projectReadOnly || saving} /></label>
        {#if creating}<details class="wiki-page-info"><summary>{$tr("wiki.pageDetails")}</summary><label class="wiki-field">{$tr("wiki.pageAddress")}<input bind:value={slugDraft} placeholder={$tr("wiki.slugHint")} /></label></details>{/if}
        {#if conflictPage}
          <section class="wiki-conflict" role="alert">
            <strong>{$tr("wiki.editConflict")}</strong><p>{$tr("wiki.conflictHelp")}</p>
            <button class="sm" onclick={() => showConflict = !showConflict}>{$tr("wiki.compareSaved")}</button>
            {#if showConflict}<DiffView segments={lineDiff(bodyDraft, conflictPage.body_md)} variant="bordered" ariaLabel={$tr("wiki.changes")} />{/if}
            <button class="sm" onclick={() => requestLeave(() => {editing=false; conflictPage=null; load();})}>{$tr("wiki.reloadSaved")}</button>
          </section>
        {/if}
        <div class="ac-wrap" role="presentation" onclick={onWikiClick} onkeydown={onWikiKeydown}>
          <MarkdownEditor renderPreview={(text) => renderWikiDocument(wikiReadingBody(text,titleDraft),knownRefs,projectKeys,currentScope,pageTitles).html} value={bodyDraft} oninput={(event) => {bodyDraft=event.currentTarget.value;onEditorInput();}}
            bind:textareaRef={editorEl} rows={20} ariaLabel={$tr("wiki.content")} placeholder={$tr("wiki.markdownEdit")}
            onsubmit={creating ? saveCreate : saveEdit} onkeydown={onEditorKeydown}>
            {#snippet dropdown()}{@render acDropdown()}{/snippet}
          </MarkdownEditor>
        </div>
        <footer class="wiki-editor-actions">
          <span>{$tr("wiki.explicitSave")}</span>
          <button class="sm" onclick={() => requestLeave(() => {resetForm();})}>{$tr("common.cancel")}</button>
          <button class="primary sm" disabled={saving || projectReadOnly || !titleDraft.trim() || !!conflictPage} onclick={creating ? saveCreate : saveEdit}>{$tr(saving ? "wiki.saving" : "common.save")}</button>
        </footer>
      </article>
    {:else if current}
      <article class="wiki-doc" tabindex="-1" bind:this={articleEl} aria-label={current.title}>
        <div class="wiki-doc-toolbar">
          <div class="wiki-breadcrumb"><button class="link" onclick={backToList}>{scopeLabel}</button><ChevronRight size={13}/><span>{$tr("wiki.article")}</span></div>
          <div class="wiki-actions">
            <button class="sm" disabled={projectReadOnly} onclick={startEdit}><Pencil size={14} /> {$tr("wiki.edit")}</button>
            <div class="wiki-menu-wrap">
              <button class="icon-btn" aria-label={$tr("wiki.pageActions")} aria-expanded={menuOpen} onclick={() => menuOpen=!menuOpen}><MoreHorizontal size={20}/></button>
              {#if menuOpen}
                <div class="wiki-menu" role="group" aria-label={$tr("wiki.pageActions")}>
                  <button onclick={() => {menuOpen=false;toggleHistory();}}><History size={15}/>{$tr("wiki.history")}</button>
                  {#if me?.kind === "human" && scopeKey}<button disabled={projectReadOnly} onclick={protectPage}><Shield size={15}/>{$tr(current.protected ? "wiki.unprotect" : "wiki.protect")}</button>{/if}
                  {#if me?.kind === "human"}<button class="danger-quiet" disabled={projectReadOnly} onclick={() => {confirmDelete=true;menuOpen=false;}}><Trash2 size={15}/>{$tr("wiki.delete")}</button>{/if}
                </div>
              {/if}
            </div>
          </div>
        </div>
        <header class="wiki-doc-title-wrap">
          <h1 class="wiki-doc-title">{current.title}</h1>
          <div class="wiki-doc-meta">
            {#if current.updated_at}<span title={absoluteTime(current.updated_at,$locale)}>{$tr("wiki.changed",{time:formatTimestamp(current.updated_at,Date.now(),$locale)})}</span>{/if}
            {#if current.protected}<span class="wiki-protected"><Shield size={13}/>{$tr("wiki.protected")}</span>{/if}
          </div>
        </header>
        {#if confirmDelete}<ConfirmBar role="alertdialog" focus danger message={$tr("wiki.deleteQuestion",{slug:current.slug})} confirmLabel={$tr("wiki.yesDelete")} confirmDisabled={projectReadOnly} onconfirm={doDelete} oncancel={() => confirmDelete=false} />{/if}
        {#if revDetail}
          <section class="rev-view">
            <div class="rev-banner"><strong>{revDetail.revision.author || $tr("wiki.unknown")}</strong><span>{formatTimestamp(revDetail.revision.created_at,Date.now(),$locale)}</span></div>
            <DiffView segments={diffSegments} variant="bordered" ariaLabel={$tr("wiki.changes")} />
            {#if restoreConfirm}<ConfirmBar message={$tr("wiki.restoreQuestion")} confirmLabel={$tr("wiki.yesRestore")} confirmDisabled={projectReadOnly} onconfirm={restoreRevision} oncancel={() => restoreConfirm=false}/>
            {:else}<div class="btn-row"><button class="sm" disabled={projectReadOnly} onclick={() => restoreConfirm=true}><RotateCcw size={14}/>{$tr("wiki.restore")}</button><button class="sm" onclick={closeRevision}>{$tr("wiki.closeDiff")}</button></div>{/if}
          </section>
        {:else}
          <div class="wiki-article md" role="presentation" use:lightboxClicks={(img) => lightboxImage=img} onclick={onWikiClick} onkeydown={onWikiKeydown}>{@html document.html}</div>
          {#if !current.body_md}<p class="muted">{$tr("wiki.empty")}</p>{/if}
        {/if}
        {#if createPrompt}<ConfirmBar message={$tr("wiki.missing",{slug:createPromptScope!==currentScope ? `${createPromptScope}:${createPrompt}` : createPrompt})} confirmLabel={$tr("common.create")} confirmDisabled={projectReadOnly} onconfirm={startCreateFromPrompt} oncancel={() => createPrompt=""}/>{/if}
        <details class="wiki-page-info"><summary>{$tr("wiki.pageDetails")}</summary><dl><dt>{$tr("wiki.pageAddress")}</dt><dd>{current.slug}</dd><dt>{$tr("wiki.source")}</dt><dd>{current.source_kind || $tr("wiki.existingKnowledge")}</dd><dt>{$tr("wiki.scope")}</dt><dd>{scopeLabel}</dd></dl></details>
      </article>
    {:else if !error}
      <section class="wiki-home">
        <div class="wiki-eyebrow"><BookOpen size={19}/>{$tr("wiki.knowledge")}</div>
        <h1>{scopeLabel}</h1><p class="wiki-home-intro">{$tr("wiki.homeIntro",{count:scopedPages.length})}</p>
        <div class="wiki-home-search"><Search size={19}/><input type="search" bind:value={query} aria-label={$tr("wiki.searchKnowledge")} placeholder={$tr("wiki.searchHint")}/>{#if query}<button class="icon-btn" aria-label={$tr("wiki.clearSearch")} onclick={() => query=""}><X size={16}/></button>{/if}</div>
        <div class="wiki-home-heading"><h2>{$tr(query ? "wiki.searchResults" : "wiki.recentPages")}</h2><button class="sm" disabled={projectReadOnly} onclick={() => startCreate()}><Plus size={15}/>{$tr("wiki.new")}</button></div>
        <div class="wiki-home-pages">
          {#each query ? visiblePages : recentPages as page (page.slug)}
            <button class="wiki-home-page" onclick={() => open(page.slug)}><FileText size={20}/><span><strong>{page.title}</strong><span>{wikiSearchSnippet(page,query,175)}</span><small>{formatTimestamp(page.updated_at,Date.now(),$locale)}</small></span><ChevronRight size={16}/></button>
          {:else}<p class="wiki-empty">{$tr(query ? "wiki.noSearch" : "wiki.noPages",{query})}</p>{/each}
        </div>
      </section>
    {/if}
  </main>

  {#if current && !editing && !creating}
    <aside id="wiki-context" class="wiki-context" class:context-open={contextOpen} aria-label={$tr("wiki.onPage")}>
      {#if showHistory}
        <section class="wiki-context-section"><div class="context-title"><h2>{$tr("wiki.history")}</h2><button class="icon-btn" aria-label={$tr("common.close")} onclick={() => showHistory=false}><X size={15}/></button></div>
          {#if historyLoading}<p>{$tr("wiki.loading")}</p>{:else}<ol class="rev-list">{#each revisions as revision (revision.id)}<li><button class:active={revDetail?.revision.id===revision.id} onclick={() => openRevision(revision.id)}><strong>{revision.author || $tr("wiki.unknown")}</strong><span>{formatTimestamp(revision.created_at,Date.now(),$locale)}</span></button></li>{:else}<li>{$tr("wiki.noRevisions")}</li>{/each}</ol>{/if}
        </section>
      {:else}
        <section class="wiki-context-section"><h2>{$tr("wiki.onPage")}</h2><nav class="wiki-toc" aria-label={$tr("wiki.onPage")}>{#each document.headings as heading (heading.id)}<button class:subheading={heading.level>2} onclick={() => jumpTo(heading.id)}>{heading.title}</button>{:else}<p class="muted">{$tr("wiki.noHeadings")}</p>{/each}</nav></section>
      {/if}
      <section class="wiki-context-section backlinks"><h2>{$tr("wiki.backlinks")}</h2><div class="backlink-list">{#each showAllBacklinks ? backlinks : backlinks.slice(0,5) as page (page.slug)}<button class="backlink" onclick={() => open(page.slug)}>{page.title}</button>{:else}<p class="muted">{$tr("wiki.noBacklinks")}</p>{/each}</div>{#if backlinks.length>5}<button class="link" onclick={() => showAllBacklinks=!showAllBacklinks}>{$tr(showAllBacklinks ? "wiki.showFewer" : "wiki.showAllLinks",{count:backlinks.length})}</button>{/if}</section>
    </aside>
  {/if}
</section>

<ImageLightbox image={lightboxImage} onclose={() => lightboxImage=null} />

{#snippet acDropdown()}
  {#if acOpen && acItems.length}<ul class="ac-list" role="listbox" aria-label={$tr("wiki.suggestions")}>{#each acItems as item,i (item.slug)}<li><button class="ac-item" class:active={i===acIndex} role="option" aria-selected={i===acIndex} onmousedown={(event) => {event.preventDefault();insertSuggestion(item.slug);}} onclick={() => insertSuggestion(item.slug)}><span>{item.title}</span><small>{item.slug}</small></button></li>{/each}</ul>{/if}
{/snippet}

<style>
  .wiki-view { display:grid;grid-template-columns:260px minmax(0,780px) 220px;gap:40px;max-width:1420px;padding:28px 24px 64px;margin:0 auto;align-items:start; }
  .wiki-nav { position:sticky;top:80px;max-height:calc(100dvh - 105px);display:flex;flex-direction:column;min-width:0;padding-right:18px;border-right:1px solid var(--border); }
  .wiki-nav-head { display:flex;align-items:center;gap:9px;margin:0 0 20px;color:var(--text);font-size:var(--text-lg); }
  .wiki-home-link { margin:18px 0 12px;display:flex;align-items:center;gap:8px;justify-content:flex-start;text-align:left;background:none;border:none;padding:8px 9px;font-size:var(--text-sm);color:var(--text-secondary); }
  .wiki-home-link.active { background:var(--surface-3);color:var(--text); }
  .wiki-search,.wiki-home-search { display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border-interactive);border-radius:var(--radius-sm);padding:0 10px;min-width:0; }
  .wiki-search input[type="search"]:not([type="checkbox"]):not([type="radio"]):not([type="color"]),.wiki-home-search input[type="search"]:not([type="checkbox"]):not([type="radio"]):not([type="color"]) { min-width:0;width:100%;border:none;background:transparent;padding:10px 0;outline:none;font:inherit;box-shadow:none; }
  .wiki-search:focus-within,.wiki-home-search:focus-within { outline:2px solid var(--accent);outline-offset:2px; }
  .wiki-search :global(svg),.wiki-home-search :global(svg) { flex-shrink:0;color:var(--text-secondary); }
  .wiki-search .icon-btn { flex:0 0 auto; }
  .wiki-list-tools { display:flex;justify-content:space-between;align-items:center;gap:6px;margin:15px 0 8px;font-size:var(--text-xs);color:var(--text-secondary); }
  .wiki-list-tools :global(.select-trigger) { min-height:28px;padding:3px 6px;font-size:var(--text-xs);border:none;background:transparent; }
  .wiki-list { overflow:auto;min-height:80px;display:flex;flex-direction:column;gap:2px;flex:1; }
  .wiki-row { flex-shrink:0;display:flex;justify-content:flex-start;align-items:flex-start;gap:8px;background:none;border:1px solid transparent;border-radius:var(--radius-sm);padding:9px;text-align:left;width:100%;min-width:0;white-space:normal;min-height:38px;line-height:1.4;font-size:var(--text-sm);color:var(--text-secondary); }
  .wiki-row>span { min-width:0; }
  .wiki-row :global(svg) { flex:0 0 auto;margin-top:2px; }
  .wiki-row-title { display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere; }
  .wiki-row:hover,.wiki-home-link:hover { background:var(--surface-2);color:var(--text); }
  .wiki-row.active { background:var(--accent-soft);color:var(--text);border-left:3px solid var(--accent);padding-left:7px;font-weight:600; }
  .wiki-row-snippet { display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:var(--text-xs);color:var(--text-secondary);font-weight:400;margin-top:4px;overflow-wrap:anywhere; }
  .wiki-nav-empty { color:var(--text-secondary);font-size:var(--text-sm);padding:8px; }
  .wiki-new { margin-top:18px;justify-content:center; }
  .wiki-board { display:flex;align-items:center;gap:5px;margin-top:12px;align-self:flex-start; }
  .wiki-main { min-width:0;grid-column:2; }
  .overview .wiki-main { grid-column:2 / -1;max-width:920px; }
  .wiki-doc { min-width:0;outline:none; }
  .wiki-doc-toolbar { display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:30px; }
  .wiki-breadcrumb { display:flex;align-items:center;gap:7px;min-width:0;font-size:var(--text-sm);color:var(--text-secondary); }
  .wiki-breadcrumb button { overflow:hidden;text-overflow:ellipsis;max-width:230px;white-space:nowrap; }
  .wiki-actions { display:flex;gap:8px;align-items:center;flex-shrink:0; }
  .wiki-doc-title { font-size:clamp(26px,2.1vw,36px);line-height:1.2;letter-spacing:-.025em;font-weight:700;margin:0;overflow-wrap:anywhere; }
  .wiki-doc-meta { display:flex;gap:16px;flex-wrap:wrap;align-items:center;font-size:var(--text-sm);color:var(--text-secondary);margin-top:16px; }
  .wiki-protected { display:inline-flex;align-items:center;gap:5px; }
  .wiki-doc-title-wrap { padding-bottom:28px;border-bottom:1px solid var(--border);margin-bottom:26px; }
  .wiki-view :global(a[data-wiki]),.wiki-view :global(a[data-ticket]) { cursor:pointer; }
  .wiki-article { font-size:15px;line-height:1.8;color:var(--text);overflow-wrap:anywhere; }
  .wiki-article :global(h1),.wiki-article :global(h2),.wiki-article :global(h3),.wiki-article :global(h4) { scroll-margin-top:84px;line-height:1.35;margin:32px 0 12px;letter-spacing:-.015em; }
  .wiki-article :global(h2) { font-size:23px; }
  .wiki-article :global(h3) { font-size:19px; }
  .wiki-article :global(p) { margin:0 0 16px; }
  .wiki-article :global(li) { margin:7px 0; }
  .wiki-article :global(pre) { max-width:100%;overflow:auto;white-space:pre; }
  .wiki-article :global(table) { display:block;max-width:100%;overflow:auto; }
  .wiki-article :global(img) { max-width:100%;height:auto;border-radius:var(--radius-sm); }
  .wiki-context { grid-column:3;position:sticky;top:80px;max-height:calc(100dvh - 105px);overflow:auto;font-size:var(--text-sm);padding-top:10px; }
  .wiki-context-section { margin-bottom:30px; }
  .wiki-context h2 { font-size:var(--text-xs);color:var(--text-secondary);text-transform:uppercase;letter-spacing:.07em;margin:0 0 14px;font-weight:600; }
  .wiki-toc,.backlink-list { display:flex;flex-direction:column;align-items:stretch;gap:3px; }
  .wiki-toc button,.backlink { justify-content:flex-start;background:none;border:none;text-align:left;white-space:normal;font-size:var(--text-sm);line-height:1.5;padding:6px 0;color:var(--text-secondary);min-height:unset;overflow-wrap:anywhere; }
  .wiki-toc button:hover,.backlink:hover { color:var(--accent); }
  .wiki-toc .subheading { padding-left:12px;font-size:var(--text-xs); }
  .context-title { display:flex;align-items:center;justify-content:space-between; }
  .wiki-page-info { border-top:1px solid var(--border);margin-top:36px;padding-top:15px;color:var(--text-secondary);font-size:var(--text-sm); }
  .wiki-page-info summary { cursor:pointer; }
  dl { display:grid;grid-template-columns:90px minmax(0,1fr);gap:8px;margin-bottom:0; }
  dd { margin:0;overflow-wrap:anywhere; }
  .wiki-menu-wrap { position:relative; }
  .wiki-menu { position:absolute;right:0;top:100%;z-index:var(--z-dropdown,30);min-width:210px;padding:6px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);box-shadow:var(--shadow-md); }
  .wiki-menu button { display:flex;gap:8px;align-items:center;width:100%;text-align:left;background:none;border:none;white-space:normal;font-size:var(--text-sm);padding:9px; }
  .wiki-menu button:hover { background:var(--surface-2); }
  .wiki-home { padding:35px 0; }
  .wiki-eyebrow { display:flex;align-items:center;gap:8px;color:var(--text-secondary);font-size:var(--text-sm); }
  .wiki-home h1 { font-size:clamp(30px,3vw,44px);line-height:1.2;letter-spacing:-.03em;margin:12px 0; }
  .wiki-home-intro { color:var(--text-secondary);margin-bottom:25px; }
  .wiki-home-search { max-width:650px;padding:4px 14px; }
  .wiki-home-heading { display:flex;align-items:center;justify-content:space-between;gap:15px;margin:40px 0 12px; }
  .wiki-home-heading h2 { font-size:var(--text-lg);margin:0; }
  .wiki-home-pages { display:flex;flex-direction:column; }
  .wiki-home-page { display:flex;align-items:flex-start;gap:15px;background:none;border:none;border-top:1px solid var(--border);border-radius:0;padding:20px 0;white-space:normal;text-align:left; }
  .wiki-home-page>span { flex:1;min-width:0;display:flex;flex-direction:column;gap:7px; }
  .wiki-home-page :global(svg) { margin-top:3px;flex:0 0 auto;color:var(--text-secondary); }
  .wiki-home-page strong { font-weight:600;font-size:16px;overflow-wrap:anywhere; }
  .wiki-home-page span span { color:var(--text-secondary);font-size:var(--text-sm);line-height:1.6;overflow-wrap:anywhere; }
  .wiki-home-page small { color:var(--text-secondary);font-size:var(--text-xs); }
  .wiki-home-page:hover strong { color:var(--accent); }
  .wiki-editor-head { display:flex;align-items:center;justify-content:space-between;gap:12px;margin:24px 0; }
  .wiki-editor-head h1 { font-size:28px;margin:0; }
  .wiki-editor-head>span { font-size:var(--text-xs);color:var(--text-secondary); }
  .wiki-field { display:flex;flex-direction:column;gap:8px;margin-bottom:20px;font-size:var(--text-sm);font-weight:600; }
  .wiki-field input { width:100%;font-weight:400; }
  .wiki-editor :global(.auto-ta) { min-height:420px;max-height:65dvh;font-family:ui-monospace,monospace;font-size:14px;line-height:1.7; }
  .wiki-editor-actions { display:flex;align-items:center;justify-content:flex-end;gap:10px;position:sticky;bottom:0;padding:16px 0;background:var(--bg);border-top:1px solid var(--border);z-index:2; }
  .wiki-editor-actions>span { margin-right:auto;font-size:var(--text-xs);color:var(--text-secondary); }
  .wiki-editor .wiki-page-info { margin:0 0 20px;padding:0;border:0;font-weight:400; }
  .ac-wrap { position:relative; }
  .ac-list { position:absolute;bottom:100%;left:0;right:0;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);box-shadow:var(--shadow-md);z-index:20;list-style:none;padding:5px; }
  .ac-item { display:flex;justify-content:space-between;gap:15px;width:100%;background:none;border:none;text-align:left;white-space:normal; }
  .ac-item.active { background:var(--accent-soft); }
  .wiki-leave { position:sticky;top:65px;z-index:40;margin-bottom:20px; }
  .wiki-conflict { padding:15px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:20px; }
  .wiki-conflict button { margin:6px 6px 0 0; }
  .rev-list { list-style:none;padding:0;display:flex;flex-direction:column;gap:7px; }
  .rev-list button { width:100%;display:flex;flex-direction:column;align-items:flex-start;white-space:normal;text-align:left;background:none;border:0;font-size:var(--text-sm); }
  .rev-list button.active { background:var(--accent-soft); }
  .rev-banner { display:flex;gap:12px;margin-bottom:14px;font-size:var(--text-sm); }
  .wiki-notice { padding:12px 16px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:var(--text-sm); }
  .muted,.readonly-note { color:var(--text-secondary);font-size:var(--text-sm); }
  .wiki-mobile-bar { display:none; }
  @media(max-width:1200px) {
    .wiki-view { grid-template-columns:240px minmax(0,780px);gap:30px; }
    .wiki-context { grid-column:2;position:static;max-height:none;display:grid;grid-template-columns:1fr 1fr;gap:24px;border-top:1px solid var(--border);padding-top:22px; }
  }
  @media(max-width:760px) {
    .wiki-view { display:flex;flex-direction:column;padding:12px 18px 40px;gap:0; }
    .wiki-mobile-bar { order:0;width:100%; }
    .wiki-nav { order:1;width:100%; }
    .wiki-main { order:3;width:100%; }
    .wiki-context { order:4;width:100%; }
    .wiki-context.context-open { order:2;margin-bottom:20px; }
    .wiki-mobile-bar { display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:20px; }
    .wiki-mobile-bar>span { overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary);font-size:var(--text-xs); }
    .wiki-mobile-bar button { flex-shrink:0; }
    .wiki-nav { display:none;position:static;max-height:65dvh;padding:12px;border:1px solid var(--border);border-radius:var(--radius-md);margin-bottom:20px;background:var(--surface); }
    .wiki-nav.nav-open { display:flex; }
    .wiki-context { display:block;position:static;padding:0;border:0; }
    .wiki-context-section:not(.backlinks) { display:none; }
    .wiki-context.context-open .wiki-context-section:not(.backlinks) { display:block; }
    .wiki-context.context-open { border:1px solid var(--border);padding:16px;border-radius:var(--radius-md); }
    .wiki-context .backlinks { margin-top:25px;padding-top:20px;border-top:1px solid var(--border); }
    .wiki-doc-toolbar { margin-bottom:24px;gap:8px; }
    .wiki-breadcrumb { font-size:var(--text-xs); }
    .wiki-breadcrumb button { max-width:120px; }
    .wiki-actions button { white-space:normal; }
    .wiki-home { padding:15px 0; }
    .wiki-home-heading { margin-top:28px; }
    .wiki-home-heading button { font-size:var(--text-xs); }
    .wiki-editor :global(.auto-ta) { min-height:300px; }
    .wiki-editor-actions { flex-wrap:wrap; }
    .wiki-editor-actions>span { width:100%; }
    .wiki-article { font-size:15px;line-height:1.75; }
    .wiki-doc-meta { gap:8px;font-size:var(--text-xs); }
  }
</style>
