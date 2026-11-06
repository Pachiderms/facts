"""Briques de résilience : disjoncteur et quota mensuel.

Servent à protéger les fournisseurs de recherche gratuits : on cesse de s'acharner sur un service
qui échoue (disjoncteur) et on ne dépasse jamais le quota gratuit d'un service payant (quota).
Les horloges sont injectables pour tester sans dormir. État en mémoire : une seule instance.
"""

import time
from collections.abc import Callable
from datetime import datetime, timezone


class CircuitBreaker:
    """Ouvre après `failure_threshold` échecs consécutifs, puis laisse passer UN essai après `cooldown_s`.

    Un succès referme le disjoncteur ; un échec pendant l'essai le rouvre pour un nouveau délai.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold doit être >= 1")
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probing = False

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if self._clock() - self._opened_at < self.cooldown_s:
            return False
        if self._probing:  # un essai est déjà en cours : on n'en autorise pas un second
            return False
        self._probing = True
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._probing = False

    def record_failure(self) -> None:
        self._probing = False
        self._failures += 1
        if self._failures >= self.failure_threshold or self._opened_at is not None:
            self._opened_at = self._clock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MonthlyQuota:
    """Compteur remis à zéro chaque mois civil (UTC). `try_consume` réserve un crédit avant l'appel.

    On compte à la tentative, pas au succès : un appel échoué a pu consommer un crédit côté
    fournisseur, et surestimer est le sens sûr pour un quota gratuit.
    """

    def __init__(self, limit: int, clock: Callable[[], datetime] = _utc_now) -> None:
        if limit < 0:
            raise ValueError("limit doit être >= 0")
        self.limit = limit
        self._clock = clock
        self._period: tuple[int, int] | None = None
        self._used = 0

    def _roll(self) -> None:
        now = self._clock()
        period = (now.year, now.month)
        if period != self._period:
            self._period, self._used = period, 0

    def try_consume(self, n: int = 1) -> bool:
        self._roll()
        if self._used + n > self.limit:
            return False
        self._used += n
        return True

    @property
    def remaining(self) -> int:
        self._roll()
        return max(0, self.limit - self._used)
