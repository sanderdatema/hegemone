// Een opgevangen laadfout leesbaar maken ZONDER de oorzaak weg te gooien
// (BETON-411). `Drawer.load()` ving zijn fout op, zette er "probeer opnieuw"
// neer en liet `e` vallen: het scherm zei dat het misging, de console bleef
// leeg, en een ticket dat niet openging liet geen enkel spoor na om op te
// zoeken. Puur gehouden zodat de vorm van de regel zonder component te
// toetsen is; het loggen zelf hoort in de aanroeper.

/**
 * Haal een korte, toonbare oorzaak uit een opgevangen fout. De API-client
 * (`api.js:handleResponse`) hangt `status` + `detail` aan zijn Error; een
 * netwerkfout heeft alleen een `message` ("Failed to fetch"). Levert een lege
 * string als er niets zinnigs te melden valt — dan blijft de basisregel kaal.
 *
 * @param {unknown} error
 * @returns {string}
 */
export function errorCause(error) {
  if (!error) return "";
  if (typeof error === "string") return error.trim();
  const status = typeof error.status === "number" ? error.status : null;
  const shown = typeof error.displayDetail === "string" ? error.displayDetail : error.detail;
  const detail = typeof shown === "string" ? shown.trim() : "";
  if (status) return detail ? `${status}: ${detail}` : String(status);
  const message = typeof error.message === "string" ? error.message.trim() : "";
  return message;
}

/**
 * Basisregel + de oorzaak tussen haakjes. Zonder bruikbare oorzaak blijft de
 * basisregel ongewijzigd — een "(onbekende fout)" erachter voegt niets toe.
 *
 * @param {string} base
 * @param {unknown} error
 * @returns {string}
 */
export function loadErrorMessage(base, error) {
  const cause = errorCause(error);
  return cause ? `${base} (${cause})` : base;
}
