import { describe, it, expect } from "vitest";
import {
  optionAnswer,
  textAnswer,
  isQuestion,
  questionState,
  matchedOptionIndex,
  openQuestionRows,
} from "./question.js";

// BETON-219: pure vraagmodule-logica. Deze tests borgen de payload-vorm (de
// nul-index-val), de afgeleide staat, de gekozen-optie-match en het vormen van
// de open-vragen-lijst.

describe("optionAnswer", () => {
  it("bouwt {option_index} — óók voor de eerste optie (index 0)", () => {
    expect(optionAnswer(0)).toEqual({ option_index: 0 });
    expect(optionAnswer(2)).toEqual({ option_index: 2 });
  });
  it("bevat nooit een text-sleutel", () => {
    expect("text" in optionAnswer(0)).toBe(false);
  });
});

describe("textAnswer", () => {
  it("bouwt {text} en trimt whitespace", () => {
    expect(textAnswer("  hoi  ")).toEqual({ text: "hoi" });
  });
  it("gaat om met null/undefined", () => {
    expect(textAnswer(null)).toEqual({ text: "" });
    expect(textAnswer(undefined)).toEqual({ text: "" });
  });
  it("bevat nooit een option_index-sleutel", () => {
    expect("option_index" in textAnswer("x")).toBe(false);
  });
});

describe("isQuestion", () => {
  it("herkent een vraag-comment", () => {
    expect(isQuestion({ kind: "question" })).toBe(true);
  });
  it("een gewone comment is geen vraag", () => {
    expect(isQuestion({ kind: "comment" })).toBe(false);
    expect(isQuestion({})).toBe(false);
    expect(isQuestion(null)).toBe(false);
  });
});

describe("questionState", () => {
  it("leidt onbeantwoorde staat af", () => {
    const s = questionState({
      kind: "question",
      question_options: ["A", "B"],
      answered_at: null,
    });
    expect(s).toEqual({
      isQuestion: true,
      withdrawn: false,
      withdrawnReason: null,
      answered: false,
      options: ["A", "B"],
      answeredBy: null,
      answerText: null,
      answerOptionIndex: null,
      answerLocked: false,
      editable: false,
      answerCommentId: null,
    });
  });
  it("leidt beantwoorde staat af met inline antwoord", () => {
    const s = questionState({
      kind: "question",
      question_options: [],
      answered_at: "2026-07-14T10:00:00Z",
      answered_by: "person",
      answer_text: "groen",
    });
    expect(s.answered).toBe(true);
    expect(s.answeredBy).toBe("person");
    expect(s.answerText).toBe("groen");
  });
  it("is wijzigbaar zolang niet gelockt (BETON-263)", () => {
    const base = {
      kind: "question",
      question_options: ["A", "B"],
      answered_at: "2026-07-14T10:00:00Z",
      answer_option_index: 1,
    };
    expect(questionState({ ...base, answer_locked: false }).editable).toBe(true);
    expect(questionState({ ...base, answer_locked: true }).editable).toBe(false);
    // Onbeantwoord is nooit 'editable'.
    expect(questionState({ ...base, answered_at: null }).editable).toBe(false);
    expect(questionState({ ...base }).answerOptionIndex).toBe(1);
  });
});

describe("matchedOptionIndex", () => {
  it("vindt de gekozen optie op tekst-match", () => {
    expect(matchedOptionIndex(["Ja", "Nee"], "Nee")).toBe(1);
    expect(matchedOptionIndex(["Ja", "Nee"], "Ja")).toBe(0);
  });
  it("geeft -1 bij een vrijtekst-antwoord", () => {
    expect(matchedOptionIndex(["Ja", "Nee"], "Misschien")).toBe(-1);
    expect(matchedOptionIndex([], "wat dan ook")).toBe(-1);
    expect(matchedOptionIndex(["Ja"], null)).toBe(-1);
  });
});

describe("openQuestionRows", () => {
  const q = (id, ref, opts = {}) => ({
    id,
    body_md: opts.body ?? `Vraag ${id}`,
    question_options: opts.options ?? null,
    created_at: opts.created_at,
    item: opts.item === null ? undefined : { ref, title: opts.title ?? `Titel ${ref}` },
  });

  it("vormt en sorteert nieuwste-eerst op id", () => {
    const rows = openQuestionRows([q(1, "SOS-1"), q(3, "SOS-3"), q(2, "SOS-2")]);
    expect(rows.map((r) => r.id)).toEqual([3, 2, 1]);
    expect(rows[0]).toEqual({
      id: 3,
      ref: "SOS-3",
      title: "Titel SOS-3",
      state: null,
      body_md: "Vraag 3",
      options: [],
      created_at: undefined,
    });
  });
  it("draagt opties mee", () => {
    const rows = openQuestionRows([q(1, "SOS-1", { options: ["A", "B"] })]);
    expect(rows[0].options).toEqual(["A", "B"]);
  });
  it("negeert entries zonder item", () => {
    const rows = openQuestionRows([q(1, "SOS-1", { item: null }), q(2, "SOS-2")]);
    expect(rows.map((r) => r.id)).toEqual([2]);
  });
  it("gaat om met leeg/undefined", () => {
    expect(openQuestionRows(null)).toEqual([]);
    expect(openQuestionRows([])).toEqual([]);
  });
});

describe("ingetrokken vraag (BETON-454)", () => {
  it("questionState toont withdrawn + reden, en is niet beantwoord", () => {
    const s = questionState({
      kind: "question",
      withdrawn_at: "2026-10-25T10:00:00Z",
      withdrawn_reason: "antwoord kwam in de chat",
    });
    expect(s.withdrawn).toBe(true);
    expect(s.withdrawnReason).toBe("antwoord kwam in de chat");
    expect(s.answered).toBe(false);
  });
  it("een gewone open vraag is niet ingetrokken", () => {
    expect(questionState({ kind: "question" }).withdrawn).toBe(false);
  });
  it("openQuestionRows draagt de ticket-state mee", () => {
    const rows = openQuestionRows([
      { id: 1, body_md: "x", item: { ref: "SOS-1", title: "t", state: "Done" } },
      { id: 2, body_md: "y", item: { ref: "SOS-2", title: "t" } },
    ]);
    expect(rows.find((r) => r.id === 1).state).toBe("Done");
    expect(rows.find((r) => r.id === 2).state).toBeNull();
  });
});
