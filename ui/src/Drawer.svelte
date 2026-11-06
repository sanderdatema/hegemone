<script>
  import { t as uiText } from "./lib/i18n.js";
  import { t, locale } from "./lib/i18n.js";
  import PickerSuggestions from "./PickerSuggestions.svelte";
  import { textPicker, relationPicker, toggleSelection } from "./lib/inputPickers.js";
  import { latestTask } from "./lib/latestTask.js";
  import { tick, onDestroy } from "svelte";
  import { api } from "./api.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import Avatar from "./Avatar.svelte";
  import DiffView from "./DiffView.svelte";
  import { labelHueOf, projectKeyOfRef } from "./lib/labelPalette.svelte.js";
  import { lineDiff } from "./lib/diff.js";
  import { Copy, Check, Archive, ArchiveRestore, X, Pencil, Trash2, ArrowLeft, Sparkles, Scissors, ImagePlus, MoreHorizontal, Plus, FolderInput, MessageCircleQuestion, CornerDownRight, History, Lock, LockOpen, ShieldAlert, ShieldQuestionMark, FileText, ChevronRight, ChevronLeft, ChevronDown, Files, ClipboardCopy, Unlink, CalendarPlus } from "@lucide/svelte";
  import { DropdownMenu } from "bits-ui";
  import {
    describeEvent,
    timelineEvents,
    formatTimestamp,
    formatTimeRange,
    absoluteTime,
    stateColor,
  } from "./lib/board.js";
  import { withPrecondition, conflictMessage } from "./lib/concurrency.js";
  import { loadErrorMessage } from "./lib/loadError.js";
  import { renderMarkdown } from "./lib/markdown.js";
  import { attachmentMarkdown, isImageAttachment } from "./lib/attachments.js";
  import {
    attachableFilesFromFileList,
    attachableFilesFromTransfer,
    removeImageMarkdown,
    insertIntoDrafts,
  } from "./lib/drawerImages.js";
  import {
    handoffTargets,
    triagePendingNote,
    preferredHandoffTarget,
    enrichQuestionsNotice,
    mergeTimeline,
    labelPickerList,
    escapeLadder,
    railProperties,
    followerAvatars,
    selfFollowState,
    followChoiceOps,
    followChoices,
    shouldStartEdit,
    shouldScrollToComment,
    commentScrollTargetId,
    filterTimeline,
    collapseEvents,
    itemToMarkdown,
    duplicateDraft,
    neighbours,
    commentAlwaysOpen,
    commentCollapse,
    commentLineCount,
  } from "./lib/drawerLogic.js";
  import {
    GUARDRAIL_MAX_CHARS,
    guardrailMeta,
    emptyAddLinks,
    guardrailProposalMeta,
    guardrailValidation,
    proposalDiffSegments,
    proposalReviewLabel,
    scopeSummary,
  } from "./lib/guardrail.js";
  import { drawerShortcutAction } from "./lib/palette.js";
  import { readPersisted, writePersisted } from "./lib/viewState.js";
  import {
    duplicateRefForRelation,
    resolveDuplicateCancelAction,
  } from "./lib/duplicateCancel.js";
  import SegmentedControl from "./SegmentedControl.svelte";
  import MarkdownEditor from "./MarkdownEditor.svelte";
  import Chip from "./Chip.svelte";
  import ConfirmBar from "./ConfirmBar.svelte";
  import AssigneeSelect from "./AssigneeSelect.svelte";
  import Select from "./Select.svelte";
  import RelatedList from "./RelatedList.svelte";
  import { relationGroups, subtaskGroups } from "./lib/relatedList.js";
  import SectionHead from "./SectionHead.svelte";
  import DrawerDialog from "./DrawerDialog.svelte";
  import ImageLightbox from "./ImageLightbox.svelte";
  import { lightboxClicks } from "./lib/lightbox.js";
  import ErrorNote from "./ErrorNote.svelte";
  import Skeleton from "./Skeleton.svelte";
  import EmptyState from "./EmptyState.svelte";
  import { workloadOptions, stateOptions } from "./lib/segmentedOptions.js";
  import { relationLabel, RELATION_TYPES } from "./lib/labels.js";
  import {
    optionAnswer,
    textAnswer,
    questionState,
    matchedOptionIndex,
  } from "./lib/question.js";

  let {
    ref,
    states,
    users,
    avatarMap = new Map(),
    projectLabels = [],
    milestones = [],
    me = null,
    liveTick = 0,
    // BETON-362: vorige/volgende ticket binnen de huidige kolom/lijst — de
    // ZICHTBARE volgorde die de aanroeper (App.svelte) al berekende (gefilterd/
    // gesorteerd), niet een ruwe items-array.
    siblings = [],
    targetCommentId = null,
    // BETON-361: "e" op een gefocuste kaart opent de drawer én start meteen de
    // omschrijving-edit. `autoEdit` is een one-shot signaal (geen state) — de
    // aanroeper wist zijn eigen vlag via onautoedited zodra deze drawer hem
    // heeft opgepakt, spiegelt targetCommentId/onscrolledtocomment hierboven.
    autoEdit = false,
    onscrolledtocomment,
    onduplicate,
    onnew,
    onautoedited,
    onclose,
    onchanged,
    onopen,
  } = $props();

  let item = $state(null);
  let activity = $state([]);
  let attachments = $state([]);
  // Lightbox (BETON-474): afbeelding uit markdown of bijlage groot tonen.
  let lightboxImage = $state(null);
  const openLightbox = (img) => (lightboxImage = img);
  // Volgers-lijst (BETON-245): afgeleide subscribers-union met muted-vlag.
  let subscribers = $state([]);
  let error = $state("");
  let loading = $state(false);
  // Lopende property-mutatie (BETON-62): controls disablen zodat er geen
  // dubbele calls ontstaan terwijl een optimistische edit onderweg is.
  let busy = $state(false);

  let editingTitle = $state(false);
  let titleDraft = $state("");
  let editingDesc = $state(false);
  let descDraft = $state("");
  // @mention/#ticket-autocomplete voor de omschrijving-edit (BETON-289): eigen
  // state, los van de comment-composer hierboven — anders beïnvloeden de twee
  // tekstvelden elkaar (open dropdown in het ene veld terwijl je in het andere
  // typt). Spiegelt onCommentInput/onCommentKeydown 1-op-1.
  let descCaret = $state(0);
  let descMentionMatches = $state([]);
  let descMentionActive = $state(0);
  let descHashMatches = $state([]);
  let descHashActive = $state(0);

  let relType = $state("relates_to");
  let relTarget = $state("");
  // BETON-242: lege secties tonen een compacte "+ toevoegen"-affordance; de
  // volledige relatie-invoerrij verschijnt pas na een klik hierop.
  let relAddOpen = $state(false);
  // Autocomplete voor de relatie-target (BETON-12): cross-project zoek op titel.
  let relMatches = $state([]);
  let relActive = $state(0);
  let relInput = $state();

  let commentText = $state("");
  let caret = $state(0);
  let mentionMatches = $state([]);
  let mentionActive = $state(0);
  // #-autocomplete voor ticket-refs (BETON-254), mirror van de mention-flow:
  // los van @mentions maar op dezelfde textarea, dus @ en # sluiten elkaar uit
  // (er is per caretpositie hoogstens één actief token).
  let hashMatches = $state([]);
  let hashActive = $state(0);
  let textarea = $state();

  let editingCommentId = $state(null);
  let editCommentText = $state("");

  // Inline bevestigingen i.p.v. native browser-dialogs.
  let confirmArchive = $state(false);
  let confirmLock = $state(false);
  let confirmDelete = $state(false);
  let confirmClose = $state(false);
  let confirmMove = $state(false);
  let moveTarget = $state("");
  let movePickerOpen = $state(false);
  let projects = $state([]);
  let confirmDeleteId = $state(null);
  // BETON-415: relatie verbreken is de enige onomkeerbare van de drie ×-jes
  // (relatie/mute/label) en had als enige geen bevestiging. { type, target }
  // van de relatie die wacht op bevestiging, of null.
  let confirmRelation = $state(null);
  let copied = $state(false);
  let copyTimer = null;

  // BETON-223: bits-ui-dialog i.p.v. handgemaakte overlay. `dialogOpen=false`
  // sluit programmatisch (X-knop / "Toch sluiten") via onOpenChange → onclose.
  let dialogOpen = $state(true);
  // Property-rail: welke rij staat uitgeklapt (per-rij bewerken). null = alles
  // ingeklapt als samenvattings-chips. Alleen voor de rijen die GEEN eigen
  // open-state hebben (milestone/einddatum/uitstellen + de subtaak-knoppen):
  // hij is enkelvoudig, dus een rij met een lopende invoer (relatie, label-
  // picker, opknip-voorstel) hoort er niet in (BETON-414).
  let expandedProp = $state(null);
  // BETON-414: de eigenschappenlijst staat onder 1024px dicht (CSS-gated).
  let propsOpen = $state(false);
  // Label-picker-popover (alleen toegekende labels tonen + "+" om te kiezen).
  let labelPickerOpen = $state(false);
  let labelQuery = $state("");

  // BETON-212: state & werklast als knopgroepen (SegmentedControl).
  const workloadOpts = $derived(workloadOptions({ colored: true, locale: $locale }));
  // BETON-425: gekozen knop in de kleur van de state-groep (zelfde bron als de
  // kolomstip op het bord).
  const stateOpts = $derived(stateOptions(states, { colored: true }));
  // RELATION_TYPES komt uit lib/labels.js (BETON-331) — één bron, gedeeld met
  // NewItem.svelte. Labels komen ook uit lib/labels.js (BETON-227) — één
  // vertaallaag voor relatietypen i.p.v. een losse kopie hier.

  const loadLatest = latestTask(async (targetRef) => {
    const [nextItem, events, nextAttachments, nextSubscribers] = await Promise.all([
      api.item(targetRef), api.activity(targetRef), api.attachments(targetRef), api.subscribers(targetRef),
    ]);
    return { nextItem, events, nextAttachments, nextSubscribers };
  }, {
    apply: ({ nextItem, events, nextAttachments, nextSubscribers }) => {
      item = nextItem;
      activity = timelineEvents(events);
      attachments = nextAttachments;
      subscribers = nextSubscribers.subscribers;
    },
    error: (e) => {
      console.error(`Laden van ${ref} mislukt:`, e);
      error = loadErrorMessage($uiText("detail.load"), e);
    },
    settled: () => { loading = false; },
  });

  async function load() {
    error = "";
    loading = true;
    await loadLatest(ref);
  }

  $effect(() => {
    ref; // herlaad wanneer een andere kaart wordt geopend
    item = null;
    descPicker.close(); commentPicker.close(); relPicker.close();
    editingTitle = false;
    editingDesc = false;
    editingCommentId = null;
    confirmArchive = false;
    confirmClose = false;
    confirmDeleteId = null;
    expandedProp = null;
    labelPickerOpen = false;
    labelQuery = "";
    relAddOpen = false;
    confirmRelation = null;
    movePickerOpen = false;
    pendingOption = null;
    answerDrafts = {};
    enrichNotice = null;
    // Plan-state hoort bij het vorige item (BETON-218) — reset en laad lazy.
    showPlan = false;
    planMd = null;
    editingPlan = false;
    // Guardrail-formulier hoort bij het vorige item (BETON-420).
    editingGuardrail = false;
    confirmLiftGuardrail = false;
    guardrailScopeQuery = "";
    // Idem voor de conceptstanden (BETON-422): een openstaande bevestiging of
    // een half bewerkt voorstel hoort niet mee te reizen naar het volgende
    // ticket.
    confirmRejectGuardrail = false;
    editingFromProposal = false;
    load();
  });

  // BETON-273: na openen vanuit een open-vraag-notificatie doorscrollen naar de
  // betreffende vraag-comment. Pas als het item geladen is én die comment in de
  // tijdlijn staat (anders bestaat het anker `#cmt-{id}` nog niet). Eén keer per
  // doel: onscrolledtocomment wist het doel in App, zodat een latere live-reload
  // niet opnieuw scrollt.
  $effect(() => {
    if (shouldScrollToComment(targetCommentId, loading, item?.comments)) {
      const id = targetCommentId;
      pinnedCommentId = id;
      tick().then(() => {
        scrollToComment(id);
        onscrolledtocomment?.();
      });
    }
  });

  // BETON-361: "e" op een gefocuste kaart → drawer opent én start meteen de
  // omschrijving-edit. Zelfde vorm als hierboven: pas als het item klaar is
  // met laden, en eenmalig — de aanroeper wist `autoEdit` via onautoedited.
  $effect(() => {
    if (autoEdit && !loading && item && !editingDesc) {
      startDesc();
      onautoedited?.();
    }
  });

  // Live update binnengekomen → stil herladen, maar niet terwijl er bewerkt
  // wordt (anders overschrijven we een half getypte comment/omschrijving).
  let lastLive = liveTick;
  $effect(() => {
    if (liveTick !== lastLive) {
      lastLive = liveTick;
      if (item && !editingTitle && !editingDesc && editingCommentId == null) load();
    }
  });

  let quickHandoffs = $derived(handoffTargets(item, me, users));
  let triageNote = $derived(triagePendingNote(item, $locale));

  async function patch(body) {
    // Optimistische property-edit (BETON-62): pas de lokale state meteen aan en
    // draai terug bij een fout — zelfde patroon als applyMove op het board.
    const prev = item;
    item = { ...item, ...body };
    busy = true;
    // Optimistic concurrency (BETON-44): stuur het gelezen updated_at mee zodat
    // de server een tussentijdse wijziging van iemand anders detecteert.
    try {
      await api.updateItem(ref, withPrecondition(body, prev));
      await load();
      onchanged?.();
    } catch (e) {
      const conflict = conflictMessage(e, $locale);
      if (conflict) {
        // Iemand anders was ons voor; herlaad de verse versie en waarschuw.
        error = conflict;
        await load();
        onchanged?.();
      } else {
        error = e.message;
        item = prev; // rollback
      }
    } finally {
      busy = false;
    }
  }

  function startTitle() {
    titleDraft = item.title;
    editingTitle = true;
  }
  async function saveTitle() {
    const t = titleDraft.trim();
    editingTitle = false;
    if (t && t !== item.title) await patch({ title: t });
  }

  function startDesc() {
    descDraft = item.description_md || "";
    editingDesc = true;
    descMentionMatches = [];
    descHashMatches = [];
  }
  async function saveDesc() {
    editingDesc = false;
    descPicker.closeHash();
    descMentionMatches = [];
    descHashMatches = [];
    if (descDraft !== (item.description_md || "")) await patch({ description_md: descDraft });
  }
  // Eén edit-idioom (BETON-223): klik op de gerenderde omschrijving = bewerken —
  // behalve op een ticketref/link (eigen actie) of een actieve tekstselectie
  // (BETON-415: anders slikt de klik een kopieerpoging op een lange
  // omschrijving op — het blok klapt om in een textarea en de selectie is weg).
  function onDescClick(e) {
    if (!shouldStartEdit(e.target, window.getSelection()?.toString())) return;
    startDesc();
  }
  function onDescEditKeydown(e) {
    if (e.key !== "Enter") return;
    if (!shouldStartEdit(e.target, window.getSelection()?.toString())) return;
    e.preventDefault();
    startDesc();
  }
  // Opslaan op blur — maar niet als de focus naar een knop binnen de editor
  // springt (Afbeelding/Annuleren/Opslaan), anders klobbert de blur die klik.
  function onDescBlur(e) {
    const editor = e.currentTarget.closest(".desc-editor");
    if (editor && e.relatedTarget && editor.contains(e.relatedTarget)) return;
    saveDesc();
  }

  // --- Plan/handover (BETON-218): lazy geladen, standaard ingeklapt ---------
  let showPlan = $state(false);
  let planMd = $state(null); // null = nog niet geladen
  let planLoading = $state(false);
  let editingPlan = $state(false);
  let planDraft = $state("");

  async function loadPlan() {
    planLoading = true;
    try {
      planMd = (await api.getPlan(ref)).plan_md;
    } catch (e) {
      error = e.message;
    } finally {
      planLoading = false;
    }
  }
  async function togglePlan() {
    showPlan = !showPlan;
    // Altijd vers laden bij openen: het plan kan intussen door een agent
    // bijgewerkt zijn (live-reloads verversen alleen het item, niet dit veld).
    if (showPlan) await loadPlan();
  }
  async function startPlanEdit() {
    if (item.has_plan && planMd == null) await loadPlan();
    planDraft = planMd || "";
    editingPlan = true;
  }
  async function savePlan() {
    editingPlan = false;
    const next = planDraft.trim();
    if (next === (planMd || "")) return;
    await patch({ plan_md: next });
    planMd = next || null;
    showPlan = Boolean(next);
  }
  // Klik op het gerenderde plan = bewerken (zelfde idioom als titel/omschrijving,
  // zelfde selectie-guard als onDescClick, BETON-415).
  function onPlanClick(e) {
    if (!shouldStartEdit(e.target, window.getSelection()?.toString())) return;
    startPlanEdit();
  }
  function onPlanBlur(e) {
    const editor = e.currentTarget.closest(".plan-editor");
    if (editor && e.relatedTarget && editor.contains(e.relatedTarget)) return;
    savePlan();
  }

  // --- Guardrail (BETON-420) -----------------------------------------------
  //
  // Zetten/wijzigen/opheffen is mens-only (de backend geeft een agent 403);
  // een agent stelt voor via de MCP-tool `propose_guardrail`, niet hier. De
  // guardrail zelf zit al in de item-serialisatie (begrensd op 1000 tekens),
  // dus er is geen lazy load zoals bij het plan.
  let editingGuardrail = $state(false);
  let guardrailDraft = $state("");
  let guardrailReviewDraft = $state("");
  let guardrailScopeDraft = $state([]);
  let guardrailScopeQuery = $state("");
  let confirmLiftGuardrail = $state(false);
  // Concept-standen (BETON-422): een agent stelt voor, een mens beslist.
  // `editingFromProposal` zegt alleen dat het formulier mét de conceptwaarden
  // geopend is — opslaan loopt hoe dan ook via `setGuardrail`, die de bewerkte
  // versie meteen actief maakt en het concept wist ("goedkeuren met
  // wijzigingen").
  let confirmRejectGuardrail = $state(false);
  let editingFromProposal = $state(false);

  const guardrail = $derived(guardrailMeta(item));
  const guardrailProposal = $derived(guardrailProposalMeta(item));
  // Alleen bij een `set`-voorstel náást een actieve guardrail valt er iets te
  // vergelijken; anders toont de sectie het voorstel zelf (zie lib/guardrail.js).
  const guardrailProposalDiff = $derived(
    proposalDiffSegments(guardrail, guardrailProposal, undefined, $locale),
  );
  const guardrailScopeList = $derived(
    labelPickerList(projectLabels, guardrailScopeDraft, guardrailScopeQuery),
  );
  // Lokale voorcontrole zodat de gebruiker de 422 niet hoeft op te halen. De
  // backend blijft beslissen (hij rekent in UTC, de browser lokaal), dus de
  // servertekst wint zodra die er is.
  const guardrailCheck = $derived(
    guardrailValidation({ text: guardrailDraft, reviewBy: guardrailReviewDraft }, undefined, $locale),
  );

  // Na een activatie via een voorstel (stap 3.3 van BETON-420) is de guardrail
  // altijd projectbreed en bezet hij een van de vijf schaarse plekken. De
  // serialisatie legt niet vast HÓE hij geactiveerd werd — een voorstel-
  // activatie en een bewust projectbrede zijn identiek — dus in plaats van dat
  // geval te herkennen biedt de sectie de scope-stap aan zolang een actieve
  // guardrail projectbreed is. Scopen blijft zo één klik, zonder een veld te
  // verzinnen dat de backend niet heeft.
  function startGuardrailEdit() {
    guardrailDraft = guardrail.text;
    guardrailReviewDraft = guardrail.reviewBy || "";
    guardrailScopeDraft = [...guardrail.scope];
    guardrailScopeQuery = "";
    editingFromProposal = false;
    editingGuardrail = true;
  }

  // "Wijzigen" op een concept: hetzelfde formulier, maar voorgevuld met de
  // VOORGESTELDE waarden. Een verstreken voorgestelde datum laten we leeg —
  // `guardrailValidation` weigert hem toch, en de mens moet hem dan bewust
  // kiezen (de backend zou bij goedkeuren de default-horizon pakken).
  function startGuardrailEditFromProposal() {
    if (!guardrailProposal) return;
    guardrailDraft = guardrailProposal.text;
    const proposed = guardrailProposal.reviewBy || "";
    guardrailReviewDraft = guardrailValidation({ text: "x", reviewBy: proposed }).ok
      ? proposed
      : "";
    guardrailScopeDraft = [...guardrailProposal.scope];
    guardrailScopeQuery = "";
    editingFromProposal = true;
    editingGuardrail = true;
  }

  async function doApproveGuardrail() {
    busy = true;
    try {
      await api.approveGuardrail(ref);
      error = "";
      await load();
      onchanged?.();
    } catch (e) {
      // 409 draagt de servertekst: geen concept meer, of het plafond zit vol.
      error = e.message;
    } finally {
      busy = false;
    }
  }

  async function doRejectGuardrail() {
    confirmRejectGuardrail = false;
    busy = true;
    try {
      await api.rejectGuardrail(ref);
      error = "";
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  function toggleGuardrailScope(name) {
    guardrailScopeDraft = guardrailScopeDraft.includes(name)
      ? guardrailScopeDraft.filter((n) => n !== name)
      : [...guardrailScopeDraft, name];
  }

  async function saveGuardrail() {
    if (!guardrailCheck.ok) {
      error = guardrailCheck.error;
      return;
    }
    busy = true;
    try {
      await api.setGuardrail(ref, {
        guardrail_md: guardrailDraft.trim(),
        review_by: guardrailReviewDraft,
        scope_labels: guardrailScopeDraft,
      });
      editingGuardrail = false;
      error = "";
      await load();
      onchanged?.();
    } catch (e) {
      // 409 (plafond bereikt) en 422 dragen een servertekst die zegt wat te doen.
      error = e.message;
    } finally {
      busy = false;
    }
  }

  async function doLiftGuardrail() {
    confirmLiftGuardrail = false;
    busy = true;
    try {
      await api.liftGuardrail(ref);
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  // --- LLM-verrijking: voorstellen-en-bevestigen (BETON-13) ----------------
  let enriching = $state(false);
  let enrichProposal = $state(null); // null = geen voorstel open
  let enrichCurrent = $state("");
  // BETON-163: bij te magere input stelt de bot vragen als comment i.p.v. een
  // pseudo-omschrijving; dan tonen we een melding i.p.v. een (lege) diff.
  let enrichNotice = $state(null);
  let enrichDiff = $derived(
    enrichProposal == null ? [] : lineDiff(enrichCurrent, enrichProposal)
  );
  // BETON-355: het voorstel draagt ook labels. De server levert alleen labels die
  // op het project bestaan en er nog niet op staan; hier kiest de mens welke er
  // daadwerkelijk bij mogen (standaard allemaal aan).
  let enrichLabels = $state([]);
  let enrichLabelsPicked = $state([]);

  function toggleEnrichLabel(name) {
    enrichLabelsPicked = enrichLabelsPicked.includes(name)
      ? enrichLabelsPicked.filter((l) => l !== name)
      : [...enrichLabelsPicked, name];
  }

  async function runEnrich() {
    enriching = true;
    enrichNotice = null;
    try {
      const res = await api.enrich(ref);
      if (res.kind === "questions") {
        // De bot had onvoldoende info en heeft (idealiter) vragen in de comments
        // gezet. Herlaad zodat die comment meteen zichtbaar wordt.
        enrichNotice = enrichQuestionsNotice(res.comment_posted, $locale);
        await load();
      } else {
        enrichCurrent = res.current || "";
        enrichProposal = res.proposal;
        enrichLabels = res.labels || [];
        enrichLabelsPicked = [...enrichLabels];
      }
    } catch (e) {
      error = e.message;
    } finally {
      enriching = false;
    }
  }
  async function acceptEnrich() {
    const proposal = enrichProposal;
    const labels = enrichLabelsPicked;
    enrichProposal = null;
    enrichLabels = [];
    enrichLabelsPicked = [];
    error = "";
    await patch({ description_md: proposal });
    // Eerst de omschrijving, dan pas de labels: `patch` stuurt een precondition
    // mee (BETON-44) en bij een conflict is er niets opgeslagen — dan horen de
    // labels ook niet stilletjes tóch te landen. Labels AANVULLEN, nooit de set
    // vervangen (BETON-65): per label de toevoeg-route, geen PATCH met de hele
    // lijst.
    if (error || !labels.length) return;
    busy = true;
    try {
      for (const name of labels) await api.addLabel(ref, name);
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }
  function cancelEnrich() {
    enrichProposal = null;
    enrichLabels = [];
    enrichLabelsPicked = [];
  }

  // --- Decompose (opknippen in subtaken, BETON-31) ------------------------
  let decomposing = $state(false);
  let decomposeProposal = $state(null); // null = geen voorstel open

  async function runDecompose() {
    decomposing = true;
    error = "";
    try {
      decomposeProposal = await api.decompose(ref);
    } catch (e) {
      error = e.message;
    } finally {
      decomposing = false;
    }
  }
  async function applyDecompose() {
    const proposal = decomposeProposal;
    decomposeProposal = null;
    try {
      await api.decomposeApply(ref, proposal);
      onchanged?.();
    } catch (e) {
      error = e.message;
    }
  }
  function cancelDecompose() {
    decomposeProposal = null;
  }

  async function toggleLabel(name) {
    const prev = item;
    const has = (item.labels || []).includes(name);
    const labels = toggleSelection(item.labels || [], name);
    item = { ...item, labels }; // optimistisch
    busy = true;
    try {
      if (has) await api.removeLabel(ref, name);
      else await api.addLabel(ref, name);
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
      item = prev; // rollback
    } finally {
      busy = false;
    }
  }

  async function addRelation() {
    const target = relTarget.trim();
    if (!target) return;
    const type = relType;
    const prev = item;
    const relations = { ...(item.relations || {}) };
    relations[type] = [...(relations[type] || []), target]; // optimistisch
    item = { ...item, relations };
    relTarget = "";
    relPicker.close();
    busy = true;
    try {
      await api.addRelation(ref, type, target);
      // Melding pas ná load() zetten — load() begint zelf met `error = ""`,
      // dus een eerder gezette melding wordt anders geruisloos overschreven.
      const notice = await cancelDuplicateIfNeeded(type, target);
      await load();
      if (notice) error = notice;
      onchanged?.();
    } catch (e) {
      error = e.message;
      item = prev; // rollback
    } finally {
      busy = false;
    }
  }

  // BETON-279: na een geslaagde duplicate_of/duplicated_by-relatie het
  // duplicaat automatisch naar de cancelled-state van zíjn project zetten.
  // item_id (src) is altijd het duplicaat — bij "duplicate_of" is dat het
  // HUIDIGE item, bij "duplicated_by" het DOEL (repo/relations.py:19-23).
  // Cancel-beslissing zit in de pure helper (lib/duplicateCancel.js);
  // hier alleen de state ophalen en de mutatie uitvoeren. Nooit een fout hier
  // laten de relatie zelf ongedaan maken — die staat er al. Geeft een
  // melding terug i.p.v. `error` direct te zetten (zie call-site).
  async function cancelDuplicateIfNeeded(type, target) {
    const duplicateRef = duplicateRefForRelation(type, ref, target);
    if (!duplicateRef) return null;
    try {
      const dupItem = await api.item(duplicateRef);
      const dupStates = await api.states(dupItem.project);
      const curState = dupStates.find((s) => s.name === dupItem.state);
      const cancelledState = dupStates.find((s) => s.group === "cancelled");
      const action = resolveDuplicateCancelAction({
        stateGroup: curState?.group ?? null,
        cancelledStateName: cancelledState?.name ?? null,
      });
      if (action.action !== "cancel") {
        if (action.reason === "no-cancelled-state") {
          return $uiText("detail.duplicateNoCancelled", {ref: duplicateRef, project: dupItem.project});
        }
        return null;
      }
      await api.updateItem(duplicateRef, { state: action.stateName });
      return null;
    } catch (e) {
      return $uiText("detail.duplicateCancelFailed", {ref: duplicateRef, cause: e.message});
    }
  }

  // --- Relatie-target autocomplete (cross-project zoek op titel) ------------
  function onRelInput(e) { return relPicker.input(e); }

  function onRelKeydown(e) { return relPicker.keydown(e); }

  // BETON-414: de relatie-invoer opent op verzoek i.p.v. permanent open te
  // staan, dus de focus moet mee — zelfde tick/focus-patroon als pickRelTarget.
  async function openRelAdd() {
    relAddOpen = true;
    await tick();
    relInput?.focus();
  }

  function pickRelTarget(targetRef) { return relPicker.pick(targetRef); }

  async function removeRelation(type, target) {
    const prev = item;
    const relations = { ...(item.relations || {}) };
    relations[type] = (relations[type] || []).filter((r) => r !== target); // optimistisch
    item = { ...item, relations };
    busy = true;
    try {
      await api.deleteRelation(ref, type, target);
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
      item = prev; // rollback
    } finally {
      busy = false;
    }
  }

  // --- Eigen volg-/demp-keuze (BETON-245/369/459) --------------------------
  // Eén keuze (Volgen / Dempen / Normaal) vertaalt via `followChoiceOps` naar de
  // bestaande endpoints (follow/unfollow, mute/unmute op jezelf). Mens-only voor
  // volgen; andermans mute-status tonen we niet meer. Na afloop item +
  // volgerslijst vers laden.
  async function applyFollowChoice(choice) {
    if (!choice || !me) return;
    const ops = followChoiceOps(choice, { following: item?.is_following === true, muted: selfMuted });
    if (!ops.length) return;
    busy = true;
    try {
      for (const op of ops) {
        if (op === "follow") await api.follow(ref);
        else if (op === "unfollow") await api.unfollow(ref);
        else if (op === "mute") await api.muteSubscriber(ref, me.handle);
        else await api.unmuteSubscriber(ref, me.handle);
      }
      subscribers = (await api.subscribers(ref)).subscribers;
      item = { ...item, is_following: choice === "follow" || (choice === "mute" && item?.is_following === true) };
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  // Noodstop (BETON-302). Mens-only: de knoppen staan alleen voor een mens in
  // het menu, en de backend weigert een agent sowieso met 403.
  async function doLock() {
    confirmLock = false;
    try {
      await api.lockItem(ref);
      onchanged?.();
    } catch (e) {
      error = e.message;
    }
  }

  // BETON-338: ontgrendelen mét gekozen ruimte (5/10/20). Eén pad voor alle
  // aangrijppunten — de banner, het ⋯-menu en de wachtende comment in de
  // tijdlijn roepen dit alle drie aan.
  let unlockMenuOpen = $state(false);

  async function doUnlock(headroom = 5) {
    unlockMenuOpen = false;
    try {
      await api.unlockItem(ref, headroom);
      onchanged?.();
    } catch (e) {
      error = e.message;
    }
  }

  async function doArchive() {
    confirmArchive = false;
    try {
      await api.archiveItem(ref);
      onchanged?.();
      onclose?.();
    } catch (e) {
      error = e.message;
    }
  }

  // Projectenlijst voor "verplaats naar ander project" (BETON-95). Eén keer laden.
  $effect(() => {
    api.projects().then((p) => (projects = p)).catch((e) => {
      error = $uiText("detail.projectsError", { cause: e.message });
    });
  });

  async function doMove() {
    confirmMove = false;
    const target = moveTarget;
    moveTarget = "";
    if (!target) return;
    try {
      const res = await api.moveItem(ref, target);
      onchanged?.();
      // Navigeer naar het nieuwe item (in het doelproject; het origineel is nu
      // gearchiveerd). Via onopen zodat App het juiste project kiest + de drawer
      // opent — de app routeert op pad, niet op #hash (BETON-95/107 fix).
      onopen?.(res.ref);
    } catch (e) {
      error = e.message;
    }
  }

  async function doDelete() {
    confirmDelete = false;
    try {
      await api.deleteItem(ref);
      onchanged?.();
      onclose?.();
    } catch (e) {
      error = e.message;
    }
  }

  // Herstel uit archief (BETON-59): zet het item terug op het board.
  async function doRestore() {
    try {
      await api.restoreItem(ref);
      onchanged?.();
      await load();
    } catch (e) {
      error = e.message;
    }
  }

  function copyRef() {
    navigator.clipboard?.writeText(item.ref).then(() => {
      copied = true;
      clearTimeout(copyTimer);
      copyTimer = setTimeout(() => (copied = false), 1500);
    });
  }

  // BETON-373: kleine zelfstandige melding voor acties zonder eigen
  // aangrijppunt (het ⋯-menu sluit meteen na een klik) — geen los toast-
  // component, spiegelt de bestaande copyRef()-checkmark maar met tekst.
  let copyMdMsg = $state("");
  let copyMdTimer = null;
  function flashCopyMdMsg(msg) {
    copyMdMsg = msg;
    clearTimeout(copyMdTimer);
    copyMdTimer = setTimeout(() => (copyMdMsg = ""), 2000);
  }

  // "Kopieer als markdown" (BETON-373): het plan hoort er alleen bij als het
  // al geladen is (item.has_plan) — anders eerst ophalen, net als
  // startPlanEdit() dat doet.
  async function copyAsMarkdown() {
    try {
      if (item.has_plan && planMd == null) await loadPlan();
      const md = itemToMarkdown(item, { comments: item.comments, plan: planMd, states, locale: $locale });
      await navigator.clipboard?.writeText(md);
      flashCopyMdMsg($uiText("detail.copied"));
    } catch (e) {
      error = e.message;
    }
  }

  // "Dupliceer ticket" (BETON-373): sluit dit item, opent NewItem voorgevuld.
  // De relates_to-relatie naar het origineel legt de aanroeper (App.svelte) —
  // duplicateDraft() kent het origineel zelf niet.
  function doDuplicate() {
    onduplicate?.(duplicateDraft(item, $locale), item.ref);
  }

  // --- Comments + mention-autocomplete ------------------------------------

  function onCommentInput(e) { return commentPicker.input(e); }

  function onCommentKeydown(e) { return commentPicker.keydown(e); }

  function pickMention(handle) { return commentPicker.pickMention(handle); }

  function pickHashRef(ref) { return commentPicker.pickHash(ref); }

  // --- Omschrijving-edit: zelfde @mention/#ticket-autocomplete (BETON-289) -
  // Eigen controllerstate houdt omschrijving en comment onafhankelijk.
  function onDescInput(e) { return descPicker.input(e); }

  function onDescKeydown(e) { return descPicker.keydown(e); }

  function pickDescMention(handle) { return descPicker.pickMention(handle); }

  function pickDescHashRef(ref) { return descPicker.pickHash(ref); }

  // --- Afbeeldingen slepen/plakken/uploaden (BETON-5, BETON-74) ------------
  let uploading = $state(false);
  let descTextarea = $state();
  let descFileInput = $state();
  let descQuickFileInput = $state();
  let commentFileInput = $state();
  // Zichtbare bevestiging dat een gesleepte/geplakte afbeelding in de
  // comment-composer echt geüpload is (BETON-94): zonder preview leek het
  // alsof slepen niets deed — je zag alleen de rauwe markdown-tekst in de
  // textarea totdat de comment geplaatst werd. Gebruikt de echte server-URL
  // (geen object-URL nodig, het attachment bestaat al na upload).
  let commentImages = $state([]); // { id, url, filename }
  let nextCommentImageId = 0;

  function imageFilesFrom(e) {
    return attachableFilesFromTransfer(e.dataTransfer || e.clipboardData);
  }

  // Upload elke afbeelding en voeg de markdown-image op de caretpositie in.
  // target: "desc" (omschrijving-edit), "comment" (nieuwe-reactie-composer) of
  // "editComment" (een reactie die al in bewerkmodus staat, BETON-403),
  // "answer" (antwoordveld van vraag `questionId`) of "editAnswer" (BETON-434).
  // Gedeeld door de sleep/plak-flow (dataTransfer/clipboardData) én de
  // zichtbare upload-knop (file-input, BETON-74).
  async function uploadImages(files, target, el, questionId) {
    if (!files.length) return;
    uploading = true;
    try {
      for (const file of files) {
        const att = await api.uploadAttachment(ref, file);
        attachments = [...attachments, att];
        insertAtCaret(target, el, attachmentMarkdown(att), questionId);
        if (target === "comment" && isImageAttachment(att)) {
          commentImages = [
            ...commentImages,
            { id: nextCommentImageId++, url: att.url, filename: att.filename },
          ];
        }
      }
    } catch (err) {
      error = err.message;
    } finally {
      uploading = false;
    }
  }

  async function handleImageDrop(e, target, questionId) {
    const files = imageFilesFrom(e);
    if (!files.length) return;
    e.preventDefault();
    await uploadImages(files, target, e.currentTarget, questionId);
  }

  // Zichtbare upload-knop (BETON-74): opent een verborgen file-input; de
  // gekozen bestanden lopen door dezelfde upload-en-invoegen-flow als
  // slepen/plakken, ingevoegd op de caretpositie van `el` (het bijbehorende
  // tekstveld — niet de file-input zelf).
  async function handleImageFileInput(e, target, el) {
    const files = attachableFilesFromFileList(e.currentTarget.files);
    e.currentTarget.value = ""; // zelfde bestand nog eens kunnen kiezen
    await uploadImages(files, target, el);
  }

  // Snelle upload-knop naast "Bewerk"/"Verrijk" (BETON-74): werkt ook als de
  // omschrijving nog NIET in bewerk-modus staat — dat was precies de reden
  // dat plakken/slepen voor veel gebruikers "niet werkte" (die handlers
  // zitten alleen op de textarea in editingDesc-modus). Zet zelf eerst de
  // bewerk-modus aan, upload/voeg in, en sla meteen op zodat het resultaat
  // direct zichtbaar is zonder een aparte, niet-voor-de-hand-liggende
  // Opslaan-stap.
  async function quickAddDescImage(e) {
    const files = attachableFilesFromFileList(e.currentTarget.files);
    e.currentTarget.value = "";
    if (!files.length) return;
    if (!editingDesc) startDesc();
    await tick();
    await uploadImages(files, "desc", descTextarea);
    await saveDesc();
  }

  // "Invoegen in omschrijving" vanuit de bijlagen-galerij (BETON-175): een
  // attachment kan al bestaan zonder in de omschrijving te staan (bv. via de
  // comment-flow, of een oudere upload). Zelfde patroon als quickAddDescImage:
  // zet zo nodig eerst bewerk-modus aan, voeg de markdown-ref toe op het
  // eind, sla direct op.
  async function insertAttachmentInDesc(att) {
    if (!editingDesc) startDesc();
    await tick();
    const sep = descDraft && !descDraft.endsWith("\n") ? "\n" : "";
    insertAtCaret("desc", descTextarea, `${sep}${attachmentMarkdown(att)}`);
    await saveDesc();
  }

  // Preview-thumbnail verwijderen: haalt ook de bijbehorende markdown-regel
  // uit de nog niet geplaatste comment-tekst.
  function removeCommentImage(id) {
    const img = commentImages.find((c) => c.id === id);
    if (!img) return;
    commentImages = commentImages.filter((c) => c.id !== id);
    commentText = removeImageMarkdown(commentText, img.filename, img.url);
  }

  // `questionId`: bij target "answer" de vraag waarvan het antwoordveld
  // gevuld wordt (BETON-434); de antwoordconcepten zijn per vraag.
  function insertAtCaret(target, el, text, questionId) {
    const next = insertIntoDrafts(
      target,
      {
        desc: descDraft,
        comment: commentText,
        editComment: editCommentText,
        answer: answerDrafts[questionId] ?? "",
        editAnswer: answerEditDraft,
      },
      el?.selectionStart,
      text,
    );
    descDraft = next.desc;
    commentText = next.comment;
    editCommentText = next.editComment;
    answerEditDraft = next.editAnswer;
    if (target === "answer") answerDrafts = { ...answerDrafts, [questionId]: next.answer };
  }

  // In-flight-guard (BETON-217): zonder deze vuurde een ingedrukte Cmd+Enter
  // (key-repeat) submitComment meermaals vóór de eerste POST terugkwam —
  // dezelfde comment werd dan 4× geplaatst en elke kopie triggerde agents.
  let commentBusy = $state(false);
  async function submitComment() {
    const body = commentText.trim();
    if (!body || commentBusy) return;
    commentBusy = true;
    try {
      const created = await api.comment(ref, body);
      commentText = "";
      commentImages = [];
      mentionMatches = [];
      await load();
      onchanged?.();
      // BETON-253: scroll de zojuist geplaatste comment in beeld. De DOM-update
      // van load() is async in Svelte 5 → wacht op tick() vóór het ophalen van
      // het anker (id="cmt-{id}"). Id uit de POST-response, met fallback op de
      // nieuwste comment.
      await tick();
      const targetId = commentScrollTargetId(created, item?.comments);
      if (targetId != null) scrollToComment(targetId);
    } catch (e) {
      error = e.message;
    } finally {
      commentBusy = false;
    }
  }

  // --- Vraagmodule: beantwoorden (BETON-219) -------------------------------
  // Vrijtekst-concepten per vraag-comment-id; de gekozen-optie-bevestiging als
  // {id, index} zodat een optieklik niet meteen vuurt (inline confirm-bar, in
  // hetzelfde idioom als de andere drawer-bevestigingen). answerBusy voorkomt
  // een dubbele POST (het antwoord herlaadt de tijdlijn).
  let answerDrafts = $state({});
  let pendingOption = $state(null); // { id, index } of null
  let answerBusy = $state(false);

  async function answerWith(questionId, body) {
    if (answerBusy) return;
    answerBusy = true;
    try {
      await api.answerQuestion(questionId, body);
      pendingOption = null;
      const { [questionId]: _drop, ...rest } = answerDrafts;
      answerDrafts = rest;
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
    } finally {
      answerBusy = false;
    }
  }
  // Antwoord wijzigen tot het verstuurd is (BETON-263).
  let editingAnswerId = $state(null);
  let answerEditDraft = $state("");
  function startEditAnswer(c) {
    editingAnswerId = c.id;
    answerEditDraft = questionState(c).answerText ?? "";
  }
  async function saveAnswerEdit(questionId, body) {
    if (answerBusy) return;
    answerBusy = true;
    try {
      await api.updateAnswer(questionId, body);
      editingAnswerId = null;
      await load();
      onchanged?.();
    } catch (e) {
      error = e.message;
    } finally {
      answerBusy = false;
    }
  }
  function submitAnswerTextEdit(id) {
    const t = (answerEditDraft || "").trim();
    if (!t) return;
    saveAnswerEdit(id, textAnswer(t));
  }
  function pickOption(id, index) {
    pendingOption = { id, index };
  }
  function confirmOption() {
    const p = pendingOption;
    if (p) answerWith(p.id, optionAnswer(p.index));
  }
  function submitTextAnswer(id) {
    const t = (answerDrafts[id] || "").trim();
    if (!t) return;
    answerWith(id, textAnswer(t));
  }
  function scrollToComment(id) {
    pinnedCommentId = id; // een comment waar naartoe gesprongen is klapt niet in (BETON-458)
    document.getElementById(`cmt-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function startEditComment(c) {
    confirmDeleteId = null;
    editingCommentId = c.id;
    editCommentText = c.body_md;
  }
  let savingEditComment = false; // dubbele Cmd+Enter (BETON-462)
  async function saveEditComment() {
    const body = editCommentText.trim();
    if (!body || savingEditComment) return;
    savingEditComment = true;
    try {
      await api.updateComment(ref, editingCommentId, body);
      editingCommentId = null;
      await load();
    } catch (e) {
      error = e.message;
    } finally {
      savingEditComment = false;
    }
  }
  async function doDeleteComment(id) {
    confirmDeleteId = null;
    try {
      await api.deleteComment(ref, id);
      await load();
    } catch (e) {
      error = e.message;
    }
  }

  // Bekende handles voor mention-chips in gerenderde markdown (BETON-60).
  let knownHandles = $derived((users || []).map((u) => u.handle));
  // Bekende project-keys zodat ticketrefs (bv. BETON-91) in omschrijving en
  // comments klikbaar worden (BETON-107).
  let projectKeys = $derived(projects.map((p) => p.key));

  // Een ticketref activeren (klik of Enter/Space): laat App het ticket openen via
  // onopen (wisselt zo nodig van project + opent de drawer). De app routeert op
  // pad (/KEY/seq), niet op #hash — vandaar de callback (BETON-107 fix).
  function activateTicketLink(link) {
    const ref = link.getAttribute("data-ticket");
    if (!ref) return;
    onopen?.(ref);
  }

  function onTicketClick(e) {
    const ticket = e.target.closest?.("[data-ticket]");
    if (!ticket) return;
    e.preventDefault();
    activateTicketLink(ticket);
  }

  function onTicketKeydown(e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    const ticket = e.target.closest?.("[data-ticket]");
    if (!ticket) return;
    e.preventDefault();
    activateTicketLink(ticket);
  }

  let relationList = $derived(relationGroups(item, relationLabel));
  let subtaskList = $derived(subtaskGroups(item));
  // Volgers-chips (BETON-245): ontdubbeld + gesorteerd (actief vóór gemute).
  let followerRow = $derived(followerAvatars(subscribers));
  let selfMuted = $derived(subscribers.find((s) => s.handle === me?.handle)?.muted === true);
  let selfFollow = $derived(selfFollowState({ following: item?.is_following === true, muted: selfMuted }, $locale));
  // Volg-knop (BETON-369): mens-only tegenhanger van de mute.
  let hasUnsavedComment = $derived(commentText.trim().length > 0);

  // Samengevoegde tijdlijn: comments (kaarten) + activiteitsregels (BETON-223).
  let timeline = $derived(mergeTimeline(item?.comments, activity, item?.held_comment));

  // Tijdlijn-modus (BETON-364): "Alles" of "Reacties" (comments/held/
  // question.answered), persistent per sessie zoals de andere UI-voorkeuren.
  const TIMELINE_MODE_KEY = "betonning-timeline";
  let timelineMode = $state(
    readPersisted(TIMELINE_MODE_KEY, (v) => v === "all" || v === "comments", "all"),
  );
  function setTimelineMode(v) {
    timelineMode = v;
    writePersisted(TIMELINE_MODE_KEY, v);
  }
  const TIMELINE_MODE_OPTS = $derived([
    { value: "all", label: $uiText("detail.all") },
    { value: "comments", label: $uiText("detail.comments") },
  ]);
  // BETON-273/364: een deep-link naar een specifieke comment moet altijd
  // zichtbaar zijn, ongeacht de opgeslagen tijdlijn-voorkeur — anders scrollt
  // scrollToComment naar een anker dat door het filter niet gerenderd is.
  let effectiveTimelineMode = $derived(targetCommentId != null ? "all" : timelineMode);
  // Ingeklapte event-groepen staan standaard dicht; per sleutel onthouden
  // welke de gebruiker heeft uitgeklapt.
  let expandedGroups = $state(new Set());
  function toggleGroup(key) {
    const next = new Set(expandedGroups);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    expandedGroups = next;
  }
  // BETON-458: lange comments klappen in op de GEMETEN hoogte (ResizeObserver
  // in `measureComment`). Nieuwste, eigen en aangesprongen comments niet.
  let commentSizes = $state({}); // id → { h, first }
  let expandedComments = $state(new Set());
  let pinnedCommentId = $state(null);
  let lastCommentId = $derived(
    [...timeline].reverse().find((e) => e.kind === "comment")?.comment.id ?? null,
  );
  function collapseOf(c) {
    const size = commentSizes[c.id];
    return commentCollapse({
      height: size?.h ?? 0,
      firstBlockHeight: size?.first ?? 0,
      alwaysOpen: commentAlwaysOpen(c, { lastCommentId, meHandle: me?.handle, pinnedId: pinnedCommentId }),
      expanded: expandedComments.has(c.id),
    });
  }
  function toggleComment(id) {
    const next = new Set(expandedComments);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    expandedComments = next;
  }
  // Action: meet de volle hoogte (scrollHeight, ook als max-height knipt) en
  // die van het eerste blok; meet opnieuw bij elke grootteverandering
  // (afbeeldingen die laden, breedte van het paneel).
  function measureComment(node, arg) {
    let id = arg.id;
    const report = () => {
      const h = node.scrollHeight;
      const first = node.firstElementChild?.offsetHeight ?? 0;
      const cur = commentSizes[id];
      if (!cur || cur.h !== h || cur.first !== first) commentSizes[id] = { h, first };
    };
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(report) : null;
    const observeAll = () => {
      ro?.disconnect();
      ro?.observe(node);
      for (const child of node.children) ro?.observe(child);
    };
    report();
    observeAll();
    return {
      // Nieuwe body (bewerkt door een ander): kinderen zijn vervangen, dus
      // opnieuw meten en opnieuw observeren.
      update(next) {
        id = next.id;
        queueMicrotask(() => {
          report();
          observeAll();
        });
      },
      destroy: () => ro?.disconnect(),
    };
  }

  // BETON-458: de reactiebalk is in rust één regel; hij groeit bij focus of
  // zodra er een concept of een afbeelding staat — een concept verdwijnt nooit.
  let composerFocused = $state(false);
  function onComposerFocusOut(e) {
    if (!e.currentTarget.contains(e.relatedTarget)) composerFocused = false;
  }
  let composerCompact = $derived(
    !composerFocused && !commentText.trim() && commentImages.length === 0 && !uploading,
  );

  let displayTimeline = $derived(
    collapseEvents(filterTimeline(timeline, effectiveTimelineMode)),
  );
  // BETON-340: op een gelockt ticket hoort de ontgrendel-actie óók "bij de
  // comment" te staan, niet alleen in de banner. De laatste comment in de
  // tijdlijn is precies de juiste plek: staat er iets in de wacht, dan is dát
  // de laatste entry (BETON-338); anders is het de comment die de drempel
  // raakte en het slot deed vallen. Eén regel, geen aparte gevalsonderscheiding.
  let lastCommentKey = $derived(
    [...timeline].reverse().find((e) => e.kind === "comment" || e.kind === "held")?.key ?? null,
  );
  // BETON-414: de regels van de compacte eigenschappenlijst (label + waarde +
  // leeg-markering), op sleutel opzoekbaar. propertySummary zit eronder.
  let railProps = $derived(
    new Map(railProperties(item, { subscribers, milestones, locale: $locale }).map((r) => [r.key, r])),
  );
  // Label-picker-lijst (gefilterd + toegekend-markering).
  let labelList = $derived(labelPickerList(projectLabels, item?.labels, labelQuery));
  // Projecten waarheen verplaatst kan worden (niet het huidige).
  let moveTargets = $derived(projects.filter((p) => p.key !== item?.project));

  // BETON-362: vorige/volgende in de huidige kolom/lijst.
  let nav = $derived(neighbours(siblings, ref));
  // Ref waar de "Toch doorgaan"-bevestiging naartoe moet navigeren i.p.v. de
  // drawer echt te sluiten — hergebruikt de bestaande confirmClose-poort
  // (onopgeslagen reactie), zie navTo/forceClose hieronder.
  let pendingNav = $state(null);

  function navTo(targetRef) {
    if (!targetRef) return;
    if (hasUnsavedComment) {
      pendingNav = targetRef;
      confirmClose = true;
      return;
    }
    onopen?.(targetRef);
  }

  // Header-X / expliciete sluitknop: met onopgeslagen concept eerst waarschuwen,
  // anders programmatisch sluiten (dialogOpen=false → onOpenChange → onclose).
  function tryClose() {
    if (hasUnsavedComment) {
      confirmClose = true;
      return;
    }
    dialogOpen = false;
  }

  // "Toch sluiten"/"Toch doorgaan": concept-guard opheffen. Stond er een
  // navigatiedoel klaar (pendingNav, BETON-362) dan navigeren we daarheen
  // i.p.v. de drawer te sluiten.
  function forceClose() {
    commentText = "";
    confirmClose = false;
    if (pendingNav) {
      const target = pendingNav;
      pendingNav = null;
      onopen?.(target);
      return;
    }
    dialogOpen = false;
  }

  // Gecentraliseerde Escape-ladder (BETON-223): bits-ui roept dit op Content aan.
  // Een actieve sub-state vangt Escape af (preventDefault); staat er niets open,
  // dan sluit de dialog (geen preventDefault → onOpenChange → onclose). De
  // onopgeslagen-comment-guard is de laatste rung: die toont de bevestiging i.p.v.
  // meteen te sluiten.
  function onEscapeKeydown(e) {
    const rung = escapeLadder({
      mention: mentionMatches.length > 0,
      hashMatches: hashMatches.length > 0,
      relMatches: relMatches.length > 0,
      editingComment: editingCommentId != null,
      editingTitle,
      descMention: descMentionMatches.length > 0,
      descHashMatches: descHashMatches.length > 0,
      editingDesc,
      editingPlan,
      editingGuardrail,
      confirm:
        confirmArchive ||
        confirmLiftGuardrail ||
        confirmRejectGuardrail ||
        confirmDelete ||
        confirmClose ||
        confirmMove ||
        confirmDeleteId != null ||
        confirmRelation != null ||
        pendingOption != null,
      unsavedComment: hasUnsavedComment,
    });
    if (!rung) return; // niets open → laat de dialog sluiten
    e.preventDefault();
    applyEscapeRung(rung);
  }

  function applyEscapeRung(rung) {
    switch (rung) {
      case "mention":
        mentionMatches = [];
        break;
      case "hashMatches":
        commentPicker.closeHash();
        hashMatches = [];
        break;
      case "relMatches":
        relPicker.close();
        break;
      case "editingComment":
        editingCommentId = null;
        break;
      // Draft eerst terugzetten naar de opgeslagen waarde: het verbergen van het
      // veld kan onderweg een blur afvuren (→ save). Door de draft gelijk te
      // maken aan de bron slaat die save niets op — Esc annuleert dus echt.
      case "editingTitle":
        titleDraft = item.title;
        editingTitle = false;
        break;
      case "descMention":
        descMentionMatches = [];
        break;
      case "descHashMatches":
        descPicker.closeHash();
        descHashMatches = [];
        break;
      case "editingDesc":
        descDraft = item.description_md || "";
        editingDesc = false;
        break;
      case "editingPlan":
        planDraft = planMd || "";
        editingPlan = false;
        break;
      case "editingGuardrail":
        editingGuardrail = false;
        break;
      case "confirm":
        confirmArchive = false;
        confirmLiftGuardrail = false;
        confirmRejectGuardrail = false;
        confirmDelete = false;
        confirmClose = false;
        confirmMove = false;
        confirmDeleteId = null;
        confirmRelation = null;
        moveTarget = "";
        pendingOption = null;
        break;
      case "unsavedComment":
        confirmClose = true;
        break;
    }
  }

  // Buiten-klik (backdrop): alleen de onopgeslagen-comment-guard; sub-states laten
  // we door de klik gewoon sluiten (net als voorheen de overlay-klik).
  function onInteractOutside(e) {
    if (hasUnsavedComment) {
      e.preventDefault();
      confirmClose = true;
    }
  }

  function toggleProp(key) {
    expandedProp = expandedProp === key ? null : key;
  }

  // BETON-362: `[`/`]` = vorige/volgende, alleen als de focus niet in een
  // tekstveld/dropdown zit (zelfde poort als de kaart-sneltoetsen, BETON-361)
  // — anders zou `[`/`]` typen in de omschrijving/een comment de drawer laten
  // wegnavigeren.
  function onDrawerKeydown(e) {
    const action = drawerShortcutAction(e);
    if (!action) return;
    if (action.type === "handoff") {
      const target = preferredHandoffTarget(quickHandoffs, item, me);
      if (!target || busy) return;
      e.preventDefault();
      patch({ assignee: target.handle });
    } else if (action.type === "prev-item" && nav.prev) {
      e.preventDefault();
      navTo(nav.prev);
    } else if (action.type === "next-item" && nav.next) {
      e.preventDefault();
      navTo(nav.next);
    }
  }
  const commentPicker = textPicker({
    get: () => ({ text: commentText, caret: caret, mentionMatches: mentionMatches, mentionActive: mentionActive, hashMatches: hashMatches, hashActive: hashActive }),
    set: (patch) => {
      if ("text" in patch) commentText = patch.text;
      if ("caret" in patch) caret = patch.caret;
      if ("mentionMatches" in patch) mentionMatches = patch.mentionMatches;
      if ("mentionActive" in patch) mentionActive = patch.mentionActive;
      if ("hashMatches" in patch) hashMatches = patch.hashMatches;
      if ("hashActive" in patch) hashActive = patch.hashActive;
    },
    users: () => users, project: () => item?.project, api, tick,
    textarea: () => textarea, localEscape: false,
  });
  const descPicker = textPicker({
    get: () => ({ text: descDraft, caret: descCaret, mentionMatches: descMentionMatches, mentionActive: descMentionActive, hashMatches: descHashMatches, hashActive: descHashActive }),
    set: (patch) => {
      if ("text" in patch) descDraft = patch.text;
      if ("caret" in patch) descCaret = patch.caret;
      if ("mentionMatches" in patch) descMentionMatches = patch.mentionMatches;
      if ("mentionActive" in patch) descMentionActive = patch.mentionActive;
      if ("hashMatches" in patch) descHashMatches = patch.hashMatches;
      if ("hashActive" in patch) descHashActive = patch.hashActive;
    },
    users: () => users, project: () => item?.project, api, tick,
    textarea: () => descTextarea, localEscape: false,
  });
  const relPicker = relationPicker({
    get: () => ({ target: relTarget, matches: relMatches, active: relActive }),
    set: (patch) => {
      if ("target" in patch) relTarget = patch.target;
      if ("matches" in patch) relMatches = patch.matches;
      if ("active" in patch) relActive = patch.active;
    },
    project: () => item?.project, self: () => ref, api, tick,
    textarea: () => relInput, add: () => addRelation(),
    onerror: (e) => { error = $uiText("detail.relationError", { cause: e.message }); },
    localEscape: false,
  });
  onDestroy(() => { descPicker.close(); relPicker.close(); commentPicker.close(); });
</script>

<DrawerDialog
  label={item?.ref ?? "Ticket"}
  width="min(1440px, 94vw)"
  bind:open={dialogOpen}
  {onclose}
  {onEscapeKeydown}
  {onInteractOutside}
>
  {#if item}
    <div class="dw" onkeydown={onDrawerKeydown} role="presentation">
      <header class="dw-head">
        <button class="icon-btn dw-back" onclick={tryClose} aria-label={$t("drawer.back")} title={$t("drawer.back")}>
          <ArrowLeft size={19} />
        </button>
        {#if nav.total > 1}
          <span class="dw-nav">
            <button
              class="icon-btn"
              disabled={!nav.prev}
              title={nav.prev ? $uiText("detail.previousRef", { ref: nav.prev }) : $uiText("detail.noPrevious")}
              aria-label={$t("drawer.previous")}
              onclick={() => navTo(nav.prev)}
            >
              <ChevronLeft size={16} />
            </button>
            {#if nav.index > 0}<span class="dw-nav-count">{nav.index} / {nav.total}</span>{/if}
            <button
              class="icon-btn"
              disabled={!nav.next}
              title={nav.next ? $uiText("detail.nextRef", { ref: nav.next }) : $uiText("detail.noNext")}
              aria-label={$t("drawer.next")}
              onclick={() => navTo(nav.next)}
            >
              <ChevronRight size={16} />
            </button>
          </span>
        {/if}
        <Chip tone="neutral" onclick={copyRef} title={$t("drawer.copyRef")}>
          {#if copied}<Check size={13} />{:else}<Copy size={13} />{/if}
          <span>{item.ref}</span>
          {#if copied}<span class="copied">{$t("drawer.copied")}</span>{/if}
        </Chip>
        {#if item.parent}
          <span class="parent-link">
            <span class="parent-label">{$t("drawer.parent")}</span>
            <button class="ref-link" title={$uiText("detail.parent")} onclick={() => onopen?.(item.parent)}>{item.parent}</button>
          </span>
        {/if}
        <!-- BETON-240: één pill-designtaal — de status-chip gebruikt nu dezelfde
             neutrale Chip als de ref-chip (statusstip als kind). -->
        <Chip tone="neutral" title={$t("drawer.status")}>
          <span class="col-dot" style:background={stateColor(states, item.state)}></span>
          {item.state}
        </Chip>
        {#if item.archived_at}<span class="arch-badge">{$t("drawer.archived")}</span>{/if}
        {#if copyMdMsg}<span class="copy-md-msg" role="status">{copyMdMsg}</span>{/if}
        <div class="dw-actions">
          <DropdownMenu.Root>
            <DropdownMenu.Trigger class="icon-btn" title={$t("drawer.more")} aria-label={$t("drawer.more")}>
              <MoreHorizontal size={18} />
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content class="dw-menu" align="end" sideOffset={4}>
                <DropdownMenu.Item class="dw-menu-item" onSelect={copyAsMarkdown}>
                  <ClipboardCopy size={15} /> {$uiText("detail.copyMarkdown")}
                </DropdownMenu.Item>
                {#if !item.archived_at}
                  <DropdownMenu.Item class="dw-menu-item" onSelect={doDuplicate}>
                    <Files size={15} /> {$uiText("detail.duplicate")}
                  </DropdownMenu.Item>
                {/if}
                {#if moveTargets.length && !item.archived_at}
                  <DropdownMenu.Item class="dw-menu-item" onSelect={() => (movePickerOpen = true)}>
                    <FolderInput size={15} /> {$t("drawer.move")}
                  </DropdownMenu.Item>
                {/if}
                {#if me?.kind === "human" && !item.archived_at}
                  {#if item.locked_at}
                    <!-- Opent de ruimte-keuze in de banner (BETON-338) i.p.v.
                         direct te ontgrendelen. NB: nooit `onSelect={doUnlock}` —
                         bits-ui geeft het event mee, dat zou als `headroom`
                         binnenkomen. -->
                    <DropdownMenu.Item
                      class="dw-menu-item"
                      onSelect={() => (unlockMenuOpen = true)}
                    >
                      <LockOpen size={15} /> {$t("drawer.unlock")}
                    </DropdownMenu.Item>
                  {:else}
                    <DropdownMenu.Item class="dw-menu-item" onSelect={() => (confirmLock = true)}>
                      <Lock size={15} /> {$t("drawer.lock")}
                    </DropdownMenu.Item>
                  {/if}
                {/if}
                {#if item.archived_at}
                  <DropdownMenu.Item class="dw-menu-item" onSelect={doRestore}>
                    <ArchiveRestore size={15} /> {$uiText("detail.restoreArchived")}
                  </DropdownMenu.Item>
                {:else}
                  <DropdownMenu.Item class="dw-menu-item" onSelect={() => (confirmArchive = true)}>
                    <Archive size={15} /> {$t("drawer.archive")}
                  </DropdownMenu.Item>
                {/if}
                <DropdownMenu.Item class="dw-menu-item danger" onSelect={() => (confirmDelete = true)}>
                  <Trash2 size={15} /> {$uiText("ui.remove")}
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
          <button class="icon-btn dw-close" title={$t("drawer.close")} onclick={tryClose}>
            <X size={19} />
          </button>
        </div>
      </header>

      {#if confirmArchive}
        <ConfirmBar
          role="alertdialog"
          ariaLabel={$t("drawer.archiveConfirm")}
          focus
          message={$uiText("detail.archive", {ref:item.ref})}
          confirmLabel={$t("drawer.yesArchive")}
          onconfirm={doArchive}
          oncancel={() => (confirmArchive = false)}
        />
      {/if}

      {#if confirmLock}
        <ConfirmBar
          role="alertdialog"
          ariaLabel={$uiText("ui.confirmLock")}
          focus
          message={$uiText("detail.lock", {ref:item.ref})}
          confirmLabel={$uiText("ui.yesLock")}
          onconfirm={doLock}
          oncancel={() => (confirmLock = false)}
        />
      {/if}

      <!-- BETON-302: het slot moet zichtbaar zijn zonder het ⋯-menu te openen —
           anders is "waarom reageert er niemand?" een raadsel. -->
      {#if item.locked_at}
        <div class="lock-banner">
          <Lock size={15} />
          <span>
            {$uiText("detail.locked")}
            {#if me?.kind === "human"}{$uiText("detail.resume")}{/if}
          </span>
          {#if me?.kind === "human"}
            <!-- BETON-338: niet meteen ontgrendelen, eerst kiezen hoeveel
                 ruimte het gesprek krijgt — anders is het altijd 5. -->
            {#if unlockMenuOpen}
              <span class="unlock-choice">
                <span class="unlock-label">{$uiText("ui.headroom")}</span>
                {#each [5, 10, 20] as n}
                  <button class="sm" onclick={() => doUnlock(n)}>{n}</button>
                {/each}
                <button class="sm" onclick={() => (unlockMenuOpen = false)}>{$t("drawer.cancel")}</button>
              </span>
            {:else}
              <button class="sm" onclick={() => (unlockMenuOpen = true)}>{$uiText("detail.unlock")}</button>
            {/if}
          {/if}
        </div>
      {/if}
      {#if confirmDelete}
        <ConfirmBar
          danger
          role="alertdialog"
          ariaLabel={$t("drawer.deleteConfirm")}
          focus
          message={$uiText("detail.delete", {ref:item.ref})}
          confirmLabel={$t("drawer.yesDelete")}
          confirmClass="danger"
          onconfirm={doDelete}
          oncancel={() => (confirmDelete = false)}
        />
      {/if}
      {#if confirmClose}
        <ConfirmBar
          role="alertdialog"
          ariaLabel={$uiText("ui.confirmClose")}
          focus
          message={$uiText("detail.unsent")}
          confirmLabel={$uiText(pendingNav ? "detail.continueAnyway" : "detail.closeAnyway")}
          cancelLabel={$uiText("ui.stay")}
          onconfirm={forceClose}
          oncancel={() => { confirmClose = false; pendingNav = null; }}
        />
      {/if}
      {#if movePickerOpen && moveTargets.length}
        <ConfirmBar
          role="group"
          ariaLabel={$t("drawer.move")}
          focus
          message={$uiText("detail.move")}
          oncancel={() => (movePickerOpen = false)}
        >
          <Select
            action
            ariaLabel={$t("drawer.moveOther")}
            disabled={busy}
            value=""
            options={[
              { value: "", label: $uiText("detail.chooseProject") },
              ...moveTargets.map((p) => ({ value: p.key, label: `${p.key} — ${p.name}` })),
            ]}
            onchange={(v) => {
              if (v) {
                moveTarget = v;
                movePickerOpen = false;
                confirmMove = true;
              }
            }}
          />
        </ConfirmBar>
      {/if}
      {#if confirmMove}
        <ConfirmBar
          role="alertdialog"
          ariaLabel={$t("drawer.moveConfirm")}
          focus
          message={$uiText("detail.moveQuestion", {project:moveTarget})}
          confirmLabel={$uiText("ui.move")}
          onconfirm={doMove}
          oncancel={() => { confirmMove = false; moveTarget = ""; }}
        />
      {/if}
      {#if error}<div class="dw-error"><ErrorNote message={error} onRetry={load} /></div>{/if}

      <div class="dw-cols">
        <div class="dw-title-area">
          {#if editingTitle}
            <!-- svelte-ignore a11y_autofocus -->
            <input
              class="title-edit"
              bind:value={titleDraft}
              autofocus
              onblur={saveTitle}
              onkeydown={(e) => e.key === "Enter" && saveTitle()}
            />
          {:else}
            <h2
              class="dw-title editable"
              role="button"
              tabindex="0"
              title={$uiText("ui.clickEdit")}
              onclick={startTitle}
              onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); startTitle(); } }}
            >{item.title}</h2>
          {/if}
        </div>

        <aside class="dw-rail">
          <!-- BETON-414, laag 1 — de drie mutaties waarvoor de drawer opengaat.
               Sticky op ≥1024px (zie CSS) zodat ze bereikbaar blijven op een
               venster waarop de rail langer is dan het beeld. -->
          <div class="rail-actions">
            <div class="rail-seg">
              <span class="rail-head">{$t("drawer.status")}</span>
              <SegmentedControl
                ariaLabel={$t("drawer.status")}
                options={stateOpts}
                value={item.state}
                disabled={busy}
                onchange={(v) => patch({ state: v })}
              />
            </div>
            <div class="rail-seg">
              <span class="rail-head">{$uiText("ui.workload")}</span>
              <SegmentedControl
                ariaLabel={$uiText("ui.workload")}
                options={workloadOpts}
                value={item.workload}
                disabled={busy}
                onchange={(v) => patch({ workload: v })}
              />
            </div>

            <!-- BETON-243: toewijzen in één klik — de select staat altijd open
                 i.p.v. eerst een samenvattings-chip die je moet uitklappen. -->
            <div class="rail-seg">
              <span class="rail-head">{$uiText("ui.assigned")}</span>
              <AssigneeSelect
                class="rail-select"
                ariaLabel={$uiText("ui.assignedTo")}
                value={item.assignee ?? ""}
                {users}
                {me}
                disabled={busy}
                onchange={(v) => patch({ assignee: v })}
              />
              {#if triageNote}
                <p class="triage-pending" role="status">{triageNote}</p>
              {/if}
              {#if quickHandoffs.length}
                <div class="quick-handoffs" aria-label={$uiText("detail.handoff")}>
                  {#each quickHandoffs as target (target.handle)}
                    <button type="button" disabled={busy} onclick={() => patch({ assignee: target.handle })}>{target.label}</button>
                  {/each}
                </div>
              {/if}
            </div>
          </div>

          <!-- BETON-414, laag 2 — de overige eigenschappen als compacte lijst:
               label links, waarde rechts, één regel per eigenschap. Onder
               1024px staat die lijst dicht achter één "Eigenschappen"-knop
               (zuiver CSS-gated: knop én .collapsed gelden alleen daar), zodat
               op een telefoon de omschrijving vlak onder de acties begint. -->
          <button
            class="rail-props-toggle"
            type="button"
            aria-expanded={propsOpen}
            onclick={() => (propsOpen = !propsOpen)}
          >
            {#if propsOpen}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}
            {$uiText("detail.properties")}
          </button>

          <div class="rail-props" class:collapsed={!propsOpen}>
            {#if railProps.has("milestone")}
              <div class="prop-row">
                <button
                  class="prop-line"
                  aria-expanded={expandedProp === "milestone"}
                  onclick={() => toggleProp("milestone")}
                >
                  <span class="prop-label">{railProps.get("milestone").label}</span>
                  <span class="prop-val" class:prop-empty={railProps.get("milestone").empty}>
                    {railProps.get("milestone").text}
                  </span>
                </button>
                {#if expandedProp === "milestone"}
                  <Select
                    class="rail-select"
                    ariaLabel="Milestone"
                    value={item.milestone ?? ""}
                    disabled={busy}
                    options={[
                      { value: "", label: $uiText("detail.noMilestone") },
                      ...milestones.map((m) => ({ value: m.name, label: m.name })),
                    ]}
                    onchange={(v) => patch({ milestone: v })}
                  />
                {/if}
              </div>
            {/if}

            <div class="prop-row">
              <!-- BETON-415: een lege einddatum/uitstel las als grijze DATA naast
                   echte <select>'s met chevron — nergens te zien dat een klik een
                   datumveld opent. Leeg krijgt nu dezelfde ghost-affordance als de
                   andere bewerkbare rail-rijen (icoon + "+ label"); gezet blijft de
                   waarde + de bestaande wissen-link. -->
              <button class="prop-line" aria-expanded={expandedProp === "due"} onclick={() => toggleProp("due")}>
                <span class="prop-label">{railProps.get("due").label}</span>
                <span class="prop-val">
                  {#if railProps.get("due").empty}
                    <span class="prop-add"><CalendarPlus size={13} /> {$uiText("ui.date")}</span>
                  {:else}
                    {railProps.get("due").text}
                  {/if}
                </span>
              </button>
              {#if expandedProp === "due"}
                <span class="prop-defer">
                  <input
                    type="date"
                    aria-label={$t("drawer.due")}
                    disabled={busy}
                    value={(item.due_date || "").slice(0, 10)}
                    onchange={(e) => patch({ due_date: e.currentTarget.value || null })}
                  />
                  {#if item.due_date}
                    <button class="link" title={$uiText("ui.clearDue")} disabled={busy} onclick={() => patch({ due_date: null })}>{$uiText("ui.clear")}</button>
                  {/if}
                </span>
              {/if}
            </div>

            <div class="prop-row">
              <button class="prop-line" aria-expanded={expandedProp === "defer"} onclick={() => toggleProp("defer")}>
                <span class="prop-label">{railProps.get("defer").label}</span>
                <span class="prop-val">
                  {#if railProps.get("defer").empty}
                    <span class="prop-add"><CalendarPlus size={13} /> {$uiText("detail.defer")}</span>
                  {:else}
                    {railProps.get("defer").text}
                  {/if}
                </span>
              </button>
              {#if expandedProp === "defer"}
                <span class="prop-defer">
                  <input
                    type="date"
                    aria-label={$t("drawer.defer")}
                    disabled={busy}
                    value={(item.deferred_until || "").slice(0, 10)}
                    onchange={(e) => patch({ deferred_until: e.currentTarget.value || null })}
                  />
                  {#if item.deferred_until}
                    <button class="link" title={$uiText("ui.clearDefer")} disabled={busy} onclick={() => patch({ deferred_until: null })}>{$uiText("ui.clear")}</button>
                  {/if}
                </span>
              {/if}
            </div>

            <!-- Chips-regels (labels/subtaken/relaties/volgers) lopen bewust NIET
                 via `expandedProp`: die is enkelvoudig, en labelPickerOpen /
                 relAddOpen / decomposeProposal houden hun eigen open-state. Een
                 klik op een andere rij zou anders een half getypte relatie of
                 een openstaand opknip-voorstel wegklappen. De regel breekt af
                 naar een tweede regel i.p.v. een eigen blok met kop te worden. -->
            <div class="prop-row">
              <div class="prop-line static">
                <span class="prop-label">{railProps.get("labels").label}</span>
                <div class="prop-val dchips">
                  {#if railProps.get("labels").empty}
                    <span class="prop-empty">{railProps.get("labels").text}</span>
                  {/if}
                  {#each item.labels || [] as name (name)}
                    <Chip tone="label" hue={labelHueOf(name, projectKeyOfRef(item?.ref))} removable onremove={() => toggleLabel(name)}>{name}</Chip>
                  {/each}
                  <button
                    class="label-add"
                    type="button"
                    title={$t("drawer.addLabel")}
                    aria-label={$t("drawer.addLabel")}
                    aria-expanded={labelPickerOpen}
                    disabled={busy}
                    onclick={() => { labelPickerOpen = !labelPickerOpen; labelQuery = ""; }}
                  >
                    <Plus size={14} />
                  </button>
                </div>
              </div>
              {#if labelPickerOpen}
                <div class="label-picker">
                  {#if projectLabels.length}
                    <input class="label-search" placeholder={$t("drawer.searchLabel")} bind:value={labelQuery} />
                    <div class="label-options">
                      {#each labelList as l (l.name)}
                        <Chip
                          tone="label"
                          hue={labelHueOf(l.name)}
                          selected={l.assigned}
                          disabled={busy}
                          onclick={() => toggleLabel(l.name)}
                        >
                          {l.name}
                        </Chip>
                      {/each}
                      {#if !labelList.length}<span class="muted label-empty">{$t("drawer.noMatch")}</span>{/if}
                    </div>
                  {:else}
                    <span class="muted label-empty">{$t("drawer.noLabels")}</span>
                  {/if}
                </div>
              {/if}
            </div>

            <!-- BETON-248: subtaken in de rail; sinds BETON-414 als regel, met
                 de twee aanmaak-knoppen achter het "+"-affordance. Een lopend
                 opknip-voorstel staat er los van (en blijft dus staan). -->
            <div class="prop-row">
              <div class="prop-line static">
                <span class="prop-label">
                  {railProps.get("subtasks").label}
                  {#if item.children_total}
                    <span class="subtask-progress" class:done={item.children_done === item.children_total}>
                      {item.children_done}/{item.children_total}
                    </span>
                  {/if}
                </span>
                <div class="prop-val dchips">
                  {#if railProps.get("subtasks").empty}
                    <span class="prop-empty">{railProps.get("subtasks").text}</span>
                  {/if}
                  {#if decomposeProposal == null}
                    <button
                      class="label-add"
                      type="button"
                      title={$uiText("ui.subtasks")}
                      aria-label={$uiText("ui.subtasks")}
                      aria-expanded={expandedProp === "subtasks"}
                      onclick={() => toggleProp("subtasks")}
                    >
                      <Plus size={14} />
                    </button>
                  {/if}
                </div>
              </div>
              <RelatedList groups={subtaskList} {states} {onopen} />
              {#if decomposeProposal == null}
                {#if expandedProp === "subtasks"}
                  <div class="subtask-actions">
                    <button
                      class="sm rail-full-btn"
                      onclick={() => onnew?.({ parent: item.ref, milestone: item.milestone })}
                      title={$uiText("ui.addSubtask")}
                    >
                      <Plus size={13} /> {$t("drawer.subtask")}
                    </button>
                    {#if !item.children?.length}
                      <button
                        class="sm rail-full-btn"
                        onclick={runDecompose}
                        disabled={decomposing}
                        title={$t("drawer.splitAi")}
                      >
                        <Scissors size={13} /> {decomposing ? $uiText("detail.splitBusy") : $uiText("detail.split")}
                      </button>
                    {/if}
                  </div>
                {/if}
              {:else if decomposeProposal.should_decompose && decomposeProposal.subtasks.length}
                {#if decomposeProposal.reason}<p class="muted decompose-reason">{decomposeProposal.reason}</p>{/if}
                <ol class="decompose-list">
                  {#each decomposeProposal.subtasks as s}
                    <li>
                      <strong>{s.title}</strong>
                      {#if s.description_md}<span class="muted"> — {s.description_md}</span>{/if}
                    </li>
                  {/each}
                </ol>
                <ConfirmBar
                  confirmLabel={$uiText("detail.createSubtasks", {count: decomposeProposal.subtasks.length})}
                  onconfirm={applyDecompose}
                  oncancel={cancelDecompose}
                />
              {:else}
                <p class="muted">
                  {$uiText("detail.noSplit")}: {decomposeProposal.reason || $uiText("detail.smallEnough")}
                </p>
                <button class="sm" onclick={cancelDecompose}>{$t("drawer.close")}</button>
              {/if}
            </div>

            <!-- BETON-248: relaties in de rail; de add-UI stapelt verticaal. -->
            <div class="prop-row">
              <div class="prop-line static">
                <span class="prop-label">{railProps.get("relations").label}</span>
                <div class="prop-val rel-groups">
                  {#if railProps.get("relations").empty}
                    <span class="prop-empty">{railProps.get("relations").text}</span>
                  {/if}
                </div>
              </div>
              <RelatedList groups={relationList} {states} busy={busy} {onopen} onremove={(type, target) => (confirmRelation = { type, target })} />
              {#if confirmRelation}
                <ConfirmBar
                  inline
                  role="alertdialog"
                  ariaLabel={$uiText("ui.confirmUnlink")}
                  focus
                  message={$uiText("detail.unlink", {ref:confirmRelation.target})}
                  confirmLabel={$uiText("ui.yesUnlink")}
                  confirmClass="danger"
                  cancelLabel={$uiText("ui.no")}
                  confirmDisabled={busy}
                  onconfirm={() => {
                    const { type, target } = confirmRelation;
                    confirmRelation = null;
                    removeRelation(type, target);
                  }}
                  oncancel={() => (confirmRelation = null)}
                />
              {/if}
              <!-- BETON-414: de compacte knop is de ENIGE affordance, ook als
                   er al relaties liggen. Voorheen gold `empty.relations &&
                   !relAddOpen`, dus een ticket met vijf relaties kreeg
                   permanent een select + tekstveld + knop die niemand vroeg. -->
              {#if !relAddOpen}
                <button class="add-affordance" type="button" onclick={openRelAdd}>
                  <Plus size={14} /> {$uiText("ui.addRelation")}
                </button>
              {:else}
              <div class="rel-add">
                <Select
                  ariaLabel={$uiText("ui.relationType")}
                  bind:value={relType}
                  options={RELATION_TYPES.map((t) => ({ value: t, label: relationLabel(t, $locale) }))}
                />
                <div class="rel-box">
                  <input
                    bind:this={relInput}
                    class="rel-target"
                    placeholder={$uiText("detail.relationHint")}
                    value={relTarget}
                    oninput={onRelInput}
                    onkeydown={onRelKeydown}
                    role="combobox"
                    aria-expanded={relMatches.length > 0}
                    aria-controls="rel-suggest"
                    autocomplete="off"
                  />
                  <PickerSuggestions id="rel-suggest" tickets={relMatches} ticketActive={relActive} onticket={pickRelTarget} />
                </div>
                <button class="sm rail-full-btn" disabled={busy} onclick={addRelation}>{$t("drawer.addRelation")}</button>
              </div>
              {/if}
            </div>

            <!-- BETON-245: volgers (afgeleide subscribers-union) met mute-kruisje.
                 BETON-369: mens-only knop om dit ticket zelf te volgen. -->
            <div class="prop-row">
              <div class="prop-line static">
                <span class="prop-label">{railProps.get("followers").label}</span>
                <div class="prop-val dchips follower-row">
                  {#if railProps.get("followers").empty}
                    <span class="prop-empty">{railProps.get("followers").text}</span>
                  {/if}
                  {#each followerRow.shown as handle (handle)}
                    <span title={`@${handle}`}><Avatar {handle} avatarUrl={avatarMap.get(handle)} size={22} /></span>
                  {/each}
                  {#if followerRow.extra}<span class="follower-more">+{followerRow.extra}</span>{/if}
                  {#if me?.kind === "human"}
                    <Select
                      class="follow-select"
                      ariaLabel={$uiText("ui.notifications")}
                      title={$uiText("detail.followHint")}
                      value={selfFollow.state === "muted" ? "mute" : selfFollow.state === "following" ? "follow" : "normal"}
                      disabled={busy}
                      options={followChoices($locale)}
                      onchange={applyFollowChoice}
                    />
                  {/if}
                </div>
              </div>
            </div>

            {#if item.created_at}
              <div class="prop-row">
                <div class="prop-line static">
                  <span class="prop-label">{$uiText("detail.created")}</span>
                  <span class="prop-val" title={absoluteTime(item.created_at, $locale)}>{formatTimestamp(item.created_at, undefined, $locale)}</span>
                </div>
              </div>
            {/if}
            {#if item.updated_at && item.updated_at !== item.created_at}
              <div class="prop-row">
                <div class="prop-line static">
                  <span class="prop-label">{$uiText("ui.changed")}</span>
                  <span class="prop-val" title={absoluteTime(item.updated_at, $locale)}>{formatTimestamp(item.updated_at, undefined, $locale)}</span>
                </div>
              </div>
            {/if}
          </div>
        </aside>

        <div class="dw-main">
          <section class="dw-section" onclick={onTicketClick} onkeydown={onTicketKeydown} role="presentation">
            <!-- BETON-416: geen "OMSCHRIJVING"-kop meer — dit is de eerste
                 sectie en het enige prozablok, de kop voegde niets toe naast
                 zestien andere. De actieknoppen (Verrijk/Afbeelding) blijven,
                 nu in een kale rechts-uitgelijnde balk i.p.v. naast een label. -->
            {#if !editingDesc && enrichProposal == null}
              <div class="section-actions">
                <!-- BETON-423: aanmaak- (en wijzig)datum in de lege ruimte links
                     van de knoppen; de rail onderaan houdt ze ook. -->
                {#if item.created_at}
                  <span class="section-meta">
                    <span title={absoluteTime(item.created_at, $locale)}>{$uiText("detail.created")} {formatTimestamp(item.created_at, undefined, $locale)}</span>
                    {#if item.updated_at && item.updated_at !== item.created_at}
                      · <span title={absoluteTime(item.updated_at, $locale)}>{$uiText("detail.modified")} {formatTimestamp(item.updated_at, undefined, $locale)}</span>
                    {/if}
                  </span>
                {/if}
                <button class="sm" onclick={runEnrich} disabled={enriching} title={$t("drawer.enrich")}>
                  <Sparkles size={13} /> {enriching ? $uiText("detail.enrichBusy") : $uiText("detail.enrich")}
                </button>
                <button
                  class="sm"
                  type="button"
                  disabled={uploading}
                  title={$uiText("ui.addImageDirect")}
                  onclick={() => descQuickFileInput?.click()}
                >
                  <ImagePlus size={13} /> {uploading ? $uiText("detail.uploadBusy") : $uiText("detail.image")}
                </button>
                <input
                  bind:this={descQuickFileInput}
                  type="file"
                  accept="image/*,text/*,application/json,application/pdf,.log,.md,.csv"
                  multiple
                  class="visually-hidden"
                  tabindex="-1"
                  onchange={quickAddDescImage}
                />
              </div>
            {/if}
            {#if enrichNotice != null && enrichProposal == null && !editingDesc}
              <div class="enrich-notice">
                <p>{enrichNotice}</p>
                <button class="sm" onclick={() => (enrichNotice = null)}>{$t("drawer.close")}</button>
              </div>
            {/if}
            {#if enrichProposal != null}
              <div class="enrich-panel">
                <p class="muted enrich-hint">{$uiText("ui.proposalHint")}</p>
                <DiffView segments={enrichDiff} variant="surface" />
                {#if enrichLabels.length}
                  <div class="enrich-labels">
                    <span class="muted enrich-hint">{$uiText("detail.labelsHint")}</span>
                    <div class="dchips">
                      {#each enrichLabels as name (name)}
                        <Chip
                          tone="label"
                          hue={labelHueOf(name, projectKeyOfRef(item?.ref))}
                          selected={enrichLabelsPicked.includes(name)}
                          onclick={() => toggleEnrichLabel(name)}
                        >
                          {name}
                        </Chip>
                      {/each}
                    </div>
                  </div>
                {/if}
                <div class="btn-row">
                  <button class="sm" onclick={cancelEnrich}>{$t("drawer.cancel")}</button>
                  <button class="primary sm" onclick={acceptEnrich}>{$t("drawer.saveProposal")}</button>
                </div>
              </div>
            {:else if editingDesc}
              <div class="desc-editor">
                <MarkdownEditor
                  bind:textareaRef={descTextarea}
                  value={descDraft}
                  rows={6}
                  placeholder={$uiText("detail.markdownHint")}
                  {knownHandles}
                  {projectKeys}
                  oninput={onDescInput}
                  onsubmit={saveDesc}
                  onpaste={(e) => handleImageDrop(e, "desc")}
                  ondragover={(e) => e.preventDefault()}
                  ondrop={(e) => handleImageDrop(e, "desc")}
                  onblur={onDescBlur}
                  onkeydown={onDescKeydown}
                >
                  {#snippet dropdown()}
                    <PickerSuggestions mentions={descMentionMatches} tickets={descHashMatches} mentionActive={descMentionActive} ticketActive={descHashActive} onmention={pickDescMention} onticket={pickDescHashRef} />
                  {/snippet}
                </MarkdownEditor>
                <input
                  bind:this={descFileInput}
                  type="file"
                  accept="image/*,text/*,application/json,application/pdf,.log,.md,.csv"
                  multiple
                  class="visually-hidden"
                  tabindex="-1"
                  onchange={(e) => handleImageFileInput(e, "desc", descTextarea)}
                />
                <div class="btn-row">
                  <div class="upload-actions">
                    <button
                      class="sm img-upload-btn"
                      type="button"
                      disabled={uploading}
                      title={$uiText("ui.addImage")}
                      onclick={() => descFileInput?.click()}
                    >
                      <ImagePlus size={14} /> {$uiText("detail.image")}
                    </button>
                    <span class="muted upload-hint">{uploading ? $uiText("detail.uploadBusy") : $uiText("detail.drop")}</span>
                  </div>
                  <button
                    class="sm"
                    onclick={() => {
                      editingDesc = false;
                      descMentionMatches = [];
                      descHashMatches = [];
                    }}>{$t("drawer.cancel")}</button
                  >
                  <button class="primary sm" onclick={saveDesc}>{$uiText("ui.save")}</button>
                </div>
              </div>
            {:else if item.description_md}
              <!-- eslint-disable-next-line svelte/no-at-html-tags — renderMarkdown escapet -->
              <!-- BETON-415: geen `title` meer — dat tooltipje verscheen midden
                   in een alinea omdat het hele blok het hitgebied is. De
                   bestaande hover-achtergrond (.desc.editable:hover) blijft de
                   enige affordance. -->
              <div
                class="desc md editable"
                role="button"
                tabindex="0"
                onclick={onDescClick}
                use:lightboxClicks={openLightbox}
                onkeydown={onDescEditKeydown}
              >{@html renderMarkdown(item.description_md, knownHandles, projectKeys)}</div>
            {:else}
              <button class="empty-edit" onclick={startDesc}>{$uiText("ui.emptyDescription")}</button>
            {/if}
          </section>

          <!-- Guardrail (BETON-420): bindende kennis die niet in een
               regressietest past. Altijd zichtbaar zodra hij actief is — ook
               voor een agent die meeleest, want hij moet hem naleven. Zetten,
               wijzigen en opheffen is mens-only; een agent stelt voor via de
               MCP-tool `propose_guardrail`, niet vanuit dit scherm.
               BETON-422: een voorstel staat als CONCEPT naast de actieve
               versie. Een agent mag het lezen (hij moet weten dat er een
               wijziging aankomt) maar niet bedienen — vandaar het concept in de
               poort hieronder en de knoppen achter de mens-poort. -->
          {#if guardrail.active || guardrailProposal || editingGuardrail}
            <section class="dw-section">
              <SectionHead>
                Guardrail
                {#if me?.kind === "human" && !editingGuardrail}
                  <!-- Eén groep: SectionHead verdeelt zijn kinderen met
                       space-between, dus twee losse knoppen zetten "Wijzigen"
                       midden in de kop. -->
                  <span class="guardrail-head-actions">
                    <button class="sm" onclick={startGuardrailEdit}>
                      {guardrail.active ? $uiText("ui.change") : $uiText("guardrail.set")}
                    </button>
                    {#if guardrail.active}
                      <button
                        class="sm danger-quiet"
                        onclick={() => (confirmLiftGuardrail = true)}
                      >{$uiText("ui.lift")}</button>
                    {/if}
                  </span>
                {/if}
              </SectionHead>

              {#if guardrail.active && !editingGuardrail}
                <div class="guardrail-card">
                  <div class="guardrail-head">
                    <ShieldAlert size={15} strokeWidth={2.5} />
                    <span>{$uiText("guardrail.applies")}</span>
                  </div>
                  <p class="guardrail-text">{guardrail.text}</p>
                  <div class="guardrail-meta">
                    <span class="guardrail-scope">
                      {#if guardrail.scope.length}
                        {#each guardrail.scope as name (name)}
                          <Chip tone="label" hue={labelHueOf(name, projectKeyOfRef(item?.ref))}>{name}</Chip>
                        {/each}
                      {:else}
                        <span class="muted">{scopeSummary(guardrail.scope, $locale)}</span>
                      {/if}
                    </span>
                    <span class="guardrail-review" class:overdue={guardrail.overdue}>
                      {$uiText(guardrail.overdue ? "guardrail.overdue" : "guardrail.reviewOn", { date: guardrail.reviewBy })}
                    </span>
                    {#if guardrail.setBy}
                      <span class="muted">
                        <!-- Als expressie i.p.v. {#if}: Svelte strípt de
                             spatie aan het begin van een blok ("@person· …"). -->
                        {$uiText("guardrail.by", { handle: guardrail.setBy })}{guardrail.setAt ? ` · ${formatTimestamp(guardrail.setAt, undefined, $locale)}` : ""}
                      </span>
                    {/if}
                  </div>
                  {#if !guardrail.scope.length && me?.kind === "human"}
                    <!-- Projectbreed bezet een van de vijf plekken; scopen is
                         daarom één klik. Zie de toelichting bij
                         startGuardrailEdit waarom dit niet alleen ná een
                         voorstel-activatie verschijnt. -->
                    <button class="sm guardrail-scope-hint" onclick={startGuardrailEdit}>
                      {$uiText("ui.projectScope")}
                    </button>
                  {/if}
                </div>
              {/if}

              <!-- Het concept: herkenbaar ánders dan een actieve guardrail —
                   gestippelde neutrale rand i.p.v. de rode lijn, want er geldt
                   hier nog niets. Geen overdue-accent op de reviewdatum: die
                   klok loopt pas na goedkeuren. -->
              {#if guardrailProposal && !editingGuardrail}
                <div class="guardrail-concept">
                  <div class="guardrail-concept-head">
                    <ShieldQuestionMark size={15} strokeWidth={2.5} />
                    <span>
                      {$uiText("guardrail.proposal")}{guardrailProposal.proposedBy ? $uiText("guardrail.proposedBy", { handle: guardrailProposal.proposedBy }) : ""}{guardrailProposal.proposedAt ? ` · ${formatTimestamp(guardrailProposal.proposedAt, undefined, $locale)}` : ""}
                    </span>
                  </div>

                  {#if guardrailProposal.isLift}
                    <p class="guardrail-text">{$uiText("ui.liftProposal")}</p>
                    <p class="guardrail-concept-reason">{guardrailProposal.reason}</p>
                  {:else if guardrailProposalDiff}
                    <DiffView
                      segments={guardrailProposalDiff}
                      variant="surface"
                      ariaLabel={$uiText("ui.activeGuardrail")}
                    />
                  {:else}
                    <p class="guardrail-text">{guardrailProposal.text}</p>
                    <div class="guardrail-meta">
                      <span class="guardrail-scope">
                        {#if guardrailProposal.scope.length}
                          {#each guardrailProposal.scope as name (name)}
                            <Chip tone="label" hue={labelHueOf(name, projectKeyOfRef(item?.ref))}>{name}</Chip>
                          {/each}
                        {:else}
                          <span class="muted">{scopeSummary(guardrailProposal.scope, $locale)}</span>
                        {/if}
                      </span>
                      <span class="muted">{proposalReviewLabel(guardrailProposal.reviewBy, undefined, $locale)}</span>
                    </div>
                  {/if}

                  <span class="guardrail-concept-note">
                    {$uiText("guardrail.concept")}
                  </span>

                  {#if me?.kind === "human"}
                    <div class="btn-row">
                      <button class="primary sm" onclick={doApproveGuardrail} disabled={busy}>
                        {$uiText("ui.approve")}
                      </button>
                      {#if !guardrailProposal.isLift}
                        <button class="sm" onclick={startGuardrailEditFromProposal}>
                          {$uiText("ui.change")}
                        </button>
                      {/if}
                      <button
                        class="sm danger-quiet"
                        onclick={() => (confirmRejectGuardrail = true)}
                      >{$uiText("ui.reject")}</button>
                    </div>
                  {/if}
                </div>
              {/if}

              {#if confirmRejectGuardrail}
                <ConfirmBar
                  message={$uiText("detail.reject")}
                  danger
                  role="alertdialog"
                  ariaLabel={$uiText("ui.rejectProposal")}
                  focus
                  confirmLabel={$uiText("ui.yesReject")}
                  confirmClass="danger"
                  onconfirm={doRejectGuardrail}
                  oncancel={() => (confirmRejectGuardrail = false)}
                />
              {/if}

              {#if confirmLiftGuardrail}
                <ConfirmBar
                  message={$uiText("detail.lift")}
                  danger
                  role="alertdialog"
                  ariaLabel={$uiText("ui.liftGuardrail")}
                  focus
                  confirmLabel={$uiText("ui.yesLift")}
                  confirmClass="danger"
                  onconfirm={doLiftGuardrail}
                  oncancel={() => (confirmLiftGuardrail = false)}
                />
              {/if}

              {#if editingGuardrail}
                <div class="guardrail-editor">
                  <AutoTextarea
                    rows="6"
                    bind:value={guardrailDraft}
                    placeholder={$uiText("guardrail.placeholder")}
                    onsubmit={() => { if (!busy && guardrailCheck.ok) saveGuardrail(); }}
                  />
                  <div class="guardrail-formrow">
                    <span
                      class="guardrail-count"
                      class:over={guardrailDraft.trim().length > GUARDRAIL_MAX_CHARS}
                    >{guardrailDraft.trim().length} / {GUARDRAIL_MAX_CHARS}</span>
                    <label class="guardrail-date">
                      {$uiText("ui.reviewDate")}
                      <input type="date" bind:value={guardrailReviewDraft} />
                    </label>
                  </div>
                  <div class="guardrail-scope-edit">
                    <span class="muted">{$uiText("guardrail.scopeHint")}</span>
                    {#if projectLabels.length}
                      <input class="label-search" placeholder={$t("drawer.searchLabel")} bind:value={guardrailScopeQuery} />
                      <div class="label-options">
                        {#each guardrailScopeList as l (l.name)}
                          <Chip
                            tone="label"
                            hue={labelHueOf(l.name)}
                            selected={l.assigned}
                            disabled={busy}
                            onclick={() => toggleGuardrailScope(l.name)}
                          >
                            {l.name}
                          </Chip>
                        {/each}
                        {#if !guardrailScopeList.length}<span class="muted label-empty">{$t("drawer.noMatch")}</span>{/if}
                      </div>
                    {:else}
                      <span class="muted label-empty">{$t("drawer.noLabels")}</span>
                    {/if}
                  </div>
                  {#if !guardrailCheck.ok}
                    <!-- Altijd tonen zolang de invoer niet klopt: "Opslaan" is
                         dan disabled, en een disabled knop zonder reden laat de
                         gebruiker raden (leeg tekstveld is precies dat geval). -->
                    <span class="guardrail-hint">{guardrailCheck.error}</span>
                  {/if}
                  <div class="btn-row">
                    <button class="sm" onclick={() => (editingGuardrail = false)}>{$t("drawer.cancel")}</button>
                    <button
                      class="primary sm"
                      onclick={saveGuardrail}
                      disabled={busy || !guardrailCheck.ok}
                    >{$uiText(editingFromProposal ? "guardrail.approveChanges" : "guardrail.save")}</button>
                  </div>
                </div>
              {/if}
            </section>
          {/if}

          <!-- Plan/handover (BETON-218): apart veld, standaard ingeklapt en pas
               geladen bij uitklappen — het plan kan groot zijn en zit bewust niet
               in de item-serialisatie (alleen has_plan). -->
          {#if item.has_plan || editingPlan}
          <section class="dw-section" onclick={onTicketClick} onkeydown={onTicketKeydown} role="presentation">
            <SectionHead>
              Plan
              {#if item.has_plan && !editingPlan}
                <button class="sm" onclick={togglePlan}>
                  {showPlan ? $uiText("detail.hide") : $uiText("detail.show")}
                </button>
              {/if}
            </SectionHead>
            {#if editingPlan}
              <div class="plan-editor">
                <MarkdownEditor
                  value={planDraft}
                  rows={12}
                  {knownHandles}
                  {projectKeys}
                  oninput={(e) => (planDraft = e.currentTarget.value)}
                  onblur={onPlanBlur}
                  onsubmit={savePlan}
                />
                <div class="btn-row">
                  <button class="sm" onclick={() => (editingPlan = false)}>{$t("drawer.cancel")}</button>
                  <button class="primary sm" onclick={savePlan} disabled={busy}>{$uiText("ui.save")}</button>
                </div>
              </div>
            {:else if showPlan && item.has_plan}
              {#if planLoading}
                <Skeleton preset="lines" count={3} />
              {:else if planMd}
                <!-- eslint-disable-next-line svelte/no-at-html-tags — renderMarkdown escapet -->
                <!-- BETON-415: geen `title` — zelfde reden als bij de omschrijving.
                     BETON-416: géén .desc (het gevulde grijze vlak) meer — het plan
                     is voor de agent die het uitvoert, niet voor de mens die het
                     ticket beoordeelt (dat is de omschrijving), en moet er stiller
                     en ondergeschikt uitzien i.p.v. als gelijkwaardige muur tekst. -->
                <div
                  class="plan-body md editable"
                  role="button"
                  tabindex="0"
                  onclick={onPlanClick}
                  use:lightboxClicks={openLightbox}
                  onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); startPlanEdit(); } }}
                >{@html renderMarkdown(planMd, knownHandles, projectKeys)}</div>
              {/if}
            {/if}
          </section>
          {/if}

          <!-- BETON-459: lege Plan-/Guardrail-secties zijn één rustige regel
               met tekstlinks; zodra er iets is of wordt bewerkt, staat de
               volledige sectie er (BETON-242/420). Guardrail alleen voor mensen. -->
          {#each [emptyAddLinks({ hasPlan: item.has_plan, planEditing: editingPlan, guardrailVisible: guardrail.active || !!guardrailProposal || editingGuardrail, isHuman: me?.kind === "human" })] as links}
            {#if links.length}
              <div class="add-links">
                {#each links as l, i (l)}
                  {#if i > 0}<span aria-hidden="true">·</span>{/if}
                  <button class="add-link" onclick={l === "plan" ? startPlanEdit : startGuardrailEdit}>
                    + {l === "plan" ? "Plan" : "Guardrail"}
                  </button>
                {/each}
              </div>
            {/if}
          {/each}

          {#if attachments.length}
            <section class="dw-section">
              <SectionHead>{$uiText("ui.attachments")}</SectionHead>
              <div class="attachment-grid">
                {#each attachments as att (att.id)}
                  <div class="attachment-item">
                    <a
                      href={att.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={att.filename}
                      onclick={(e) => {
                        if (!isImageAttachment(att)) return;
                        e.preventDefault();
                        openLightbox({ src: att.url, alt: att.filename });
                      }}
                    >
                      {#if isImageAttachment(att)}
                        <img class="attachment-thumb" src={att.url} alt={att.filename} loading="lazy" />
                      {:else}
                        <!-- BETON-374: tekst/JSON/PDF hebben geen thumbnail en
                             worden door de backend als download geserveerd. -->
                        <span class="attachment-file">
                          <FileText size={16} />
                          <span class="attachment-file-name">{att.filename}</span>
                        </span>
                      {/if}
                    </a>
                    <button
                      class="sm attachment-insert"
                      type="button"
                      title={$uiText("ui.insertDescription")}
                      onclick={() => insertAttachmentInDesc(att)}
                    >
                      {$uiText("ui.insert")}
                    </button>
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          <!-- BETON-338/340: één definitie van de ontgrendel-affordance; hij
               hangt zowel onder de wachtende comment als onder de laatste
               comment van een gelockt ticket. Kopiëren zou de 5/10/20-lijst op
               drie plekken uit elkaar laten lopen. -->
          {#snippet unlockAffordance(hint)}
            {#if me?.kind === "human"}
              <div class="held-actions">
                {#if hint}<span class="muted">{hint}</span>{/if}
                {#if unlockMenuOpen}
                  <span class="unlock-choice">
                    <span class="unlock-label">{$uiText("ui.headroom")}</span>
                    {#each [5, 10, 20] as n}
                      <button class="sm" onclick={() => doUnlock(n)}>{n}</button>
                    {/each}
                    <button class="sm" onclick={() => (unlockMenuOpen = false)}>{$t("drawer.cancel")}</button>
                  </span>
                {:else}
                  <button class="sm" onclick={() => (unlockMenuOpen = true)}>
                    <LockOpen size={13} /> {$t("drawer.unlock")}
                  </button>
                {/if}
              </div>
            {/if}
          {/snippet}

          <section class="dw-section dw-timeline" onclick={onTicketClick} onkeydown={onTicketKeydown} role="presentation">
            <!-- BETON-416: geen "TIJDLIJN"-kop meer — een lijst zichtbare
                 reacties spreekt voor zich. Het Alles/Reacties-filter blijft,
                 in dezelfde kale rechts-uitgelijnde balk als bij Omschrijving. -->
            <div class="section-actions">
              <!-- BETON-415: soft i.p.v. pill — dit filtert alleen de WEERGAVE
                   (geen mutatie), dus geen volle accent-selectie. -->
              <SegmentedControl
                ariaLabel={$t("drawer.timeline")}
                variant="soft"
                options={TIMELINE_MODE_OPTS}
                value={timelineMode}
                onchange={setTimelineMode}
              />
            </div>
            <ul class="tl">
              {#each displayTimeline as entry (entry.key)}
                {#if entry.kind === "comment"}
                  {@const c = entry.comment}
                  {@const qs = questionState(c)}
                  <li id="cmt-{c.id}" class="tl-comment" class:cmt-long-open={collapseOf(c).collapsible && !collapseOf(c).collapsed} class:question={qs.isQuestion} class:answered={qs.isQuestion && qs.answered} class:withdrawn={qs.isQuestion && qs.withdrawn}>
                    {#if qs.isQuestion}
                      <span class="q-icon" aria-hidden="true"><MessageCircleQuestion size={20} /></span>
                    {:else}
                      <Avatar handle={c.author ?? "?"} avatarUrl={avatarMap.get(c.author)} size={28} />
                    {/if}
                    <div class="cmt-main">
                      <div class="cmt-meta">
                        <span class="cmt-author">{qs.isQuestion ? $uiText("detail.questionFrom", {author: c.author ?? "?"}) : `@${c.author ?? "?"}`}</span>
                        <span class="cmt-time" title={absoluteTime(c.created_at, $locale)}>{formatTimestamp(c.created_at, undefined, $locale)}</span>
                        {#if qs.isQuestion && qs.answered}<span class="q-tag">{$uiText("detail.answered")}</span>{/if}
                        {#if qs.isQuestion && qs.withdrawn}<span class="q-tag">{$uiText("detail.withdrawn")} {qs.withdrawnReason ?? ""}</span>{/if}
                        {#if me && c.author === me.handle && editingCommentId !== c.id}
                          <span class="cmt-actions">
                            <button class="icon-btn sm" title={$uiText("ui.edit")} onclick={() => startEditComment(c)}>
                              <Pencil size={13} />
                            </button>
                            <button class="icon-btn sm danger-quiet" title={$t("drawer.delete")} onclick={() => (confirmDeleteId = c.id)}>
                              <Trash2 size={13} />
                            </button>
                          </span>
                        {/if}
                      </div>
                      {#if editingCommentId === c.id}
                        <AutoTextarea
                          class="full"
                          bind:value={editCommentText}
                          rows="3"
                          onsubmit={saveEditComment}
                          onpaste={(e) => handleImageDrop(e, "editComment")}
                          ondragover={(e) => e.preventDefault()}
                          ondrop={(e) => handleImageDrop(e, "editComment")}
                        />
                        <div class="btn-row">
                          <button class="sm" onclick={() => (editingCommentId = null)}>{$t("drawer.cancel")}</button>
                          <button class="primary sm" onclick={saveEditComment}>{$uiText("ui.save")}</button>
                        </div>
                      {:else if confirmDeleteId === c.id}
                        <ConfirmBar
                          inline
                          role="alertdialog"
                          ariaLabel={$uiText("ui.deleteComment")}
                          focus
                          message={$uiText("detail.deleteComment")}
                          confirmLabel={$uiText("ui.yes")}
                          cancelLabel={$uiText("ui.no")}
                          onconfirm={() => doDeleteComment(c.id)}
                          oncancel={() => (confirmDeleteId = null)}
                        />
                      {:else}
                        <!-- eslint-disable-next-line svelte/no-at-html-tags — renderMarkdown escapet -->
                        {@const col = collapseOf(c)}
                        <div
                          class="cmt-body md"
                          class:cmt-collapsed={col.collapsed}
                          style:max-height={col.collapsed ? `${col.maxHeight}px` : null}
                          use:measureComment={{ id: c.id, body: c.body_md }}
                          use:lightboxClicks={openLightbox}
                        >{@html renderMarkdown(c.body_md, knownHandles, projectKeys)}</div>
                        {#if col.collapsible}
                          <button class="cmt-toggle" aria-expanded={!col.collapsed} onclick={() => toggleComment(c.id)}>
                            {col.collapsed ? $uiText("detail.showAll", { count: commentLineCount(c.body_md) }) : $uiText("detail.showLess")}
                          </button>
                        {/if}
                        {#if qs.isQuestion && qs.answered}
                          {@const chosen = qs.answerOptionIndex ?? matchedOptionIndex(qs.options, qs.answerText)}
                          <div class="q-answer">
                            {#if editingAnswerId === c.id}
                              <!-- Antwoord wijzigen (BETON-263/274): opties als
                                   snelkeuze én altijd een vrijtekst-veld. -->
                              {#if qs.options.length}
                                <div class="q-options">
                                  {#each qs.options as opt, i}
                                    <button class="q-opt-btn" class:chosen={i === chosen} disabled={answerBusy} onclick={() => saveAnswerEdit(c.id, optionAnswer(i))}>
                                      {opt}
                                    </button>
                                  {/each}
                                </div>
                              {/if}
                              <div class="q-freetext">
                                <AutoTextarea class="full" rows="2" aria-label={$uiText("ui.editAnswer")} bind:value={answerEditDraft}
                                  onsubmit={() => submitAnswerTextEdit(c.id)}
                                  oncancel={() => (editingAnswerId = null)}
                                  onpaste={(e) => handleImageDrop(e, "editAnswer")}
                                  ondragover={(e) => e.preventDefault()}
                                  ondrop={(e) => handleImageDrop(e, "editAnswer")}
                                />
                                <div class="btn-row">
                                  <button class="sm" onclick={() => (editingAnswerId = null)}>{$t("drawer.cancel")}</button>
                                  <button class="primary sm" disabled={answerBusy || !(answerEditDraft || "").trim()} onclick={() => submitAnswerTextEdit(c.id)}>
                                    {$uiText(answerBusy ? "detail.saving" : "detail.saveAnswer")}
                                  </button>
                                </div>
                              </div>
                            {:else}
                              <!-- BETON-274: bij een gekozen optie de opties tonen
                                   (gekozen gemarkeerd); bij een vrijtekst-antwoord
                                   (geen optie gekozen) de getypte tekst tonen. -->
                              {#if qs.options.length && chosen >= 0}
                                <div class="q-options">
                                  {#each qs.options as opt, i}
                                    <span class="q-opt" class:chosen={i === chosen}>
                                      {#if i === chosen}<Check size={13} />{/if}
                                      {opt}
                                    </span>
                                  {/each}
                                </div>
                              {:else if qs.answerText}
                                <!-- Markdown zoals een comment, anders blijft een geplakte
                                     afbeelding ruwe tekst (BETON-434). -->
                                <div class="q-answer-text md" use:lightboxClicks={openLightbox}>{@html renderMarkdown(qs.answerText, knownHandles, projectKeys)}</div>
                              {/if}
                              <div class="q-answer-meta">
                                <span class="q-answered-by">
                                  <CornerDownRight size={13} />
                                  {qs.answeredBy ? $uiText("detail.answeredBy", {author: qs.answeredBy}) : $uiText("detail.answered")}
                                </span>
                                {#if qs.editable && me}
                                  <button class="link sm q-edit-answer" disabled={answerBusy} onclick={() => startEditAnswer(c)}>{$uiText("ui.changeAnswer")}</button>
                                {/if}
                              </div>
                            {/if}
                          </div>
                        {:else if qs.isQuestion && !qs.withdrawn}
                          <div class="q-answer">
                            {#if qs.options.length}
                              <div class="q-options">
                                {#each qs.options as opt, i}
                                  <button class="q-opt-btn" disabled={answerBusy} onclick={() => pickOption(c.id, i)}>
                                    {opt}
                                  </button>
                                {/each}
                              </div>
                              {#if pendingOption && pendingOption.id === c.id}
                                <ConfirmBar
                                  inline
                                  role="alertdialog"
                                  ariaLabel={$uiText("ui.confirmAnswer")}
                                  focus
                                  message={$uiText("detail.answer", {answer:qs.options[pendingOption.index]})}
                                  confirmLabel={$uiText("ui.yesAnswer")}
                                  confirmDisabled={answerBusy}
                                  onconfirm={confirmOption}
                                  oncancel={() => (pendingOption = null)}
                                />
                              {/if}
                            {/if}
                            <div class="q-freetext">
                              <AutoTextarea
                                class="full"
                                rows="2"
                                aria-label={$uiText("ui.ownAnswer")}
                                onsubmit={() => submitTextAnswer(c.id)}
                                placeholder={$uiText("ui.ownAnswerHint")}
                                value={answerDrafts[c.id] ?? ""}
                                oninput={(e) => (answerDrafts = { ...answerDrafts, [c.id]: e.currentTarget.value })}
                                onpaste={(e) => handleImageDrop(e, "answer", c.id)}
                                ondragover={(e) => e.preventDefault()}
                                ondrop={(e) => handleImageDrop(e, "answer", c.id)}
                              />
                              <div class="btn-row">
                                <button
                                  class="primary sm"
                                  disabled={answerBusy || !(answerDrafts[c.id] || "").trim()}
                                  onclick={() => submitTextAnswer(c.id)}
                                >
                                  {$uiText(answerBusy ? "detail.sending" : "detail.sendAnswer")}
                                </button>
                              </div>
                            </div>
                          </div>
                        {/if}
                      {/if}
                      <!-- BETON-340: op een gelockt ticket hangt de ontgrendel-
                           actie onder de laatste comment — "bij de comment die
                           het slot triggerde", zoals gevraagd. Staat er iets in
                           de wacht, dan is die de laatste entry en hangt hij
                           daar (de tak hieronder). -->
                      {#if item.locked_at && entry.key === lastCommentKey}
                        {@render unlockAffordance($uiText("detail.locked"))}
                      {/if}
                    </div>
                  </li>
                {:else if entry.kind === "held"}
                  <!-- BETON-338: de comment die op de noodstop stuitte. Nog niet
                       geplaatst, dus bewust een afwijkende layout (gestippeld,
                       gedempt) — hij is geen deel van het gesprek maar een
                       openstaande handeling. Ontgrendelen kan hier direct, want
                       dít is de plek waar je ziet wát er wacht. -->
                  {@const h = entry.held}
                  <li class="tl-held">
                    <Avatar handle={h.author ?? "?"} avatarUrl={avatarMap.get(h.author)} size={28} />
                    <div class="cmt-main">
                      <div class="cmt-meta">
                        <span class="cmt-author">@{h.author ?? "?"}</span>
                        <span class="held-badge">{$uiText("detail.held")}</span>
                        <span class="cmt-time" title={absoluteTime(h.created_at, $locale)}>{formatTimestamp(h.created_at, undefined, $locale)}</span>
                      </div>
                      <!-- eslint-disable-next-line svelte/no-at-html-tags — renderMarkdown escapet -->
                      <div class="cmt-body md" use:lightboxClicks={openLightbox}>{@html renderMarkdown(h.body_md, knownHandles, projectKeys)}</div>
                      {@render unlockAffordance($uiText("detail.heldHint"))}
                    </div>
                  </li>
                {:else if entry.kind === "event-group"}
                  <!-- BETON-364: 3+ opeenvolgende system-events ingeklapt tot
                       één regel — houdt de tijdlijn leesbaar bij lange
                       reeksen automatische wijzigingen (bv. triage-passes). -->
                  <li class="tl-event tl-event-group">
                    <button
                      class="tl-line tl-linkish tl-group-toggle"
                      aria-expanded={expandedGroups.has(entry.key)}
                      onclick={() => toggleGroup(entry.key)}
                    >
                      {#if expandedGroups.has(entry.key)}<ChevronDown size={13} />{:else}<ChevronRight size={13} />{/if}
                      <span class="tl-actor">{$uiText("detail.changeCount", {count: entry.events.length})}</span>
                      · {entry.actors.map((a) => `@${a}`).join(", ")}
                      <span class="tl-time" title={`${absoluteTime(entry.first.created_at, $locale)} – ${absoluteTime(entry.last.created_at, $locale)}`}>
                        · {formatTimeRange(entry.first.created_at, entry.last.created_at, undefined, $locale)}
                      </span>
                    </button>
                  </li>
                  {#if expandedGroups.has(entry.key)}
                    {#each entry.events as e (e.id ?? e.created_at)}
                      {@render eventLine(e)}
                    {/each}
                  {/if}
                {:else}
                  {@render eventLine(entry.event)}
                {/if}
              {/each}
              {#if !timeline.length}
                <li class="tl-empty"><EmptyState icon={History} title={$t("drawer.emptyActivity")} /></li>
              {/if}
            </ul>
          </section>

          {#snippet eventLine(e)}
            {@const questionCmt = e.type === "question.answered" ? e.payload?.comment_id : null}
            <li class="tl-event">
              <Avatar handle={e.actor ?? "?"} avatarUrl={avatarMap.get(e.actor)} size={20} />
              {#if questionCmt != null}
                <!-- BETON-274: klik op de beantwoord-regel scrollt naar de vraag. -->
                <button class="tl-line tl-linkish" onclick={() => scrollToComment(questionCmt)} title={$uiText("detail.goQuestion")}>
                  <span class="tl-actor">@{e.actor ?? "?"}</span>
                  {describeEvent(e, $locale)}
                  <span class="tl-time" title={absoluteTime(e.created_at, $locale)}>· {formatTimestamp(e.created_at, undefined, $locale)}</span>
                </button>
              {:else}
                <span class="tl-line">
                  <span class="tl-actor">@{e.actor ?? "?"}</span>
                  {describeEvent(e, $locale)}
                  <span class="tl-time" title={absoluteTime(e.created_at, $locale)}>· {formatTimestamp(e.created_at, undefined, $locale)}</span>
                </span>
              {/if}
            </li>
          {/snippet}

          <!-- Composer (BETON-237): staat buiten de tijdlijn-sectie, als laatste
               kind van .dw-main. Zo is het sticky-bottom-anker de volledige
               kolom i.p.v. de (korte) tijdlijn-sectie onderaan — daardoor blijft
               de composer altijd in beeld zonder naar beneden te scrollen. -->
          <div class="composer" class:compact={composerCompact} onfocusin={() => (composerFocused = true)} onfocusout={onComposerFocusOut}>
              <MarkdownEditor
                bind:textareaRef={textarea}
                ariaLabel={$uiText("ui.newComment")}
                rows={composerCompact ? 1 : 3}
                placeholder={$t("drawer.reply")}
                value={commentText}
                {knownHandles}
                {projectKeys}
                oninput={onCommentInput}
                onsubmit={submitComment}
                onkeydown={onCommentKeydown}
                onpaste={(e) => handleImageDrop(e, "comment")}
                ondragover={(e) => e.preventDefault()}
                ondrop={(e) => handleImageDrop(e, "comment")}
              >
                {#snippet dropdown()}
                  <PickerSuggestions mentions={mentionMatches} tickets={hashMatches} mentionActive={mentionActive} ticketActive={hashActive} onmention={pickMention} onticket={pickHashRef} />
                {/snippet}
              </MarkdownEditor>
              {#if commentImages.length}
                <ul class="pending-images">
                  {#each commentImages as img (img.id)}
                    <li class="pending-image">
                      <img src={img.url} alt={img.filename} />
                      <span class="pending-image-name">{img.filename}</span>
                      <button
                        type="button"
                        class="icon-btn pending-image-remove"
                        onclick={() => removeCommentImage(img.id)}
                        title={$uiText("ui.remove")}
                        aria-label={$uiText("ui.removeImage")}
                      >
                        <X size={13} />
                      </button>
                    </li>
                  {/each}
                </ul>
              {/if}
              <input
                bind:this={commentFileInput}
                type="file"
                accept="image/*,text/*,application/json,application/pdf,.log,.md,.csv"
                multiple
                class="visually-hidden"
                tabindex="-1"
                onchange={(e) => handleImageFileInput(e, "comment", textarea)}
              />
              <div class="btn-row">
                <div class="upload-actions">
                  <button
                    class="sm img-upload-btn"
                    type="button"
                    disabled={uploading}
                    title={$uiText("ui.addImage")}
                    onclick={() => commentFileInput?.click()}
                  >
                    <ImagePlus size={14} /> {$uiText("detail.image")}
                  </button>
                  <span class="muted upload-hint">{uploading ? $uiText("detail.uploadBusy") : $uiText("detail.drop")}</span>
                </div>
                <button class="primary sm" onclick={submitComment} disabled={commentBusy}>
                  {commentBusy ? $uiText("detail.postBusy") : $uiText("detail.post")}
                </button>
              </div>
            </div>
        </div>
      </div>
    </div>
  {:else if error}
    <div class="dw-loading">
      <ErrorNote message={error} onRetry={load} />
    </div>
  {:else}
    <div class="dw-loading">
      <Skeleton preset="title" />
      <Skeleton preset="lines" count={4} />
      <Skeleton preset="rows" count={3} />
    </div>
  {/if}
</DrawerDialog>

<ImageLightbox image={lightboxImage} onclose={() => (lightboxImage = null)} />

<style>
  .triage-pending { margin: 6px 0 0; font-size: var(--text-xs); color: var(--text-secondary); }
  .quick-handoffs { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .quick-handoffs button { min-height: 28px; padding: 3px 7px; font-size: var(--text-xs); max-width: 100%; overflow-wrap: anywhere; }

  .dw-back {
    display: none;
  }

  /* BETON-362: vorige/volgende + teller in de header, vóór de ref-chip. */
  .dw-nav {
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  .dw-nav-count {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    min-width: 3.5em;
    text-align: center;
  }

  /* Header */
  .dw-head {
    position: sticky;
    top: -20px;
    z-index: var(--z-sticky-header);
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin: -20px -20px 16px;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--surface) 88%, transparent);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
  }
  .copied {
    color: var(--success);
    font-weight: 500;
  }
  .arch-badge {
    font-size: var(--text-xs);
    padding: 2px 8px;
    border-radius: var(--radius-full);
    background: var(--warning);
    color: var(--on-solid);
  }
  /* Kortstondige melding na een ⋯-menu-actie zonder eigen aangrijppunt
     (BETON-373: "Kopieer als markdown") — het menu is al gesloten, dus geen
     checkmark-op-de-knop mogelijk zoals copyRef(). */
  .copy-md-msg {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    animation: toast-in var(--dur-med) var(--ease);
  }
  /* BETON-137: "subtaak van {parent}"-label in de header, naast de ref-Chip. */
  .parent-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .parent-link .parent-label {
    font-size: var(--text-xs);
    opacity: 0.8;
  }
  .parent-link .ref-link {
    min-height: unset;
    font-size: var(--text-sm);
    padding: 2px 8px;
  }
  .dw-actions {
    margin-left: auto;
    display: flex;
    /* 2px zette twee knoppen van 28px praktisch tegen elkaar; dat leest als één
       besturingselement in plaats van twee losse acties — en de rechter is
       "sluiten". */
    gap: var(--space-2);
  }
  .dw-error {
    margin: 0 0 10px;
  }

  /* Overflow-menu (bits-ui DropdownMenu, geportald → :global). BETON-239: het
     menu portalt naar body en moet dus BOVEN het drawer-paneel liggen
     (--z-overlay + 1). Met --z-popover (5) rendert het achter de drawer en lijkt
     de knop dood — align="end" plaatst het precies achter het rechter-paneel. */
  :global(.dw-menu) {
    z-index: calc(var(--z-overlay) + 2);
    min-width: 220px;
    padding: 5px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg);
  }
  :global(.dw-menu-item) {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    font-size: var(--text-base);
    color: var(--text);
    cursor: pointer;
    user-select: none;
  }
  :global(.dw-menu-item[data-highlighted]) {
    background: var(--surface-2);
    outline: none;
  }
  :global(.dw-menu-item.danger) {
    color: var(--danger);
  }
  :global(.dw-menu-item.danger[data-highlighted]) {
    background: var(--danger-soft);
  }

  /* Twee-koloms content-first layout (BETON-223): titel bovenaan over de volle
     breedte, links de inhoud, rechts de property-rail. Onder 1024px stapelen ze
     (titel → rail → inhoud) zodat de properties direct onder de titel staan.

     BETON-414: die stapeling blijft, maar de rail is daar kort geworden —
     alleen de actiegroep plus één dichte $uiText("detail.properties")-knop. De feitelijke
     volgorde op een telefoon is dus titel → acties → eigenschappen (dicht) →
     omschrijving → plan → tijdlijn: lezen staat weer vooraan zonder dat de
     mutaties wegzakken. Dat vraagt géén andere grid-areas (en dus géén
     `display: contents` op de aside, wat zijn rol zou slopen). */
  .dw-cols {
    display: grid;
    gap: var(--space-6);
    grid-template-columns: 1fr;
    grid-template-areas: "title" "rail" "main";
    /* BETON-414: het contentVLAK krijgt zelf een maat. De drawer is
       min(1440px, 94vw), dus de 1fr-kolom werd ~1080px breed terwijl de
       leesregel op 82ch (~700px) staat — ~380px leegte naast elke alinea.
       Variant-keuze: de kolom blijft `minmax(0, 1fr)` en het BLOK begrenst
       zichzelf. Een `minmax(0, 860px)`-kolom + spacerkolom zou de bestaande
       grid-template-areas (de rail spant beide rijen, BETON-412) opnieuw
       moeten uitschrijven; dit niet. De slack valt zo tussen content en
       rail, niet in de rail. */
    --dw-content-max: 860px;
  }
  .dw-title-area {
    grid-area: title;
    /* Zelfde maat als de content: een titel/titelveld dat 220px breder is dan
       de tekst eronder leest als een tweede kolombreedte. */
    max-width: var(--dw-content-max);
  }
  .dw-rail {
    grid-area: rail;
  }
  .dw-main {
    grid-area: main;
    min-width: 0;
    max-width: var(--dw-content-max);
  }
  @media (min-width: 1024px) {
    .dw-cols {
      grid-template-columns: minmax(0, 1fr) 288px;
      /* De rail spant beide rijen. Zonder expliciete rijmaten zijn beide rijen
         `auto` en verdeelt grid de overhoogte van een rail die langer is dan
         de inhoud over BEIDE gespande rijen — ook over de titelrij, wat een
         leeg blok onder de titel geeft (BETON-412). Een flexibele tweede rij
         trekt die slack naar zich toe: een spannend item verdeelt zijn hoogte
         niet meer over de intrinsieke rijen zodra één gespande rij `fr` is. */
      grid-template-rows: auto 1fr;
      grid-template-areas:
        "title rail"
        "main  rail";
      column-gap: var(--space-8);
      /* De contentkolom is op --dw-content-max gekapt (BETON-414), maar de
         grid-kolom bleef `1fr`: op een breed venster viel die overruimte
         tússen de content en de rail, wat als een gat leest. Het hele
         tweekoloms-blok krijgt daarom zelf een maat en wordt gecentreerd, zodat
         de ruimte naar de buitenmarges gaat — daar leest hij als rust. */
      max-width: calc(var(--dw-content-max) + 288px + var(--space-8));
      margin-inline: auto;
    }
    /* BETON-427: de hele rail blijft staan terwijl de hoofdkolom scrolt.
       Scroll-container is .drawer-dialog; tussen die twee zit geen enkele
       `overflow` (voorwaarde voor sticky). `align-self: start` is nodig: een
       uitgerekte grid-item is zo hoog als zijn gridgebied, dus er is niets om
       overheen te schuiven. Het gridgebied (beide rijen) is zo hoog als de
       hoofdkolom, en daarbinnen schuift de rail mee. Is de rail hoger dan het
       beeld, dan scrolt hij zelf (max-height + overflow). 40px = net onder de
       sticky .dw-head; 20px = de padding van .drawer-dialog onderaan.
       (Vervangt de BETON-414-oplossing waarbij alleen .rail-actions sticky
       was en de rail uitgerekt bleef — daardoor scrolde de rest wel weg.)
       Onder 1024px geldt dit blok niet: daar stapelt alles en scrolt de rail
       gewoon mee. */
    .dw-rail {
      position: sticky;
      top: 40px;
      align-self: start;
      max-height: calc(100dvh - 40px - 20px);
      overflow-y: auto;
      overscroll-behavior: contain;
      /* Ruimte voor focusringen/outlines die anders op de scrollrand
         afknappen; de negatieve marge houdt de uitlijning gelijk. */
      padding-inline: 4px;
      margin-inline: -4px;
    }
    /* Binnen de scrollende rail blijft de actiegroep bovenaan staan als de
       lijst eronder langer is dan het beeld. top = de negatieve marge, zodat
       de inhoud op dezelfde plek blijft als in rust. */
    .rail-actions {
      position: sticky;
      top: calc(var(--space-3) * -1);
      z-index: var(--z-raised);
      /* Ondoorzichtig: .rail-props schuift er ónder door. */
      background: var(--surface);
      padding-block: var(--space-3);
      margin-block: calc(var(--space-3) * -1);
      /* Grens eronder, anders lijkt een eigenschapsregel halverwege op te
         houden (BETON-414). */
      border-bottom: 1px solid var(--border);
    }
  }

  /* Title */
  .dw-title {
    font-size: var(--text-2xl);
    font-weight: 600;
    line-height: 1.3;
    margin: 0;
    text-align: inherit;
  }
  .dw-title.editable {
    display: block;
    width: 100%;
    background: none;
    border: none;
    padding: 4px 6px;
    margin-left: -6px;
    border-radius: var(--radius-sm);
    cursor: text;
    color: var(--text);
  }
  .dw-title.editable:hover {
    background: var(--surface-2);
  }
  .title-edit {
    display: block;
    font-size: var(--text-2xl);
    font-weight: 600;
    line-height: 1.3;
    width: 100%;
    min-height: 0;
    padding: 4px 6px;
    margin-left: -6px;
  }

  /* Property-rail (BETON-414: twee lagen — actiegroep + eigenschappenlijst) */
  .dw-rail {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .rail-actions {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  /* De "Eigenschappen"-knop bestaat alleen onder 1024px; op desktop staat de
     lijst altijd open en is een knop die niets toevoegt alleen ruis. */
  .rail-props-toggle {
    display: none;
    align-items: center;
    gap: 6px;
    align-self: flex-start;
    padding: 4px 6px;
    margin-left: -6px;
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: var(--text-sm);
    font-weight: 600;
    cursor: pointer;
  }
  .rail-props-toggle:hover {
    background: var(--surface-2);
    color: var(--text);
  }
  .rail-props {
    display: flex;
    flex-direction: column;
  }
  @media (max-width: 1023px) {
    .rail-props-toggle {
      display: inline-flex;
    }
    .rail-props.collapsed {
      display: none;
    }
  }
  /* Eén regel per eigenschap: label links (stil, geen kapitalen — de
     actiegroep houdt de uppercase .rail-head, dát is de hiërarchie), waarde
     rechts. Chips-waarden breken af naar een tweede regel binnen dezelfde rij
     i.p.v. een eigen blok met kop te worden. */
  .prop-row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: 3px 0;
  }
  .prop-row + .prop-row {
    border-top: 1px solid var(--border);
  }
  .prop-line {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    padding: 4px 6px;
    margin-left: -6px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    color: var(--text);
    font-size: var(--text-sm);
    min-height: 0;
  }
  .prop-line.static {
    cursor: default;
  }
  .prop-line:not(.static):hover {
    background: var(--surface-2);
  }
  .prop-label {
    display: flex;
    align-items: baseline;
    gap: 6px;
    flex: none;
    color: var(--text-secondary);
    font-size: var(--text-sm);
  }
  .prop-val {
    margin-left: auto;
    min-width: 0;
    text-align: right;
    color: var(--text);
    font-size: var(--text-sm);
    font-variant-numeric: tabular-nums;
  }
  .prop-val.dchips {
    justify-content: flex-end;
  }
  .prop-empty {
    color: var(--text-tertiary);
  }
  /* BETON-415: ghost-affordance voor een lege einddatum/uitstel-rij — leest als
     "hier kan iets", niet als grijze data. Zelfde kleurgedrag als .label-add:
     rustig in rust, accent op hover van de hele (klikbare) rij. */
  .prop-add {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--text-tertiary);
  }
  .prop-line:hover .prop-add {
    color: var(--accent);
  }
  .rail-seg {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .rail-head {
    font-size: var(--text-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
  }
  /* Altijd-zichtbare rail-select (BETON-243): vult de railbreedte. */
  :global(.rail-select) {
    width: 100%;
  }
  .rail-row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  /* Ingeklapte property-rij als klikbare samenvattings-chip (per-rij bewerken). */
  .rail-chip {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    padding: 4px 6px;
    margin-left: -6px;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .rail-chip:hover {
    background: var(--surface-2);
  }
  .rail-val {
    margin-left: auto;
    font-size: var(--text-base);
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .prop-defer {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .rail-labels {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .label-add {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    min-height: 0;
    /* De globale button-regel in app.css zet `padding: 6px 12px`. Met
       box-sizing: border-box houdt een knop van 26px dan 26 - 2 (rand) - 24
       (padding) = 0px inhoud over, en wordt het plus-icoon van 14px tot 0px
       breed samengedrukt: een leeg gestippeld rondje. Gemeten in de browser
       (computed width 0px bij een width-attribuut van 14). */
    padding: 0;
    border-radius: var(--radius-full);
    /* Gestippeld = "hier kan iets bij"; kleur van een gewone actie (BETON-418). */
    border: 1px dashed var(--border-interactive);
    background: none;
    color: var(--text);
    cursor: pointer;
  }
  .label-add:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .label-picker {
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface);
    padding: 8px;
    box-shadow: var(--shadow-sm);
  }
  .label-search {
    width: 100%;
    margin-bottom: 6px;
  }
  .label-options {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    max-height: 220px;
    overflow-y: auto;
  }
  .label-empty {
    font-size: var(--text-sm);
  }
  /* BETON-248: subtaken/relaties in de smalle rail — knoppen vullen de kolom,
     de relatie-add-controls stapelen verticaal zodat select/input/suggestielijst
     in 288px passen. */
  .rail-full-btn {
    width: 100%;
    justify-content: center;
  }
  .subtask-actions {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .prop-label .subtask-progress {
    margin-left: 0;
  }
  /* Relatiegroepen binnen één eigenschapsregel: type boven de chips, rechts
     uitgelijnd met de rest van de waardekolom. */
  .rel-add {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    margin-top: 6px;
  }
  .rel-add :global(.select-trigger),
  .rel-add .rel-box {
    width: 100%;
  }

  /* BETON-245: volger-chips (avatar + handle + mute-kruisje), idioom van de
     label-/relatie-chips. Gemute = gedimd + doorgestreepte handle; het kruisje
     wordt een plus om te ontmuten. */
  .follower-row {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
  }
  .follower-more {
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .add-links {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 4px 0 8px;
    color: var(--text-tertiary);
    font-size: var(--text-sm);
  }
  .add-link {
    border: 0;
    background: none;
    padding: 2px 4px;
    min-height: 0;
    color: var(--text-secondary);
    font-size: var(--text-sm);
  }
  .add-link:hover {
    color: var(--accent);
    background: none;
  }
  /* BETON-369: volg-knop naast de "Volgers"-kop. Compacte tekstknop; de globale
     button-regel in app.css levert rand, vlak en tekstkleur van een gewone
     actie, en `.toggle[aria-pressed="true"]` de aan-staat (BETON-418). Hier
     alleen de maat. */

  /* BETON-50: subtaak-voortgang naast de sectiekop. */
  .subtask-progress {
    margin-left: 8px;
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
  }
  .subtask-progress.done {
    color: var(--accent);
  }
  /* BETON-416: kale actiebalk voor secties die géén all-caps kop meer hebben
     (Omschrijving, Tijdlijn) — rechts uitgelijnd i.p.v. SectionHead's
     space-between, want zonder label-tekst zou dat de knoppen naar links
     trekken. */
  .section-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 6px;
    margin-bottom: 10px;
  }
  /* BETON-423: datum links, knoppen rechts. */
  .section-meta {
    margin-right: auto;
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  /* Klik-om-te-bewerken veld (omschrijving). Padding ruimer dan de krappe
     4px/6px van voorheen (BETON-400: tekst stond strak tegen de rand van het
     grijze .desc-vlak). BETON-400 annuleerde de padding-left met een
     negatieve margin zodat de TEKST met de kop uitlijnde — gevolg was dat het
     VLAK zelf 14px naar links uitstak (BETON-401). Het vlak hoort op één
     lijn met de kop; de tekst mag daarvoor inspringen. */
  .desc.editable {
    cursor: text;
    border-radius: var(--radius-sm);
    padding: 12px 14px;
  }
  /* --surface-2 is al de achtergrond van .desc zelf (app.css) — die kleur
     op :hover herhalen liet de hover onzichtbaar zijn. --surface-3 is de
     volgende stap op de tokenschaal en wordt elders al als hover-tint op
     --surface-2-achtergronden gebruikt. */
  .desc.editable:hover {
    background: var(--surface-3);
  }
  /* BETON-416: het plan krijgt een stillere, dichtere behandeling dan de
     omschrijving — een linkerlijn i.p.v. een gevuld vlak, en iets kleinere
     regelafstand (1.45 t.o.v. de basis 1.5) — zodat het ondergeschikt en
     scanbaar oogt zonder onleesbaar te worden. Klik-om-te-bewerken en de
     BETON-415-selectie-guard blijven ongewijzigd; alleen het uiterlijk
     verandert. */
  .plan-body {
    /* --text-tertiary en niet --border: deze lijn is het ENIGE wat het plan van
       de omschrijving onderscheidt (die heeft een gevuld vlak), dus hij moet
       zichtbaar zijn. Contrast tegen de paneelachtergrond, in de browser
       nagerekend: --border haalt 1,31 (licht) en 1,28 (donker) — dat is geen
       lijn maar een vermoeden; --border-strong 1,60/1,67; --text-tertiary
       3,09/3,58 en zit daarmee boven de 3:1 die voor niet-tekstuele
       elementen geldt. */
    border-left: 2px solid var(--text-tertiary);
    padding: 4px 4px 4px 14px;
    line-height: 1.45;
  }
  .plan-body.editable {
    cursor: text;
    border-radius: var(--radius-sm);
  }
  .plan-body.editable:hover {
    background: var(--surface-2);
  }
  /* Guardrail-sectie (BETON-420). Rode linkerlijn i.p.v. een gevuld vlak: de
     omschrijving heeft het vlak al, en een tweede zou de twee gelijkwaardig
     maken. De kleur komt uit het semantische token, niet uit --danger zelf. */
  .guardrail-head-actions {
    display: flex;
    gap: 6px;
  }
  .guardrail-card {
    border-left: 3px solid var(--guardrail-border);
    padding: 4px 4px 4px 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .guardrail-head {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--guardrail-border);
    font-size: var(--text-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .guardrail-text {
    margin: 0;
    white-space: pre-wrap;
    line-height: 1.45;
  }
  .guardrail-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 10px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .guardrail-scope {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  /* Een verstreken reviewdatum is geen fout maar een openstaande vraag —
     vandaar --warning en niet de guardrail-kleur zelf. */
  .guardrail-review.overdue {
    color: var(--warning);
  }
  .guardrail-scope-hint {
    align-self: flex-start;
  }
  /* Concept (BETON-422) — bewust NIET de guardrail-kleur: rood betekent "dit
     geldt", en een concept geldt juist nog niet. Gestippelde neutrale rand rond
     het hele blok, zodat het als een voorstel leest naast de actieve lijn. */
  .guardrail-concept {
    border: 1px dashed var(--border-strong);
    border-radius: var(--radius-md);
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .guardrail-concept-head {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-secondary);
    font-size: var(--text-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .guardrail-concept-reason {
    margin: 0;
    white-space: pre-wrap;
    line-height: 1.45;
    color: var(--text-secondary);
  }
  .guardrail-concept-note {
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }
  .guardrail-editor {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .guardrail-editor :global(textarea) {
    width: 100%;
  }
  .guardrail-formrow {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 12px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .guardrail-count.over {
    color: var(--danger);
  }
  .guardrail-date {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .guardrail-scope-edit {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: var(--text-sm);
  }
  .guardrail-hint {
    font-size: var(--text-sm);
    color: var(--danger);
  }
  .empty-edit {
    background: none;
    border: 1px dashed var(--border-interactive);
    border-radius: var(--radius-md);
    color: var(--text-secondary);
    padding: 10px 12px;
    width: 100%;
    text-align: left;
    cursor: text;
  }
  .empty-edit:hover {
    border-color: var(--accent);
    color: var(--text);
  }

  /* Sections */
  .dw-section {
    padding-top: 18px;
    margin-top: 18px;
    border-top: 1px solid var(--border);
  }
  .dw-main > .dw-section:first-child {
    padding-top: 0;
    margin-top: 0;
    border-top: none;
  }

  @media (max-width: 640px) {
    /* De drawer heeft hier 16px padding i.p.v. 20px (app.css); met de
       desktopmarge stak de kop 4px uit en scrolde de drawer horizontaal. */
    .dw-head {
      top: -16px;
      margin: -16px -16px 16px;
    }
    .dw-back {
      display: inline-flex;
    }
    .dw-close {
      display: none;
    }
    /* Vorige/volgende-knoppen blijven staan, de teller verdwijnt (BETON-362). */
    .dw-nav-count {
      display: none;
    }
    .icon-btn,
    .ref-link {
      min-height: 40px;
    }
    /* BETON-414: de eigenschappenregels zijn op de telefoon aanraakdoelen —
       zelfde maat als de andere knoppen hierboven. `.static`-regels (labels,
       subtaken, relaties, volgers, tijdstempels) zijn geen knop en houden hun
       compacte hoogte; hun eigen chips/knoppen vallen al onder .ref-link. */
    .rail-props-toggle,
    .prop-line:not(.static) {
      min-height: 40px;
      align-items: center;
    }
  }

  /* Label chips */
  .dchips {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    align-items: center;
  }
  /* Subtaak-chip (BETON-203): statusstip + ref, zelfde stipkleur als het bord. */
  /* Decompose-voorstel (BETON-31). */
  .decompose-reason {
    margin: 4px 0 8px;
  }
  .decompose-list {
    margin: 4px 0 10px;
    padding-left: 20px;
    display: flex;
    flex-direction: column;
    gap: 5px;
    font-size: var(--text-base);
    line-height: 1.4;
  }
  /* light-dark() volgt de color-scheme → labels flippen mee met systeem én
     de handmatige thema-toggle (BETON-61). */
  /* Inactief = outline-chip (transparante vulling, gekleurde rand+tekst) zodat
     niet-geselecteerde labels duidelijk "niet toegepast" lezen; actief = gevuld
     + vinkje. Voorheen had de inactieve staat al een gevulde achtergrond,
     waardoor alle labels actief leken als er geen enkele geselecteerd was
     (BETON-93). */
  /* Refs / relaties */
  .ref-link {
    border: none;
    background: none;
    color: var(--accent);
    padding: 2px 4px;
    min-height: unset;
    font-variant-numeric: tabular-nums;
    border-radius: var(--radius-sm);
  }
  .ref-link:hover {
    background: var(--accent-soft);
    text-decoration: none;
  }
  /* Op touch bestaat hover niet, dus een affordance die zich achter :hover
     verstopt is daar géén affordance: gemeten op 390px stond de knop op
     opacity 0 en was een relatie dus niet te verbreken. Vóór BETON-415 stond
     het kruisje er altijd. Zelfde idioom als Chip.svelte/App.svelte, die de
     touch-uitzondering ook op `pointer: coarse` hangen. De bevestiging
     (ConfirmBar) blijft de beveiliging tegen een misklik — niet de
     onzichtbaarheid. */
  /* Volger-mute (BETON-415): zelfde vorm als .rel-x had, maar altijd zichtbaar —
     muten is geen verwijderen en verdient geen verstopte affordance. */
  .rel-add {
    display: flex;
    gap: 8px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  /* Compacte "+ toevoegen"-affordance voor lege secties (BETON-242): klikken
     toont het invoerblok. BETON-418: omlijnd als gewone actie (rand, vlak en
     tekstkleur uit de globale button-regel) — als kale --text-tertiary-tekst
     (3,09/3,58) las hij als uitgeschakeld. Hier alleen de maat. */
  .add-affordance {
    gap: 5px;
    margin-top: 2px;
    padding: 4px 8px;
    min-height: 0;
    font-size: var(--text-sm);
  }
  .rel-box {
    position: relative;
    flex: 1;
    min-width: 120px;
  }
  .rel-target {
    width: 100%;
  }
  /* BETON-350: rechts ankeren en naar links laten groeien i.p.v. exact de
     (in de rail altijd smalle, 288px) input-breedte te matchen — anders
     klipt elke wat langere tickettitel in de suggestie af tot onleesbaars.
     Zelfde regel als app.css (twee kopieën door historische groei; hier
     bewust in sync gehouden i.p.v. ontward — zie BETON-350-commit). Cap
     alleen op de viewport, niet meer op een vaste 360px — die vaste waarde
     kapte nog steeds af (live gemeten: titels hier ~770px natuurlijke
     breedte, en de drawer-hoofdkolom heeft daar ruimschoots plek voor). */
  .rel-box :global(.mention-list) {
    left: auto;
    right: 0;
    min-width: 100%;
    width: max-content;
    max-width: calc(100vw - 40px);
  }
  .rel-suggest-ref {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    margin-right: 6px;
    white-space: nowrap;
  }
  .rel-box :global(.mention-list li) {
    display: flex;
    align-items: baseline;
    overflow: hidden;
  }
  .rel-box :global(.mention-list li .muted) {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Tijdlijn (BETON-223): comments (kaarten) + events (regels) door elkaar. */
  .tl {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .tl-empty {
    padding: 8px 0;
  }
  /* Comment-kaart */
  .tl-comment {
    display: flex;
    gap: 10px;
    padding: 12px 0;
  }
  .cmt-main {
    flex: 1;
    min-width: 0;
  }
  .cmt-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    margin-bottom: 3px;
  }
  .cmt-author {
    font-weight: 600;
    color: var(--text);
  }
  .cmt-actions {
    display: flex;
    gap: 1px;
    margin-left: auto;
    opacity: 0;
    transition: opacity var(--dur-fast) var(--ease);
  }
  .tl-comment:hover .cmt-actions,
  .cmt-actions:focus-within {
    opacity: 1;
  }
  .cmt-body {
    white-space: pre-wrap;
    word-break: break-word;
  }
  /* Gerenderde markdown regelt zelf de blok-witruimte — geen pre-wrap. */
  .cmt-body.md {
    white-space: normal;
  }
  /* BETON-458: ingeklapte lange comment — max-height komt inline uit de
     gemeten eerste alinea; de fade laat zien dat er meer is. */
  .cmt-body.cmt-collapsed {
    position: relative;
    overflow: hidden;
  }
  .cmt-body.cmt-collapsed::after {
    content: "";
    position: absolute;
    inset: auto 0 0 0;
    height: 48px;
    background: linear-gradient(to bottom, transparent, var(--surface));
    pointer-events: none;
  }
  .cmt-toggle {
    margin-top: 4px;
    padding: 2px 0;
    border: 0;
    background: none;
    color: var(--accent);
    font-size: var(--text-sm);
    cursor: pointer;
  }
  /* Kop van een uitgeklapte lange comment blijft in beeld tijdens het lezen.
     Net onder de sticky drawer-kop (`.dw-head`, ~56px). */
  .tl-comment.cmt-long-open .cmt-meta {
    position: sticky;
    top: 40px;
    z-index: 1;
    background: var(--surface);
    padding: 2px 0;
  }

  /* --- Vraag-kaart (BETON-219) --------------------------------------------
     Een vraag-comment krijgt een eigen kaartvorm: accent-rand links, een
     vraag-icoon i.p.v. avatar. Beantwoord = gedempt. */
  .tl-comment.question {
    padding: 12px;
    margin: 4px 0;
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--accent) 5%, transparent);
  }
  .tl-comment.question.answered {
    opacity: 0.72;
    border-left-color: var(--border-strong);
    background: transparent;
  }
  .q-icon {
    flex: 0 0 auto;
    display: inline-flex;
    color: var(--accent);
  }
  .tl-comment.question.answered .q-icon {
    color: var(--text-tertiary);
  }
  .q-tag {
    font-size: var(--text-xs);
    padding: 1px 8px;
    border-radius: var(--radius-full);
    background: var(--surface-2);
    border: 1px solid var(--border);
    color: var(--text-secondary);
  }
  .q-answer {
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  /* BETON-258/271: korte opties (Ja/Nee) delen nog steeds één rij; lange
     labels wrappen naar hun eigen rij i.p.v. de rij te laten overlopen. Elke
     knop krijgt bovendien interne tekstwrap zodat een lang label dat toch
     samen met anderen op een rij past, netjes over meerdere regels afbreekt
     in plaats van te overlappen. */
  .q-options {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .q-opt-btn {
    flex: 1 1 130px;
    min-width: 130px;
    min-height: 34px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    white-space: normal;
    overflow-wrap: anywhere;
    gap: 6px;
    padding: 8px 14px;
    border: 1px solid var(--accent);
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--accent);
    font: inherit;
    line-height: 1.3;
    cursor: pointer;
  }
  .q-opt-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent) 14%, transparent);
  }
  .q-opt-btn.chosen {
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    font-weight: 600;
  }
  .q-opt-btn:disabled {
    cursor: default;
    opacity: 0.6;
  }
  /* Weergave van de opties in beantwoorde staat; de gekozen optie gemarkeerd. */
  .q-opt {
    flex: 1 1 130px;
    min-width: 130px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    white-space: normal;
    overflow-wrap: anywhere;
    gap: 5px;
    padding: 5px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
    line-height: 1.3;
    color: var(--text-tertiary);
  }
  .q-opt.chosen {
    border-color: var(--accent);
    color: var(--accent);
    font-weight: 600;
  }
  .q-freetext {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  /* Inline vrijtekst-antwoord (BETON-265). Gerenderde markdown (BETON-434)
     regelt zelf de blok-witruimte — geen pre-wrap, net als `.cmt-body.md`. */
  .q-answer-text {
    word-break: break-word;
    padding: 6px 10px;
    background: var(--surface-2);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
  }
  .q-answer-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .q-answered-by {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--text-tertiary);
    font-size: var(--text-sm);
  }
  .q-edit-answer {
    flex: none;
  }
  /* Event-regel: compacte, één-regelige activiteit tussen de comments. */
  .tl-event {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 0 5px 8px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .tl-line {
    min-width: 0;
  }
  /* Klikbare activiteitsregel (BETON-274): oogt als tekst, cursor + hover-onderstreping. */
  .tl-linkish {
    display: inline;
    justify-content: flex-start;
    background: none;
    border: none;
    padding: 0;
    min-height: 0;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  .tl-linkish:hover {
    text-decoration: underline;
  }
  .tl-actor {
    font-weight: 600;
    color: var(--text);
  }
  .tl-time {
    color: var(--text-tertiary);
  }
  /* Ingeklapte event-groep (BETON-364): het chevron-icoon staat naast de
     tekst i.p.v. inline erin, dus deze knop krijgt zijn eigen flex-layout
     boven op .tl-linkish. */
  .tl-group-toggle {
    display: inline-flex;
    flex-wrap: wrap;
    max-width: 100%;
    align-items: center;
    gap: 4px;
  }

  /* Composer: sticky onderaan de drawer — blijft altijd in beeld terwijl de
     tijdlijn eronder scrollt (BETON-237). `bottom: 0` trekt 'm omhoog in de
     scrollport; een negatieve bottom zou 'm juist ónder de vouw verstoppen.

     BETON-417: `.drawer-dialog` (gedeeld met Inbox/App/TriageChat, app.css)
     heeft `padding: 20px` — sticky rekent "bottom" t.o.v. de PADDING-box van
     die scroll-ancestor, dus `bottom: 0` liet precies die 20px padding als
     kale strook onder de composer staan (de achtergrond-gradient van de
     composer dekt alleen zichzelf, niet de padding-ruimte erbuiten). Van de
     drie kandidaten uit het plan (1: bottom-padding verhuizen naar de inhoud,
     2: negatieve margin zoals `.dw-head` bovenaan, 3: dekkende achtergrond
     i.p.v. gradient) is dit een variant op 1 die noch de gedeelde
     `.drawer-dialog` noch andere componenten raakt: `bottom: -20px` schuift
     het sticky-ankerpunt zelf 20px verder naar beneden, tot de border-box-rand
     van het paneel — de strook verdwijnt, en er komt zelfs 20px extra
     scrollruimte bij i.p.v. dat er iets wegvalt. Kandidaat 2 (margin-bottom)
     verschuift ditzelfde ankerpunt via een omweg die de knoppenrij onder de
     zichtbare rand kan duwen (de reden dat BETON-416 dit niet meenam);
     kandidaat 3 lost de strook niet op, alleen de leesbaarheid erin. */
  .composer {
    position: sticky;
    bottom: -20px;
    margin-top: 12px;
    padding-top: 12px;
    padding-bottom: var(--space-4);
    background: linear-gradient(
      to bottom,
      transparent,
      var(--surface) 14px
    );
  }
  /* Volgt ná de basisregel: gelijke specificiteit, dus bronvolgorde beslist —
     vóór de basisregel gezet zou hij door `.composer { bottom: -20px }`
     worden overschreven (dat overkwam deze wijziging een eerste keer).

     BETON-417 stap 3: op de telefoon kost de sticky composer ~200px van het
     scherm — een kwart van 390×844 — en dat kost precies leesruimte op de
     omschrijving, de meest voorkomende handeling op een ticket. In plaats
     van de composer in te klappen tot een balk (dat vraagt een
     tik-om-uit-te-klappen-affordance die op `pointer: coarse` moet hangen en
     dus met dit gereedschap niet vast te stellen is of hij werkt) laat hij
     hier gewoon zijn sticky-gedrag los: onder 640px staat hij in de
     normale flow, onderaan de tijdlijn. Geen state, geen nieuwe knop, alle
     bestaande functionaliteit (mentions, #refs, sleep/plak, Editor/
     Voorbeeld, Plaats reactie, lock-banner) blijft ongemoeid — er verandert
     niets aan de markup, alleen aan waar de composer in de flow staat. De
     `bottom`-waarde hierboven is dan inert (die geldt alleen voor sticky/
     fixed); met `position: static` doet hij niets meer, vandaar geen aparte
     override op `bottom` in dit blok. */
  @media (max-width: 640px) {
    .composer {
      position: static;
    }
  }
  /* BETON-458: rusttoestand = invoerveld + Plaats reactie op één regel. De
     editor blijft gemount (het concept verdwijnt nooit); alleen de schakelaar
     en de upload-acties zijn verborgen tot focus of inhoud. */
  .composer.compact {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
  .composer.compact :global(.md-editor) {
    flex: 1;
    min-width: 0;
  }
  .composer.compact :global(.md-editor-toggle),
  .composer.compact .upload-actions {
    display: none;
  }
  .composer.compact .btn-row {
    margin: 0;
  }

  /* BETON-302: het slot is een waarschuwing, geen neutrale mededeling — vandaar
     de danger-token i.p.v. surface-2 (zoals ConfirmBar.svelte). */
  .lock-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 8px 12px;
    margin-bottom: 12px;
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
    border-radius: var(--radius-md);
    font-size: var(--text-base);
  }
  .lock-banner span {
    flex: 1;
  }
  /* BETON-338: de ruimte-keuze (5/10/20) is een span binnen .lock-banner, dus
     de `flex: 1` hierboven zou hem uitrekken en de knoppen uit elkaar trekken.
     Expliciet terugzetten naar inhoudsbreedte. */
  .lock-banner .unlock-choice,
  .unlock-choice {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
  }
  .unlock-label {
    flex: 0 0 auto;
    font-size: var(--text-sm);
    opacity: 0.85;
  }
  /* De wachtende comment (BETON-338): herkenbaar géén geplaatste comment —
     gestippelde rand en gedempte kleur, zodat direct zichtbaar is dat dit
     nog niet in het gesprek staat. */
  .tl-held {
    display: flex;
    gap: 10px;
    padding: 10px 12px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--surface-2) 60%, transparent);
    opacity: 0.9;
  }
  .held-badge {
    padding: 1px 7px;
    border-radius: 999px;
    font-size: var(--text-xs);
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  }
  .held-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 8px;
  }
  /* Verwijder-icoon kleurt rood bij hover; de bevestigingsknop is een rode
     danger-knop (onherroepelijke actie). */
  .dw-delete:hover {
    color: var(--danger);
  }
  button.danger {
    background: var(--danger);
    color: var(--on-danger);
    border-color: var(--danger);
  }
  button.danger:hover {
    background: color-mix(in srgb, var(--danger) 88%, black);
    border-color: color-mix(in srgb, var(--danger) 88%, black);
  }

  /* Shared bits */
  .btn-row {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 8px;
  }
  /* Verrijk-voorstel: regel-diff (BETON-13) */
  .enrich-panel {
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 10px;
    background: var(--surface-2);
  }
  .enrich-hint {
    margin: 0 0 8px;
    font-size: var(--text-sm);
  }
  /* Voorgestelde labels bij een verrijking (BETON-355) */
  .enrich-labels {
    margin-top: 10px;
  }
  .enrich-labels .enrich-hint {
    display: block;
    margin-bottom: 6px;
  }
  /* Verrijk-melding: bot stelde vragen i.p.v. een voorstel (BETON-163) */
  .enrich-notice {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 8px 10px;
    background: var(--surface-2);
    font-size: var(--text-base);
  }
  .enrich-notice p {
    margin: 0;
  }
  /* Zichtbare upload-knop (BETON-74): staat links in de btn-row, los van de
     rechts uitgelijnde primaire acties. */
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
  .upload-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-right: auto;
  }
  .img-upload-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .upload-hint {
    font-size: var(--text-sm);
  }
  /* Preview-thumbnails van net geüploade comment-afbeeldingen (BETON-94) —
     mirror van NewItem.svelte's pending-images (daar object-URLs vóór
     aanmaken, hier de echte server-URL ná upload). */
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
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    width: 72px;
  }
  .pending-image img {
    width: 64px;
    height: 64px;
    object-fit: cover;
    border-radius: var(--radius-md);
    border: 1px solid var(--border);
  }
  .pending-image-name {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    max-width: 72px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pending-image-remove {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 20px;
    height: 20px;
    min-height: 0;
    /* Zelfde reden als bij .label-add: de globale button-padding (6px 12px)
       laat bij 20px geen inhoudsbreedte over en drukt het icoon tot 0px. */
    padding: 0;
    background: var(--surface);
    box-shadow: var(--shadow-sm);
  }
  .dw-loading {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
    padding: 24px;
  }

  /* Bijlagen-galerij (BETON-175): alle attachments van het item, ook als ze
     niet (meer) in de omschrijving staan. */
  .attachment-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }
  .attachment-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    width: 88px;
  }
  .attachment-file {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.5rem;
    min-height: 64px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-2);
    color: var(--text-secondary);
    font-size: 0.78rem;
  }

  .attachment-file-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .attachment-thumb {
    width: 88px;
    height: 64px;
    object-fit: cover;
    border-radius: var(--radius-md);
    border: 1px solid var(--border);
    display: block;
  }
  .attachment-insert {
    width: 100%;
    font-size: var(--text-xs);
  }

  .md :global(pre) {
    background: var(--surface-2);
    padding: 10px;
    border-radius: var(--radius-sm);
    overflow-x: auto;
  }
  .md :global(code) {
    background: var(--surface-2);
    padding: 1px 4px;
    border-radius: var(--radius-sm);
  }
  .md :global(h3),
  .md :global(h4),
  .md :global(h5) {
    margin: 8px 0 4px;
  }
  .md :global(a) {
    color: var(--accent);
  }
  .md :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: var(--radius-md);
    margin: 6px 0;
    display: block;
  }
  .md :global(blockquote) {
    margin: 6px 0;
    padding: 2px 0 2px 10px;
    border-left: 3px solid var(--border);
    color: var(--text-muted);
  }
  .md :global(hr) {
    border: 0;
    border-top: 1px solid var(--border);
    margin: 10px 0;
  }
  .md :global(ol),
  .md :global(ul) {
    margin: 4px 0;
    padding-left: 20px;
  }
  /* Leesregel van lopende tekst begrenzen op brede drawers (BETON-399) —
     tabellen, diffs en codeblokken (pre) blijven bewust de volle .dw-main-breedte
     gebruiken, alleen alinea's en losse listitems worden begrensd. Sinds
     BETON-414 is die volle breedte zelf begrensd op --dw-content-max (860px);
     wat daar niet in past houdt zijn eigen overflow-x. BETON-416: 82ch was de
     bovenkant van de comfortabele band (45–75ch is gebruikelijk); 70ch leest
     rustiger. */
  .md :global(p),
  .md :global(li) {
    max-width: 70ch;
  }
  /* Ticketref-link zoals BETON-91 in omschrijving/comments (BETON-107) */
  .md :global(.ticketlink) {
    color: var(--accent);
    cursor: pointer;
    text-decoration: none;
    border-bottom: 1px solid var(--accent);
    font-variant-numeric: tabular-nums;
  }
  .md :global(.ticketlink):hover {
    opacity: 0.8;
  }
  .md :global(.ticketlink):focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 2px;
  }
</style>
