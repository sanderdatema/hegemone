# Knowledge base design

This design makes the wiki a place for people to find and read shared knowledge. It retains the existing page identities, scope-aware links, Markdown, revisions, permissions, human review and memory interfaces. The interactive [prototype](wiki-prototype.html) uses fictional content and makes no API requests. Changes in the prototype last only until reload.

## Layout and visual language

Retain the application’s system font and existing surface, border, text and orange accent tokens. The prototype samples their light values; production uses the runtime tokens in both themes. Navigation uses 13–14 px text; article prose uses 16 px with a 1.7 line height. Titles use 28–30 px. Use the existing 6 px control radius, 8/12/16/24/32 px spacing rhythm and visible focus rings. Avoid decorative cards around each page.

At wide desktop sizes the knowledge base has a 1,220 px maximum width: 260 px navigation, 740 px article region and 220 px context. Article padding leaves approximately 660 px for text. Extra width stays outside the frame. The application shell remains responsible for project selection and closing the wiki.

Below 1,100 px, use a 240 px navigation column and a flexible reading column; move context below the article. Below 700 px, show one reading surface with 20 px horizontal padding. A `Pages` button reveals the complete scope/search/list navigation above the article. An `On this page` button reveals the TOC and references; omit it on the home and editor screens. Both expose `aria-expanded` and `aria-controls`; they are ordinary disclosure regions, without focus traps. Wrapping titles and links must never create horizontal page scrolling.

## Navigation, home and search

Navigation contains the knowledge base label and Home action, explicit Project/Global scope choice, current project name, a labeled search input with clear control, New page, result/page count and Alphabetical/Recently updated sorting. Browsing rows show titles only, wrapping when needed. Selected rows use accent-soft background and `aria-current="page"`. Sorting is deterministic; title is the secondary key for equal timestamps. Retain list position and query when following a result, so returning to browsing does not lose orientation.

Search uses the existing title/slug/body match contract within the chosen scope. A nonempty query exposes clear, result count and short context snippets. Snippets are plain text with Markdown syntax removed and bounded around a match; never render source HTML. A title/slug-only match may use the opening text. Do not add a search service or cross-scope aggregation. Selecting a result opens that page directly, without an intermediate card.

The start screen shows the knowledge base name, page count, scope explanation, recent pages and New page in the adjacent navigation. Mobile exposes the same search and New page through Pages. Recent entries show title, a short plain-text introduction and update time. They are direct page links. Search with no article selected shows a fuller result list in the main region. While reading, searching updates navigation results without replacing the article.

No results: “No pages match. Try another term or clear the search.” A truly empty knowledge base instead shows “A fresh place for shared knowledge” with Create first page. Keep loading distinct from empty. Loading uses a status announcement; an initial request error provides a clear retry. A refresh error should retain already loaded reading content and show a non-destructive error banner.

## Article and context

The article begins with a clickable Knowledge base breadcrumb, explicit scope, title and one compact update line. Keep Edit page visible. Move Page details, History, Protect/Unprotect page and Delete page into a labeled page menu. Archived/read-only permissions continue to determine whether actions are available. Do not show technical identifiers in the reading header.

Preserve the existing sanitized Markdown renderer and duplicate-opening-title suppression. Source Markdown and history remain unchanged. Scope-qualified and aliased links retain their current destinations and authorization behavior. Cross-project/global navigation updates the visible scope. Missing pages retain the existing create-page flow and its target scope.

Context contains an On this page navigation from rendered level 2/3 headings. Use unique stable heading IDs and actual anchor links; omit the TOC when there are no headings. Heading text is safe text. Duplicate headings receive deterministic suffixes. Ignore fenced code, raw source examples and the suppressed title heading. Give targets scroll margin beneath any sticky shell. Navigation follows document order; do not create a nested tree deeper than two levels.

Show up to five Linked from titles and a `Show all references (N)` disclosure for the remainder. Label references as belonging to the current knowledge base, matching the existing backlink contract. Never imply cross-scope coverage. Reference lists wrap and remain secondary to the article. Zero references shows a quiet “No pages link here yet.” The expanded list must remain bounded or scrollable at narrow sizes. Opening a reference behaves exactly like opening a navigation row.

