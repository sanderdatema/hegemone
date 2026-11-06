<script module>
  // Zet elke entry met event_id <= watermark op read (spiegelt de backend-
  // watermark in repo/inbox.py:mark_seen). Los, puur en getest (BETON-125).
  export function markUpTo(list, watermark) {
    return (list || []).map((e) =>
      e.event_id <= watermark ? { ...e, read: true } : e
    );
  }
</script>

<script>
  // Mention-inbox (BETON-55), gegroepeerd per ticket (BETON-228): events die jou
  // raken (mentions, toewijzingen, comments op je items) bundelen zich per ticket
  // tot één rij met samenvatting + ongelezen-telling. Uitklappen toont de losse
  // events; klik opent het ticket via het bestaande navigateRef-pad. Gelezen-
  // markering blijft de bestaande watermark op event_id.
  import { t, locale } from "./lib/i18n.js";
  import { api } from "./api.js";
  import { formatTimestamp, absoluteTime } from "./lib/board.js";
  import {
    openInboxGroup, groupNotifications, dueLabel, guardrailLabel, INBOX_FETCH_LIMIT,
    isOptionQuestion, mergeAnswered, openCount, answeredLabel,
    agentAlerts, agentUnreachableLabel,
  } from "./lib/inbox.js";
  import { openQuestionRows, optionAnswer } from "./lib/question.js";
  import DrawerDialog from "./DrawerDialog.svelte";
  import Avatar from "./Avatar.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import ErrorNote from "./ErrorNote.svelte";
  import Skeleton from "./Skeleton.svelte";
  import EmptyState from "./EmptyState.svelte";
  import {
    X, AtSign, UserCheck, MessageSquare, Bell, CheckCheck, ChevronRight, Check,
    MessageCircleQuestion, CalendarClock, ShieldQuestionMark, ServerOff,
  } from "@lucide/svelte";

  let {
    liveTick = 0,
    avatarMap = new Map(),
    onopen = () => {},
    onseen = () => {},
    ondeliveries = () => {},
    onclose = () => {},
  } = $props();

  let entries = $state([]);
  // Open (onbeantwoorde) vragen aan mij (BETON-219) — server levert al gericht.
  let questions = $state([]);
  let loading = $state(false);
  let error = $state("");
  let filter = $state("all"); // 'all' | 'unread'
  let expanded = $state(new Set()); // uitgeklapte groepen, gekeyd op ref
  const PAGE = 20;
  let visible = $state(PAGE); // hoeveel (gefilterde) groepen we tonen

  const FILTER_OPTIONS = $derived([
    { value: "unread", label: $t("filter.unread") },
    { value: "all", label: $t("filter.all") },
  ]);

  const REASON_META = $derived({
    // BETON-367: deadline-entry; het label komt uit `dueLabel` (vandaag vs verstreken).
    due: { icon: CalendarClock, label: $t("inbox.reason.due") },
    // BETON-422: openstaand guardrail-concept; het label komt uit
    // `guardrailLabel` (voorstellen vs opheffen) en houdt de @actor-prefix.
    guardrail: { icon: ShieldQuestionMark, label: $t("inbox.reason.guardrail") },
    mention: { icon: AtSign, label: $t("inbox.reason.mention") },
    assigned: { icon: UserCheck, label: $t("inbox.reason.assigned") },
    comment: { icon: MessageSquare, label: $t("inbox.reason.comment") },
    update: { icon: Bell, label: $t("inbox.reason.update") },
  });

  let groups = $derived(groupNotifications(entries, $locale));
  // Lokaal beantwoorde vragen blijven als "Beantwoord: …" staan (BETON-456).
  let answered = $state({}); // { [id]: { row, index } }
  let answerBusy = $state(0); // id van de vraag die nu verstuurd wordt
  let answerError = $state({}); // { [id]: melding }
  let changing = $state(null); // id van de vraag waarvan het antwoord gewijzigd wordt
  let bodyOpen = $state(new Set()); // uitgeklapte vraagteksten
  let openQuestions = $derived(mergeAnswered(openQuestionRows(questions), answered));
  let openTotal = $derived(openCount(openQuestions));
  // Onbereikbare agents (BETON-457): geen ticket, dus buiten de groepen.
  let alerts = $derived(agentAlerts(entries));
  let unreadGroups = $derived(groups.filter((g) => g.unread > 0).length);
  let unreadTotal = $derived(unreadGroups + alerts.length);
  // In de Ongelezen-weergave houden we uitgeklapte groepen gepind: uitklappen
  // markeert een groep gelezen, maar hij mag niet halverwege het lezen uit de
  // lijst springen. Ingeklapt verdwijnt hij daarna alsnog netjes.
  let filteredGroups = $derived(
    filter === "unread"
      ? groups.filter((g) => g.unread > 0 || expanded.has(g.ref))
      : groups
  );
  let visibleGroups = $derived(filteredGroups.slice(0, visible));
  let hasMore = $derived(filteredGroups.length > visible);

  async function load() {
    loading = true;
    error = "";
    try {
      const [data, q] = await Promise.all([
        api.inbox(INBOX_FETCH_LIMIT),
        api.openQuestions().catch(() => []),
      ]);
      entries = data.items;
      questions = q;
    } catch (e) {
      error = $t("inbox.loadFailed");
    } finally {
      loading = false;
    }
  }

  // Watermark op event_id (repo/inbox.py:mark_seen): bumpen naar het verste
  // event van een groep markeert die groep — en alle oudere events — gelezen.
  // Dit hergebruikt bewust het bestaande éénwatermark-model.
  async function markRead(watermark) {
    if (!watermark) return;
    try {
      await api.inboxSeen(watermark);
      entries = markUpTo(entries, watermark);
      onseen();
    } catch (e) {
      error = e.message;
    }
  }

  async function markAllRead() {
    const top = entries.reduce((mx, e) => Math.max(mx, e.event_id), 0);
    await markRead(top);
  }

  async function markGroupRead(group) {
    if (group.unread) await markRead(group.latestEventId);
  }

  function toggle(group) {
    const next = new Set(expanded);
    if (next.has(group.ref)) {
      next.delete(group.ref);
    } else {
      next.add(group.ref);
      markGroupRead(group); // uitklappen = de groep gezien
    }
    expanded = next;
  }

  function open(group) {
    return openInboxGroup(group, onopen, markGroupRead);
  }

  // Open-vraag aanklikken: open het ticket én scroll naar de vraag-comment
  // (BETON-273). De comment-id (`q.id`) gaat als tweede argument mee.
  // Optie kiezen: eerste keer POST, daarna (wijzigen) PATCH zolang het antwoord
  // niet verstuurd is (BETON-262/263); een 409 betekent "al verstuurd".
  async function pickOption(q, index) {
    if (answerBusy) return;
    answerBusy = q.id;
    const { [q.id]: _e, ...restErr } = answerError;
    answerError = restErr;
    try {
      if (q.answeredIndex == null) await api.answerQuestion(q.id, optionAnswer(index));
      else await api.updateAnswer(q.id, optionAnswer(index));
      const { answeredIndex: _a, ...row } = q;
      answered = { ...answered, [q.id]: { row, index } };
      changing = null;
      onseen();
    } catch (e) {
      answerError = { ...answerError, [q.id]: e.message };
      if (q.answeredIndex != null) changing = null;
    } finally {
      answerBusy = 0;
    }
  }
  function toggleBody(id) {
    const next = new Set(bodyOpen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    bodyOpen = next;
  }

  function openQuestion(q) {
    onopen(q.ref, q.id);
  }

  // Herlaad bij live-updates. Expansie is op ref gekeyd (Set) en overleeft de
  // regroepering, zodat een open groep niet dichtklapt tijdens het lezen.
  $effect(() => {
    liveTick;
    load();
  });

  // Filterwissel: begin weer bovenaan de onthulling.
  $effect(() => {
    filter;
    visible = PAGE;
  });
</script>

<DrawerDialog label="Inbox" width="min(640px, 100%)" onclose={() => onclose()}>
  <div class="inbox-panel">
    <header class="inbox-head">
      <div class="inbox-title">
        <Bell size={18} />
        <span>Inbox</span>
        {#if unreadTotal}<span class="unread-pill">{unreadTotal > 99 ? "99+" : unreadTotal}</span>{/if}
      </div>
      <div class="inbox-actions">
        <button class="link" onclick={markAllRead} disabled={!unreadGroups} title={$t("inbox.markAllTitle")}>
          <CheckCheck size={15} /> {$t("inbox.markAll")}
        </button>
        <button class="icon-btn" title={$t("common.close")} aria-label={$t("common.close")} onclick={() => onclose()}>
          <X size={19} />
        </button>
      </div>
    </header>

    <div class="inbox-filter">
      <SegmentedControl
        options={FILTER_OPTIONS}
        value={filter}
        onchange={(v) => (filter = v)}
        variant="soft"
        ariaLabel={$t("inbox.filter")}
      />
    </div>

    {#if alerts.length}
      <section class="agent-alerts" aria-label={$t("inbox.unreachable")}>
        <ul class="oq-list">
          {#each alerts as a (a.handle)}
            <li class="aa-row">
              <ServerOff size={15} />
              <span class="aa-text">
                <strong>@{a.handle}</strong> {$t("inbox.unreachablePrefix")} — {agentUnreachableLabel(a, $locale)}
                {#if a.last_error}<span class="aa-err">{a.last_error}</span>{/if}
              </span>
              <button class="link" onclick={() => ondeliveries(a.handle)}>{$t("inbox.deliveries")}</button>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if openQuestions.length}
      <section class="open-questions">
        <div class="oq-head">
          <MessageCircleQuestion size={15} />
          <span>{$t("inbox.openQuestions")}</span>
          <span class="oq-count">{openTotal}</span>
        </div>
        <ul class="oq-list">
          {#each openQuestions as q (q.id)}
            <li class="oq-row" class:oq-done={q.answeredIndex != null}>
              <button class="oq-item" onclick={() => openQuestion(q)}>
                <span class="oq-line">
                  <span class="row-ref">{q.ref}</span>
                  <span class="oq-title">{q.title}</span>
                  {#if q.state}<span class="oq-state">{q.state}</span>{/if}
                </span>
              </button>
              <div class="oq-detail">
                <div class="oq-body" class:open={bodyOpen.has(q.id)}>{q.body_md}</div>
                {#if q.body_md.length > 140 || q.body_md.includes("\n")}
                  <button class="link oq-more" onclick={() => toggleBody(q.id)}>
                    {$t(bodyOpen.has(q.id) ? "inbox.less" : "inbox.more")}
                  </button>
                {/if}
                {#if !isOptionQuestion(q)}
                  <button class="link oq-more" onclick={() => openQuestion(q)}>{$t("inbox.answerTicket")}</button>
                {:else if q.answeredIndex != null && changing !== q.id}
                  <div class="oq-answered">
                    <Check size={14} />
                    <span>{answeredLabel(q, $locale)}</span>
                    <button class="link oq-more" onclick={() => (changing = q.id)}>{$t("inbox.change")}</button>
                  </div>
                {:else}
                  <div class="oq-options">
                    {#each q.options as opt, i}
                      <button
                        class="oq-opt"
                        class:chosen={i === q.answeredIndex}
                        disabled={answerBusy !== 0}
                        onclick={() => pickOption(q, i)}
                      >{opt}</button>
                    {/each}
                  </div>
                  <button class="link oq-more" onclick={() => openQuestion(q)}>{$t("inbox.answerText")}</button>
                {/if}
                {#if answerError[q.id]}<div class="oq-error">{answerError[q.id]}</div>{/if}
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    <div class="inbox-error-wrap"><ErrorNote message={error} onRetry={load} /></div>

    {#if loading && !entries.length}
      <div class="inbox-loading"><Skeleton preset="rows" count={5} /></div>
    {:else if !filteredGroups.length}
      <div class="inbox-fill">
        <EmptyState
          icon={Bell}
          title={$t(filter === "unread" ? "inbox.emptyUnread" : "inbox.empty")}
        />
      </div>
    {:else}
      <ul class="inbox-list">
        {#each visibleGroups as g (g.ref)}
          {@const isOpen = expanded.has(g.ref)}
          <li class="group" class:unread={g.unread > 0}>
            <div class="group-row">
              <button
                class="expand"
                aria-label={$t(isOpen ? "inbox.collapse" : "inbox.expand")}
                aria-expanded={isOpen}
                onclick={() => toggle(g)}
              >
                <span class="dot" class:visible={g.unread} aria-hidden={!g.unread} aria-label={g.unread ? $t("filter.unread") : undefined}></span>
                <span class="chev" class:open={isOpen}><ChevronRight size={15} /></span>
              </button>
              <button class="group-main" onclick={() => open(g)}>
                <span class="row-body">
                  <span class="row-line">
                    <span class="row-ref">{g.ref}</span>
                    {#if g.unread}<span class="count">{$t("inbox.unread", {count: g.unread})}</span>{/if}
                  </span>
                  <span class="row-title">{g.title}</span>
                  <span class="row-summary" class:handover={!!g.events[0]?.handover_md}>{g.summary}</span>
                </span>
              </button>
              <div class="group-side">
                <span class="row-time" title={absoluteTime(g.latestAt, $locale)}>{formatTimestamp(g.latestAt, Date.now(), $locale)}</span>
                {#if g.unread}
                  <button class="mark" title={$t("inbox.markRead")} aria-label={$t("inbox.markRead")} onclick={() => markGroupRead(g)}>
                    <Check size={15} />
                  </button>
                {/if}
              </div>
            </div>

            {#if isOpen}
              <ul class="event-list">
                <!-- Afgeleide entries (deadline BETON-367, guardrail-concept
                     BETON-422) dragen allebei event_id 0, dus één ticket kan er
                     twee in dezelfde groep hebben: de reason hoort in de key. -->
                {#each g.events as e (`${e.reason}:${e.event_id}`)}
                  {@const meta = REASON_META[e.reason] ?? REASON_META.update}
                  {@const Icon = meta.icon}
                  <li>
                    <button class="event-row" class:unread={!e.read} onclick={() => open(g)}>
                      <span class="row-icon" title={meta.label}><Icon size={14} /></span>
                      {#if e.actor}<Avatar handle={e.actor} avatarUrl={avatarMap.get(e.actor)} size={20} />{/if}
                      <span class="event-reason" class:handover={!!e.handover_md}>{e.handover_md || (e.reason === "due" ? dueLabel(e, $locale) : `${e.actor ? `@${e.actor} ` : ""}${e.reason === "guardrail" ? guardrailLabel(e, $locale) : meta.label}`)}</span>
                      <span class="row-time" title={absoluteTime(e.created_at, $locale)}>{formatTimestamp(e.created_at, Date.now(), $locale)}</span>
                    </button>
                  </li>
                {/each}
              </ul>
            {/if}
          </li>
        {/each}
      </ul>

      {#if hasMore}
        <div class="more">
          <button class="link" onclick={() => (visible += PAGE)}>{$t("inbox.loadMore")}</button>
        </div>
      {/if}
    {/if}
  </div>
</DrawerDialog>

<style>
  .inbox-panel {
    display: flex;
    flex-direction: column;
    width: 100%;
  }
  .inbox-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-4) var(--space-5);
    border-bottom: 1px solid var(--border);
  }
  .inbox-title {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    font-weight: 700;
    font-size: var(--text-lg);
  }
  .unread-pill {
    background: var(--accent);
    color: var(--accent-text);
    border-radius: var(--radius-full);
    padding: 0 var(--space-3);
    font-size: var(--text-sm);
    font-weight: 700;
    min-width: 20px;
    text-align: center;
  }
  .inbox-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .inbox-filter {
    padding: var(--space-3) var(--space-5);
    border-bottom: 1px solid var(--border);
  }
  .link {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    background: none;
    border: none;
    color: var(--accent);
    cursor: pointer;
    font-size: var(--text-base);
    padding: var(--space-1) var(--space-2);
  }
  .link:disabled {
    color: var(--text-tertiary);
    cursor: default;
  }

  /* --- Onbereikbare agents (BETON-457) ------------------------------------- */
  .agent-alerts {
    border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--danger) 7%, transparent);
    padding-top: var(--space-2);
  }
  .aa-row {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-5);
    border-left: 3px solid var(--danger);
    color: var(--danger);
  }
  .aa-text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    font-size: var(--text-sm);
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .aa-err {
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }

  /* --- Open vragen (BETON-219) --------------------------------------------- */
  .open-questions {
    border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--accent) 5%, transparent);
  }
  .oq-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-5);
    font-size: var(--text-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--accent);
  }
  .oq-count {
    background: var(--accent);
    color: var(--accent-text);
    border-radius: var(--radius-full);
    padding: 0 var(--space-2);
    font-size: var(--text-xs);
    font-weight: 700;
    min-width: 18px;
    text-align: center;
    letter-spacing: 0;
  }
  .oq-list {
    list-style: none;
    margin: 0;
    padding: 0 0 var(--space-2);
  }
  .oq-item {
    display: flex;
    flex-direction: column;
    /* Expliciete stretch: anders erft de knop align-items:center van de globale
       button-reset en centreert de nowrap-inhoud, die dan de kaart uit puilt
       (BETON-271, zelfde oorzaak als .group-main). */
    align-items: stretch;
    gap: 3px;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    border-left: 3px solid var(--accent);
    cursor: pointer;
    color: inherit;
    padding: var(--space-3) var(--space-5);
  }
  .oq-item:hover {
    background: color-mix(in srgb, var(--accent) 8%, transparent);
  }
  .oq-line {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    min-width: 0;
  }
  .oq-title {
    font-size: var(--text-base);
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .oq-row {
    border-left: 3px solid var(--accent);
  }
  .oq-row.oq-done {
    border-left-color: var(--border);
  }
  .oq-row .oq-item {
    border-left: none;
    padding-bottom: var(--space-1);
  }
  .oq-detail {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
    padding: 0 var(--space-5) var(--space-3);
  }
  .oq-more {
    padding: 0;
    font-size: var(--text-xs);
  }
  .oq-options {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-self: stretch;
  }
  .oq-opt {
    flex: 1 1 130px;
    min-width: 130px;
    min-height: 38px;
    justify-content: center;
    text-align: center;
    white-space: normal;
    overflow-wrap: anywhere;
    padding: 8px 14px;
    border: 1px solid var(--accent);
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--accent);
    font: inherit;
    line-height: 1.3;
    cursor: pointer;
  }
  .oq-opt:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent) 14%, transparent);
  }
  .oq-opt.chosen {
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    font-weight: 600;
  }
  .oq-opt:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .oq-answered {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .oq-error {
    font-size: var(--text-xs);
    color: var(--danger);
  }
  .oq-body.open {
    display: block;
    -webkit-line-clamp: unset;
    line-clamp: unset;
  }
  .oq-body {
    align-self: stretch;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .oq-state {
    flex: none;
    font-size: var(--text-xs);
    padding: 1px 8px;
    border-radius: var(--radius-full);
    background: var(--surface-2);
    border: 1px solid var(--border);
    color: var(--text-secondary);
  }
  .inbox-error-wrap {
    margin: var(--space-3) var(--space-5) 0;
  }
  .inbox-loading {
    padding: var(--space-5) var(--space-7);
  }
  .inbox-fill {
    flex: 1;
    display: flex;
  }
  .inbox-list {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
  }
  .group {
    border-bottom: 1px solid var(--border);
  }
  .group.unread {
    background: color-mix(in srgb, var(--accent) 8%, transparent);
  }
  .group-row {
    display: flex;
    align-items: stretch;
    gap: var(--space-2);
    padding-right: var(--space-4);
  }
  .group-row:hover {
    background: color-mix(in srgb, var(--accent) 6%, transparent);
  }
  .expand {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-secondary);
    padding: var(--space-4) var(--space-2) var(--space-4) var(--space-5);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent);
    flex: 0 0 auto;
    visibility: hidden;
  }
  .dot.visible {
    visibility: visible;
  }
  .chev {
    display: inline-flex;
    transition: transform 0.12s ease;
  }
  .chev.open {
    transform: rotate(90deg);
  }
  .group-main {
    flex: 1;
    min-width: 0;
    /* De globale button-reset zet display:inline-flex + align-items:center +
       justify-content:center. Als kolom-flex mét align-items:stretch vult
       .row-body de volle breedte van .group-main; zonder de expliciete stretch
       erft het component het center-gedrag van de reset, waardoor .row-body zich
       verbreedt tot de nowrap-titel en die zowel links (ref afgekapt) als rechts
       (over de tijd) uit de rij puilt (BETON-269). */
    display: flex;
    flex-direction: column;
    align-items: stretch;
    text-align: left;
    background: none;
    border: none;
    cursor: pointer;
    color: inherit;
    padding: var(--space-4) 0;
  }
  .row-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .row-line {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
  }
  .row-ref {
    font-family: ui-monospace, monospace;
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--text-tertiary);
  }
  .count {
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--accent);
  }
  .row-title {
    font-size: var(--text-base);
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .row-summary {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .group-side {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex: 0 0 auto;
  }
  .row-time {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    white-space: nowrap;
    flex: 0 0 auto;
  }
  .mark {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    cursor: pointer;
    padding: var(--space-1);
  }
  .mark:hover {
    color: var(--accent);
    border-color: var(--accent);
  }
  .event-list {
    list-style: none;
    margin: 0;
    padding: 0 0 var(--space-2) 0;
  }
  .event-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    cursor: pointer;
    color: inherit;
    padding: var(--space-2) var(--space-5) var(--space-2) 44px;
  }
  .event-row:hover {
    background: color-mix(in srgb, var(--accent) 6%, transparent);
  }
  .event-row.unread {
    font-weight: 600;
  }
  .row-icon {
    color: var(--text-secondary);
    display: inline-flex;
    flex: 0 0 auto;
  }
  .event-reason {
    flex: 1;
    min-width: 0;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Een korte overdrachtsvraag moet zonder openen van het ticket leesbaar zijn. */
  .row-summary.handover, .event-reason.handover {
    white-space: normal;
    overflow: visible;
    overflow-wrap: anywhere;
  }
  .more {
    display: flex;
    justify-content: center;
    padding: var(--space-4);
  }
</style>
