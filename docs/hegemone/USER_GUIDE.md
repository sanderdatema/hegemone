# Hegemone user guide

Hegemone brings project tickets, conversations and reusable knowledge together
for people and AI agents. This guide explains everyday use of the application.
The [README](README.md) covers installation; [agent setup](AGENT_SETUP.md) covers
MCP and webhook connections. AI features are optional: you can manage projects
and tickets without configuring a model or an external agent.

## First sign-in and orientation

On a new installation, follow the setup wizard described in the README. The
first human administrator creates the installation and can then create projects
and additional identities. Save a newly displayed API key in your password
manager: the application does not show it again. Signing in exchanges the key
for a browser session. Sign out from the account menu when finished on a shared
computer.

The top bar contains the project picker, search, filters, view controls, inbox,
More actions, New ticket and your account menu. On smaller screens, some controls
move into menus. Hover over icon buttons to see their purpose.

- Use the project picker to open a project or the cross-project Overview.
  Type a project code or name in its search field to narrow the choices.
  Quiet projects remain searchable in their own group.
- Switch between Board and List to work with the same project tickets.
- Use Wiki for persistent knowledge and Activity for the project event history.
- Open your account menu for My tickets, My settings, appearance, language and
  sign-out. My tickets collects your open assignments across projects.
- Open More actions for project management and, when permitted, agent management,
  installation settings, triage chat and webhook deliveries.

Choose English or Dutch from the account menu. This changes the browser
interface, not existing tickets, project names or wiki text. Installation language
controls new server-generated messages; AI output language is a separate setting.
External agents control their own output language.

## Projects and workflow

Open **More actions → Manage projects** to create a project. Choose a short,
stable project key and a descriptive name. The key appears in ticket references:
a fictional project `DEMO` has tickets such as `DEMO-12`. Use these references
when discussing work or linking tickets.

Project settings contain the project description, columns, labels, milestones,
automatic triage, wiki compilation and agent access. New projects inherit the
project template; changing the template does not rewrite existing projects.

A column is a workflow state. Its name, order, color, group and execution policy
are configurable. A closed/collapsed column and a column that blocks agent
execution are different settings. Closing a column visually does not itself
specify whether an agent may execute work there. Use the execution policy when
you want a waiting state in which agents may respond but must not begin work.
A column containing tickets cannot be deleted; move its tickets first.

Use labels to categorize work and milestones to group tickets toward a goal.
Milestones show progress and can have a due date. Agent work-class labels are
`routine`, `standaard` and `complex`; these stored values remain the same in both
interface languages. Agent/model mappings are managed separately.

Projects can be archived and restored from project management. Archived projects
appear in a separate group in the project picker and remain readable through
their existing links. They are read-only: tickets, comments, answers, attachments,
wiki pages and project settings cannot be changed until a human restores the
project. Background work also stops. Personal read markers still work so reading
history does not leave it permanently unread. Archiving is distinct from
completing a milestone or closing an individual ticket.

## Create and describe a ticket

Select a project, then choose **New ticket**. Give the ticket a concrete title
and explain the expected outcome in the description. Set the available workflow
fields, such as state, assignee, priority, workload, labels, milestone and due
date, as appropriate. A ticket reference is assigned when the ticket is created.

A useful description states what happens now, what should happen instead and how
to check the result. For a bug, include reproducible steps and relevant error
text. For a feature, describe who needs it and what a successful interaction looks
like. Attach a small relevant image or document when it helps explain the issue.

Open a ticket to see its detail panel. You can update fields, edit the description,
read the conversation and inspect the activity history. A plan is separate from
the description: use it for implementation steps, verification and handover.
For agent-created tickets, add the plan before discussion begins; later plan and
description edits can be restricted by the workflow.

Ticket fields have different purposes:

| Field | Use |
| --- | --- |
| State | The current step in the project's workflow |
| Assignee | The person or agent responsible for the next action |
| Priority | Urgency relative to other work |
| Workload | Estimated size of the task |
| Labels | Categories, including an agent work class where applicable |
| Milestone | A delivery goal shared with other tickets |
| Due date | When the work needs to be completed |
| Deferred-until date | When deferred work should return to its previous state |

Changing the assignee is a handover. When an agent hands work to a person, it must
include a concrete question or a brief handover explaining what is needed. A
person should not have to reconstruct the request from a long conversation.

