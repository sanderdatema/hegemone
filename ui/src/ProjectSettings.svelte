<script>
  import { t, locale } from "./lib/i18n.js";
  import { api } from "./api.js";
  import AutoTextarea from "./AutoTextarea.svelte";
  import { labelHueOf, setLabelPalette } from "./lib/labelPalette.svelte.js";
  import { hexToHue } from "./lib/avatar.js";
  import { stateGroupLabel, agentTypeLabel } from "./lib/labels.js";
  import ErrorNote from "./ErrorNote.svelte";
  import Skeleton from "./Skeleton.svelte";
  import EmptyState from "./EmptyState.svelte";
  import Chip from "./Chip.svelte";
  import ConfirmBar from "./ConfirmBar.svelte";
  import Select from "./Select.svelte";
  import {
    ArrowLeft,
    Plus,
    Trash2,
    Check,
    RotateCcw,
    Sparkles,
    Flag,
    BookOpen,
    Info,
    Users,
    ChevronUp,
    ChevronDown,
    Tag,
  } from "@lucide/svelte";

  let {
    projectKey,
    readOnly = false,
    projectName,
    projectDescription = "",
    triageEnabled = false,
    wikiCompileEnabled = false,
    onback,
    onchanged,
  } = $props();

  const STATE_GROUPS = ["backlog", "unstarted", "started", "completed", "cancelled"];

  let error = $state("");
  let loading = $state(false);
  let triage = $state(triageEnabled);
  let triageBusy = $state(false);
  let backfillMsg = $state("");
  let wikiCompile = $state(wikiCompileEnabled);
  let wikiBusy = $state(false);
  let wikiBackfillMsg = $state("");

  let nameDraft = $state(projectName || "");
  let nameSaved = $state(false);

  // Projectomschrijving (BETON-26): bewerkbaar, opslaan bij blur/knop.
  let descDraft = $state(projectDescription || "");
  let descSaved = $state(false);

  let labels = $state([]);
  let milestones = $state([]);
  let states = $state([]);

  // Agent-toegang (BETON-123): per-type defaults + per-agent overrides.
  const ACCESS_LEVELS = ["none", "respond", "assign"];
  const ACCESS_LABEL = $derived({ none: $t("projectSettings.access.none"), respond: $t("projectSettings.access.respond"), assign: $t("projectSettings.access.assign") });
  let access = $state({ type_defaults: {}, agents: [] });
  let agentTypes = $derived([
    ...new Set(access.agents.map((a) => a.agent_type).filter(Boolean)),
  ]);

  // Nieuwe-invoer-drafts. (Labels krijgen hun kleur deterministisch uit de naam,
  // net als op de kaarten — geen kleurkiezer nodig.)
  let newLabel = $state({ name: "" });
  let newMilestone = $state({ name: "", due_date: "" });
  let newState = $state({
    name: "", group: "unstarted", color: "#3498db", closed: false, blocks_work: false,
  });
  async function load() {
    error = "";
    loading = true;
    try {
      [labels, milestones, states, access] = await Promise.all([
        api.labels(projectKey),
        api.milestones(projectKey),
        api.states(projectKey),
        api.access(projectKey),
      ]);
      setLabelPalette(labels, projectKey);
    } catch (e) {
      error = $t("projectSettings.loadFailed");
    } finally {
      loading = false;
    }
  }
  $effect(() => {
    projectKey;
    load();
  });

  async function guard(fn) {
    if (readOnly) return;
    error = "";
    try {
      await fn();
      onchanged?.();
    } catch (e) {
      error = e.message;
    }
  }

  async function saveName() {
    const name = nameDraft.trim();
    if (!name || name === projectName) return;
    await guard(async () => {
      const p = await api.updateProject(projectKey, { name });
      projectName = p.name;
      nameDraft = p.name;
      nameSaved = true;
    });
  }

  // --- Omschrijving ---
  async function saveDescription() {
    if (descDraft === (projectDescription || "")) return;
    await guard(async () => {
      const p = await api.updateProject(projectKey, { description: descDraft });
      projectDescription = p.description;
      descSaved = true;
      setTimeout(() => (descSaved = false), 1500);
    });
  }

  // --- Triage ---
  async function toggleTriage() {
    triageBusy = true;
    const next = !triage;
    await guard(async () => {
      const p = await api.setTriage(projectKey, next);
      triage = p.triage_enabled;
    });
    triageBusy = false;
  }
  async function backfill() {
    backfillMsg = "";
    await guard(async () => {
      const r = await api.backfillTriage(projectKey);
      backfillMsg = $t("projectSettings.triageQueued", {count: r.queued});
    });
  }

  // --- Wiki-compiler ---
  async function toggleWikiCompile() {
    wikiBusy = true;
    const next = !wikiCompile;
    await guard(async () => {
      const p = await api.setWikiCompile(projectKey, next);
      wikiCompile = p.wiki_compile_enabled;
    });
    wikiBusy = false;
  }
  async function wikiBackfill() {
    wikiBackfillMsg = "";
    await guard(async () => {
      const r = await api.backfillWikiCompile(projectKey);
      wikiBackfillMsg = $t("projectSettings.wikiQueued", {count: r.queued});
    });
  }

  // --- Agent-toegang (BETON-123) ---
  // Type-niveau: 'assign' is de globale default → als niveau wissen (null) i.p.v.
  // een expliciete rij. none/respond zetten wel een rij.
  async function setType(type, level) {
    await guard(async () => {
      access = await api.setTypeAccess(projectKey, type, level === "assign" ? null : level);
    });
  }
  // Per-agent: 'inherit' (null) wist de override; anders expliciet niveau.
  async function setAgent(handle, value) {
    const level = value === "inherit" ? null : value;
    await guard(async () => {
      access = await api.setAgentAccess(projectKey, handle, level);
    });
  }

  // --- Labels ---
  async function addLabel() {
    const name = newLabel.name.trim();
    if (!name) return;
    await guard(async () => {
      await api.createLabel(projectKey, { name });
      newLabel = { name: "" };
      labels = await api.labels(projectKey);
      setLabelPalette(labels, projectKey);
    });
  }
  async function setLabelColor(l, color) {
    await guard(async () => {
      await api.updateProjectLabel(projectKey, l.name, { color });
      labels = await api.labels(projectKey);
      setLabelPalette(labels, projectKey);
    });
  }
  async function delLabel(name) {
    await guard(async () => {
      await api.deleteProjectLabel(projectKey, name);
      labels = await api.labels(projectKey);
      setLabelPalette(labels, projectKey);
    });
  }

  // --- Milestones ---
  async function addMilestone() {
    const name = newMilestone.name.trim();
    if (!name) return;
    await guard(async () => {
      await api.createMilestone(projectKey, {
        name,
        due_date: newMilestone.due_date || null,
      });
      newMilestone = { name: "", due_date: "" };
      milestones = await api.milestones(projectKey);
    });
  }
  async function toggleMilestone(m) {
    await guard(async () => {
      await api.updateMilestone(projectKey, m.name, {
        status: m.status === "completed" ? "open" : "completed",
      });
      milestones = await api.milestones(projectKey);
    });
  }
  async function setMilestoneDueDate(m, dueDate) {
    await guard(async () => {
      await api.updateMilestone(projectKey, m.name, { due_date: dueDate || null });
      milestones = await api.milestones(projectKey);
    });
  }
  let confirmDeleteMilestone = $state(null);
  async function delMilestone(name) {
    await guard(async () => {
      await api.deleteMilestone(projectKey, name);
      milestones = await api.milestones(projectKey);
    });
    confirmDeleteMilestone = null;
  }

  // --- States ---
  async function addState() {
    const name = newState.name.trim();
    if (!name) return;
    await guard(async () => {
      await api.createState(projectKey, {
        name,
        group: newState.group,
        color: newState.color,
        sort_order: states.length,
        closed: newState.closed,
        blocks_work: newState.blocks_work,
      });
      newState = {
        name: "", group: "unstarted", color: "#3498db", closed: false, blocks_work: false,
      };
      states = await api.states(projectKey);
    });
  }
  async function setStateWorkBlock(s, blocksWork) {
    await guard(async () => {
      await api.updateState(projectKey, s.name, { blocks_work: blocksWork });
      states = await api.states(projectKey);
    });
  }

  // Naam bewerken (BETON-177): inline, zelfde patroon als de ticket-titel in de
  // Drawer (input i.p.v. tekst, opslaan bij blur/Enter). Hernoemen is veilig —
  // items refereren via state_id — de server bewaakt uniciteit (409).
  let editingStateName = $state(null);
  let stateNameDraft = $state("");
  function startEditStateName(s) {
    editingStateName = s.name;
    stateNameDraft = s.name;
  }
  async function saveStateName(s) {
    const name = stateNameDraft.trim();
    editingStateName = null;
    if (!name || name === s.name) return;
    await guard(async () => {
      await api.updateState(projectKey, s.name, { name });
      states = await api.states(projectKey);
    });
  }

  async function setStateColor(s, color) {
    await guard(async () => {
      await api.updateState(projectKey, s.name, { color });
      states = await api.states(projectKey);
    });
  }

  // Volgorde (BETON-177): omhoog/omlaag wisselt sort_order met de buur —
  // geen herbalancering nodig, de lijst sorteert al op sort_order.
  async function moveState(index, direction) {
    const other = index + direction;
    if (other < 0 || other >= states.length) return;
    const a = states[index];
    const b = states[other];
    await guard(async () => {
      await api.updateState(projectKey, a.name, { sort_order: b.sort_order });
      await api.updateState(projectKey, b.name, { sort_order: a.sort_order });
      states = await api.states(projectKey);
    });
  }

  // Verwijderen (BETON-351): de server bewaakt de laatste kolom en items die
  // er nog in staan (409 met aantal) — die foutmelding komt via guard() in
  // `error` terecht, geen client-side gok naar wanneer het mag.
  let confirmDeleteState = $state(null);
  async function delState(name) {
    await guard(async () => {
      await api.deleteState(projectKey, name);
      states = await api.states(projectKey);
    });
    confirmDeleteState = null;
  }
