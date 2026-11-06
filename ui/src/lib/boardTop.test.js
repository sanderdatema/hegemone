import { describe, it, expect } from "vitest";
import { boardTop, trackBoardTop, BOARD_TOP_VAR } from "./boardTop.js";

function fakeEnv(top, scrollY = 0) {
  const listeners = {};
  const props = {};
  const node = {
    top,
    parentElement: null,
    getBoundingClientRect() {
      return { top: this.top };
    },
  };
  const win = {
    scrollY,
    addEventListener: (n, f) => (listeners[n] = f),
    removeEventListener: (n) => delete listeners[n],
  };
  const doc = {
    body: {},
    documentElement: {
      style: {
        setProperty: (k, v) => (props[k] = v),
        removeProperty: (k) => delete props[k],
      },
    },
  };
  let cb;
  const observed = [];
  class RO {
    constructor(f) {
      cb = f;
    }
    observe(el) {
      observed.push(el);
    }
    disconnect() {
      observed.length = 0;
    }
  }
  return { node, win, doc, RO, props, listeners, observed, fire: () => cb() };
}

describe("boardTop", () => {
  it("telt de scrollpositie mee, want de variabele is een documentafstand", () => {
    const e = fakeEnv(64, 40);
    expect(boardTop(e.node, e.win)).toBe(104);
  });
});

describe("trackBoardTop", () => {
  it("zet de variabele direct en werkt hem bij als er een rij boven het bord bijkomt", () => {
    const e = fakeEnv(64);
    trackBoardTop(e.node, { win: e.win, doc: e.doc, ResizeObserver: e.RO });
    expect(e.props[BOARD_TOP_VAR]).toBe("64px");
    e.node.top = 104; // snelfilter-rij verschijnt
    e.fire();
    expect(e.props[BOARD_TOP_VAR]).toBe("104px");
  });

  it("herberekent bij een venster-resize", () => {
    const e = fakeEnv(64);
    trackBoardTop(e.node, { win: e.win, doc: e.doc, ResizeObserver: e.RO });
    e.node.top = 90;
    e.listeners.resize();
    expect(e.props[BOARD_TOP_VAR]).toBe("90px");
  });

  it("ruimt op bij destroy", () => {
    const e = fakeEnv(64);
    const a = trackBoardTop(e.node, { win: e.win, doc: e.doc, ResizeObserver: e.RO });
    a.destroy();
    expect(e.props[BOARD_TOP_VAR]).toBeUndefined();
    expect(e.listeners.resize).toBeUndefined();
  });

  it("doet niets zonder DOM", () => {
    expect(trackBoardTop({}, { win: null, doc: null })).toEqual({});
  });
});
