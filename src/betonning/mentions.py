"""@handle-parsing uit vrije tekst (item-description én comments).

Een mention is `@handle` waarbij handle begint met een letter/cijfer en verder
letters, cijfers, `_` of `-` bevat. Een `@` direct na een woordkarakter telt
niet mee (zodat e-mailadressen zoals `person@example.invalid` geen mention worden).
"""

from __future__ import annotations

import re

# (?<![\w-]) : niet voorafgegaan door woordkarakter of koppelteken (geen e-mail,
# geen dubbele mention-staart). Handle: start alfanumeriek, dan [\w-] — een
# superset (geen lengtelimiet, `\w` is breder dan `[A-Za-z0-9_-]`) van
# `repo/users.py:HANDLE_RE` (BETON-385), dus elke geldig aangemaakte handle is
# hier altijd mentionbaar.
_MENTION = re.compile(r"(?<![\w-])@([A-Za-z0-9][\w-]*)")


def parse(text: str | None) -> list[str]:
    """Geef de unieke handles (zonder @) in volgorde van voorkomen terug."""
    if not text:
        return []
    seen: dict[str, None] = {}
    for m in _MENTION.finditer(text):
        seen.setdefault(m.group(1), None)
    return list(seen)