## Board, list, filters and search

On the board, tickets appear in state columns. Open a card to inspect it or drag
it to another column to change its state. Closed columns can be expanded. Large
closed columns initially load a limited number of tickets; **Show more** retrieves
the next page. The remaining count concerns unloaded tickets, not cards hidden
by a quick filter. With a filter active, the column heading counts visible cards.

List view presents ticket fields as rows and sortable columns. Use selection
mode for operations on several tickets. Review the selected set before applying
bulk changes. Shift-selection can select a range; selection controls can also
select a column's visible tickets.

Use the filter panel for assignee, label, workload and milestone filters.
Quick filters include Assigned to me, Unread, Open question, Overdue, This week
and Unassigned. Clear filters if a ticket appears to be missing. Unread is
personal: opening or marking a ticket read changes your own unread state.

Search can operate within the current project or across all projects. It looks
in ticket titles, descriptions and comments. A result marked as a comment match
opens the matching conversation entry. Searching by a known ticket reference is
a direct way to find it. The cross-project scope has its own results presentation;
it is not a board column filter.

Project and ticket URLs, including supported view and filter parameters, can be
bookmarked or shared with someone who has access. Authentication and permissions
still apply to shared links.

## Conversations and questions

Comments support Markdown, attachments, ticket references and `@handle` mentions.
Mention a person or agent when the next response is specifically for them. Keep
comments readable: lead with the outcome or request, then add supporting detail.
When referring to an earlier comment, name its author, date or a short quote,
rather than expecting another person to recognize an internal numeric ID.

A question is a structured request for a human answer, distinct from an ordinary
comment. It can offer answer options or accept a free-text answer. Answer using
the question's answer controls so the workflow records it as resolved. Merely
posting an unrelated comment does not necessarily resolve an open question.

Asking a human a question assigns the ticket to that person; after the answer,
the workflow can return it to the prior assignee. With multiple open questions,
work resumes only when the applicable open questions have been resolved. An open
question can prevent reassignment or completion. If a question is obsolete or
answered elsewhere, withdraw it with a reason instead of leaving it open.
For an open triage question, a human can choose **Not relevant** and confirm.
The question remains visible with its withdrawal reason; it is not recorded as
an answer and no longer counts as an open question. If it was the last open
question, the normal workflow can return the ticket to its prior assignee.
Already delivered answers can be locked against editing.

The inbox collects relevant notifications and open questions. Open the linked
ticket for context, and use the provided read/answer controls as appropriate.
An inbox entry is a notification, not evidence that an external agent has already
started or completed work.

## Related work, subtasks and archiving

Use parent/child tickets to split a larger result into independently trackable
steps. Parent progress reflects the child tickets. Review the overall result
before completing the parent; a progress count does not replace that review.

Relations explain how tickets interact:

- **Blocked by** identifies work that must finish before this ticket can proceed.
- **Blocks** is the corresponding relationship seen from the prerequisite ticket.
- **Relates to** connects relevant work without declaring an execution order.
- **Duplicate of** identifies the canonical ticket where work should continue.

Ticket archiving removes a ticket from ordinary active views while preserving
its history. Use the archive controls to inspect or restore it. Permanent deletion
is a separate human-only action; archiving is the normal reversible choice.
The ticket menu also offers duplication and Markdown export.

Human administrators can use ticket locks and guardrails to limit agent work.
An agent may propose a guardrail; activating or lifting one is a human action.
A lock or stand-down is a stop signal, including when a ticket still has an
assignee. Restore or explicitly release work through the applicable controls
before expecting an agent to continue.

## Wiki and durable knowledge

Use the wiki for conventions, decisions and operational knowledge that should
outlive a ticket. Global pages apply across projects; project pages belong to
one project. Give each page a clear title and stable slug. Link related pages and
keep instructions concise enough to remain useful when loaded as agent context.

Agents access this knowledge through memory tools. A bounded memory response
includes complete selected pages and an index of pages not loaded; agents can
fetch additional pages when needed. The index does not mean that all page bodies
were included.

The optional wiki compiler can turn completed project work into persistent
knowledge. Enable it deliberately in project settings after configuring the AI
provider and installation-level background-work setting. Review generated
knowledge for accuracy. Wiki pages retain revision history; editing knowledge is
not the same operation as changing the original ticket.

## AI triage and external agents

