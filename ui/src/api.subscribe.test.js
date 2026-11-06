import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { subscribe } from "./api.js";

// Simuleert een SSE-response.body.getReader() die je stap voor stap kunt
// voeden (heartbeat/event-frames) en die reageert op de AbortSignal van de
// fetch-call (net als een echte fetch-stream: abort() laat de pending
// reader.read() falen).
function createFakeReader(signal) {
  let pendingResolve = null;
  let pendingReject = null;
  const encoder = new TextEncoder();

  signal.addEventListener("abort", () => {
    if (pendingReject) {
      const err = new DOMException("aborted", "AbortError");
      const reject = pendingReject;
      pendingResolve = null;
      pendingReject = null;
      reject(err);
    }
  });

  return {
    read() {
      return new Promise((resolve, reject) => {
        pendingResolve = resolve;
        pendingReject = reject;
      });
    },
    // Levert een frame aan een openstaande read() (bv. een heartbeat-comment).
    feed(text) {
      if (pendingResolve) {
        const resolve = pendingResolve;
        pendingResolve = null;
        pendingReject = null;
        resolve({ value: encoder.encode(text), done: false });
      }
    },
  };
}

function createFakeFetch(readersOut) {
  return vi.fn((url, { signal } = {}) => {
    const reader = createFakeReader(signal);
    readersOut.push(reader);
    return Promise.resolve({
      ok: true,
      body: { getReader: () => reader },
    });
  });
}

// Minimale document-stub voor de visibilitychange-trigger (deze testomgeving
// heeft geen jsdom): één luisteraar + een instelbare visibilityState.
function createFakeDocument() {
  const listeners = new Set();
  return {
    visibilityState: "visible",
    addEventListener: (type, fn) => {
      if (type === "visibilitychange") listeners.add(fn);
    },
    removeEventListener: (type, fn) => {
      if (type === "visibilitychange") listeners.delete(fn);
    },
    listenerCount: () => listeners.size,
    setVisibility(state) {
      this.visibilityState = state;
      for (const fn of [...listeners]) fn();
    },
  };
}

// Een écht dode socket: read() blijft hangen en trekt zich niets aan van de
// AbortSignal (geen FIN/RST, geen error). Dit is de toestand uit BETON-405 —
// zonder wachter komt er nooit een catch, dus ook nooit een offline-status.
function createDeadReader() {
  return {
    read() {
      return new Promise(() => {});
    },
  };
}

function createDeadFetch() {
  return vi.fn(() =>
    Promise.resolve({ ok: true, body: { getReader: () => createDeadReader() } })
  );
}

// Bootst een slapende machine na: de stall-`setTimeout` wordt wél gezet maar
// vuurt nooit (bevroren timer). Alle andere timers — met name de backoff van de
// herverbindingslus — lopen normaal door.
function createFrozenStallTimeout(stallTimeout) {
  return (fn, delay) => {
    if (delay === stallTimeout) return setTimeout(() => {}, 1e9);
    return setTimeout(fn, delay);
  };
}

// Laat de eerste verbinding vallen en kijkt hoe de tweede eruitziet.
function urlsOf(fetchMock) {
  return fetchMock.mock.calls.map(([url]) => url);
}

