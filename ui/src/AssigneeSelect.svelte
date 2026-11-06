<script>
  // Gegroepeerde toewijs-select (BETON-366): één plek voor de markup die
  // Drawer/App(bulk-bar+filter)/NewItem eerst allemaal apart als platte
  // `{#each users as u}<option>` opbouwden. De groepering zelf komt uit
  // lib/agentType.js:groupAssignees (puur, vitest-getest).
  import { t } from "./lib/i18n.js";
  import { groupAssignees } from "./lib/agentType.js";
  import Select from "./Select.svelte";

  let {
    value,
    users,
    me = null,
    disabled = false,
    onchange,
    allowNone = true,
    ariaLabel = undefined,
    id = undefined,
    class: klass = "",
    // Kiezer die na een keuze leeg blijft (bulkbalk), zie Select.svelte.
    action = false,
  } = $props();

  let groups = $derived(
    groupAssignees(users, me, { keep: value }).map((g) => ({
      label: ({ "Aan mij": $t("filter.mine"), "Mensen": $t("assignee.people"), "Overig": $t("assignee.other") })[g.label] ?? g.label,
      options: g.options.map((u) => ({ value: u.handle, label: `@${u.handle}` })),
    }))
  );
  let none = $derived(
    allowNone === false
      ? []
      : [{ value: "", label: allowNone === true ? $t("assignee.none") : allowNone }]
  );
</script>

<!-- Eigen keuzelijst i.p.v. native <select> (BETON-439, traag in Safari). -->
<Select
  {id}
  class={klass}
  ariaLabel={ariaLabel ?? $t("filter.assignee")}
  {value}
  {disabled}
  options={none}
  {groups}
  {action}
  {onchange}
/>
