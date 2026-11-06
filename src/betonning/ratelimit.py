"""Rate-limits rond de LLM-endpoints (BETON-387).

Twee onafhankelijke poorten, want er zijn twee manieren waarop de LLM geld en
tokens kost:

1. **Per-user token-bucket** (`RateLimiter`) — voor de HTTP-endpoints die een
   LLM-call doen: `POST /items/{ref}/enrich`, `POST /items/{ref}/decompose` en
   de twee triage-chat-endpoints. Een agent in een lus kan daar anders
   ongelimiteerd calls afvuren.
2. **Dagbudget** (`DailyBudget` + `BudgetedLLM`) — voor de ingebouwde
   triage-worker. Die roept `llm.complete` RECHTSTREEKS aan (`triage_worker.py`,
   in-process, als user `triage`) en komt dus nooit langs een
   FastAPI-dependency: de token-bucket raakt hem per constructie niet. Dat is
   bewust — een limiet die de bot stillegt breekt de triage. Het dagbudget is
   zijn eigen, veel ruimere plafond tegen een op hol geslagen lus.

Beide zijn **process-lokaal** en in-memory: geen tabel, geen migratie. Prod
draait één uvicorn-worker, dus dat dekt de hele installatie. De bucket-store
hangt aan `app.state` (niet aan een module-global) zodat elke TestClient met een
schone limiter start.
"""

from __future__ import annotations

from .config import env

import logging
import threading
import time
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

# Calls per uur per user, voor een agent. Mensen krijgen `HUMAN_FACTOR` keer
# zoveel: een mens klikt zelf op "Verrijk"/"Opknippen" en chat met triage, dus
# daar is een strak plafond hinderlijk zonder iets te beschermen.
DEFAULT_LLM_RATE_PER_HOUR = 30
HUMAN_FACTOR = 3

# Plafond op het aantal LLM-calls dat de triage-worker per UTC-dag doet.
DEFAULT_TRIAGE_DAILY_BUDGET = 500


def llm_rate_per_hour() -> int:
    """Calls per uur per agent-user (`BETONNING_LLM_RATE`). <= 0 = geen limiet."""
    raw = env("BETONNING_LLM_RATE", "").strip()
    if not raw:
        return DEFAULT_LLM_RATE_PER_HOUR
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ongeldige BETONNING_LLM_RATE %r; default gebruikt", raw)
        return DEFAULT_LLM_RATE_PER_HOUR


def triage_daily_budget() -> int:
    """LLM-calls per UTC-dag voor de triage-worker. <= 0 = geen limiet."""
    raw = env("BETONNING_TRIAGE_DAILY_BUDGET", "").strip()
    if not raw:
        return DEFAULT_TRIAGE_DAILY_BUDGET
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Ongeldige BETONNING_TRIAGE_DAILY_BUDGET %r; default gebruikt", raw
        )
        return DEFAULT_TRIAGE_DAILY_BUDGET


class RateLimiter:
    """Token-bucket per sleutel (in de praktijk: per user-id).

    Sync en thread-safe (`threading.Lock`) — de endpoints draaien in FastAPI's
    threadpool, dus asyncio-primitieven zouden hier niet helpen. De klok is
    `time.monotonic`, zodat een systeemklok-sprong de limiet niet omzeilt of
    vastzet.

    De emmer vult continu bij met `rate_per_hour / 3600` token per seconde en
    loopt over bij `burst`. Rate en burst komen per aanroep binnen (niet in de
    constructor), zodat dezelfde store een mens en een agent met verschillende
    plafonds kan bedienen.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key → (tokens, last_refill_monotonic)
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, key: str, *, rate_per_hour: int, burst: int | None = None) -> float:
        """Neem één token. Geeft 0.0 als het mag, anders de wachttijd in seconden.

        `rate_per_hour <= 0` betekent "geen limiet" en geeft altijd 0.0 terug —
        zonder state bij te houden.
        """
        if rate_per_hour <= 0:
            return 0.0
        cap = float(burst if burst is not None else rate_per_hour)
        per_second = rate_per_hour / 3600.0
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (cap, now))
            tokens = min(cap, tokens + (now - last) * per_second)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return 0.0
            self._buckets[key] = (tokens, now)
            # Afronden naar boven: een Retry-After van 0 nodigt uit tot direct
            # opnieuw proberen terwijl het antwoord dan nog steeds 429 is.
            return max(1.0, round((1.0 - tokens) / per_second, 3))

    def clear_prefix(self, prefix: str) -> None:
        """Een menselijke beheeractie kan geblokkeerde tellers herstellen."""
        with self._lock:
            for key in list(self._buckets):
                if key.startswith(prefix):
                    del self._buckets[key]


class DailyBudget:
    """Teller met een plafond per UTC-dag; rolt vanzelf om bij dagwissel.

    Gebruikt door de triage-worker (`BudgetedLLM`). `limit <= 0` = geen limiet.
    Thread-safe, want de worker draait via `asyncio.to_thread`.
    """

    def __init__(self, limit: int, *, today: date | None = None) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._day = today or self._utc_today()
        self._spent = 0
        self._warned = False

    @staticmethod
    def _utc_today() -> date:
        return datetime.now(timezone.utc).date()

    def _roll(self) -> None:
        today = self._utc_today()
        if today != self._day:
            self._day = today
            self._spent = 0
            self._warned = False

    @property
    def spent(self) -> int:
        with self._lock:
            self._roll()
            return self._spent

    def spend(self, n: int = 1) -> None:
        with self._lock:
            self._roll()
            self._spent += n

    def exhausted(self) -> bool:
        """Is het budget op? Logt de eerste keer per dag een waarschuwing."""
        if self.limit <= 0:
            return False
        with self._lock:
            self._roll()
            over = self._spent >= self.limit
            if over and not self._warned:
                self._warned = True
                logger.warning(
                    "Triage-dagbudget bereikt (%d LLM-calls); de worker slaat "
                    "batches over tot middernacht UTC.",
                    self.limit,
                )
            return over


class BudgetedLLM:
    """LLM-client-wrapper die elke `complete` op een `DailyBudget` afschrijft.

    Alleen tellen, nooit weigeren: een `raise` midden in `triage_once` zou als
    item-fout gelden en het item na drie ronden in quarantaine duwen. Het
    afkappen gebeurt een laag hoger, in `_run_batch`, dat de batch overslaat
    zodra het budget op is.
    """

    def __init__(self, inner, budget: DailyBudget) -> None:
        self._inner = inner
        self._budget = budget

    def complete(self, messages: list[dict]) -> str:
        self._budget.spend()
        return self._inner.complete(messages)
