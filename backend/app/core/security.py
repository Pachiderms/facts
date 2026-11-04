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


def get_client_ip(request: HTTPConnection, trust_proxy_headers: bool = False) -> str:
    """IP du client pour le rate limiting.

    X-Forwarded-For est contrôlable par le client : on ne le lit que derrière un proxy de
    confiance, et on prend la DERNIÈRE entrée (celle ajoutée par ce proxy), pas la première.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            last = forwarded.split(",")[-1].strip()
            if last:
                return last
    return request.client.host if request.client else "unknown"