</script>

<div class="ps">
  <header class="ps-top">
    <button class="icon-btn" title={$t("common.back")} onclick={() => onback?.()}><ArrowLeft size={18} /></button>
    <h3 class="ps-title"><strong>{projectKey}</strong> — {$t("projectSettings.title")}</h3>
  </header>
  <ErrorNote message={error} onRetry={load} />

  {#if readOnly}<p class="project-readonly-note" role="status">{$t("api.project_archived_readonly")}</p>{/if}
  <fieldset disabled={readOnly} class="settings-fields">
  <section class="ps-sec">
    <div class="ps-head"><Info size={14} /> {$t("projectSettings.name")}</div>
    <form class="desc-edit name-edit" onsubmit={(e) => { e.preventDefault(); saveName(); }}>
      <label for="project-name" class="ps-note">{$t("projectSettings.nameLabel")}</label>
      <input id="project-name" bind:value={nameDraft} oninput={() => { nameSaved = false; }} required maxlength="200" />
      <div class="desc-actions">
        <button class="primary sm" type="submit" disabled={!nameDraft.trim() || nameDraft.trim() === projectName}>
          <Check size={14} /> {$t("projectSettings.saveName")}
        </button>
        {#if nameSaved}<span class="ps-ok">{$t("common.saved")}</span>{/if}
      </div>
    </form>
  </section>

  <!-- Omschrijving -->
  <section class="ps-sec">
    <div class="ps-head"><Info size={14} /> {$t("ticket.description")}</div>
    <span class="ps-note">
      {$t("projectSettings.descriptionHint")}
    </span>
    <div class="desc-edit">
      <AutoTextarea
        rows="3"
        bind:value={descDraft}
        placeholder={$t("projectSettings.descriptionHint")}
        onblur={saveDescription}
        onsubmit={() => { if (descDraft !== (projectDescription || "")) saveDescription(); }}
      />
      <div class="desc-actions">
        <button class="primary sm" onclick={saveDescription} disabled={descDraft === (projectDescription || "")}>
          <Check size={14} /> {$t("common.save")}
        </button>
        {#if descSaved}<span class="ps-ok">{$t("common.saved")}</span>{/if}
      </div>
    </div>
  </section>

  <!-- Triage -->
  <section class="ps-sec">
    <div class="ps-head"><Sparkles size={15} /> {$t("projectSettings.triage")}</div>
    <div class="ps-row ps-triage">
      <span class="ps-note">
        {$t("projectSettings.triageNote")}
      </span>
      <button
        class="switch"
        class:on={triage}
        role="switch"
        aria-checked={triage}
        aria-label={$t("projectSettings.triage")}
        disabled={triageBusy}
        onclick={toggleTriage}
      >
        <span class="knob"></span>
      </button>
    </div>
    {#if triage}
      <div class="ps-row">
        <button class="sm" onclick={backfill}>
          <RotateCcw size={14} /> {$t("projectSettings.triageExisting")}
        </button>
        {#if backfillMsg}<span class="ps-ok">{backfillMsg}</span>{/if}
      </div>
    {/if}
  </section>

  <!-- Wiki-compiler -->
  <section class="ps-sec">
    <div class="ps-head"><BookOpen size={15} /> {$t("projectSettings.wiki")}</div>
    <div class="ps-row ps-triage">
      <span class="ps-note">
        {$t("projectSettings.wikiNote")}
      </span>
      <button
        class="switch"
        class:on={wikiCompile}
        role="switch"
        aria-checked={wikiCompile}
        aria-label={$t("projectSettings.wiki")}
        disabled={wikiBusy}
        onclick={toggleWikiCompile}
      >
        <span class="knob"></span>
      </button>
    </div>
    {#if wikiCompile}
      <div class="ps-row">
        <button class="sm" onclick={wikiBackfill}>
          <RotateCcw size={14} /> {$t("projectSettings.wikiExisting")}
        </button>
        {#if wikiBackfillMsg}<span class="ps-ok">{wikiBackfillMsg}</span>{/if}
      </div>
    {/if}
  </section>

  <!-- Agent-toegang (BETON-123) -->
  <section class="ps-sec">
    <div class="ps-head"><Users size={15} /> {$t("projectSettings.access")}</div>
    <span class="ps-note">
      {$t("projectSettings.accessNote")}
    </span>

    {#if loading}
      <Skeleton preset="lines" count={3} />
    {:else if agentTypes.length}
      <div class="ac-block">
        <div class="ac-sub">{$t("projectSettings.perType")}</div>
        {#each agentTypes as agentType}
          <div class="ps-row ac-row">
            <span class="ac-name">{agentTypeLabel(agentType, $locale)}</span>
            <div class="seg" role="group" aria-label={$t("projectSettings.accessFor", {name: agentTypeLabel(agentType, $locale)})}>
              {#each ACCESS_LEVELS as lvl}
                <button
                  class="seg-btn"
                  class:on={(access.type_defaults[agentType] ?? "assign") === lvl}
                  onclick={() => setType(agentType, lvl)}
                >{ACCESS_LABEL[lvl]}</button>
              {/each}
            </div>
          </div>
        {/each}
      </div>

      <div class="ac-block">
        <div class="ac-sub">{$t("projectSettings.perAgent")}</div>
        {#each access.agents as a (a.handle)}
          <div class="ps-row ac-row">
            <span class="ac-name">
              @{a.handle}
              <span class="ac-type">{a.agent_type ? agentTypeLabel(a.agent_type, $locale) : "—"}</span>
            </span>
            <span class="ac-eff">{$t("projectSettings.effective", {level: ACCESS_LABEL[a.effective]})}</span>
            <Select
              class="ac-select"
              ariaLabel={$t("projectSettings.accessFor", {name: "@" + a.handle})}
              value={a.override ?? "inherit"}
              options={[
                { value: "inherit", label: $t("projectSettings.inherit") },
                ...ACCESS_LEVELS.map((lvl) => ({ value: lvl, label: ACCESS_LABEL[lvl] })),
              ]}
              onchange={(v) => setAgent(a.handle, v)}
            />
          </div>
        {/each}
      </div>
    {:else}
      <EmptyState icon={Users} title={$t("projectSettings.noAgents")} />
    {/if}
  </section>

  <!-- Labels -->
  <section class="ps-sec">
    <div class="ps-head">Labels</div>
    {#if loading}
      <Skeleton preset="lines" count={2} />
    {:else}
      <div class="chips">
        {#each labels as l (l.name)}
          <input
            type="color"
            class="swatch sm"
            value={hexToHue(l.color) === null ? "#3498db" : l.color}
            title={$t("projectSettings.colorFor", {name: l.name})}
            onchange={(e) => setLabelColor(l, e.currentTarget.value)}
          />
          <Chip
            tone="label"
            hue={labelHueOf(l.name)}
            removable
            onremove={() => delLabel(l.name)}
            title={$t("projectSettings.removeLabel")}
          >
            {l.name}
          </Chip>
        {:else}
          <EmptyState icon={Tag} title={$t("projectSettings.noLabels")} />
        {/each}
      </div>
    {/if}
    <div class="add-row">
      <input placeholder={$t("projectSettings.newLabel")} bind:value={newLabel.name}
             onkeydown={(e) => e.key === "Enter" && addLabel()} />
      <button class="primary sm" onclick={addLabel}><Plus size={14} /> {$t("common.add")}</button>
    </div>
  </section>

  <!-- Milestones -->
  <section class="ps-sec">
    <div class="ps-head"><Flag size={14} /> Milestones</div>
    {#if loading}
      <Skeleton preset="lines" count={2} />
    {:else}
      {#each milestones as m (m.name)}
        <div class="ps-row ps-item">
          <span class="ms-name" class:done={m.status === "completed"}>{m.name}</span>
          {#if m.items_total}
            <span
              class="ms-progress"
              class:complete={m.items_done === m.items_total}
              title={$t("projectSettings.progress", {done: m.items_done, total: m.items_total})}
            >{m.items_done}/{m.items_total}</span>
          {/if}
          <input
            type="date"
            class="ms-due-input"
            class:overdue={m.overdue}
            value={m.due_date ? m.due_date.slice(0, 10) : ""}
            title={$t("projectSettings.deadline")}
            onchange={(e) => setMilestoneDueDate(m, e.currentTarget.value)}
          />
          <span class="ps-actions">
            <button class="icon-btn sm" title={$t(m.status === "completed" ? "projectSettings.reopen" : "projectSettings.finish")}
                    onclick={() => toggleMilestone(m)}>
              {#if m.status === "completed"}<RotateCcw size={15} />{:else}<Check size={15} />{/if}
            </button>
            <button class="icon-btn sm danger-quiet" title={$t("common.remove")} onclick={() => (confirmDeleteMilestone = m.name)}>
              <Trash2 size={15} />
            </button>
          </span>
        </div>
        {#if confirmDeleteMilestone === m.name}
          <ConfirmBar
            inline
            role="alertdialog"
            ariaLabel={$t("projectSettings.confirmMilestone")}
            focus
            message={$t("projectSettings.deleteMilestone", {name: m.name})}
            confirmLabel={$t("projectSettings.confirmDelete")}
            cancelLabel={$t("common.cancel")}
            danger
            onconfirm={() => delMilestone(m.name)}
            oncancel={() => (confirmDeleteMilestone = null)}
          />
        {/if}
      {:else}
        <EmptyState icon={Flag} title={$t("projectSettings.noMilestones")} />
      {/each}
    {/if}
    <div class="add-row">
      <input placeholder={$t("projectSettings.newMilestone")} bind:value={newMilestone.name}
             onkeydown={(e) => e.key === "Enter" && addMilestone()} />
      <input type="date" bind:value={newMilestone.due_date} title={$t("projectSettings.optionalDeadline")} />
      <button class="primary sm" onclick={addMilestone}><Plus size={14} /> {$t("common.add")}</button>
    </div>
  </section>

  <!-- States / kolommen -->
  <section class="ps-sec">
    <div class="ps-head">{$t("projectSettings.columns")}</div>
    {#if loading}<Skeleton preset="lines" count={3} />{/if}
    {#each states as s, i (s.name)}
      <div class="ps-row ps-item st-row">
        <input
          type="color"
          class="swatch sm"
          value={s.color}
          title={$t("projectSettings.color")}
          onchange={(e) => setStateColor(s, e.currentTarget.value)}
        />
        {#if editingStateName === s.name}
          <!-- svelte-ignore a11y_autofocus -->
          <input
            class="st-name-edit"
            bind:value={stateNameDraft}
            autofocus
            onblur={() => saveStateName(s)}
            onkeydown={(e) => e.key === "Enter" && saveStateName(s)}
          />
        {:else}
          <button class="st-name-btn" title={$t("projectSettings.editName")} onclick={() => startEditStateName(s)}>
            {s.name}
          </button>
        {/if}
        <span class="st-group">{stateGroupLabel(s.group, $locale)}</span>
        <span class="st-badge-cell">{#if s.closed}<span class="st-badge">{$t("projectSettings.closed")}</span>{/if}</span>
        <span class="st-order-btns">
          <button
            class="icon-btn sm"
            title={$t("projectSettings.up")}
            disabled={i === 0}
            onclick={() => moveState(i, -1)}
          ><ChevronUp size={14} /></button>
          <button
            class="icon-btn sm"
            title={$t("projectSettings.down")}
            disabled={i === states.length - 1}
            onclick={() => moveState(i, 1)}
          ><ChevronDown size={14} /></button>
        </span>
        <label class="closed-check" title={$t("projectSettings.respondOnly")}>
          <input
            type="checkbox"
            checked={s.blocks_work}
            onchange={(event) => setStateWorkBlock(s, event.currentTarget.checked)}
          />
          {$t("projectSettings.noExecution")}
        </label>
        <button
          class="icon-btn sm"
          title={$t(states.length === 1 ? "projectSettings.lastColumn" : "common.remove")}
          disabled={states.length === 1}
          onclick={() => (confirmDeleteState = s.name)}
        >
          <Trash2 size={15} />
        </button>
      </div>
      {#if confirmDeleteState === s.name}
        <ConfirmBar
          inline
          role="alertdialog"
          ariaLabel={$t("projectSettings.confirmColumn")}
          focus
          message={$t("projectSettings.deleteColumn", {name: s.name})}
          confirmLabel={$t("projectSettings.confirmDelete")}
            cancelLabel={$t("common.cancel")}
          danger
          onconfirm={() => delState(s.name)}
          oncancel={() => (confirmDeleteState = null)}
        />
      {/if}
    {/each}
    <div class="add-row add-state st-row">
      <input type="color" class="swatch" bind:value={newState.color} title={$t("projectSettings.color")} />
      <input placeholder={$t("projectSettings.newColumn")} bind:value={newState.name}
             onkeydown={(e) => e.key === "Enter" && addState()} />
      <Select
        bind:value={newState.group}
        title={$t("projectSettings.group")}
        ariaLabel={$t("projectSettings.group")}
        options={STATE_GROUPS.map((g) => ({ value: g, label: stateGroupLabel(g, $locale) }))}
      />
      <label class="closed-check st-add-closed"><input type="checkbox" bind:checked={newState.closed} /> {$t("projectSettings.closed")}</label>
      <label class="closed-check st-add-block" title={$t("projectSettings.respondOnlyNew")}>
        <input type="checkbox" bind:checked={newState.blocks_work} /> {$t("projectSettings.noExecution")}
      </label>
      <button class="primary sm st-add-btn" onclick={addState}><Plus size={14} /> {$t("common.add")}</button>
    </div>
  </section>
  </fieldset>
</div>

<style>
  .settings-fields { padding: 0; border: 0; margin: 0; min-width: 0; }
  .ps-top {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }
  .ps-title {
    font-size: var(--text-lg);
    font-weight: 600;
    margin: 0;
  }
  .ps-sec {
    padding: 14px 0;
    border-top: 1px solid var(--border);
  }
  .ps-head {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-sm);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
    margin-bottom: 10px;
  }
  .ps-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 6px 0;
  }
  .ps-note {
    flex: 1;
    font-size: var(--text-base);
    color: var(--text-secondary);
    line-height: 1.4;
  }
  .ps-ok {
    font-size: var(--text-base);
    color: var(--success);
  }
  /* Toggle-switch */
  .switch {
    flex: 0 0 auto;
    width: 42px;
    height: 24px;
    /* Overschrijf de globale button-min-height (34px, mobiel 40px) — anders wordt
       de pil eivormig. */
    min-height: 0;
    padding: 0;
    border-radius: var(--radius-full);
    background: var(--surface-3);
    /* --border-strong haalde 1,60/1,67; een schakelaar die uit staat moet
       nog steeds als bedienbaar lezen (BETON-418). */
    border: 1px solid var(--border-interactive);
    position: relative;
    transition: background var(--dur-fast) var(--ease);
  }
  .switch .knob {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--surface);
    box-shadow: var(--shadow-sm);
    transition: transform var(--dur-fast) var(--ease);
  }
  .switch.on {
    background: var(--accent);
    border-color: var(--accent);
  }
  .switch.on .knob {
    transform: translateX(18px);
  }
  /* Label-chips: Chip.svelte (tone="label") tekent de pill zelf. */
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
  }
  .name-edit {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .name-edit input { width: 100%; }
  .desc-edit {
    margin-top: 8px;
  }
  .desc-edit :global(textarea) {
    width: 100%;
  }
  .desc-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 6px;
  }
  .add-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 4px;
  }
  .add-row input:not([type="color"]):not([type="checkbox"]) {
    flex: 1 1 140px;
    min-width: 0;
  }
  /* Toevoegen-knop: niet laten krimpen en icoon+tekst op één regel houden,
     anders wrapt "Toevoegen" onder het +-icoon. */
  .add-row .primary {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
  }
  .swatch {
    width: 34px;
    height: 34px;
    padding: 2px;
    flex: 0 0 auto;
    cursor: pointer;
  }
  .ps-item {
    padding: 7px 0;
    border-bottom: 1px solid var(--border);
  }
  .ms-name {
    flex: 1;
    min-width: 0;
    font-weight: 500;
  }
  .ms-name.done {
    text-decoration: line-through;
    color: var(--text-tertiary);
  }
  .ms-progress {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
    padding: 0 6px;
  }
  .ms-progress.complete {
    color: var(--success);
  }
  .ms-due-input {
    flex: 0 0 auto;
    min-height: 0;
    padding: 3px 6px;
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .ms-due-input.overdue {
    color: var(--danger);
    font-weight: 600;
  }
  .ps-actions {
    display: inline-flex;
    gap: 2px;
    flex: 0 0 auto;
  }
  .st-name-btn {
    flex: 1;
    min-width: 0;
    /* globale button-reset centreert (inline-flex + justify-content:center) */
    justify-content: flex-start;
    text-align: left;
    font-weight: 500;
    background: none;
    border: none;
    padding: 2px 4px;
    min-height: unset;
    color: inherit;
  }
  .st-name-btn:hover {
    background: var(--surface-3);
    border-radius: var(--radius-sm, 4px);
  }
  .st-name-edit {
    flex: 1;
    min-width: 0;
  }
  .st-order-btns {
    display: inline-flex;
    gap: 2px;
    flex: 0 0 auto;
  }
  .swatch.sm {
    width: 24px;
    height: 24px;
  }
  .st-group {
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }
  .st-badge {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    background: var(--surface-3);
    padding: 1px 7px;
    border-radius: var(--radius-full);
  }
  /* Gedeeld kolomraster voor alle state-rijen en de invoerrij (BETON-424):
     kleur | naam | groep | gesloten-badge | pijltjes | niet uitvoeren | prullenbak.
     Elke rij heeft dezelfde template en de 1fr-kolom is de enige rekbare, dus de
     rechterkolommen staan in elke rij op dezelfde x. */
  .st-row {
    display: grid;
    grid-template-columns: 24px minmax(0, 1fr) 7.5rem 6rem 3.75rem 8.5rem 2rem;
    column-gap: 10px;
    align-items: center;
  }
  .st-row > .st-name-btn,
  .st-row > .st-name-edit {
    flex: none;
    width: 100%;
  }
  .st-badge-cell {
    display: flex;
  }
  .st-badge {
    white-space: nowrap;
  }
  .st-row .closed-check {
    white-space: nowrap;
  }
  .add-state {
    row-gap: 8px;
  }
  .add-state > input:not([type="color"]),
  .add-state > :global(.select-trigger) {
    width: 100%;
    min-width: 0;
  }
  .add-state .st-add-block {
    grid-column: 6;
  }
  .add-state .st-add-btn {
    grid-column: 2 / -1;
    justify-self: start;
  }
  @media (max-width: 640px) {
    /* Smal: rijen mogen wrappen, nooit horizontaal scrollen. */
    .st-row {
      display: flex;
      flex-wrap: wrap;
      row-gap: 6px;
    }
    .st-row > .st-name-btn,
    .st-row > .st-name-edit {
      flex: 1 1 8rem;
      width: auto;
    }
    .st-badge-cell:empty {
      display: none;
    }
    .add-state > input:not([type="color"]),
    .add-state > :global(.select-trigger) {
      width: auto;
      flex: 1 1 8rem;
    }
  }
  .closed-check {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: var(--text-base);
    color: var(--text-secondary);
    flex: 0 0 auto;
  }
  /* Agent-toegang (BETON-123) */
  .ac-block {
    margin-top: 12px;
  }
  .ac-sub {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-tertiary);
    margin-bottom: 4px;
  }
  .ac-row {
    gap: 10px;
    padding: 5px 0;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .ac-name {
    flex: 1;
    min-width: 90px;
    font-weight: 500;
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
  }
  .ac-type {
    font-size: var(--text-xs);
    font-weight: 400;
    color: var(--text-tertiary);
  }
  .ac-eff {
    font-size: var(--text-sm);
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
  }
  :global(.ac-select) {
    flex: 0 0 auto;
    min-height: 0;
    padding: 4px 8px;
    font-size: var(--text-base);
  }
  /* Segmented control voor de per-type keuze */
  .seg {
    display: inline-flex;
    flex: 0 0 auto;
    border: 1px solid var(--border-interactive);
    border-radius: var(--radius-full);
    overflow: hidden;
  }
  .seg-btn {
    min-height: 0;
    padding: 4px 12px;
    font-size: var(--text-sm);
    border: none;
    border-radius: 0;
    /* BETON-418: niet-gekozen niveau = beschikbare actie, dus geen
       grijs-op-grijs (--surface-2 + --text-secondary); dat is de look van
       `:disabled`. Gekozen blijft vol accent. */
    background: var(--surface);
    color: var(--text);
  }
  .seg-btn:not(:last-child) {
    border-right: 1px solid var(--border-interactive);
  }
  .seg-btn.on {
    background: var(--accent);
    color: var(--accent-text);
  }
</style>