describe("subscribe", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Deze testomgeving heeft geen jsdom/localStorage; getKey() gebruikt
    // localStorage.getItem, dus die stubben we minimaal.
    globalThis.localStorage = { getItem: () => "test-key" };
  });
  afterEach(() => {
    vi.useRealTimers();
    delete globalThis.localStorage;
  });

  it("reconnect via abort als de stream stilvalt (geen bytes binnen STALL_TIMEOUT)", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const onEvent = vi.fn();
    const statuses = [];

    const stop = subscribe(onEvent, { onStatus: (s) => statuses.push(s) }, {
      fetch: fetchMock,
      stallTimeout: 12000,
    });

    // Laat de eerste fetch + connectie tot stand komen.
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(statuses).toContain("live");

    // Stream levert helemaal niets (geen heartbeat, geen event) — de
    // read()-promise blijft hangen. Laat de stall-timeout verlopen.
    await vi.advanceTimersByTimeAsync(12000);

    // De watchdog moet de controller geabort hebben -> reader.read() faalt
    // -> catch -> onStatus("offline") -> backoff-wachttijd -> reconnect.
    expect(statuses).toContain("offline");
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    stop();
  });

  it("blijft verbonden zolang er regelmatig heartbeats binnenkomen", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const onEvent = vi.fn();
    const statuses = [];

    const stop = subscribe(onEvent, { onStatus: (s) => statuses.push(s) }, {
      fetch: fetchMock,
      stallTimeout: 12000,
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Voed elke 5s een heartbeat-comment, ruim binnen de 12s-stall-timeout,
    // over meerdere cycli heen.
    for (let i = 0; i < 5; i++) {
      readers[0].feed(": heartbeat\n\n");
      await vi.advanceTimersByTimeAsync(5000);
    }

    // Geen tweede fetch/reconnect nodig geweest.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(statuses).not.toContain("offline");

    stop();
  });

  // Regressiewacht (gold al vóór BETON-402, moet blijven gelden): de UI heeft
  // net een volledige loadBoard() gedaan, dus de eerste verbinding speelt geen
  // historie af (BETON-186) en er hoort géén resync-herlaad bij.
  it("eerste verbinding gebruikt from=latest en vraagt geen resync", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const onResync = vi.fn();

    const stop = subscribe(vi.fn(), { onResync }, { fetch: fetchMock, stallTimeout: 12000 });
    await vi.advanceTimersByTimeAsync(0);

    expect(urlsOf(fetchMock)).toEqual(["/api/v1/events/stream?since=0&from=latest"]);
    expect(onResync).not.toHaveBeenCalled();

    stop();
  });

  // BETON-402, gat 1: `since` blijft 0 zolang er nog geen event langskwam, dus
  // de herverbinding gebruikt opnieuw from=latest en slaat alles uit het gat
  // over. Zonder resync-signaal blijft het bord stil verouderd staan.
  it("herverbinding met since=0 vraagt precies één resync", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const onResync = vi.fn();

    const stop = subscribe(vi.fn(), { onResync }, { fetch: fetchMock, stallTimeout: 12000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(onResync).not.toHaveBeenCalled();

    // Verbinding valt stil -> abort -> reconnect na de backoff.
    await vi.advanceTimersByTimeAsync(12000);
    await vi.advanceTimersByTimeAsync(1000);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onResync).toHaveBeenCalledTimes(1);

    stop();
  });

  // BETON-402, gat 2: hervatten vanaf het laatst geziene id is goed, maar er is
  // geen garantie dat het gat volledig is ingehaald -> ook hier een resync.
  it("herverbinding met since>0 hervat vanaf dat id én vraagt één resync", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const onEvent = vi.fn();
    const onResync = vi.fn();

    const stop = subscribe(onEvent, { onResync }, { fetch: fetchMock, stallTimeout: 12000 });
    await vi.advanceTimersByTimeAsync(0);

    readers[0].feed('id: 42\ndata: {"type":"item.created"}\n\n');
    await vi.advanceTimersByTimeAsync(0);
    expect(onEvent).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(12000);
    await vi.advanceTimersByTimeAsync(1000);

    expect(urlsOf(fetchMock)[1]).toBe("/api/v1/events/stream?since=42");
    expect(onResync).toHaveBeenCalledTimes(1);

    stop();
  });

  // Een mislukte poging levert geen resync op (er is niets verbonden); de
  // geslaagde poging erna precies één.
  it("mislukte pogingen vragen geen resync, de geslaagde erna één", async () => {
    const readers = [];
    let failNext = false;
    const fetchMock = vi.fn((url, { signal } = {}) => {
      if (failNext) {
        failNext = false;
        return Promise.resolve({ ok: false, status: 502, body: null });
      }
      const reader = createFakeReader(signal);
      readers.push(reader);
      return Promise.resolve({ ok: true, body: { getReader: () => reader } });
    });
    const onResync = vi.fn();

    const stop = subscribe(vi.fn(), { onResync }, { fetch: fetchMock, stallTimeout: 12000 });
    await vi.advanceTimersByTimeAsync(0);

    // Val stil; de eerste herverbindingspoging faalt (502), de tweede lukt.
    failNext = true;
    await vi.advanceTimersByTimeAsync(12000);
    await vi.advanceTimersByTimeAsync(1000); // poging 2 -> 502
    expect(onResync).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2000); // poging 3 -> ok
    expect(onResync).toHaveBeenCalledTimes(1);

    stop();
  });

  // Een tabblad dat uit slaap komt: de timers stonden stil (dus de
  // stall-watchdog vuurde niet) terwijl de wandklok doorliep en er geen bytes
  // meer kwamen. Terugkeren forceert een verse verbinding + resync.
  it("uit slaap gekomen tabblad forceert bij terugkeer een herverbinding met resync", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const onResync = vi.fn();
    const doc = createFakeDocument();

    const stop = subscribe(vi.fn(), { onResync }, {
      fetch: fetchMock,
      stallTimeout: 12000,
      document: doc,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Slaapstand: de wandklok springt vooruit zónder dat er timers vuren (dus
    // geen watchdog-abort) en er kwamen geen bytes meer. De reconnect hieronder
    // komt daarmee aantoonbaar van de visibility-trigger.
    doc.setVisibility("hidden");
    vi.setSystemTime(Date.now() + 120000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    doc.setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onResync).toHaveBeenCalledTimes(1);

    // stop() ruimt de luisteraar op — anders stapelen ze bij logout/login.
    stop();
    expect(doc.listenerCount()).toBe(0);
  });

  // Van tabblad wisselen mag een gezonde verbinding niet slopen — ook niet als
  // je lang wegblijft, zolang de heartbeats bleven komen.
  it("wegklikken met doorlopende heartbeats laat de verbinding staan", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const onResync = vi.fn();
    const doc = createFakeDocument();

    const stop = subscribe(vi.fn(), { onResync }, {
      fetch: fetchMock,
      stallTimeout: 12000,
      document: doc,
    });
    await vi.advanceTimersByTimeAsync(0);

    doc.setVisibility("hidden");
    for (let i = 0; i < 12; i++) {
      readers[0].feed(": heartbeat\n\n");
      await vi.advanceTimersByTimeAsync(5000);
    }
    doc.setVisibility("visible");
    await vi.advanceTimersByTimeAsync(1000);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onResync).not.toHaveBeenCalled();

    stop();
  });

  // BETON-405. Het scenario van de melder: extern scherm in slaap, tabblad op de
  // voorgrond. `visibilitychange` vuurt dan nooit (document.hidden verandert
  // niet) en de stall-`setTimeout` stond stil zolang de machine sliep. Zonder
  // wachter hangt reader.read() op een dode socket en gebeurt er níets.
  it("wachter aborteert een stille stream ook als de stall-timer niet vuurt", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const statuses = [];
    const onResync = vi.fn();

    const stop = subscribe(vi.fn(), { onStatus: (s) => statuses.push(s), onResync }, {
      fetch: fetchMock,
      stallTimeout: 12000,
      setTimeout: createFrozenStallTimeout(12000),
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Geen bytes, en de bevroren stall-timer vuurt niet. Alleen de wachter kan
    // dit nog vaststellen: op zijn tick voorbij de 12s slaat hij toe.
    await vi.advanceTimersByTimeAsync(15000);
    expect(statuses).toContain("offline");

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onResync).toHaveBeenCalledTimes(1);

    stop();
  });

  // BETON-405, tijdsprong: de wandklok springt vooruit terwijl er geen enkele
  // timer op tijd vuurde. Dat is de signatuur van een slaapstand. Beoordeeld met
  // Date.now() (via de now-seam), niet met performance.now().
  it("tijdsprong forceert een herverbinding, ook binnen de stall-timeout", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const statuses = [];
    const onResync = vi.fn();
    let offset = 0;

    const stop = subscribe(vi.fn(), { onStatus: (s) => statuses.push(s), onResync }, {
      fetch: fetchMock,
      // Ruim boven elke tijd die deze test laat verstrijken: de byte-poort kan
      // hier per constructie niet toeslaan, dus de reconnect komt aantoonbaar
      // van de sprongdetectie.
      stallTimeout: 600000,
      now: () => Date.now() + offset,
    });

    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(statuses).not.toContain("offline");

    // Twee minuten wandkloktijd, geen enkele tick onderweg.
    offset += 120000;
    await vi.advanceTimersByTimeAsync(5000);
    expect(statuses).toContain("offline");

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onResync).toHaveBeenCalledTimes(1);

    stop();
  });

  // De wachter mag geen herverbindingsstorm veroorzaken: zolang de heartbeats
  // doorkomen blijft de stream staan, en pas als ze stoppen grijpt hij in.
  it("wachter laat een stream met heartbeats staan en grijpt pas in als ze stoppen", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const statuses = [];

    const stop = subscribe(vi.fn(), { onStatus: (s) => statuses.push(s) }, {
      fetch: fetchMock,
      stallTimeout: 12000,
      setTimeout: createFrozenStallTimeout(12000),
    });
    await vi.advanceTimersByTimeAsync(0);

    for (let i = 0; i < 12; i++) {
      readers[0].feed(": heartbeat\n\n");
      await vi.advanceTimersByTimeAsync(4000);
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(statuses).not.toContain("offline");

    // Heartbeats stoppen -> de wachter stelt de stream dood vast.
    await vi.advanceTimersByTimeAsync(15000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(statuses).toContain("offline");
    expect(fetchMock).toHaveBeenCalledTimes(2);

    stop();
  });

  // De helft van BETON-405: de indicator. Op een socket die zich niets van de
  // abort aantrekt komt er nooit een catch, dus de `offline` uit de catch valt
  // weg. Een groen bolletje boven stilstaande data is misleidender dan rood.
  it("indicator springt op offline zodra de wachter toeslaat, ook zonder catch", async () => {
    const fetchMock = createDeadFetch();
    const statuses = [];

    const stop = subscribe(vi.fn(), { onStatus: (s) => statuses.push(s) }, {
      fetch: fetchMock,
      stallTimeout: 12000,
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(statuses).toEqual(["live"]);

    await vi.advanceTimersByTimeAsync(15000);
    expect(statuses).toContain("offline");

    stop();
  });

  // Een verborgen tabblad wordt door de browser afgeknepen (Firefox rekt timers
  // tot ~15s), dus een late tick is óók zonder slaapstand normaal. Zolang de
  // bytes doorkomen is de stream gezond en mag de wachter niet toeslaan — een
  // abort zou een offline-flikker plus een volledige herlaad kosten.
  it("afgeknepen tick met verse bytes laat de verbinding staan", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const statuses = [];
    const onResync = vi.fn();
    let offset = 0;

    const stop = subscribe(vi.fn(), { onStatus: (s) => statuses.push(s), onResync }, {
      fetch: fetchMock,
      stallTimeout: 12000,
      now: () => Date.now() + offset,
    });
    await vi.advanceTimersByTimeAsync(0);

    readers[0].feed(": heartbeat\n\n");
    // De tick komt een minuut te laat (throttling), maar er kwamen net bytes.
    offset += 60000;
    readers[0].feed(": heartbeat\n\n");
    await vi.advanceTimersByTimeAsync(5000);

    expect(statuses).not.toContain("offline");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onResync).not.toHaveBeenCalled();

    stop();
  });

  // stop() moet de wachter opruimen, net als de visibility-luisteraar — anders
  // blijft er bij logout/login een interval per abonnement achter tikken.
  it("stop() ruimt het wachter-interval op", async () => {
    const readers = [];
    const fetchMock = createFakeFetch(readers);
    const setIntervalSpy = vi.fn((fn, delay) => setInterval(fn, delay));
    const clearIntervalSpy = vi.fn((id) => clearInterval(id));

    const stop = subscribe(vi.fn(), {}, {
      fetch: fetchMock,
      stallTimeout: 12000,
      setInterval: setIntervalSpy,
      clearInterval: clearIntervalSpy,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);

    stop();
    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);
    expect(clearIntervalSpy).toHaveBeenCalledWith(setIntervalSpy.mock.results[0].value);
  });
});