Automatic triage can classify tickets, suggest or apply workflow metadata,
detect duplicates and request missing information. It requires a configured AI
provider and the relevant installation and project opt-ins. Project settings can
queue existing tickets for triage. AI output should be reviewed like any other
contribution.

Triage chat is a separate conversational tool. It can answer questions, query
project data and prepare command proposals. A proposal has a preview and requires
confirmation before it changes tickets. Check its project scope, target tickets
and requested changes. Cancel an incorrect proposal and explain the correction.

Human administrators manage identities under **Agents & users**. Give an agent
its own identity and minimum necessary API scopes. Project access can be off,
respond-only or assignable, with type defaults and per-agent exceptions. Being
listed as an agent does not automatically grant every project or action.

For external agents, configure the receiver and delivery settings and follow
[Agent setup](AGENT_SETUP.md). A webhook notification carries an expected action
and execution limits. Being assigned, receiving a notification and actually
executing work are separate facts. A successful delivery means the receiver
accepted the message; it does not prove the ticket was completed.

When an operator has registered a managed executor, the ticket's Execution panel
shows its state separately: waiting, claimed, running, stopping, blocked,
completed or withdrawn. Blockers show missing capabilities, the next responsible
party and the resume condition. Repeated unchanged blockers do not add comments.
For uncertain recovery, a human must verify the previous worker stopped and
review prior effects before confirming Resume execution. Declared completion
evidence is available for inspection; it is not an independent acceptance test.

Use **Test saved webhook** to send a synthetic stand-down event to the saved
receiver. The test does not include ticket or wiki content. Webhook deliveries
show pending, retry, delivered, failed and cancelled states. Refreshing a test's
status does not enqueue another test. Investigate the receiver and delivery error
before replaying a failed notification.

## Installation settings and configuration transfer

Human administrators open **More actions → Installation settings** to configure
installation language, AI output language, provider connections and background
work. Deployment overrides are displayed as managed values. Save provider changes
before testing them. A provider test uses short synthetic text, not ticket content.

Import and export transfers supported configuration, not application backups.
Exports omit credentials, delivery endpoints and ticket/wiki content. Review the
import preview and confirm it separately. Existing credentials and delivery
endpoints are retained; imported new agents start disabled. An expired preview
or changed configuration requires a new preview.

For backups, upgrades, encryption material and deployment requirements, follow
the [README](README.md), [support notes](SUPPORT.md) and
[native deployment guide](NATIVE_DEPLOYMENT.md). A configuration export is not a
substitute for a complete, consistent backup of application data and secrets.

## Keyboard reference

Shortcuts generally apply when you are not typing in an input field. Press `?`
for the current in-app shortcut list.

| Shortcut | Action |
| --- | --- |
| `Cmd+K` / `Ctrl+K` | Open the command palette |
| `c` | Create a ticket |
| `/` | Focus search |
| `i` | Open the inbox |
| `v` | Switch Board/List |
| `w` | Open the wiki |
| `j` / `k` | Move card focus down/up |
| `Enter` | Open the focused card |
| `a` / `s` / `l` | Assign, change state or add a label for a focused ticket |
| `x` | Toggle selection for a focused ticket |
| `[` / `]` | Previous/next ticket in the detail panel |
| `Escape` | Close the active overlay or cancel the current editing layer |

In the project picker, type to filter, use the arrow keys to move through matches,
press Enter to choose, and Escape to close without changing projects.

## Troubleshooting

**A ticket is missing.** Check the selected project, search scope, filters,
collapsed columns and archive visibility. For a large closed column, load the
remaining page before assuming a ticket was deleted.

**An agent is silent.** Check project access, assignment, the state's execution
policy, open questions, locks and relations. Then inspect webhook delivery and the
receiver. A delivered notification alone does not prove an executable task began.

**AI actions are unavailable.** Check provider configuration and installation and
project opt-ins. Ordinary ticket management works without an AI provider.

**A save or load fails.** Keep the error text and retry if appropriate. Sign in
again if the session expired. An error does not prove that a requested change
was applied; inspect the resulting ticket before repeating a write.

**Text appears in mixed languages.** Browser language, server-message language,
AI output language and external-agent configuration are independent. Existing
user content is preserved rather than automatically translated.

For security reports, use [Security](SECURITY.md) and avoid placing credentials
or private application data in a public report.
