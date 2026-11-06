<script>
  import { t as uiText } from "./lib/i18n.js";
  import { tick, onMount } from "svelte";
  import { api, subscribe, getKey, setKey, clearKey } from "./api.js";
  import {
    buildColumns,
    boardWindow,
  columnCount,
    orderColumns,
    filterItems,
    applyMove,
    applyBulkMove,
    applyRead,
    applyBulkAssign,
    applyBulkLabel,
    applyBulkField,
    rangeBetween,
    refsToMove,
    toggleSelection,
    resolveProject,
    projectKeyOf,
    annotateSearchResults,
    groupMine,
    formatTimestamp,
    absoluteTime,
    nextTheme,
    sortItems,
    SORT_OPTIONS,
    DEFAULT_SORT,
    columnToExpandFor,
    isColumnCollapsed,
    stateColor,
    pageTitle,
  } from "./lib/board.js";
  import { parsePath, parseHashRef, buildPath } from "./lib/routing.js";
  import { applyEvent, closedCountDeltas, applyCountDeltas } from "./lib/liveEvents.js";
  import { mergeRecentItems, filterControlsVisible } from "./lib/allProjectsScope.js";
  import { projectPickerOptions, projectPickerGroups, projectPickerValue, projectPickerAction } from "./lib/projectPicker.js";
  import { unreadGroupCount, INBOX_FETCH_LIMIT } from "./lib/inbox.js";
  import { shouldNotify, notificationText, NOTIFY_STORAGE_KEY } from "./lib/notifications.js";
  import {
    readView,
    isView,
    VIEW_KEY,
    DEFAULT_VIEW,
    pushOverlay,
    popOverlay,
    closeOverlay,
    hasOverlay,
    topOverlay,
    countActiveFilters,
    countPanelFilters,
    activeFilterChips,
    readPersisted,
    writePersisted,
    hidesProjectFilters,
  } from "./lib/viewState.js";
  import { DropdownMenu, Popover } from "bits-ui";
  import { locale, setLocale, t } from "./lib/i18n.js";
  import LanguagePicker from "./LanguagePicker.svelte";
  import Onboarding from "./Onboarding.svelte";
  import Setup from "./Setup.svelte";
  import Drawer from "./Drawer.svelte";
  import DrawerDialog from "./DrawerDialog.svelte";
  import ListView from "./ListView.svelte";
  import Inbox from "./Inbox.svelte";
  import CommandPalette from "./CommandPalette.svelte";
  import NewItem from "./NewItem.svelte";
  import NewProject from "./NewProject.svelte";
  import ProjectsManager from "./ProjectsManager.svelte";
  import ProjectSettings from "./ProjectSettings.svelte";
  import Agents from "./Agents.svelte";
  import InstallationSettings from "./InstallationSettings.svelte";
  import { canManageInstallation } from "./lib/installationSettings.js";
  import Wiki from "./Wiki.svelte";
  import Activity from "./Activity.svelte";
  import Overview from "./Overview.svelte";
  import TriageChat from "./TriageChat.svelte";
  import UserSettings from "./UserSettings.svelte";
  import Deliveries from "./Deliveries.svelte";
  import Avatar from "./Avatar.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import SectionHead from "./SectionHead.svelte";
  import Chip from "./Chip.svelte";
  import AssigneeSelect from "./AssigneeSelect.svelte";
  import Select from "./Select.svelte";
  import { avatarUrlMap, virtualHandleSet } from "./lib/avatar.js";
  import { labelHueOf, setLabelPalette, setLabelLoader, projectKeyOfRef } from "./lib/labelPalette.svelte.js";
  setLabelLoader((key) => api.labels(key));
  import DueBadge from "./DueBadge.svelte";
  import {
    workloadLabel,
    WORKLOAD_VALUES,
    relationMeta,
    relationHue,
    cardRelationPills,
    splitModelLabels,
  } from "./lib/labels.js";
  import WorkloadBadge from "./WorkloadBadge.svelte";
  import { shortcutAction, isTypingTarget, shortcutHelp } from "./lib/palette.js";
  import { groupAssignees } from "./lib/agentType.js";
  import QuickPicker from "./QuickPicker.svelte";
  import { detectCanDrag } from "./lib/pointer.js";
  import { trackBoardTop } from "./lib/boardTop.js";
  import {
    Search,
    Plus,
    X,
    SlidersHorizontal,
    LogOut,
    ChevronDown,
    ChevronRight,
    FolderCog,
    ListChecks,
    Archive,
    BookOpen,
    Settings,
    Sun,
    Moon,
    Monitor,
    Flag,
    LayoutGrid,
    Globe,
    FolderOpen,
    List,
    Bell,
    MessageSquare,
    UserCheck,
    Command,
    Bot,
    Info,
    Webhook,
    MoreHorizontal,
    Lock,
    ShieldAlert,
    ShieldQuestionMark,
    MessageCircleQuestion,
    MessageSquareDot,
    History,
    Cpu,
  } from "@lucide/svelte";

  // readPersisted/writePersisted verhuisden naar lib/viewState.js (BETON-364)
  // zodat Drawer.svelte de tijdlijn-modus met dezelfde helper kan onthouden.

  // --- Dark-mode-toggle (BETON-61): licht/donker/systeem, persistent -------
  const THEME_KEY = "betonning-theme";
  const THEME_META = {
    system: { icon: Monitor, label: "Systeem" },
    light: { icon: Sun, label: "Licht" },
    dark: { icon: Moon, label: "Donker" },
  };
  function readTheme() {
    return readPersisted(THEME_KEY, (t) => t === "light" || t === "dark", "system");
  }
  function applyTheme(t) {
    if (typeof document === "undefined") return;
    const el = document.documentElement;
    if (t === "system") el.removeAttribute("data-theme");
    else el.setAttribute("data-theme", t);
  }
  let theme = $state(readTheme());
  applyTheme(theme); // meteen toepassen bij eerste render
  function cycleTheme() {
    theme = nextTheme(theme);
    writePersisted(THEME_KEY, theme);
    applyTheme(theme);
  }
  let ThemeIcon = $derived(THEME_META[theme].icon);

  // Stipkleur per kolom/state — gedeelde pure logica met de Drawer-
  // subtakenlijst (BETON-203), zie `stateColor` in lib/board.js.
  function dotColor(col) {
    return stateColor(states, col.name);
  }
  // Zelfde kleurbron als de kaart/board (BETON-70), maar per state-naam i.p.v.
  // per kolom-object — zodat de lijstweergave dezelfde stipkleur toont.
  let stateColors = $derived(
    new Map(states.map((s) => [s.name, stateColor(states, s.name)]))
  );

  // Gesloten kolommen (done/cancelled) starten ingeklapt; hier houden we bij
  // welke de gebruiker heeft uitgeklapt (BETON-10). Set → nieuwe ref bij wijziging.
  let expandedCols = $state(new Set());
  // BETON-230: tijdens een actieve zoek/filter mag geen treffer verborgen
  // blijven achter een standaard-ingeklapte kolom (done/cancelled/archief) —
  // isColumnCollapsed forceert dan uitklappen voor kolommen mét resultaten.
  function isCollapsed(col) {
    return isColumnCollapsed(col, expandedCols, activeFilterCount > 0);
  }
  function toggleCollapse(name) {
    const s = new Set(expandedCols);
    s.has(name) ? s.delete(name) : s.add(name);
    expandedCols = s;
  }
  // BETON-200: klap de kolom van een genavigeerd item (zoekresultaat/deep-link)
  // uit als die standaard ingeklapt is, anders blijft de kaart onzichtbaar.
  function expandColumnFor(refStr) {
    const name = columnToExpandFor(items, states, refStr);
    if (name && !expandedCols.has(name)) {
      expandedCols = new Set(expandedCols).add(name);
    }
  }

  let key = $state(getKey());
  let me = $state(null);
  let setupStatus = $state(null);
  let onboarding = $state(null);
  onMount(async () => {
    try { setupStatus = await api.setupStatus(); } catch { /* Bestaande login blijft beschikbaar. */ }
  });
  async function setupCompleted() {
    setupStatus = { required: false, enabled: false };
    await boot();
  }
  let projects = $state([]);
  let users = $state([]);
  let current = $state(null); // project-key
  let states = $state([]);
  let items = $state([]);
  // BETON-359: state-naam → totaal-aantal op de server. Voedt de "toon
  // meer"-voet op begrensde (closed_limit) kolommen; buiten dat gebruik
  // ongebruikt (buildColumns valt zonder een bekende count terug op
  // items.length).
  let stateCounts = $state({});
  let colBusy = $state(new Set()); // kolomnamen die net "toon meer" aan het laden zijn
  let projectLabels = $state([]);
  let milestones = $state([]);
  // Beginroute uit het pad (`/SOS/42?assignee=…&view=…`), met terugval op de
  // oude hash-deeplink (#SOS-42, zonder query). BETON-358: de query-string
  // levert filters/view/scope/sort voor een deelbare link — vóór filters/
  // sortBy/activeView/searchScope hieronder, want die lezen 'm als bron vóór
  // de localStorage-fallback (readPersisted).
  const initialRoute = readRoute();
  const initialQuery = initialRoute.query || {};
  // Snelfilters (BETON-357): mine/unread/question/due/unassigned zijn client-
  // side booleans (of "week"/"overdue" voor due) op de al-geladen items; state
  // is alleen relevant in de lijstweergave. assignee/label/workload/milestone/q
  // blijven server-side (SERVER_FILTER_KEYS hieronder).
  const DEFAULT_FILTERS = {
    assignee: "",
    label: "",
    workload: "",
    milestone: "",
    q: "",
    mine: false,
    unread: false,
    question: false,
    due: "",
    unassigned: false,
    state: "",
  };
  const SERVER_FILTER_KEYS = ["assignee", "label", "workload", "milestone", "q"];
  // Query-velden die ook een filterveld zijn (view/scope/sort horen niet bij
  // `filters`, dus die vallen hier vanzelf weg).
  function filtersFromQuery(query) {
    const out = {};
    for (const k of Object.keys(DEFAULT_FILTERS)) {
      if (query && query[k] !== undefined) out[k] = query[k];
    }
    return out;
  }
  let filters = $state({ ...DEFAULT_FILTERS, ...filtersFromQuery(initialQuery) });
  // Sortering binnen de kolommen (BETON-58): URL > persistent > default
  // laatst-gewijzigd-desc.
  const SORT_KEY = "betonning-sort";
  function readSort() {
    return readPersisted(
      SORT_KEY,
      (s) => SORT_OPTIONS.some((o) => o.key === s),
      DEFAULT_SORT
    );
  }
  let sortBy = $state(
    SORT_OPTIONS.some((o) => o.key === initialQuery.sort) ? initialQuery.sort : readSort()
  );
  function setSort(s) {
    sortBy = s;
    writePersisted(SORT_KEY, s);
  }
  // App-shell view-model (BETON-222): één basis-content-view (bord/lijst/wiki,
  // persistent) + één LIFO overlay-stack die de vroegere ~14 `show*`-booleans
  // vervangt. Alle transitie-logica is puur in lib/viewState.js (vitest).
  // BETON-358: `view` in de URL wint van de persistente localStorage-waarde.
  let activeView = $state(
    isView(initialQuery.view) ? initialQuery.view : readView(readPersisted(VIEW_KEY, isView, DEFAULT_VIEW))
  );
  function setActiveView(v) {
    if (!isView(v)) return;
    activeView = v;
    writePersisted(VIEW_KEY, v);
    // BETON-357: het statusfilter is alleen zichtbaar/bedienbaar in de lijst —
    // laat 'm niet onzichtbaar het bord blijven filteren na een view-wissel.
    if (v !== "list" && filters.state) filters.state = "";
  }
  // Overlay-stack: modals/dialoog-panelen + de mobiele filter-sheet + hints.
  let overlays = $state([]);
  function openOverlay(name) {
    overlays = pushOverlay(overlays, name);
  }
  // Een bits-ui Dialog/DrawerDialog openen vanuit een bits-ui menu-item vereist
  // uitstel van één tick: het menu sluit op dezelfde pointer-event en die zou
  // anders als "klik buiten" op de net-gemonte dialog lekken → de dialog flitst
  // meteen weer dicht. setTimeout(…, 0) laat het menu eerst afronden.
  function openOverlaySoon(name) {
    setTimeout(() => openOverlay(name), 0);
  }
  function closeOverlayNamed(name) {
    overlays = closeOverlay(overlays, name);
  }
  // My Issues (BETON-55): cross-project view van open items van de ingelogde user.
  let mineItems = $state([]);
  let mineBusy = $state(false);
  let mineGroup = $state("project"); // 'project' | 'state'
  // Inbox (BETON-55): events die jou raken + ongelezen-badge.
  let inboxUnread = $state(0);
  // Browser-notificaties (BETON-368): welke inbox-event-ids (per ref, want
  // due-entries dragen allemaal event_id 0) we al zagen — alleen ná de eerste
  // poll ("seeded") melden we nieuwe, anders zou elke page-load de héle
  // bestaande achterstand als "nieuw" melden.
  let notifySeeded = false;
  let prevInboxKeys = new Set();
  // Command palette + sneltoetsen (BETON-56).
  let gChord = $state(false); // actieve "g"-chord (ga naar project)
  let gChordTimer = null;

  // Zoek-scope (BETON-7): 'project' = board-filter huidig project; 'all' =
  // cross-project /search met platte resultatenlijst. BETON-358: `scope` in de
  // URL wint (geen persistente fallback nodig — de scope is altijd "project"
  // tenzij de link 'm expliciet meegeeft).
  let searchScope = $state(initialQuery.scope === "all" ? "all" : "project");
  let searchResults = $state([]);
  let searching = $state(false);
  let searchTimer = null;
  let searchSeq = 0; // race-guard: alleen het nieuwste antwoord tonen
  // "Recent gewijzigd"-lijst voor de lege staat van "Alle projecten" (BETON-225):
  // geen cross-project endpoint, dus per project ophalen en hier samenvoegen.
  let recentAcrossProjects = $state([]);
  let recentBusy = $state(false);
  let recentSeq = 0; // race-guard, zelfde patroon als runGlobalSearch
  let selectedRef = $state(initialRoute.ref); // deep-link uit de URL bij het laden
  // BETON-300: één plek voor "ticket geopend → als gelezen markeren", die zowel
  // de initiële route (deep-link/hard refresh — navigateRef wordt daarbij NIET
  // aangeroepen) als alle SPA-navigatie dekt (navigateRef, openResult, popstate,
  // kaart-klik zetten allemaal gewoon `selectedRef`). Reageert dus puur op
  // wijzigingen van selectedRef zelf i.p.v. een aparte call per open-pad
  // (BETON-286 hing 'm alleen aan navigateRef, dat was het gat). `me` moet
  // gezet zijn (ingelogd) voordat we markeren. Svelte's state-gelijkheidscheck
  // zorgt dat dit niet opnieuw vuurt bij een re-render met dezelfde ref (dus
  // geen dubbele mark-read bij elke drawer-refresh) — stil falen mag het
  // openen van het ticket nooit blokkeren.
  $effect(() => {
    if (!me || !selectedRef) return;
    api.markItemRead(selectedRef)
      .then(() => { items = applyRead(items, selectedRef); })
      .then(refreshInbox)
      .catch(() => {});
  });
  // BETON-273: comment-id waar de drawer na openen naartoe scrollt (bv. de vraag
  // van een open-vraag-notificatie). De drawer wist 'm via onscrolled.
  let selectedCommentTarget = $state(null);
  let newColumn = $state("");
  // Voorinvulling voor NewItem (BETON-373: "Dupliceer" vanuit de Drawer).
  let newItemInitial = $state({});
  let error = $state("");
  let loading = $state(false);
  let dragRef = $state(null);
  let dragoverCol = $state(null);
  let live = $state("offline");
  let liveTick = $state(0);
  let unsubscribe = null;
  let showArchived = $state(false); // archief-browser: toon gearchiveerde items (BETON-59)
  // Multi-select (BETON-14): selectiemodus + geselecteerde refs voor bulk-acties.
  let selectMode = $state(false);
  let selectedRefs = $state([]);
  let bulkBusy = $state(false);
  // Shift-klik-bereikselectie (BETON-360): laatst aangeklikte ref als anchor.
  let lastAnchor = $state(null);
  // Bulk-label: +/− (toevoegen/verwijderen) via de bulk-bar (BETON-360).
  let bulkLabelMode = $state("add");
  // Filter-UI (BETON-222): één "Filter"-knop. Desktop opent een bits-ui Popover
  // (`filterPopoverOpen`), telefoon de bestaande bottomsheet (overlay 'filters').
  let filterPopoverOpen = $state(false);
  let isMobile = $state(false);
  $effect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(max-width: 640px)");
    const update = () => (isMobile = mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  });

  // Touch-toestellen: HTML5-drag uitzetten. iOS Safari start anders een
  // native drag zodra een veeg op een kaart begint, wat scrollen blokkeert;
  // erger nog: een tik met minieme beweging wordt als drag opgevat en de klik
  // (drawer openen) vuurt niet meer (BETON-255). We detecteren touch via
  // `any-pointer: coarse` + `maxTouchPoints` (niet alleen de primaire pointer),
  // zodat ook hybride toestellen (iPad+trackpad, touchscreen-laptop) geen drag
  // meer krijgen. State wijzigen gaat daar via de drawer-select (plan fase 5).
  const canDrag = detectCanDrag();

  // Eenmalige touch-hint (BETON-172): omdat drag&drop op touch uitstaat, leggen
  // we één keer uit dat je de status via de kaart-drawer wijzigt. "Gezien"
  // onthouden we in localStorage zodat de hint echt maar één keer verschijnt.
  const DRAG_HINT_KEY = "betonning:dragHintSeen";
  let showDragHint = $state(
    !canDrag &&
      typeof localStorage !== "undefined" &&
      localStorage.getItem(DRAG_HINT_KEY) !== "1"
  );
  function dismissDragHint() {
    showDragHint = false;
    try {
      localStorage.setItem(DRAG_HINT_KEY, "1");
    } catch {
      /* private mode e.d. — hint gewoon voor deze sessie sluiten */
    }
  }

  // Mobiel: spring naar een kolom in de verticale stapel (chips-nav).
  function scrollToCol(name) {
    const el = document.querySelector(`[data-col="${CSS.escape(name)}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // My Issues gegroepeerd op project of state (BETON-55).
  let mineGroups = $derived(groupMine(mineItems, mineGroup));
  // Handle → avatar_url-lookup (BETON-81): items dragen alleen een assignee-
  // handle, geen avatar_url zelf; kaarten/lijst/comments hebben deze map
  // nodig om `avatarUrl` aan Avatar.svelte door te geven.
  let avatarMap = $derived(avatarUrlMap(users));
  let virtualHandles = $derived(virtualHandleSet(users));

  let currentProject = $derived(projects.find((p) => p.key === current) || null);
  let currentName = $derived(currentProject?.name || current);

  // BETON-345: het huidige project in de browser-tab-titel, zodat meerdere
  // open tabbladen (verschillende projecten) uit elkaar te houden zijn.
  // BETON-368: ongelezen-teller vooraan, ook zichtbaar zonder browser-
  // notificatiepermissie (dat is opt-in en kan geweigerd zijn).
  $effect(() => {
    if (typeof document !== "undefined") document.title = pageTitle(currentName, inboxUnread);
  });

  // Server filtert al op assignee/label/workload/milestone/q; hier draaien ook
  // de client-side snelfilters (mine/unread/question/due/unassigned/state,
  // BETON-357) — hun velden staan al in de compacte item-rij, geen extra fetch.
  let filteredItems = $derived(filterItems(items, filters, { me: me?.handle }));
  // BETON-224: vaste horizontale state-volgorde — werk-kolommen eerst, dan de
  // rust-rail (done/cancelled/deferred), Archief altijd absoluut laatste.
  let columns = $derived(
    orderColumns(buildColumns(states, sortItems(filteredItems, sortBy), stateCounts))
  );

  // BETON-362: vorige/volgende in de drawer volgt de volgorde die de
  // gebruiker daadwerkelijk ZIET, niet de ruwe items-array — op het bord dus
  // kolommen in weergavevolgorde met elke kolom in zijn sorteervolgorde; in
  // de lijstweergave de tabelvolgorde. ListView sorteert lokaal (eigen
  // klik-op-kolomkop-state), dus die meldt zijn volgorde terug via onorder
  // i.p.v. dat App hem hier herberekent.
  let listOrderRefs = $state([]);
  let visibleRefs = $derived(
    activeView === "list"
      ? listOrderRefs
      : columns.flatMap((c) => c.items.map((i) => i.ref)),
  );

  async function boot() {
    error = "";
    try {
      await api.authenticate();
      key = "session";
      // Media-cookie MOET gezet zijn vóór er ook maar één avatar-/attachment-
      // <img> rendert (BETON-202): een <img> die z'n GET doet vóór de cookie er
      // is, krijgt 401 en wordt door de browser niet vanzelf opnieuw geladen. De
      // topbar-avatar hangt al aan `me`, dus dit moet vóór `api.me()`. Een fout
      // slikken we in: dan laden afbeeldingen niet, maar de rest werkt door
      // (en een ongeldige key faalt zo meteen alsnog op api.me()).
      try {
        await api.mediaCookie();
      } catch {
        /* media-afscherming faalt → afbeeldingen leeg, rest werkt door */
      }
      me = await api.me();
      onboarding = me.kind === "human" ? await api.onboarding().catch(() => null) : null;
      if (onboarding?.required) setLocale(onboarding.locale);
      users = await api.users();
      projects = await api.projects();
      if (projects.length) {
        // Kies het project uit de beginroute (deep-link), anders het eerste.
        current = resolveProject(projects, initialRoute.project);
        await loadBoard();
        if (selectedRef) expandColumnFor(selectedRef);
      }
      refreshInbox();
      startLive();
    } catch (e) {
      error = e.message;
      if (e.status === 401) {
        clearKey();
        key = "";
        me = null;
      }
    }
  }

  // BETON-359: hoeveel items een closed-state (done/cancelled/…) maximaal in
  // één keer meekrijgt — een kolom met er méér toont "toon meer" (col.hasMore,
  // via stateCounts).
  const CLOSED_LIMIT = 25;

  async function loadBoard() {
    if (!current) return;
    error = "";
    loading = true;
    try {
      states = await api.states(current);
      projectLabels = await api.labels(current);
      setLabelPalette(projectLabels, current);
      milestones = await api.milestones(current);
      const { assignee, label, workload, milestone, q } = filters;
      // BETON-397: state-counts kennen geen server-filters, dus zodra er één
      // actief is (SERVER_FILTER_KEYS) bestaat er geen venster — geen
      // closed_limit en geen counts (anders klopt hasMore niet meer).
      const { closedLimit, wantCounts } = boardWindow(filters, SERVER_FILTER_KEYS, CLOSED_LIMIT);
      const [fetchedItems, counts] = await Promise.all([
        api.items(current, {
          assignee,
          label,
          workload,
          milestone,
          q,
          archived: showArchived ? "true" : "",
          closed_limit: closedLimit,
        }),
        // Niet kritiek voor het bord zelf — bij een fout blijft hasMore
        // overal false (exact het oude gedrag).
        wantCounts ? api.stateCounts(current, { archived: showArchived }).catch(() => ({})) : {},
      ]);
      items = fetchedItems;
      stateCounts = counts;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  // "Toon meer" op een begrensde kolom (BETON-359): haalt de volgende 50 op,
  // voorbij wat er al lokaal geladen is voor déze state (niet col.items.length
  // — dat is de CLIENT-gefilterde subset; snelfilters mogen de offset niet
  // laten verschuiven).
  async function loadMoreColumn(stateName) {
    if (colBusy.has(stateName)) return;
    colBusy = new Set(colBusy).add(stateName);
    try {
      const alreadyLoaded = items.filter((i) => i.state === stateName && !i.archived_at).length;
      const more = await api.items(current, {
        state: stateName,
        offset: alreadyLoaded,
        limit: 50,
      });
      const existingRefs = new Set(items.map((i) => i.ref));
      items = [...items, ...more.filter((i) => !existingRefs.has(i.ref))];
    } catch (e) {
      error = `Meer laden mislukt (${e.message}).`;
    } finally {
      const next = new Set(colBusy);
      next.delete(stateName);
      colBusy = next;
    }
  }

  // My Issues (BETON-55): cross-project open items van de ingelogde user.
  async function loadMine() {
    mineBusy = true;
    try {
      mineItems = await api.myIssues();
    } catch (e) {
      error = e.message;
    } finally {
      mineBusy = false;
    }
  }
  // Vanuit het Account-menu (bits-ui) geopend → uitstellen (zie openOverlaySoon).
  function openMine() {
    setTimeout(async () => {
      openOverlay("mine");
      await loadMine();
    }, 0);
  }

  // Inbox (BETON-55 / groepering BETON-228): badge = aantal ongelezen GROEPEN,
  // niet losse events. We halen hetzelfde venster op als het paneel
  // (INBOX_FETCH_LIMIT) en groeperen met de gedeelde helper, zodat de badge en
  // de kop-teller in het paneel per constructie hetzelfde getal tonen.
  async function refreshInbox() {
    try {
      const data = await api.inbox(INBOX_FETCH_LIMIT);
      const items = data.items ?? [];
      inboxUnread = unreadGroupCount(items);
      notifyNewInboxItems(items);
    } catch {
      /* stil: badge is niet kritiek */
    }
  }

  // BETON-368: browser-notificatie per nieuw-ongelezen ticket (max één per
  // ref per poll, `tag: ref` laat een tweede notificatie op hetzelfde ticket
  // de vorige vervangen i.p.v. opstapelen). Puur boekhoudkundig hier — de
  // beslissing (`shouldNotify`) en de tekst (`notificationText`) zijn puur en
  // los getest; dit is de dunne DOM-laag ervoor.
  function notifyNewInboxItems(items) {
    // Ticketloze entries (onbereikbare agent, BETON-457) hebben geen ref om
    // naartoe te navigeren; die houden alleen de badge.
    const unreadItems = items.filter((e) => !e.read && e.ref);
    // event_id is 0 voor élke due-entry (BETON-367, er is geen event) — de
    // ref erbij houdt due-entries van verschillende tickets uit elkaar.
    const keys = new Set(unreadItems.map((e) => `${e.ref}:${e.event_id}`));
    if (!notifySeeded) {
      // Eerste poll na page-load: alles wat er al lag is geen "nieuw" item.
      prevInboxKeys = keys;
      notifySeeded = true;
      return;
    }
    const fresh = unreadItems.filter((e) => !prevInboxKeys.has(`${e.ref}:${e.event_id}`));
    prevInboxKeys = keys;
    if (!fresh.length) return;
    if (typeof document === "undefined" || typeof Notification === "undefined") return;
    const enabled = readPersisted(NOTIFY_STORAGE_KEY, (v) => v === "1" || v === "0", "0") === "1";
    if (
      !shouldNotify({
        enabled,
        permission: Notification.permission,
        hidden: document.hidden,
        delta: fresh.length,
      })
    ) {
      return;
    }
    const seenRefs = new Set();
    for (const entry of fresh) {
      if (seenRefs.has(entry.ref)) continue;
      seenRefs.add(entry.ref);
      const { title, body } = notificationText(entry, $locale);
      try {
        const n = new Notification(title, { body, tag: entry.ref });
        n.onclick = () => {
          window.focus();
          navigateRef(entry.ref);
        };
      } catch {
        /* stil: een melding is nooit kritiek voor de rest van de app */
      }
    }
  }

  async function login(e) {
    e.preventDefault();
    const entered = new FormData(e.target).get("key").toString().trim();
    if (!entered) return;
    setKey(entered);
    key = entered;
    await boot();
  }

  function startLive() {
    if (unsubscribe) return;
    unsubscribe = subscribe(onLiveEvent, {
      onStatus: (s) => (live = s),
      // BETON-402: na een herverbinding is er een gat dat de stream niet dicht
      // kan garanderen (met since=0 slaat from=latest het zelfs over). Volledig
      // herladen is het vangnet — via de bestaande 200ms-debounce, zodat een
      // herverbinding tijdens een burst één reload oplevert.
      onResync: () => {
        fullReloadSoon();
        refreshSideEffectsSoon();
      },
    });
  }

  // Live event → board incrementeel bijwerken (BETON-186) i.p.v. elke keer een
  // volledige loadBoard(). De reducer (lib/liveEvents.js) past het verrijkte
  // event rechtstreeks op `items` toe; alleen als dat niet betrouwbaar kan
  // (reducer geeft `null`, of er staan server-side filters aan) valt hij terug
  // op de bestaande debounce + loadBoard().
  let liveTimer = null;
  function fullReloadSoon() {
    if (liveTimer) return; // korte debounce tegen bursts
    liveTimer = setTimeout(() => {
      liveTimer = null;
      loadBoard();
    }, 200);
  }

  // Inbox/Mijn-tickets apart en gedebounced verversen — alleen voor events die
  // ze kunnen raken (mention/toewijzing/nieuwe reactie), niet bij elke wijziging.
  let sideTimer = null;
  function refreshSideEffectsSoon() {
    if (sideTimer) return;
    sideTimer = setTimeout(() => {
      sideTimer = null;
      refreshInbox();
      if (hasOverlay(overlays, "mine")) loadMine();
    }, 250);
  }
  function sideEffectRelevant(type) {
    return (
      type === "item.created" ||
      type === "item.updated" ||
      type === "item.archived" ||
      type === "item.restored" ||
      type === "item.moved" ||
      type === "comment.created" ||
      type === "comment.updated"
    );
  }

  // Incrementeel toepassen kan alleen betrouwbaar zonder server-side filters
  // (milestone/q draaien alleen server-side) en in de project-zoekscope. De
  // client-side snelfilters (BETON-357) blokkeren dit niet — filteredItems
  // herrekent toch bij elke items-wijziging.
  function canApplyIncremental() {
    return (
      !!current &&
      SERVER_FILTER_KEYS.every((k) => !filters[k]) &&
      searchScope === "project"
    );
  }

  function onLiveEvent(event) {
    // De open drawer luistert op liveTick — altijd tikken, óók als het board
    // zelf niet wijzigt (de drawer kan een cross-project ticket tonen).
    liveTick += 1;
    if (event && sideEffectRelevant(event.type)) refreshSideEffectsSoon();

    if (canApplyIncremental()) {
      const before = items;
      const next = applyEvent({ items: before, project: current, showArchived }, event);
      if (next) {
        items = next;
        // BETON-359: houdt de "toon meer"-teller van begrensde kolommen
        // synchroon — een live upsert/verwijdering in een closed state
        // verandert de server-count met evenveel als de lokale array.
        const closedNames = states.filter((s) => s.closed).map((s) => s.name);
        if (closedNames.length) {
          const deltas = closedCountDeltas(before, next, closedNames);
          if (Object.keys(deltas).length) stateCounts = applyCountDeltas(stateCounts, deltas);
        }
        return;
      }
    }
    fullReloadSoon();
  }

  async function logout() {
    unsubscribe?.();
    unsubscribe = null;
    live = "offline";
    // Het media-cookie is HttpOnly; alleen de server kan het wissen (BETON-383).
    // Nog even mét de key, dus vóór clearKey(). Mislukt het (offline), dan gaat
    // het lokaal uitloggen gewoon door — het cookie verloopt binnen 24 uur.
    try {
      await api.logout();
    } catch {}
    clearKey();
    key = "";
    me = null;
    projects = [];
    items = [];
    overlays = [];
  }

  // Projectkiezer (BETON-453): Overzicht is de bovenste optie; een project
  // kiezen vanuit het overzicht verlaat het overzicht.
  function pickProject(choice) {
    const a = projectPickerAction(choice, activeView);
    if (a.view) setActiveView(a.view);
    if (a.project) switchProject(a.project);
  }
  async function switchProject(k) {
    current = k;
    selectedRef = null;
    filters = { ...DEFAULT_FILTERS };
    searchScope = "project";
    searchResults = [];
    recentAcrossProjects = [];
    await loadBoard();
  }

  // Actieve (niet-lege) filters — voor `isColumnCollapsed` (een zoekterm
  // hoort een ingeklapte kolom te openen) en de chips-rij. BEWUST breed (telt
  // ook q/snelfilters mee) — zie viewState.js:countActiveFilters.
  let activeFilterCount = $derived(countActiveFilters(filters));
  let filterChips = $derived(activeFilterChips(filters, $locale));
  // BETON-398: de badge op de Filter-knop toont alleen wat het paneel ook
  // echt bevat (toegewezen-aan/label/werklast/milestone + archief-toggle) —
  // niet q (zoekbalk) en niet de snelfilters (chiprij), anders staat er
  // "Filter 1" met een leeg paneel.
  let panelFilterCount = $derived(countPanelFilters(filters, { archived: showArchived }));
  async function clearFilters() {
    filters = { ...DEFAULT_FILTERS };
    if (searchScope === "all") searchResults = [];
    await loadBoard();
  }
  // Eén filter-chip wegklikken: wis dat veld. Alleen server-side velden
  // (BETON-357: assignee/label/workload/milestone/q) hoeven een herlaad —
  // de snelfilters herrekenen client-side via `filteredItems`.
  async function clearOneFilter(fieldKey) {
    filters[fieldKey] = typeof filters[fieldKey] === "boolean" ? false : "";
    if (fieldKey === "q" && searchScope === "all") searchResults = [];
    if (SERVER_FILTER_KEYS.includes(fieldKey)) await loadBoard();
  }
  // Snelfilter-chip togglen (BETON-357): booleans om, "due" cyclisch tussen
  // de twee waarden ("" ↔ waarde), altijd client-side (geen loadBoard).
  function toggleQuickFilter(key) {
    filters[key] = !filters[key];
  }
  function toggleDue(value) {
    filters.due = filters.due === value ? "" : value;
  }

  // Archief-browser (BETON-59): toon/verberg gearchiveerde items op het board.
  async function toggleArchived() {
    showArchived = !showArchived;
    await loadBoard();
  }

  // --- Zoek-scope: dit project ↔ alle projecten (BETON-7) ------------------
  function onSearchInput(e) {
    filters.q = e.currentTarget.value;
    // BETON-210: filter instant terwijl je typt (gedebounced), voor beide scopes —
    // niet pas op enter/blur. Board-scope draait loadBoard (server-side q-filter),
    // global-scope de cross-project /search.
    clearTimeout(searchTimer);
    searchTimer = setTimeout(
      searchScope === "all" ? runGlobalSearch : loadBoard,
      200,
    );
  }
  function onSearchChange() {
    // Enter/blur: meteen filteren (de gedebouncede input dekt live typen al af).
    if (searchScope === "project") {
      clearTimeout(searchTimer);
      loadBoard();
    }
  }
  async function runGlobalSearch() {
    const q = filters.q.trim();
    if (!q) {
      searchResults = [];
      return;
    }
    const seq = ++searchSeq;
    searching = true;
    try {
      const rows = await api.search(q, 50);
      if (seq !== searchSeq) return; // ouder antwoord: negeren
      searchResults = annotateSearchResults(rows, projects);
    } catch (e) {
      error = e.message;
    } finally {
      if (seq === searchSeq) searching = false;
    }
  }
  // "Recent gewijzigd" over alle projecten (BETON-225): vult de lege staat van
  // de "Alle projecten"-scope zodra je erin schakelt en nog niets getypt hebt.
  // Er is geen cross-project endpoint, dus per project ophalen (net als
  // loadBoard voor het huidige project) en hier client-side samenvoegen.
  async function loadRecentAcrossProjects() {
    if (!projects.length) {
      recentAcrossProjects = [];
      return;
    }
    const seq = ++recentSeq;
    recentBusy = true;
    try {
      const lists = await Promise.all(
        projects.map((p) => api.items(p.key).catch(() => []))
      );
      if (seq !== recentSeq) return; // ouder antwoord: negeren
      recentAcrossProjects = annotateSearchResults(mergeRecentItems(lists), projects);
    } finally {
      if (seq === recentSeq) recentBusy = false;
    }
  }
  async function setScope(s) {
    if (s === searchScope) return;
    searchScope = s;
    if (s === "all") {
      focusSearch();
      loadRecentAcrossProjects();
      if (filters.q.trim()) runGlobalSearch();
    } else {
      searchResults = [];
      recentAcrossProjects = [];
      await loadBoard();
    }
  }
  // Klik op een cross-project resultaat → naar het juiste project + drawer open.
  // BETON-370: een treffer die alleen in een reactie zit draagt een comment_id;
  // de drawer scrollt dan naar die reactie. Altijd (her)zetten — een oude target
  // zou anders bij de volgende gewone treffer blijven hangen.
  async function openResult(refStr, commentId = null) {
    const key = projectKeyOf(refStr);
    const proj = key && projects.find((p) => p.key.toUpperCase() === key);
    searchScope = "project";
    searchResults = [];
    recentAcrossProjects = [];
    filters = { ...DEFAULT_FILTERS };
    // BETON-411: zelfde volgorde als navigateRef — eerst openen, dan pas het
    // bord herladen.
    selectedCommentTarget = commentId ?? null;
    selectedRef = refStr;
    if (proj && proj.key !== current) {
      current = proj.key;
      await loadBoard();
    }
    expandColumnFor(refStr);
  }

  // Navigeer naar een (mogelijk cross-project) ref en open de drawer. Anders dan
  // openResult (dat de zoekstaat opruimt): filters blijven behouden als het
  // ticket in het huidige project zit; alleen bij een échte projectwissel
  // resetten we de project-specifieke filters/zoek (zoals switchProject). Wordt
  // gebruikt door de drawer (subtaken/relaties/ticketrefs), wiki-ticketlinks en
  // de cross-project-panelen (Mijn tickets, Inbox, palette).
  async function navigateRef(refStr, commentTarget = null) {
    const key = projectKeyOf(refStr);
    const proj = key && projects.find((p) => p.key.toUpperCase() === key);
    // BETON-411: de drawer gaat OPEN vóór een eventuele board-herlaad. Stond
    // dit ná `await loadBoard()`, dan slikte een hangende board-fetch (dode
    // verbinding na slaapstand, vgl. BETON-405) de hele navigatie op: geen
    // drawer, geen foutmelding, niets in de console — precies het beeld dat
    // BETON-411 meldde. De drawer haalt zijn eigen ticket op en heeft het bord
    // dus niet nodig; zijn body zit achter `{#if item}`, dus er is ook geen
    // moment waarop hij de states van het oude project toont.
    // BETON-273: optioneel doorscrollen naar een specifieke comment in de drawer
    // (bv. de vraag bij een open-vraag-notificatie).
    selectedCommentTarget = commentTarget;
    selectedRef = refStr;
    if (proj && proj.key !== current) {
      current = proj.key;
      filters = { ...DEFAULT_FILTERS };
      searchScope = "project";
      searchResults = [];
      await loadBoard();
    }
    expandColumnFor(refStr);
    // BETON-300: mark-read gebeurt nu in het effect op selectedRef (dekt ook
    // de deep-link/hard-refresh-route die hier niet langsloopt), niet meer
    // hier expliciet.
  }

  // --- Routing: echte paden `/<project>` en `/<project>/<seq>`, + querystring
  // voor filters/view/scope/sort (BETON-358) ---------------------------------
  // Lees de route uit het pad; val terug op een oude hash-deeplink (#SOS-42,
  // die geen query draagt).
  function readRoute() {
    if (typeof location === "undefined") return { project: null, ref: null, query: {} };
    const fromPath = parsePath(location.pathname, location.search);
    if (fromPath.project) return fromPath;
    return { ...parseHashRef(location.hash), query: {} };
  }

  // De huidige filters/view/scope/sort als query-object, met alleen de velden
  // die van hun default afwijken — zo blijft een "kale" URL (bord, dit
  // project, standaardsortering, geen filters) gewoon `/SOS` i.p.v. altijd
  // volgestouwd met `?view=board&scope=project&sort=…`.
  function currentQuery() {
    const q = { ...filters };
    if (activeView !== DEFAULT_VIEW) q.view = activeView;
    if (searchScope !== "project") q.scope = searchScope;
    if (sortBy !== DEFAULT_SORT) q.sort = sortBy;
    return q;
  }

  // Houd de URL gelijk aan project + geopende drawer + filters/view/scope/sort,
  // zonder herladen. Eerste sync na boot vervangt (geen bogus history-entry).
  // Daarna: een échte navigatie (ander project of andere geopende ticket-ref —
  // switchProject/navigateRef/openResult/kaart-klik/drawer-sluiten) pusht een
  // nieuwe history-entry (zodat de back-knop 'm herstelt); een wijziging die
  // alleen de querystring raakt (filter/sort/view/scope) vervangt de huidige
  // entry — anders zou elke filterklik de back-knop vervuilen.
  let routeSynced = false;
  let lastNavKey = null;
  $effect(() => {
    if (!current) return; // wacht tot boot een project heeft gekozen
    const navKey = `${current}|${selectedRef ?? ""}`;
    const path = buildPath(current, selectedRef, currentQuery());
    if (location.pathname + location.search === path) {
      routeSynced = true;
      lastNavKey = navKey;
      return;
    }
    const navChanged = navKey !== lastNavKey;
    lastNavKey = navKey;
    if (routeSynced && navChanged) history.pushState({}, "", path);
    else history.replaceState({}, "", path);
    routeSynced = true;
  });

  // Back/forward: route opnieuw uit het pad + querystring afleiden en de
  // view/filters/scope/sort herstellen naar wat ze waren toen die entry werd
  // gepusht (ontbrekend veld = de default van dat moment, BETON-358).
  async function onPopState() {
    const r = parsePath(location.pathname, location.search);
    const next = resolveProject(projects, r.project);
    filters = { ...DEFAULT_FILTERS, ...filtersFromQuery(r.query) };
    activeView = isView(r.query.view) ? r.query.view : DEFAULT_VIEW;
    searchScope = r.query.scope === "all" ? "all" : "project";
    sortBy = SORT_OPTIONS.some((o) => o.key === r.query.sort) ? r.query.sort : DEFAULT_SORT;
    if (next !== current) {
      current = next;
      selectedRef = r.ref;
      await loadBoard();
    } else {
      selectedRef = r.ref;
    }
  }

  // --- Globale sneltoetsen (BETON-56/64/361) -------------------------------
  let searchEl = $state(null);
  // BETON-453: onder ~900px is het zoekveld een icoon dat uitklapt. Op
  // desktop-breedte is het veld altijd zichtbaar (CSS negeert `searchOpen`).
  let searchOpen = $state(false);
  async function focusSearch() {
    searchOpen = true;
    await tick();
    searchEl?.focus();
  }
  function onSearchFocusOut(e) {
    if (e.currentTarget.contains(e.relatedTarget)) return;
    if (!filters.q && searchScope === "project") searchOpen = false;
  }
  // Kaart-acties (x/a/s/l/e/m) werken op de kaart/rij die net toetsenbordfocus
  // heeft — dezelfde `data-ref`-elementen als navigateCards hieronder.
  let quickPicker = $state(null); // {items, anchorRect, onselect} of null
  // "e" opent de drawer en start meteen de omschrijving-edit (BETON-361); de
  // drawer zelf wist dit weer via onautoedited zodra hij het heeft opgepakt.
  let autoEditRef = $state(null);

  function focusedCard() {
    const el = document.activeElement;
    return el && el.dataset?.ref ? el : null;
  }

  function openQuickPicker(items, anchorEl, onselect) {
    quickPicker = { items, anchorRect: anchorEl.getBoundingClientRect(), onselect };
  }
  function closeQuickPicker() {
    quickPicker = null;
  }
  function startGChord() {
    gChord = true;
    clearTimeout(gChordTimer);
    gChordTimer = setTimeout(() => (gChord = false), 1500);
  }
  function cancelGChord() {
    gChord = false;
    clearTimeout(gChordTimer);
  }
  // Verplaats de toetsenbordfocus tussen kaarten/rijen (board én lijst). Hergebruikt
  // de bestaande Enter-afhandeling op de kaart zelf (BETON-64 = één implementatie).
  function navigateCards(delta) {
    const els = [...document.querySelectorAll(".card[data-ref], .list-row[data-ref]")];
    if (!els.length) return;
    let idx = els.indexOf(document.activeElement);
    if (idx === -1) idx = delta > 0 ? -1 : 0;
    const next = (idx + delta + els.length) % els.length;
    els[next]?.focus();
    els[next]?.scrollIntoView({ block: "nearest" });
  }
  function onGlobalKey(e) {
    if (hasOverlay(overlays, "palette")) return; // palette handelt zijn eigen toetsen af
    if (isTypingTarget(e.target)) return; // niet kapen tijdens typen
    const action = shortcutAction(e, { chord: gChord ? "g" : null });
    if (!action) return;
    switch (action.type) {
      case "palette":
        e.preventDefault();
        openOverlay("palette");
        break;
      case "new-item":
        e.preventDefault();
        openNew();
        break;
      case "focus-search":
        e.preventDefault();
        focusSearch();
        break;
      case "toggle-hints":
        e.preventDefault();
        overlays = hasOverlay(overlays, "hints")
          ? closeOverlay(overlays, "hints")
          : pushOverlay(overlays, "hints");
        break;
      case "chord-start":
        e.preventDefault();
        startGChord();
        break;
      case "goto-project": {
        e.preventDefault();
        cancelGChord();
        const c = action.char.toLowerCase();
        const hit = projects.find((p) => p.key.toLowerCase().startsWith(c));
        if (hit) pickProject(hit.key);
        break;
      }
      case "chord-cancel":
        cancelGChord();
        break;
      case "nav-card":
        e.preventDefault();
        navigateCards(action.delta);
        break;
      case "open-inbox":
        e.preventDefault();
        openOverlay("inbox");
        break;
      case "toggle-view":
        e.preventDefault();
        setActiveView(activeView === "list" ? "board" : "list");
        break;
      case "open-wiki":
        e.preventDefault();
        setActiveView("wiki");
        break;
      case "toggle-select": {
        const el = focusedCard();
        if (!el) break;
        e.preventDefault();
        if (!selectMode) selectMode = true;
        toggleSelect(el.dataset.ref);
        break;
      }
      case "quick-assign": {
        const el = focusedCard();
        if (!el) break;
        e.preventDefault();
        const ref = el.dataset.ref;
        const opts = groupAssignees(users, me).flatMap((g) => g.options).map((u) => ({ label: `@${u.handle}`, value: u.handle }));
        openQuickPicker(opts, el, async (handle) => {
          closeQuickPicker();
          try {
            await api.updateItem(ref, { assignee: handle });
            await loadBoard();
          } catch (err) {
            error = err.message;
          }
        });
        break;
      }
      case "quick-state": {
        const el = focusedCard();
        if (!el) break;
        e.preventDefault();
        const ref = el.dataset.ref;
        const opts = states.map((s) => ({ label: s.name, value: s.name }));
        openQuickPicker(opts, el, async (name) => {
          closeQuickPicker();
          await move(ref, name);
        });
        break;
      }
      case "quick-label": {
        const el = focusedCard();
        if (!el) break;
        e.preventDefault();
        const ref = el.dataset.ref;
        const opts = projectLabels.map((l) => ({ label: l.name, value: l.name }));
        openQuickPicker(opts, el, async (name) => {
          closeQuickPicker();
          try {
            await api.addLabel(ref, name);
            await loadBoard();
          } catch (err) {
            error = err.message;
          }
        });
        break;
      }
      case "edit-card": {
        const el = focusedCard();
        if (!el) break;
        e.preventDefault();
        autoEditRef = el.dataset.ref;
        navigateRef(el.dataset.ref);
        break;
      }
      case "mark-read": {
        const el = focusedCard();
        if (!el) break;
        e.preventDefault();
        const ref = el.dataset.ref;
        api
          .markItemRead(ref)
          .then(() => { items = applyRead(items, ref); })
          .catch(() => {});
        break;
      }
      case "escape": {
        // Bits-ui overlays (mine/inbox/palette/settings/…) sluiten zichzelf op
        // Esc via hun eigen focus-trap → onclose (geen dubbele pop). Alleen de
        // handgemaakte lagen bovenaan de stack sluiten we hier: de hints-overlay
        // en de mobiele filter-sheet.
        const top = topOverlay(overlays);
        if (top === "hints" || top === "filters") overlays = popOverlay(overlays).stack;
        break;
      }
      // 'open-card' laten we aan de gefocuste kaart zelf over (eigen Enter-handler).
    }
  }

  // Toast automatisch laten verdwijnen (blijft dismissbaar met de ×).
  $effect(() => {
    if (!error) return;
    const t = setTimeout(() => (error = ""), 6000);
    return () => clearTimeout(t);
  });

  async function move(ref, stateName) {
    const item = items.find((i) => i.ref === ref);
    if (!item || item.state === stateName) return;
    items = applyMove(items, ref, stateName); // optimistisch
    try {
      await api.updateItem(ref, { state: stateName });
    } catch (e) {
      error = `Verplaatsen mislukt (${e.message}) — teruggedraaid.`;
      await loadBoard(); // rollback naar serverwaarheid
    }
  }

  function onDrop(colName) {
    const ref = dragRef;
    dragRef = null;
    dragoverCol = null;
    if (ref) move(ref, colName);
  }

  // --- Multi-select (BETON-14) ---------------------------------------------
  function toggleSelectMode() {
    selectMode = !selectMode;
    selectedRefs = [];
    lastAnchor = null;
  }
  function exitSelectMode() {
    selectMode = false;
    selectedRefs = [];
    lastAnchor = null;
  }
  function toggleSelect(ref) {
    selectedRefs = toggleSelection(selectedRefs, ref);
  }
  // Shift-klik selecteert het bereik tussen de vorige klik (anchor) en deze
  // ref, over de daadwerkelijk zichtbare volgorde (`visibleRefs`: kolommen in
  // weergavevolgorde op het bord, tabelvolgorde in de lijstweergave —
  // BETON-360, hergebruikt van BETON-362's `visibleRefs`).
  function selectWithRange(ref, e) {
    if (e?.shiftKey && lastAnchor) {
      const range = rangeBetween(visibleRefs, lastAnchor, ref);
      selectedRefs = Array.from(new Set([...selectedRefs, ...range]));
    } else {
      toggleSelect(ref);
    }
    lastAnchor = ref;
  }
  // Selecteer/deselecteer een hele set refs in één keer (kolomkop "alles",
  // BETON-360) — alles-aan als niet alles al geselecteerd is, anders alles-uit.
  function toggleRefSet(refs) {
    if (!refs.length) return;
    const allSelected = refs.every((r) => selectedRefs.includes(r));
    selectedRefs = allSelected
      ? selectedRefs.filter((r) => !refs.includes(r))
      : Array.from(new Set([...selectedRefs, ...refs]));
  }
  function onCardClick(ref, e) {
    if (selectMode) selectWithRange(ref, e);
    else selectedRef = ref;
  }

  async function bulkMove(stateName) {
    if (!stateName || !selectedRefs.length || bulkBusy) return;
    const refs = refsToMove(items, selectedRefs, stateName);
    if (!refs.length) return;
    bulkBusy = true;
    items = applyBulkMove(items, refs, stateName); // optimistisch
    try {
      await Promise.all(refs.map((r) => api.updateItem(r, { state: stateName })));
      exitSelectMode();
    } catch (e) {
      error = `Bulk-verplaatsen mislukt (${e.message}) — teruggedraaid.`;
      await loadBoard();
    } finally {
      bulkBusy = false;
    }
  }

  async function bulkArchive() {
    if (!selectedRefs.length || bulkBusy) return;
    const refs = [...selectedRefs];
    bulkBusy = true;
    // Optimistisch uit de lijst halen; server-waarheid bij mislukking.
    items = items.filter((i) => !refs.includes(i.ref));
    try {
      await Promise.all(refs.map((r) => api.archiveItem(r)));
      exitSelectMode();
    } catch (e) {
      error = `Bulk-archiveren mislukt (${e.message}) — teruggedraaid.`;
      await loadBoard();
    } finally {
      bulkBusy = false;
    }
  }

  async function bulkAssign(handle) {
    if (!selectedRefs.length || bulkBusy) return;
    const refs = [...selectedRefs];
    bulkBusy = true;
    items = applyBulkAssign(items, refs, handle); // optimistisch
    try {
      await Promise.all(refs.map((r) => api.updateItem(r, { assignee: handle })));
      exitSelectMode();
    } catch (e) {
      error = `Bulk-toewijzen mislukt (${e.message}) — teruggedraaid.`;
      await loadBoard();
    } finally {
      bulkBusy = false;
    }
  }

  // BETON-360: label/milestone/werklast in bulk — zelfde optimistisch-dan-
  // Promise.all-dan-rollback-patroon als bulkMove/bulkAssign/bulkArchive.
  async function bulkLabel(name, add) {
    if (!name || !selectedRefs.length || bulkBusy) return;
    const refs = [...selectedRefs];
    bulkBusy = true;
    items = applyBulkLabel(items, refs, name, add); // optimistisch
    try {
      await Promise.all(
        refs.map((r) => (add ? api.addLabel(r, name) : api.removeLabel(r, name))),
      );
      exitSelectMode();
    } catch (e) {
      error = `Bulk-labelen mislukt (${e.message}) — teruggedraaid.`;
      await loadBoard();
    } finally {
      bulkBusy = false;
    }
  }

  async function bulkMilestone(name) {
    if (!name || !selectedRefs.length || bulkBusy) return;
    const refs = [...selectedRefs];
    bulkBusy = true;
    items = applyBulkField(items, refs, "milestone", name); // optimistisch
    try {
      await Promise.all(refs.map((r) => api.updateItem(r, { milestone: name })));
      exitSelectMode();
    } catch (e) {
      error = `Bulk-milestone mislukt (${e.message}) — teruggedraaid.`;
      await loadBoard();
    } finally {
      bulkBusy = false;
    }
  }

  async function bulkWorkload(value) {
    if (!value || !selectedRefs.length || bulkBusy) return;
    const refs = [...selectedRefs];
    bulkBusy = true;
    items = applyBulkField(items, refs, "workload", value); // optimistisch
    try {
      await Promise.all(refs.map((r) => api.updateItem(r, { workload: value })));
      exitSelectMode();
    } catch (e) {
      error = `Bulk-werklast mislukt (${e.message}) — teruggedraaid.`;
      await loadBoard();
    } finally {
      bulkBusy = false;
    }
  }

  function endDrag() {
    dragRef = null;
    dragoverCol = null;
  }

  function openNew(colName = "", initial = {}) {
    newColumn = colName;
    newItemInitial = initial || {};
    openOverlay("new");
  }

  // BETON-373: "Dupliceer" in de Drawer — sluit de drawer, open NewItem
  // voorgevuld vanuit duplicateDraft(item) + een relates_to naar het
  // origineel (draft.originRef, apart meegegeven — duplicateDraft zelf kent
  // het origineel niet, dat is de aanroeper).
  function onDuplicate(draft, originRef) {
    selectedRef = null;
    openNew("", { ...draft, relatesTo: originRef });
  }

  // BETON-363: "Subtaak toevoegen" in de Drawer-rail — sluit de drawer niet
  // (spiegelt onDuplicate qua vorm, maar de gebruiker wil hier vaak terug naar
  // de parent), open NewItem met parent (+ milestone) voorgevuld.
  function onNewSubtask(draft) {
    openNew("", draft);
  }
  async function onCreated() {
    closeOverlayNamed("new");
    // Bewust géén drawer openen: de nieuwe kaart verschijnt via loadBoard() (BETON-3).
    await loadBoard();
  }

  // Nieuw project aangemaakt → lijst verversen en er meteen naartoe switchen.
  async function onProjectCreated(created) {
    closeOverlayNamed("newProject");
    projects = await api.projects();
    if (created?.key) await switchProject(created.key);
  }

  // Archiveren/herstellen in de manager → selector verversen; als het huidige
  // project net verdween, naar het eerste overgebleven project (of empty-state).
  async function onProjectsChanged() {
    projects = await api.projects();
    if (!projects.some((p) => p.key === current)) {
      if (projects.length) await switchProject(projects[0].key);
      else {
        current = null;
        items = [];
      }
    }
  }

  $effect(() => {
    const expire = () => {
      unsubscribe?.(); unsubscribe = null;
      key = ""; me = null; projects = []; items = []; overlays = []; selectedRef = null;
    };
    window.addEventListener("betonning-session-expired", expire);
    return () => window.removeEventListener("betonning-session-expired", expire);
  });
  $effect(() => { document.documentElement.lang = $locale; });
  if (key) boot();
</script>

<svelte:window onpopstate={onPopState} onkeydown={onGlobalKey} />

{#if !me && setupStatus?.required}
  <Setup enabled={setupStatus.enabled} oncomplete={setupCompleted} />
{:else if me && onboarding?.required}
  <Onboarding progress={onboarding} oncomplete={boot} />
{:else if !me}
  <div class="login">
    <div class="wordmark login-mark">
      <span class="mark"></span>
      <span>Hegemone</span>
    </div>
    <p class="muted login-sub">{$t("login.intro")}</p>
    <LanguagePicker />
    <form class="login-form" onsubmit={login}>
      <input name="key" type="password" placeholder="bt_…" aria-label={$t("login.key")} />
      <button class="primary" type="submit">{$t("login.signIn")}</button>
    </form>
    {#if error}<p class="error">{error}</p>{/if}
  </div>
{:else}
  <header class="topbar">
    <div class="tb-cluster tb-left">
      <div class="wordmark">
        <span class="mark buoy" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d="M12 2 L15 8 H9 Z" fill="var(--accent)" />
            <rect x="10.5" y="8" width="3" height="7.5" fill="var(--accent)" />
            <path d="M6.2 15.5 h11.6 l-1.4 5 h-8.8 Z" fill="var(--accent)" opacity="0.55" />
          </svg>
        </span>
        <span class="wordmark-text">Hegemone</span>
      </div>
      <Select
        class="tb-project"
        ariaLabel={$t("nav.project")}
        value={projectPickerValue(activeView, current)}
        options={projectPickerOptions(projects, current, undefined, $locale)}
        groups={projectPickerGroups(projects, current, undefined, $locale)}
        onchange={pickProject}
      />
    </div>

    <!-- MIDDEN: zoeken + scope + één filter-knop (BETON-222). Verborgen in de
         views die niet over één project gaan: wiki (eigen zoek/navigatie),
         activiteitenfeed (BETON-372, eigen actor/type-filters) en overzicht
         (BETON-371, cross-project) — zie hidesProjectFilters. -->
    <div class="tb-cluster tb-center" class:tb-hidden={hidesProjectFilters(activeView)}>
      <button
        class="icon-btn search-toggle"
        class:open={searchOpen}
        onclick={focusSearch}
        title={$t("nav.search")}
        aria-label={$t("nav.search")}
        aria-expanded={searchOpen}
      >
        <Search size={16} />
      </button>
      <div class="search" class:open={searchOpen} onfocusout={onSearchFocusOut}>
        <Search size={16} class="search-icon" />
        <input
          class="search-input"
          class:has-clear={!!activeFilterCount}
          bind:this={searchEl}
          placeholder={$t(searchScope === "all" ? "search.all" : "search.hint")}
          aria-label={$t("nav.search")}
          value={filters.q}
          oninput={onSearchInput}
          onchange={onSearchChange}
        />
        {#if activeFilterCount}
          <button
            class="search-clear"
            onmousedown={(e) => e.preventDefault()}
            onclick={clearFilters}
            title={$uiText("ui.clearFilters")}
            aria-label={$uiText("ui.clearFilters")}
          >
            <X size={14} />
          </button>
        {/if}
        <!-- Zoek-scope ín het veld (BETON-453): een schakelaartje, geen losse
             segmented control naast het veld. -->
        <button
          class="search-scope"
          class:all={searchScope === "all"}
          onmousedown={(e) => e.preventDefault()}
          onclick={() => setScope(searchScope === "all" ? "project" : "all")}
          aria-pressed={searchScope === "all"}
          aria-label={$t("search.scope")}
          title={$t(searchScope === "all" ? "search.toProject" : "search.toAll")}
        >
          {#if searchScope === "all"}<Globe size={14} />{:else}<FolderOpen size={14} />{/if}
          <span class="search-scope-label">{$t(searchScope === "all" ? "search.allProjects" : "search.thisProject")}</span>
        </button>
      </div>
      {#if filterControlsVisible(searchScope)}
        {#if isMobile}
          <!-- Telefoon: bestaande filter-bottomsheet hergebruiken. -->
          <button class="tb-filter-btn" onclick={() => openOverlay("filters")} aria-label={$t("filter.title")}>
            <SlidersHorizontal size={15} /> <span class="tb-filter-label">Filter</span>{#if panelFilterCount}<span class="filter-count">{panelFilterCount}</span>{/if}
          </button>
        {:else}
          <!-- Desktop: filter-popover onder de knop. -->
          <Popover.Root bind:open={filterPopoverOpen}>
            <Popover.Trigger class="tb-filter-btn" aria-label={$t("filter.title")}>
              <SlidersHorizontal size={15} /> <span class="tb-filter-label">Filter</span>{#if panelFilterCount}<span class="filter-count">{panelFilterCount}</span>{/if}
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content class="tb-filter-pop" align="start" sideOffset={8}>
                <div class="sheet-head">
                  <span class="sheet-title">{$t("filter.title")}</span>
                  {#if activeFilterCount}
                    <button class="link" onclick={clearFilters}>{$t("filter.clear")}</button>
                  {/if}
                </div>
                {@render filterFields()}
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        {/if}
      {/if}
    </div>

    <!-- RECHTS: primaire nav + Meer-overflow + Nieuw ticket + avatar-menu. -->
    <div class="tb-cluster tb-right">
      <nav class="tb-nav" aria-label={$t("nav.view")}>
        <button
          class="nav-tab"
          class:active={activeView === "board"}
          aria-pressed={activeView === "board"}
          title={$t("nav.board")}
          aria-label={$t("nav.board")}
          onclick={() => setActiveView("board")}
        >
          <LayoutGrid size={16} /> <span class="nav-label">{$t("nav.board")}</span>
        </button>
        <button
          class="nav-tab"
          class:active={activeView === "list"}
          aria-pressed={activeView === "list"}
          title={$t("nav.list")}
          aria-label={$t("nav.list")}
          onclick={() => setActiveView("list")}
        >
          <List size={16} /> <span class="nav-label">{$t("nav.list")}</span>
        </button>
        <button
          class="nav-tab"
          class:active={activeView === "wiki"}
          aria-pressed={activeView === "wiki"}
          title={$t("nav.memory")}
          aria-label={$t("nav.wiki")}
          onclick={() => setActiveView("wiki")}
        >
          <BookOpen size={16} /> <span class="nav-label">{$t("nav.wiki")}</span>
        </button>
        <button
          class="nav-tab"
          class:active={activeView === "activity"}
          aria-pressed={activeView === "activity"}
          title={$t("nav.activity")}
          aria-label={$t("nav.activity")}
          onclick={() => setActiveView("activity")}
        >
          <History size={16} /> <span class="nav-label">{$t("nav.activity")}</span>
        </button>
      </nav>

      <!-- Inbox is een paneel en geen view: bel-icoon met badge (BETON-453). -->
      <button
        class="icon-btn tb-inbox"
        class:active={hasOverlay(overlays, "inbox")}
        aria-pressed={hasOverlay(overlays, "inbox")}
        title="Inbox"
        aria-label={"Inbox" + (inboxUnread ? " — " + $t("inbox.unread", {count: inboxUnread}) : "")}
        onclick={() => openOverlay("inbox")}
      >
        <Bell size={18} />
        {#if inboxUnread}<span class="inbox-badge">{inboxUnread > 99 ? "99+" : inboxUnread}</span>{/if}
      </button>

      <!-- "Meer": laagfrequente project- en (mens-only) beheer-acties. -->
      <DropdownMenu.Root>
        <DropdownMenu.Trigger class="icon-btn tb-more" title={$t("nav.more")} aria-label={$t("nav.more")}>
          <MoreHorizontal size={18} />
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content class="tb-menu" align="end" sideOffset={6}>
            <DropdownMenu.Item class="tb-menu-item" onSelect={toggleSelectMode}>
              <ListChecks size={15} /> {$t(selectMode ? "nav.endSelection" : "nav.selectMany")}
            </DropdownMenu.Item>
            {#if current}
              <DropdownMenu.Item class="tb-menu-item" onSelect={() => openOverlaySoon("settings")}>
                <Settings size={15} /> {$t("nav.projectSettings")}
              </DropdownMenu.Item>
            {/if}
            <DropdownMenu.Item class="tb-menu-item" onSelect={() => openOverlaySoon("projects")}>
              <FolderCog size={15} /> {$t("nav.projects")}
            </DropdownMenu.Item>
            {#if canManageInstallation(me)}
              <DropdownMenu.Item class="tb-menu-item" onSelect={() => openOverlaySoon("installation")}>
                <Settings size={15} /> {$t("installation.title")}
              </DropdownMenu.Item>
            {/if}
            {#if me?.kind === "human"}
              <div class="tb-menu-sep" role="separator"></div>
              <DropdownMenu.Item class="tb-menu-item" onSelect={() => openOverlaySoon("agents")}>
                <Bot size={15} /> {$t("nav.agents")}
              </DropdownMenu.Item>
              <DropdownMenu.Item class="tb-menu-item" onSelect={() => openOverlaySoon("chat")}>
                <MessageSquare size={15} /> {$t("nav.triage")}
              </DropdownMenu.Item>
              <DropdownMenu.Item class="tb-menu-item" onSelect={() => openOverlaySoon("deliveries")}>
                <Webhook size={15} /> {$t("nav.deliveries")}
              </DropdownMenu.Item>
            {/if}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      <button class="primary tb-new" onclick={() => openNew()} aria-label={$t("nav.newTicket")} title={$t("nav.newTicket")}>
        <Plus size={16} /> <span class="tb-label">{$t("nav.newTicket")}</span>
      </button>

      <!-- Avatar-menu: eigen instellingen, mijn tickets, thema, live, uitloggen. -->
      {#if me}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger class="user-chip" title="Account" aria-label="Account (@{me.handle})">
            <Avatar handle={me.handle} avatarUrl={avatarMap.get(me.handle)} size={26} />
            <span class="live-dot user-live" class:on={live === "live"} aria-hidden="true"></span>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content class="tb-menu" align="end" sideOffset={6}>
              <div class="tb-menu-head">@{me.handle}</div>
              <DropdownMenu.Item class="tb-menu-item" closeOnSelect={false} onSelect={() => setLocale("en")}>
                English {$locale === "en" ? "✓" : ""}
              </DropdownMenu.Item>
              <DropdownMenu.Item class="tb-menu-item" closeOnSelect={false} onSelect={() => setLocale("nl")}>
                Nederlands {$locale === "nl" ? "✓" : ""}
              </DropdownMenu.Item>
              <DropdownMenu.Item class="tb-menu-item" onSelect={() => openOverlaySoon("userSettings")}>
                <Settings size={15} /> {$t("nav.mySettings")}
              </DropdownMenu.Item>
              <DropdownMenu.Item class="tb-menu-item" onSelect={openMine}>
                <UserCheck size={15} /> {$t("nav.myTickets")}
              </DropdownMenu.Item>
              <div class="tb-menu-sep" role="separator"></div>
              <DropdownMenu.Item class="tb-menu-item" closeOnSelect={false} onSelect={cycleTheme}>
                <ThemeIcon size={15} /> {$t("nav.theme")}: {$t("theme." + theme)}
              </DropdownMenu.Item>
              <div class="tb-menu-status">
                <span class="live-dot" class:on={live === "live"} aria-hidden="true"></span>
                {$t(live === "live" ? "nav.live" : "nav.offline")}
              </div>
              <div class="tb-menu-sep" role="separator"></div>
              <DropdownMenu.Item class="tb-menu-item danger" onSelect={logout}>
                <LogOut size={15} /> {$t("nav.logout")}
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      {/if}
    </div>
  </header>

  <!-- Eén cross-project resultaatregel, gedeeld door de zoekresultaten en de
       "Recent gewijzigd"-lijst in de "Alle projecten"-scope (BETON-225/BETON-7). -->
  {#snippet resultRow(r)}
    <button class="result-row" onclick={() => openResult(r.ref, r.comment_id ?? null)}>
      <span class="result-proj" title={r.projectName}>{r.project}</span>
      <span class="ref">{r.ref}</span>
      <span class="result-title">{r.title}</span>
      {#if r.matched_in === "comment"}<span class="result-where">{$t("search.comment")}</span>{/if}
      {#if r.state}<span class="result-state">{r.state}</span>{/if}
      <WorkloadBadge workload={r.workload} size={14} />
      {#if r.assignee}<Avatar handle={r.assignee} avatarUrl={avatarMap.get(r.assignee)} size={20} />{/if}
    </button>
  {/snippet}

  <!-- Gedeelde filtervelden voor de desktop-popover én de mobiele sheet. -->
  {#snippet filterFields()}
    <label class="field">
      <span>{$t("filter.assignee")}</span>
      <AssigneeSelect
        value={filters.assignee}
        {users}
        {me}
        allowNone={$t("filter.everyone")}
        onchange={(v) => { filters.assignee = v; loadBoard(); }}
      />
    </label>
    <label class="field">
      <span>Label</span>
      <Select
        value={filters.label}
        options={[{ value: "", label: $t("filter.allLabels") }, ...projectLabels.map((l) => ({ value: l.name, label: l.name }))]}
        onchange={(v) => { filters.label = v; loadBoard(); }}
      />
    </label>
    {#if milestones.length}
      <label class="field">
        <span>Milestone</span>
        <Select
          value={filters.milestone}
          options={[{ value: "", label: $t("filter.allMilestones") }, ...milestones.map((m) => ({ value: m.name, label: m.name }))]}
          onchange={(v) => { filters.milestone = v; loadBoard(); }}
        />
      </label>
    {/if}
    {#if activeView === "list"}
      <!-- BETON-357: statusfilter alleen in de lijst — het bord toont de state
           al via de kolommen, dus daar zou dit filter alleen kolommen wegvegen. -->
      <label class="field">
        <span>{$t("ticket.state")}</span>
        <Select
          value={filters.state}
          options={[{ value: "", label: $t("filter.allStates") }, ...states.map((s) => ({ value: s.name, label: s.name }))]}
          onchange={(v) => { filters.state = v; }}
        />
      </label>
    {/if}
    <label class="field">
      <span>{$t("ticket.workload")}</span>
      <Select
        value={filters.workload}
        options={[{ value: "", label: $t("filter.allWorkloads") }, ...[...WORKLOAD_VALUES].reverse().map((w) => ({ value: w, label: workloadLabel(w, $locale) }))]}
        onchange={(v) => { filters.workload = v; loadBoard(); }}
      />
    </label>
    <label class="field">
      <span>{$t("filter.sort")}</span>
      <Select
        value={sortBy}
        options={SORT_OPTIONS.map((o) => ({ value: o.key, label: $t("sort." + o.key) }))}
        onchange={(v) => setSort(v)}
      />
    </label>
    <label class="arch-check">
      <input type="checkbox" checked={showArchived} onchange={toggleArchived} />
      <span>{$t("filter.archived")}</span>
    </label>
  {/snippet}

  <!-- Snelfilters (BETON-357): één klik, client-side, geen popover nodig. -->
  {#if !hidesProjectFilters(activeView) && filterControlsVisible(searchScope)}
    <div class="quick-filters" role="region" aria-label={$t("filter.quick")}>
      <Chip tone="label" hue={220} selected={filters.mine} onclick={() => toggleQuickFilter("mine")}>
        {$t("filter.mine")}
      </Chip>
      <Chip tone="label" hue={280} selected={filters.unread} onclick={() => toggleQuickFilter("unread")}>
        {$t("filter.unread")}
      </Chip>
      <Chip tone="label" hue={40} selected={filters.question} onclick={() => toggleQuickFilter("question")}>
        {$t("filter.question")}
      </Chip>
      <Chip tone="label" hue={0} selected={filters.due === "overdue"} onclick={() => toggleDue("overdue")}>
        {$t("filter.overdue")}
      </Chip>
      <Chip tone="label" hue={150} selected={filters.due === "week"} onclick={() => toggleDue("week")}>
        {$t("filter.week")}
      </Chip>
      <Chip tone="label" hue={200} selected={filters.unassigned} onclick={() => toggleQuickFilter("unassigned")}>
        {$t("filter.unassigned")}
      </Chip>
    </div>
  {/if}

  <!-- Actieve filters als verwijderbare chips onder de bar (BETON-222). -->
  {#if activeFilterCount && !hidesProjectFilters(activeView) && filterControlsVisible(searchScope)}
    <div class="filter-chips" role="region" aria-label={$t("filter.active")}>
      {#each filterChips as chip (chip.key)}
        <Chip removable onremove={() => clearOneFilter(chip.key)}>
          {#if chip.boolean}
            {chip.field}
          {:else}
            <span class="fc-field">{chip.field}:</span> {chip.value}
          {/if}
        </Chip>
      {/each}
      <button class="link tb-clear" onclick={clearFilters}>
        <X size={14} /> {$uiText("ui.clearFilters")}
      </button>
    </div>
  {/if}

  {#if selectMode}
    <div class="bulk-bar" role="region" aria-label={$uiText("bulk.actions")}>
      <span class="bulk-count">{$uiText("bulk.selected", {count: selectedRefs.length})}</span>
      <label class="bulk-move">
        <span>{$uiText("ui.moveTo")}</span>
        <Select
          action
          value=""
          disabled={!selectedRefs.length || bulkBusy}
          options={[{ value: "", label: $uiText("bulk.chooseColumn") }, ...states.map((s) => ({ value: s.name, label: s.name }))]}
          onchange={(v) => bulkMove(v)}
        />
      </label>
      <label class="bulk-move">
        <span>{$uiText("ui.assignedTo")}</span>
        <AssigneeSelect
          value=""
          {users}
          {me}
          allowNone={$uiText("bulk.choosePerson")}
          action
          disabled={!selectedRefs.length || bulkBusy}
          onchange={(v) => bulkAssign(v)}
        />
      </label>
      <label class="bulk-move">
        <span>Label</span>
        <SegmentedControl
          variant="pill"
          ariaLabel={$uiText("ui.changeLabel")}
          value={bulkLabelMode}
          disabled={!selectedRefs.length || bulkBusy}
          onchange={(v) => (bulkLabelMode = v)}
          options={[
            { value: "add", label: "+" },
            { value: "remove", label: "−" },
          ]}
        />
        <Select
          action
          value=""
          disabled={!selectedRefs.length || bulkBusy}
          options={[{ value: "", label: $uiText("bulk.chooseLabel") }, ...projectLabels.map((l) => ({ value: l.name, label: l.name }))]}
          onchange={(v) => bulkLabel(v, bulkLabelMode === "add")}
        />
      </label>
      {#if milestones.length}
        <label class="bulk-move">
          <span>Milestone</span>
          <Select
            action
            value=""
            disabled={!selectedRefs.length || bulkBusy}
            options={[{ value: "", label: $uiText("bulk.chooseMilestone") }, ...milestones.map((m) => ({ value: m.name, label: m.name }))]}
            onchange={(v) => bulkMilestone(v)}
          />
        </label>
      {/if}
      <label class="bulk-move">
        <span>{$t("ticket.workload")}</span>
        <SegmentedControl
          variant="pill"
          ariaLabel={$t("ticket.workload")}
          value=""
          disabled={!selectedRefs.length || bulkBusy}
          onchange={(v) => bulkWorkload(v)}
          options={WORKLOAD_VALUES.map((w) => ({ value: w, label: workloadLabel(w, $locale) }))}
        />
      </label>
      <button
        class="sm"
        disabled={!selectedRefs.length || bulkBusy}
        onclick={bulkArchive}
      >
        <Archive size={15} /> {$t("drawer.archive")}
      </button>
      <button class="ghost sm bulk-done" onclick={exitSelectMode}>{$uiText("bulk.done")}</button>
    </div>
  {/if}

  {#if hasOverlay(overlays, "filters")}
    <div class="sheet-overlay" onclick={() => closeOverlayNamed("filters")} role="presentation">
      <div class="sheet" onclick={(e) => e.stopPropagation()} role="dialog" aria-label={$t("filter.title")}>
        <span class="sheet-grip"></span>
        <div class="sheet-head">
          <span class="sheet-title">{$t("filter.title")}</span>
          {#if activeFilterCount}
            <button class="link" onclick={clearFilters}>{$t("filter.clear")}</button>
          {/if}
        </div>
        {@render filterFields()}
        <button class="primary sheet-done" onclick={() => closeOverlayNamed("filters")}>{$uiText("bulk.done")}</button>
      </div>
    </div>
  {/if}

  {#if error}
    <div class="toast" role="alert">
      <span>{error}</span>
      <button class="x" aria-label={$uiText("ui.dismiss")} onclick={() => (error = "")}>
        <X size={16} />
      </button>
    </div>
  {/if}

  {#if activeView === "wiki"}
    <Wiki
      {liveTick}
      project={current}
      projectName={currentName}
      {me}
      onclose={() => setActiveView("board")}
      onopenref={(r) => { setActiveView("board"); navigateRef(r); }}
      onswitchproject={switchProject}
    />
  {:else if activeView === "overview"}
    <Overview
      {liveTick}
      onopen={(key) => {
        setActiveView("board");
        switchProject(key);
      }}
    />
  {:else if activeView === "activity"}
    <Activity
      project={current}
      projectName={currentName}
      {users}
      {avatarMap}
      {liveTick}
      onopenref={(r) => navigateRef(r)}
    />
  {:else if !projects.length}
    <div class="empty">
      <span class="empty-mark"></span>
      <p class="empty-title">{$t("empty.projects")}</p>
      <p class="muted">{$t("empty.firstProject")}</p>
      <button class="primary" onclick={() => openOverlay("newProject")}>
        <Plus size={15} /> {$t("project.new")}
      </button>
    </div>
  {:else if loading && !items.length}
    <div class="board" aria-busy="true" use:trackBoardTop>
      {#each Array(4) as _, ci (ci)}
        <div class="column">
          <div class="col-head"><span class="skel skel-head"></span></div>
          {#each Array(3) as _, si (si)}
            <div class="card skel-card">
              <span class="skel skel-line short"></span>
              <span class="skel skel-line"></span>
              <span class="skel skel-line med"></span>
            </div>
          {/each}
        </div>
      {/each}
    </div>
  {:else if searchScope === "all"}
    <section class="results" aria-label={$t("search.results")}>
      {#if !filters.q.trim()}
        <div class="empty all-scope-empty">
          <span class="empty-mark"><Search size={20} /></span>
          <p class="empty-title">{$t("search.title")}</p>
          <p class="muted">
            {$t("search.instructions")}
          </p>
        </div>
        {#if recentAcrossProjects.length}
          <div class="recent-section">
            <SectionHead>{$t("search.recent")}</SectionHead>
            <ul class="result-list">
              {#each recentAcrossProjects as r (r.ref)}
                <li>{@render resultRow(r)}</li>
              {/each}
            </ul>
          </div>
        {:else if recentBusy}
          <p class="results-hint muted">{$t("search.loadingRecent")}</p>
        {/if}
      {:else if searching && !searchResults.length}
        <p class="results-hint muted">{$t("search.loading")}</p>
      {:else if !searchResults.length}
        <div class="empty">
          <p class="empty-title">{$t("search.none")}</p>
          <p class="muted">{$t("search.notFound", {query: filters.q.trim()})}</p>
        </div>
      {:else}
        <ul class="result-list">
          {#each searchResults as r (r.ref)}
            <li>{@render resultRow(r)}</li>
          {/each}
        </ul>
      {/if}
    </section>
  {:else if activeView === "list"}
    <ListView
      items={filteredItems}
      preferenceKey={`betonning-list-columns:${me?.handle ?? ""}`}
      stateOptions={states.map((s) => ({ value: s.name, label: s.name }))}
      onstatechange={move}
      {selectMode}
      {selectedRefs}
      {stateColors}
      {avatarMap}
      {virtualHandles}
      onopen={(r) => (selectedRef = r)}
      ontoggle={selectWithRange}
      ontoggleall={toggleRefSet}
      onorder={(refs) => (listOrderRefs = refs)}
    />
  {:else}
    <nav class="col-nav" aria-label="Kolommen">
      {#each columns as col (col.name)}
        <button class="col-nav-chip" class:closed={col.closed} onclick={() => scrollToCol(col.name)}>
          <span class="col-dot" style:background={dotColor(col)}></span>
          {col.name}
          <span class="col-nav-count">{columnCount(col, activeFilterCount > 0)}</span>
        </button>
      {/each}
    </nav>
    {#if showDragHint}
      <div class="drag-hint" role="note">
        <Info size={15} />
        <span>{$uiText("ui.touchHint")}</span>
        <button class="icon-btn drag-hint-close" onclick={dismissDragHint} aria-label={$uiText("ui.closeTip")} title={$uiText("ui.closeTip")}>
          <X size={15} />
        </button>
      </div>
    {/if}
    <div class="board" use:trackBoardTop>
      {#each columns as col (col.name)}
        <div
          class="column"
          class:dragover={dragoverCol === col.name}
          class:closed={col.closed}
          class:collapsed={isCollapsed(col)}
          class:archive-col={col.archived}
          data-col={col.name}
          role="list"
          ondragover={(e) => {
            if (col.archived) return;
            e.preventDefault();
            dragoverCol = col.name;
          }}
          ondragleave={() => (dragoverCol === col.name ? (dragoverCol = null) : null)}
          ondrop={() => (col.archived ? null : onDrop(col.name))}
        >
          <div class="col-head">
            {#if col.closed}
              <button
                class="col-collapse"
                onclick={() => toggleCollapse(col.name)}
                aria-expanded={!isCollapsed(col)}
                title={isCollapsed(col) ? "Uitklappen" : "Inklappen"}
              >
                {#if isCollapsed(col)}<ChevronRight size={15} />{:else}<ChevronDown size={15} />{/if}
              </button>
            {/if}
            <span class="col-dot" style:background={dotColor(col)}></span>
            <span class="col-name">{col.name}</span>
            <span class="col-count">{columnCount(col, activeFilterCount > 0)}</span>
            {#if selectMode && col.items.length}
              <!-- BETON-360: alles in deze kolom selecteren/deselecteren. -->
              <button
                class="col-select-all"
                title={$uiText("board.selectColumn", {column: col.name})}
                aria-label={$uiText("board.selectColumn", {column: col.name})}
                onclick={(e) => {
                  e.stopPropagation();
                  toggleRefSet(col.items.map((i) => i.ref));
                }}
              >
                <span
                  class="card-check"
                  class:on={col.items.every((i) => selectedRefs.includes(i.ref))}
                  aria-hidden="true"
                ></span>
              </button>
            {/if}
            {#if !col.closed}
              <button
                class="col-add"
                title={$uiText("ui.newHere")}
                aria-label={$uiText("board.newIn", {column: col.name})}
                onclick={() => openNew(col.name)}
              >
                <Plus size={16} />
              </button>
            {/if}
          </div>
          {#if !isCollapsed(col)}
          {#each col.items as item (item.ref)}
            <div
              class="card"
              class:dragging={dragRef === item.ref}
              class:selected={selectMode && selectedRefs.includes(item.ref)}
              class:selectable={selectMode}
              class:archived={item.archived_at}
              class:card-guardrail={item.has_guardrail}
              role="listitem"
              data-ref={item.ref}
              draggable={canDrag && !selectMode && !item.archived_at}
              ondragstart={() => (dragRef = item.ref)}
              ondragend={endDrag}
              onclick={(e) => onCardClick(item.ref, e)}
              onkeydown={(e) => e.key === "Enter" && onCardClick(item.ref, e)}
              tabindex="0"
            >
              <div class="card-head">
                {#if selectMode}
                  <span
                    class="card-check"
                    class:on={selectedRefs.includes(item.ref)}
                    aria-hidden="true"
                  ></span>
                {/if}
                <span class="ref">{item.ref}</span>
                {#if item.archived_at}
                  <span class="card-arch-badge" title={$uiText("ui.archived")}>
                    <Archive size={11} /> {$t("drawer.archived")}
                  </span>
                {/if}
                <WorkloadBadge workload={item.workload} />
                {#if item.locked}
                  <!-- BETON-302: noodstop — agents zwijgen op dit ticket. Op de
                       kaart zichtbaar, anders is "waarom reageert er niemand?"
                       een raadsel tot je de drawer opent. -->
                  <span class="card-locked" title={$uiText("board.locked")}>
                    <Lock size={15} strokeWidth={2.5} />
                  </span>
                {/if}
                {#if item.has_guardrail}
                  <!-- BETON-420: er staat een bindende guardrail op dit ticket.
                       Naast het slotje, niet in plaats daarvan — een ticket kan
                       allebei hebben. -->
                  <span
                    class="card-guardrail-icon"
                    title={$uiText("board.guardrail")}
                  >
                    <ShieldAlert size={15} strokeWidth={2.5} />
                  </span>
                {/if}
                {#if item.has_guardrail_proposal}
                  <!-- BETON-422: er ligt een guardrail-concept dat op een mens
                       wacht. Bewust neutraal en zónder de rode rand van
                       .card-guardrail: die rand betekent "hier geldt iets
                       bindends", en een concept geldt juist nog niet. Naast een
                       actieve markering, want een ticket kan allebei hebben. -->
                  <span
                    class="card-guardrail-concept"
                    title={$uiText("ui.guardrailPending")}
                  >
                    <ShieldQuestionMark size={15} strokeWidth={2.5} />
                  </span>
                {/if}
                {#if item.has_open_question}
                  <!-- BETON-275: markering dat er een open vraag op dit item staat. -->
                  <span class="card-question" title={$uiText("board.openQuestion")}>
                    <MessageCircleQuestion size={15} strokeWidth={2.5} />
                  </span>
                {/if}
                {#if item.has_unread}
                  <!-- BETON-281: markering dat er ongelezen comments op dit item
                       staan (naast een eventuele open vraag hierboven). -->
                  <span class="card-unread" title={$uiText("ui.unreadComments")}>
                    <MessageSquareDot size={15} strokeWidth={2.5} />
                  </span>
                {/if}
              </div>
              <div class="card-title">{item.title}</div>
              {#if item.children_total}
                <div
                  class="card-progress"
                  class:done={item.children_done === item.children_total}
                  title={$uiText("board.childrenProgress", {done: item.children_done, total: item.children_total})}
                >
                  {$uiText("board.childrenCount", {done: item.children_done, total: item.children_total})}
                </div>
              {/if}
              {#if item.deferred_until}
                <div class="card-deferred" title={$uiText("board.deferred", {date: item.deferred_until})}>
                  {$uiText("board.waitUntil", {date: item.deferred_until})}
                </div>
              {/if}
              <DueBadge due={item.due_date} card />
              {#if item.milestone}
                <div class="card-milestone" title="Milestone {item.milestone}">
                  <Flag size={11} />{item.milestone}
                </div>
              {/if}
              {#if cardRelationPills(item).length}
                <!-- BETON-344: relaties (+ "subtaak van") onderaan de kaart als
                     gekleurde icoon+nummer-pill — géén projectslug (ruis binnen
                     hetzelfde board; het type staat in de tooltip), en bewust
                     géén Chip: behoud exact de hoogte van de label-tags
                     (Chip.svelte's interactieve tone-label-variant is hoger/
                     omlijnd — deze pill kopieert i.p.v. daarvan de STATISCHE
                     tone-label-opmaak, zie .card-rel hieronder). Elke pill
                     opent het gerelateerde ticket zonder de eigen kaart te
                     openen (stopPropagation). -->
                <div class="card-relations">
                  {#each cardRelationPills(item) as rel (rel.type + rel.ref)}
                    {@const meta = relationMeta(rel.type)}
                    {#if meta}
                      {@const Icon = meta.icon}
                      <button
                        type="button"
                        class="card-rel"
                        style:--label-h={relationHue(rel.type)}
                        title="{meta.label}: {rel.ref}"
                        onclick={(e) => {
                          e.stopPropagation();
                          navigateRef(rel.ref);
                        }}
                      >
                        <Icon size={11} strokeWidth={2.25} />
                        {rel.ref.slice(rel.ref.lastIndexOf("-") + 1)}
                      </button>
                    {/if}
                  {/each}
                </div>
              {/if}
              {#if (item.labels && item.labels.length) || item.assignee || item.last_activity_at || item.created_at}
                <div class="card-foot">
                  <span class="card-labels">
                    {#each splitModelLabels(item.labels).plain as l}
                      <Chip tone="label" hue={labelHueOf(l, projectKeyOfRef(item.ref))}>{l}</Chip>
                    {/each}
                    {#each splitModelLabels(item.labels).models as m}
                      <span class="model-label" title={$t("list.workClass")}><Cpu size={11} />{m}</span>
                    {/each}
                  </span>
                  {#if item.last_activity_at || item.created_at}
                    <span
                      class="card-date"
                      title={$uiText("board.changedAt", {time: absoluteTime(item.last_activity_at || item.created_at, $locale)})}
                    >
                      {formatTimestamp(item.last_activity_at || item.created_at, undefined, $locale)}
                    </span>
                  {/if}
                  {#if item.assignee}
                    <Avatar handle={item.assignee} avatarUrl={avatarMap.get(item.assignee)} size={22} />
                  {/if}
                </div>
              {/if}
            </div>
          {:else}
            {#if dragRef}
              <div class="col-dropzone">{$uiText("board.dropHere")}</div>
            {:else}
              <p class="col-empty">{$t("empty.column")}</p>
            {/if}
          {/each}
          {#if col.hasMore}
            <!-- BETON-359: server heeft meer dan de begrensde (closed_limit)
                 selectie die al binnen is — laad de volgende 50 bij. -->
            <button
              class="col-more"
              disabled={colBusy.has(col.name)}
              onclick={() => loadMoreColumn(col.name)}
            >
              {colBusy.has(col.name) ? $uiText("ui.loading") : $uiText("board.more", {count: col.total - col.items.length})}
            </button>
          {/if}
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  {#if hasOverlay(overlays, "new")}
    <NewItem
      projectKey={current}
      project={currentProject}
      {states}
      {users}
      {me}
      {projectLabels}
      {milestones}
      defaultState={newColumn}
      initial={newItemInitial}
      onclose={() => closeOverlayNamed("new")}
      oncreated={onCreated}
      onerror={(msg) => (error = msg)}
    />
  {/if}

  {#if hasOverlay(overlays, "newProject")}
    <NewProject
      {me}
      onclose={() => closeOverlayNamed("newProject")}
      oncreated={onProjectCreated}
    />
  {/if}

  {#if hasOverlay(overlays, "projects")}
    <ProjectsManager
      onclose={() => closeOverlayNamed("projects")}
      onnew={() => {
        closeOverlayNamed("projects");
        openOverlay("newProject");
      }}
      onchanged={onProjectsChanged}
    />
  {/if}

  {#if hasOverlay(overlays, "chat") && me?.kind === "human"}
    <TriageChat
      project={current}
      projectName={currentName}
      onclose={() => closeOverlayNamed("chat")}
      onopenref={(r) => { closeOverlayNamed("chat"); navigateRef(r); }}
    />
  {/if}

  {#if hasOverlay(overlays, "settings") && currentProject}
    <DrawerDialog label={$t("nav.projectSettings")} width="min(760px, 92vw)" onclose={() => closeOverlayNamed("settings")}>
      <div class="settings-panel">
        <ProjectSettings
          projectKey={current}
          projectName={currentName}
          projectDescription={currentProject.description}
          triageEnabled={currentProject.triage_enabled}
          wikiCompileEnabled={currentProject.wiki_compile_enabled}
          onback={() => closeOverlayNamed("settings")}
          onchanged={onProjectsChanged}
        />
      </div>
    </DrawerDialog>
  {/if}

  {#if hasOverlay(overlays, "agents") && me?.kind === "human"}
    <DrawerDialog label={$t("nav.agents")} width="min(760px, 92vw)" onclose={() => closeOverlayNamed("agents")}>
      <div class="agents-panel">
        <Agents canTestWebhooks={canManageInstallation(me)} ondeliveries={() => openOverlaySoon("deliveries")} onback={() => closeOverlayNamed("agents")} />
      </div>
    </DrawerDialog>
  {/if}

  {#if hasOverlay(overlays, "installation") && canManageInstallation(me)}
    <DrawerDialog label={$t("installation.title")} width="min(760px, 92vw)" onclose={() => closeOverlayNamed("installation")}>
      <InstallationSettings onback={() => closeOverlayNamed("installation")} onchanged={async () => {
        [users, projects] = await Promise.all([api.users(), api.projects()]);
        if (!current && projects.length) await switchProject(projects[0].key);
        else await loadBoard();
      }} />
    </DrawerDialog>
  {/if}

  {#if hasOverlay(overlays, "userSettings") && me}
    <DrawerDialog label={$t("nav.mySettings")} width="min(680px, 92vw)" onclose={() => closeOverlayNamed("userSettings")}>
      <div class="usersettings-panel">
        <UserSettings {me} onback={() => closeOverlayNamed("userSettings")} />
      </div>
    </DrawerDialog>
  {/if}

  {#if hasOverlay(overlays, "deliveries") && me?.kind === "human"}
    <DrawerDialog label={$t("nav.deliveries")} width="min(920px, 94vw)" onclose={() => closeOverlayNamed("deliveries")}>
      <div class="deliveries-panel">
        <Deliveries {avatarMap} onback={() => closeOverlayNamed("deliveries")} />
      </div>
    </DrawerDialog>
  {/if}

  {#if hasOverlay(overlays, "mine")}
    <DrawerDialog label={$uiText("ui.myTickets")} width="min(1180px, 94vw)" onclose={() => closeOverlayNamed("mine")}>
      <div class="mine-panel">
        <header class="mine-head">
          <div class="mine-title"><UserCheck size={18} /> <span>{$uiText("ui.myTickets")}</span></div>
          <div class="mine-controls">
            <SegmentedControl
              variant="joined"
              ariaLabel="Groeperen"
              value={mineGroup}
              onchange={(v) => (mineGroup = v)}
              options={[
                { value: "project", label: "Project" },
                { value: "state", label: $t("ticket.state") },
              ]}
            />
            <button class="icon-btn" title={$t("common.close")} aria-label={$t("common.close")} onclick={() => closeOverlayNamed("mine")}>
              <X size={19} />
            </button>
          </div>
        </header>
        {#if mineBusy && !mineItems.length}
          <p class="mine-empty">{$uiText("ui.loading")}</p>
        {:else if !mineItems.length}
          <div class="mine-empty"><UserCheck size={28} /><p>{$uiText("ui.noAssigned")}</p></div>
        {:else}
          <div class="mine-body">
            {#each mineGroups as g (g.label)}
              <h3 class="mine-group-head">{g.label} <span class="mine-count">{g.items.length}</span></h3>
              <ListView preferenceKey={`betonning-list-columns:${me?.handle ?? ""}`} items={g.items} {stateColors} {avatarMap} {virtualHandles} onopen={(r) => { closeOverlayNamed("mine"); navigateRef(r); }} />
            {/each}
          </div>
        {/if}
      </div>
    </DrawerDialog>
  {/if}

  {#if hasOverlay(overlays, "inbox")}
    <Inbox
      {liveTick}
      {avatarMap}
      onopen={(r, cmtId) => { closeOverlayNamed("inbox"); navigateRef(r, cmtId); }}
      onseen={refreshInbox}
      ondeliveries={() => { closeOverlayNamed("inbox"); openOverlaySoon("deliveries"); }}
      onclose={() => { closeOverlayNamed("inbox"); refreshInbox(); }}
    />
  {/if}

  {#if hasOverlay(overlays, "palette")}
    <CommandPalette
      {projects}
      {states}
      {users}
      {me}
      view={activeView === "list" ? "list" : "board"}
      onclose={() => closeOverlayNamed("palette")}
      onnew={() => openNew()}
      onview={setActiveView}
      onwiki={() => setActiveView("wiki")}
      ongoto={switchProject}
      onopen={(r, cmtId = null) => navigateRef(r, cmtId)}
      onpatch={async (ref, body) => { try { await api.updateItem(ref, body); await loadBoard(); } catch (e) { error = e.message; } }}
    />
  {/if}

  {#if hasOverlay(overlays, "hints")}
    <div class="hints-overlay" onclick={() => closeOverlayNamed("hints")} role="presentation">
      <div class="hints" onclick={(e) => e.stopPropagation()} role="dialog" aria-label={$uiText("shortcut.title")}>
        <h2>{$uiText("shortcut.title")}</h2>
        {#each shortcutHelp($locale) as group (group.scope)}
          <h3>{group.scopeLabel}</h3>
          <ul>
            {#each group.items as it (it.key)}
              <li><kbd>{it.key}</kbd> {it.label}</li>
            {/each}
          </ul>
        {/each}
        <button class="primary" onclick={() => closeOverlayNamed("hints")}>{$t("common.close")}</button>
      </div>
    </div>
  {/if}

  {#if quickPicker}
    <QuickPicker
      title={$uiText("ui.choose")}
      items={quickPicker.items}
      anchorRect={quickPicker.anchorRect}
      onselect={quickPicker.onselect}
      onclose={closeQuickPicker}
    />
  {/if}

  {#if selectedRef}
    <Drawer
      ref={selectedRef}
      {states}
      {users}
      {avatarMap}
      {projectLabels}
      {milestones}
      {me}
      {liveTick}
      siblings={visibleRefs}
      targetCommentId={selectedCommentTarget}
      onclose={() => (selectedRef = null)}
      onchanged={loadBoard}
      onopen={(r) => navigateRef(r)}
      onscrolledtocomment={() => (selectedCommentTarget = null)}
      onduplicate={onDuplicate}
      onnew={onNewSubtask}
      autoEdit={autoEditRef === selectedRef}
      onautoedited={() => (autoEditRef = null)}
    />
  {/if}
{/if}

<style>
  /* Board-specifieke topbar-clusters verbergen in de wiki-view (BETON-182). */
  .tb-hidden {
    display: none;
  }

  /* Kruisje in het zoekveld om filters te wissen (BETON-264) — intuïtiever
     dan alleen de losse "wis filters"-chip onder de topbar. */
  .search :global(input.search-input.has-clear:not([type="checkbox"]):not([type="radio"]):not([type="color"])) {
    padding-right: calc(var(--scope-w) + 32px);
  }
  .search-clear {
    position: absolute;
    right: calc(var(--scope-w) + 8px);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    padding: 0;
    border: none;
    border-radius: var(--radius-full);
    background: transparent;
    color: var(--text-tertiary);
    cursor: pointer;
  }
  .search-clear:hover {
    background: var(--surface-3);
    color: var(--text);
  }

  /* BETON-50/39: subtaak-voortgang + uitstel-signaal op de kaart. */
  .card-progress {
    margin-top: 6px;
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
  }
  .card-progress.done {
    color: var(--accent);
  }
  .card-deferred {
    margin-top: 6px;
    display: inline-block;
    font-size: var(--text-xs);
    padding: 1px 7px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--warning) 15%, transparent);
    color: var(--warning);
    font-variant-numeric: tabular-nums;
  }
  .arch-check {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--text-md);
    color: var(--text-secondary);
  }
  .arch-check input {
    width: auto;
  }
  .card.archived {
    opacity: 0.55;
    border-style: dashed;
  }
  .card-arch-badge {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 10px;
    padding: 0 5px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--text-tertiary) 18%, transparent);
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  /* Open-vraag-markering op de kaart (BETON-275). */
  .card-question {
    display: inline-flex;
    align-items: center;
    color: var(--accent);
  }
  /* Noodstop-markering (BETON-302) — danger, want dit is een stop en geen
     gewone signalering zoals .card-question/.card-unread. */
  .card-locked {
    display: inline-flex;
    align-items: center;
    color: var(--danger);
  }
  /* Guardrail-markering (BETON-420) — zelfde vorm als het slotje; de rand van
     de kaart zelf staat in app.css bij de andere .card-states. */
  .card-guardrail-icon {
    display: inline-flex;
    align-items: center;
    color: var(--guardrail-border);
  }
  /* Guardrail-concept op de kaart (BETON-422) — neutraal token: er geldt nog
     niets, dus geen guardrail-rood en geen waarschuwingskleur. */
  .card-guardrail-concept {
    display: inline-flex;
    align-items: center;
    color: var(--text-tertiary);
  }
  /* Ongelezen-comments-markering op de kaart (BETON-281) — bewust een ander
     token dan .card-question zodat beide naast elkaar te onderscheiden zijn. */
  .card-unread {
    display: inline-flex;
    align-items: center;
    color: var(--warning);
  }
  .card-milestone {
    margin-top: 6px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--text-xs);
    padding: 1px 7px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--accent);
    font-weight: 500;
  }
  /* Relaties + "subtaak van" op de kaart (BETON-344) — gekleurde icoon+nummer-
     pills. Exact zo hoog als de label-tags (.card-labels
     hierboven, die Chip tone="label" niet-interactief gebruikt): deze CSS is
     bewust een 1-op-1 kopie van Chip.svelte's `.tone-label:not(.interactive)`
     (zelfde --label-h-hsl-formule, zelfde font-size/line-height/padding) i.p.v.
     Chip zelf — Chip's `onclick` dwingt de INTERACTIEVE tone-label-variant af
     (border + andere padding = een net iets hogere pill), en die twee metrics
     wisselen bestaat niet als losse Chip-prop. */
  .card-relations {
    margin-top: 6px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .card-rel {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    min-height: 0;
    padding: 2px 9px;
    border: none;
    border-radius: var(--radius-full);
    font: inherit;
    font-size: var(--text-sm);
    line-height: 1.4;
    background: light-dark(hsl(var(--label-h) 62% 90%), hsl(var(--label-h) 28% 26%));
    color: light-dark(hsl(var(--label-h) 42% 32%), hsl(var(--label-h) 68% 78%));
    cursor: pointer;
  }
  .card-rel:hover {
    background: light-dark(hsl(var(--label-h) 62% 84%), hsl(var(--label-h) 30% 32%));
  }
  @media (pointer: coarse) {
    .card-rel {
      min-height: 32px;
      padding: 6px 10px;
    }
  }

  /* Inbox-nav-tab + ongelezen-badge (BETON-55/222). */
  .tb-inbox {
    position: relative;
  }
  .inbox-badge {
    position: absolute;
    top: -6px;
    right: -8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    border-radius: 999px;
    background: var(--accent);
    color: var(--accent-text);
    font-size: 10px;
    font-weight: 700;
    line-height: 1;
    text-align: center;
    box-sizing: border-box;
  }

  /* My Issues-paneel (BETON-55). Breedte staat nu op de DrawerDialog-content;
     dit inner-paneel vult die en regelt alleen de kolom-lay-out. */
  .mine-panel {
    display: flex;
    flex-direction: column;
    width: 100%;
  }
  .mine-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
  }
  .mine-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
    font-size: var(--text-lg);
  }
  .mine-controls {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .mine-body {
    overflow-y: auto;
    padding: 6px 0 20px;
  }
  .mine-group-head {
    margin: 16px clamp(12px, 3vw, 28px) 4px;
    font-size: var(--text-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .mine-count {
    color: var(--text-tertiary);
    font-weight: 600;
  }
  .mine-empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    color: var(--text-tertiary);
    padding: 48px 24px;
    text-align: center;
  }

  /* Sneltoets-hint-overlay (BETON-56). */
  .hints-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: var(--z-hints);
  }
  .hints {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 24px 28px;
    width: min(420px, 92vw);
    box-shadow: 0 24px 60px -12px rgba(0, 0, 0, 0.45);
  }
  .hints h2 {
    margin: 0 0 14px;
    font-size: 17px;
  }
  .hints h3 {
    margin: 0 0 8px;
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }
  .hints ul {
    list-style: none;
    margin: 0 0 18px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .hints li {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--text-md);
    color: var(--text-secondary);
  }
  .hints kbd {
    font-family: ui-monospace, monospace;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0 5px;
    font-size: var(--text-sm);
    color: var(--text);
  }
  .model-label {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: var(--text-sm);
    color: var(--text-tertiary);
    white-space: nowrap;
  }
</style>