## Editing and page actions

Create and Edit share one central editor: explicit scope breadcrumb, title input, existing Markdown content editor and link autocomplete, Write/Preview choice, Save page and Cancel. New-page slug entry and validation retain existing semantics; an existing slug is immutable and available in Page details. Preview uses the production sanitized Markdown renderer, scope resolution and current unsaved draft. The lightweight prototype preview displays escaped draft text to avoid adding a second Markdown implementation.

Show “Unsaved changes” only when title/body differ from the loaded baseline. Switching Write/Preview preserves the draft and is not navigation. Successful save returns to the saved article. Disable repeated saves while pending; announce saving/error/success. A failed save retains all draft text. Validate the required title near the field and focus it if invalid.

Before Cancel, another page, Home, scope/project switch or wiki close would discard a dirty draft, ask “Discard unsaved changes?” with Keep editing and Discard changes. Keep editing is the safe/default focus. Browser unload uses the native warning. History back/forward and deep links must use the same guard; a cancelled navigation must also restore the prior URL. An unchanged editor leaves without a warning.

Concurrent change: retain the draft and display “This page changed while you were editing.” Offer View latest version without replacing draft text. Reuse the existing revision comparison capability when presenting the latest version. Never offer a silent overwrite. If the API does not provide a version precondition, retain draft and report the contract gap rather than presenting a preflight comparison as atomic conflict protection. Choosing a newer baseline must be explicit before retrying Save.

Page details contains slug, scope, source/author kind and revision metadata. History keeps the existing timeline, diff and confirmed restore. Protect explains the human-review consequence and requires the existing human permission. Unprotect reflects the current state. Delete retains the existing human-only authorization and confirmation; do not broaden destructive capability. Protected proposals remain reviewable with existing approve/reject controls. These are presentations of existing controls, without a new management layer.

## Accessibility and implementation boundaries

Use semantic navigation, main and complementary landmarks, one article H1 and real buttons/links. Place focus on the article heading or focusable main region after page navigation; return focus to the trigger when a menu/dialog closes. Keep native text editing keys intact. Search must not steal focus when results change; announce count politely. Destructive and unsaved-change dialogs use the existing accessible confirmation component and restore focus on cancel. A page menu must support Escape and keyboard traversal through existing menu primitives; the prototype uses native details and dialog elements for review.

Implementation divides naturally into a navigation/reading change and an editing/action change. The first owns home, compact list, sort/search snippets, responsive regions, headings/TOC and bounded backlinks. The second owns editor layout, draft guard, preview, menu presentation and existing history/protection/delete flows. Existing `Wiki.svelte`, `wikiText.js`, `markdown.js`, API methods, review/diff/editor components and English/Dutch catalogs remain the integration points. All new product copy must be translated; author content and identifiers must not be translated.

## Reviewable states and verification

Open the HTML directly in a browser. The four core flows are Home → page, search → result, related link/reference → article, and New/Edit → Preview → Save/Cancel. Preview state buttons demonstrate empty, loading, initial error and conflict without a server. Long titles and six incoming references are represented in fictional fixtures. Details, history, protection and deletion dialogs demonstrate placement and wording; no persistent or permission mutation is implemented by the prototype.

Headless review should cover home, article, search and editor on desktop, and article/context plus Pages at 390 px. Verify no horizontal overflow, no script errors, title wrapping, visible focus, exact page links and retained draft after cancelling the dirty warning. The prototype is a design artifact; it does not establish API concurrency guarantees or replace production authorization tests.

The local prototype review used headless Chrome through the existing Playwright installation. Home/article/search/editor and mobile article, contextual disclosure and Pages screenshots were captured. The dirty-warning Keep editing and Discard changes paths were exercised. The browser reported no script errors and the 390 px layout had no horizontal overflow. Desktop article, editor and mobile article images were inspected. This is design-flow verification with synthetic data; no production data or foreground app was used.
