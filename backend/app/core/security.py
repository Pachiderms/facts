"""Briques de sécurité : nettoyage des entrées, détection d'injection, rate limiting.

Défense en profondeur contre l'injection de prompt :
  1. sanitize_text   : on neutralise les balises/caractères invisibles dans l'entrée ;
  2. le prompt       : l'entrée est enfermée dans <ASSERTION> (voir services) ;
  3. validation sortie : le JSON du LLM est validé par schéma, et ses URL doivent
                         provenir des résultats de recherche (voir services).
"""

import re
import time
import unicodedata
from collections import deque
from collections.abc import Callable

from starlette.requests import HTTPConnection, Request


class InvalidInputError(ValueError):
    """Entrée utilisateur refusée (vide, trop longue, malveillante...)."""


_TAG_RE = re.compile(r"</?\s*[A-Za-z_][^>]{0,100}>")

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore[rz]?\s+(all|any|the|previous|prior|above|tout|toutes|les|mes|vos)\b.{0,30}(instruction|consigne|prompt|règle)",
        r"(oublie[sz]?|disregard|forget)\s+(all|everything|tout|toutes|les|your|tes|vos)\b.{0,30}(instruction|consigne|prompt|règle|rule)",
        r"(system\s*prompt|prompt\s+syst[èe]me|developer\s+message)",
        r"(you\s+are\s+now|tu\s+es\s+maintenant|à\s+partir\s+de\s+maintenant\s+tu)",
        r"</?\s*(assertion|search_results|system)\b",
    )
]


def sanitize_text(text: str, max_len: int) -> str:
    """Normalise et nettoie un texte libre avant de l'injecter dans un prompt."""
    text = unicodedata.normalize("NFKC", text)
    # Supprime caractères de contrôle et invisibles (zero-width, bidi override...).
    text = "".join(
        ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf")
    )
    text = _TAG_RE.sub(" ", text)
    text = text.replace("<", " ").replace(">", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise InvalidInputError("Texte vide après nettoyage.")
    if len(text) > max_len:
        raise InvalidInputError(f"Texte trop long (max {max_len} caractères).")
    return text


def looks_like_prompt_injection(text: str) -> bool:
    """Heuristique : une assertion factuelle n'a aucune raison de donner des ordres au modèle.

    Sert de garde-fou supplémentaire, pas de défense unique (une heuristique se contourne).
    """
    normalized = unicodedata.normalize("NFKC", text)
    return any(p.search(normalized) for p in _INJECTION_PATTERNS)


class SlidingWindowRateLimiter:
    """Limiteur à fenêtre glissante en mémoire (suffisant pour 1 instance gratuite).

    Pour plusieurs instances : remplacer par Redis avec la même interface.
    L'horloge est injectable pour tester sans dormir.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, dq: deque[float], now: float) -> None:
        while dq and now - dq[0] >= self.window:
            dq.popleft()

    def _make_room(self, now: float) -> None:
        """Évite qu'un attaquant gonfle la mémoire avec des millions de clés."""
        for key in [k for k, dq in self._hits.items() if not dq or now - dq[-1] >= self.window]:
            del self._hits[key]
        if len(self._hits) >= self._max_keys:
            oldest = min(self._hits, key=lambda k: self._hits[k][-1])
            del self._hits[oldest]

    def allow(self, key: str) -> bool:
        now = self._clock()
        dq = self._hits.get(key)
        if dq is None:
            if len(self._hits) >= self._max_keys:
                self._make_room(now)
            dq = self._hits[key] = deque()
        self._prune(dq, now)
        if len(dq) >= self.max_requests:
            return False
        dq.append(now)
        return True

    def used(self, key: str) -> int:
        """Nombre de requêtes déjà comptées dans la fenêtre pour cette clé (sans en consommer)."""
        dq = self._hits.get(key)
        if not dq:
            return 0
        self._prune(dq, self._clock())
        return len(dq)

    def retry_after(self, key: str) -> int:
        """Secondes avant qu'une requête soit de nouveau acceptée (pour l'en-tête Retry-After)."""
        dq = self._hits.get(key)
        if not dq:
            return 0
        now = self._clock()
        self._prune(dq, now)
        if len(dq) < self.max_requests:
            return 0
        return max(1, int(self.window - (now - dq[0])) + 1)


def get_client_ip(request: HTTPConnection, trust_proxy_headers: bool = False, proxy_hops: int = 0) -> str:
    """IP du client pour le rate limiting.

    X-Forwarded-For est contrôlable par le client : on ne le lit que derrière un proxy de confiance.
    `proxy_hops` = nombre d'adresses de PROXYS ajoutées après celle du client (0 : nginx classique, la
    dernière entrée est le client ; 1 sur Render, où un proxy s'ajoute derrière : la dernière entrée est
    alors un proxy partagé et changeant, pas le visiteur). On lit l'entrée à cette distance de la fin ;
    ce que le client écrit au début de l'en-tête n'a donc aucune influence. Chaîne trop courte
    (accès direct, hors proxy) : adresse de la connexion.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            entries = [e.strip() for e in forwarded.split(",")]
            hops = max(0, proxy_hops)
            if len(entries) > hops and entries[-(hops + 1)]:
                return entries[-(hops + 1)]
    return request.client.host if request.client else "unknown"


class DailyBudget:
    """Budget glissant sur 24 h (ex. secondes d'audio) partagé par tous les visiteurs.

    Protège un quota fournisseur global : quand il est épuisé, la fonctionnalité se ferme pour tous
    plutôt que de laisser le fournisseur bloquer le compte.
    """

    def __init__(self, limit: float, window_seconds: float = 86_400, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._entries: deque[tuple[float, float]] = deque()
        self._total = 0.0

    def _prune(self) -> None:
        now = self._clock()
        while self._entries and now - self._entries[0][0] >= self.window:
            self._total -= self._entries.popleft()[1]

    def remaining(self) -> float:
        self._prune()
        return max(0.0, self.limit - self._total)

    def spend(self, amount: float) -> None:
        self._prune()
        self._entries.append((self._clock(), amount))
        self._total += amount
