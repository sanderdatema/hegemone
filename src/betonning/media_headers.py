"""Responseheaders voor de media-serve-routes (BETON-380).

Drie dingen die op beide serve-routes (attachment en avatar) hoorden te staan:

- `X-Content-Type-Options: nosniff` — de browser mag het type niet zelf
  herinterpreteren. Nieuwe uploads worden gesnift op magic bytes, maar bestaande
  rijen dragen nog het type dat de client ooit claimde; nosniff zorgt dat een
  verkeerd gelabelde oude rij niet alsnog als HTML/script uitgevoerd wordt.
- `Content-Disposition` met een gesanitiseerde filename — het scheelt dat een
  rare filename uit de header ontsnapt. `inline` of `attachment` is sinds
  BETON-374 een keuze van de aanroeper: alléén afbeeldingen gaan inline. Een
  niet-afbeelding die inline op de origin staat is een andere risicoklasse (wat
  de browser er ook van maakt, het gebeurt op onze origin), dus tekst, JSON en
  PDF worden gedownload i.p.v. weergegeven.
- `Cache-Control` **private** — de bytes zijn achter auth (BETON-202), dus geen
  gedeelde proxy mag ze bewaren.

`immutable` verschilt per route en dat is opzet: `/api/v1/attachments/{sha256}`
is content-addressed (dezelfde URL geeft per definitie dezelfde bytes), dus een
jaar `immutable` klopt. De avatar-URL is op **handle** gekeyd en dus mutabel —
daar zou een jaar `immutable` betekenen dat een nieuwe avatar niet opgehaald
wordt. Die revalideert.

**Niet-Latijnse namen** (BETON-395): `safe_filename` bestaat om header-injectie
te voorkomen (CR/LF, aanhalingstekens, puntkomma's) — niet om niet-ASCII te
weren. Elk teken buiten `[A-Za-z0-9._-]` werd vervangen door `_`, dus een naam
als `日誌.log` werd `__.log` → na het strippen van de omringende underscores
bleef `.log` over: een naamloos dotfile, en géén bruikbare terugval. Twee
maatregelen:

1. `safe_filename` herkent het "alleen een extensie over"-geval en valt terug
   op `bestand.<ext>` (of `bestand` zonder extensie) i.p.v. een kale `.ext`.
2. `media_headers` voegt bij een echt niet-ASCII bestandsnaam een
   `filename*=UTF-8''<percent-encoded>` toe naast de ASCII-`filename=`
   (RFC 6266 / RFC 5987) — de ASCII-vorm is de terugval voor oude clients, de
   `filename*`-vorm draagt de echte naam en wint bij moderne browsers. Alleen
   bij niet-ASCII bytes: een puur-ASCII naam met rare tekens (quotes,
   puntkomma's) heeft aan de gesanitiseerde vorm genoeg en krijgt geen tweede
   directive.
"""

from __future__ import annotations

import re
from urllib.parse import quote

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")
MAX_FILENAME = 100

IMMUTABLE_CACHE = "private, max-age=31536000, immutable"
REVALIDATE_CACHE = "private, max-age=0, must-revalidate"


def safe_filename(name: str | None) -> str:
    """Alleen `[A-Za-z0-9._-]`, max 100 tekens; leeg → 'bestand'.

    Dit is de ASCII-terugval voor `Content-Disposition`, niet de echte naam
    bij niet-ASCII input (zie `media_headers` voor `filename*`). Een naam die
    na sanitisatie alleen nog een extensie overhoudt (bv. `.log`, ontstaan uit
    een volledig niet-Latijnse stam) is een naamloos dotfile — geen bruikbare
    terugval — en valt daarom terug op `bestand.<ext>`."""
    cleaned = _SAFE_FILENAME.sub("_", name or "")[:MAX_FILENAME].strip("_")
    if not cleaned:
        return "bestand"
    stem, sep, ext = cleaned.rpartition(".")
    if sep and not stem:
        return f"bestand.{ext}" if ext else "bestand"
    return cleaned


def media_headers(
    filename: str | None, *, immutable: bool, disposition: str = "inline"
) -> dict[str, str]:
    if disposition not in ("inline", "attachment"):
        raise ValueError(f"Onbekende disposition: {disposition}")
    value = f'{disposition}; filename="{safe_filename(filename)}"'
    if filename and any(ord(ch) > 127 for ch in filename):
        # Alleen bij echte niet-ASCII: de ASCII-terugval verliest dan
        # informatie die filename* (RFC 5987) wél kan dragen. quote() escapet
        # ook CR/LF/quotes volledig, dus geen header-injectie via dit pad.
        value += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return {
        "Cache-Control": IMMUTABLE_CACHE if immutable else REVALIDATE_CACHE,
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": value,
    }
