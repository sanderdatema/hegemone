// Minimale regel-diff voor de wiki-edit-history (BETON-209). Een hand-gerolde
// LCS zodat er geen afhankelijkheid nodig is; O(n·m) is ruim genoeg voor de
// omvang van een wiki-pagina. Geeft een lijst segmenten terug:
//   { type: "ctx" | "add" | "del", text }
// De consumer rendert `text` als platte tekst (Svelte escapet dat), nooit als HTML.

export function lineDiff(oldText, newText) {
  // Lege tekst = nul regels (niet één lege regel), zodat een eerste revisie of een
  // leeggemaakte pagina niet als een spurieuze lege regel in de diff verschijnt.
  const split = (t) => (t ? String(t).split("\n") : []);
  const a = split(oldText);
  const b = split(newText);
  const n = a.length;
  const m = b.length;

  // Onbetrouwbare tekst kan tienduizenden regels bevatten; begrens LCS-werk.
  if (n * m > 1_000_000) {
    return [...a.map(text => ({ type: "del", text })), ...b.map(text => ({ type: "add", text }))];
  }

  // dp[i][j] = lengte van de LCS van a[i:] en b[j:].
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const out = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ type: "ctx", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ type: "del", text: a[i] });
      i++;
    } else {
      out.push({ type: "add", text: b[j] });
      j++;
    }
  }
  while (i < n) out.push({ type: "del", text: a[i++] });
  while (j < m) out.push({ type: "add", text: b[j++] });
  return out;
}

// Aantal toegevoegde/verwijderde regels — voor een compacte "+x −y"-samenvatting.
export function diffStat(segments) {
  let added = 0;
  let removed = 0;
  for (const s of segments) {
    if (s.type === "add") added++;
    else if (s.type === "del") removed++;
  }
  return { added, removed };
}
