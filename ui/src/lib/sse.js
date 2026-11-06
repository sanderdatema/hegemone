// SSE-buffer-parsing voor de live-event-stream. Losgetrokken uit board.js
// (BETON-334).

/**
 * Parse een SSE-buffer naar events + de nog-onvolledige rest. Frames zijn
 * gescheiden door een lege regel; `id:`/`data:`-regels tellen mee, comments
 * (`: ...`, o.a. heartbeats) worden overgeslagen. `data` wordt als JSON
 * geparsed; onparsebare data levert `null` op maar breekt de stream niet.
 *
 * @param {string} buffer  (mogelijk gedeeltelijke) SSE-tekst
 * @returns {{events: Array<{id: number|null, data: any}>, rest: string}}
 */
export function parseSSE(buffer) {
  const events = [];
  const parts = buffer.split(/\n\n/);
  const rest = parts.pop() ?? ""; // laatste stuk is mogelijk incompleet
  for (const block of parts) {
    let id = null;
    let dataLines = [];
    let hasData = false;
    for (const line of block.split(/\n/)) {
      if (line.startsWith(":")) continue; // comment/heartbeat
      if (line.startsWith("id:")) id = Number(line.slice(3).trim());
      else if (line.startsWith("data:")) {
        hasData = true;
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
    }
    if (!hasData) continue;
    let data = null;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      data = null;
    }
    events.push({ id, data });
  }
  return { events, rest };
}
