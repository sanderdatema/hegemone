// Pure vraagmodule-logica (BETON-219): het bouwen van de antwoord-payload, het
// afleiden van de vraag-/beantwoord-staat uit een comment, en het vormen van de
// open-vragen-lijst voor de inbox. Bewust los van Svelte/DOM zodat het met
// vitest te testen is; de Drawer-kaart en de Inbox-sectie delen deze helpers.

/**
 * Antwoord-payload voor een gekozen optie. Aparte helper (niet één
 * gediscrimineerd object) zodat er nooit per ongeluk zowel `text` als
 * `option_index` meegaat — de backend geeft dan 422. `index` mag 0 zijn (de
 * eerste optie): géén truthiness-check, de backend controleert op `is not None`.
 *
 * @param {number} index
 * @returns {{option_index: number}}
 */
export function optionAnswer(index) {
  return { option_index: index };
}

/**
 * Antwoord-payload voor vrije tekst. Trimt de invoer; de caller weert lege tekst.
 *
 * @param {string} text
 * @returns {{text: string}}
 */
export function textAnswer(text) {
  return { text: (text ?? "").trim() };
}

/**
 * Is deze comment een vraag?
 *
 * @param {{kind?: string}|null} comment
 * @returns {boolean}
 */
export function isQuestion(comment) {
  return (comment?.kind ?? "comment") === "question";
}

/** Mensen kunnen open triagevragen als niet relevant intrekken. */
export function canDismissTriageQuestion(comment, user) {
  return user?.kind === "human" && comment?.author === "triage" && isQuestion(comment)
    && !comment.answered_at && !comment.withdrawn_at;
}

/**
 * Afgeleide staat van een vraag-comment voor de kaart-render: of het een vraag
 * is, of hij beantwoord is, de opties, en de antwoord-verwijzingen.
 *
 * @param {{kind?: string, question_options?: string[]|null, answered_at?: string|null, answered_by?: string|null, answer_text?: string|null, answer_option_index?: number|null, answer_locked?: boolean, answer_comment_id?: number|null}|null} comment
 * @returns {{isQuestion: boolean, withdrawn: boolean, withdrawnReason: string|null, answered: boolean, options: string[], answeredBy: string|null, answerText: string|null, answerOptionIndex: number|null, answerLocked: boolean, editable: boolean, answerCommentId: number|null}}
 */
export function questionState(comment) {
  const c = comment || {};
  const answered = Boolean(c.answered_at);
  const locked = Boolean(c.answer_locked);
  return {
    isQuestion: isQuestion(c),
    // BETON-454: ingetrokken door de vraagsteller; niet beantwoord, niet meer open.
    withdrawn: Boolean(c.withdrawn_at),
    withdrawnReason: c.withdrawn_reason ?? null,
    answered,
    options: c.question_options || [],
    answeredBy: c.answered_by || null,
    // BETON-265/263: het antwoord staat inline op de vraag.
    answerText: c.answer_text ?? null,
    answerOptionIndex: c.answer_option_index ?? null,
    answerLocked: locked,
    // Wijzigbaar zolang beantwoord én nog niet verstuurd (BETON-263).
    editable: answered && !locked,
    answerCommentId: c.answer_comment_id ?? null,
  };
}

/**
 * Welke optie is gekozen? De backend kopieert de gekozen optietekst letterlijk
 * naar de body van het antwoord-comment, dus matchen we de antwoordtekst tegen
 * de opties. Geeft de index terug, of -1 bij een vrijtekst-antwoord (of een
 * vrije tekst die toevallig exact een optie is — acceptabele randgeval).
 *
 * @param {string[]} options
 * @param {string} answerText
 * @returns {number}
 */
export function matchedOptionIndex(options, answerText) {
  if (answerText == null) return -1;
  return (options || []).findIndex((o) => o === answerText);
}

/**
 * Vorm de open-vragen-payload (GET /questions?open=true) tot rijen voor de
 * inbox-sectie. De server levert al gericht/gefilterd; hier alleen normaliseren
 * naar een compacte weergavevorm (nieuwste vraag eerst, op comment-id).
 *
 * @param {Array<{id: number, body_md: string, question_options?: string[]|null, created_at?: string, item?: {ref: string, title: string, state?: string}}>} questions
 * @returns {Array<{id: number, ref: string, title: string, state: string|null, body_md: string, options: string[], created_at: string|undefined}>}
 */
export function openQuestionRows(questions) {
  return (questions || [])
    .filter((q) => q && q.item)
    .map((q) => ({
      id: q.id,
      ref: q.item.ref,
      title: q.item.title,
      // BETON-454: de state van het ticket, zodat zichtbaar is dat een vraag op
      // een afgesloten ticket staat.
      state: q.item.state ?? null,
      body_md: q.body_md,
      options: q.question_options || [],
      created_at: q.created_at,
    }))
    .sort((a, b) => b.id - a.id);
}
