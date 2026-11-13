"""Mesure des coûts réels : combien coûte une vérification en appels LLM et en crédits de recherche ?

Principe
  * Les adaptateurs (LLM, recherche) signalent chaque appel avec `record_llm` / `record_search`.
  * Un `operation(...)` posé par le service appelant dit POURQUOI l'appel a lieu (vérification, modération…),
    via une variable de contexte : aucune signature n'est modifiée et aucun texte d'utilisateur ne transite.
  * Les compteurs sont agrégés en mémoire par jour UTC, puis écrits par lots dans `cost_usage`.
  * Aucune donnée personnelle : ni identité, ni IP, ni contenu — seulement des totaux par jour / opération / modèle.
  * Les prix ne sont PAS stockés : ils s'appliquent à la lecture, donc un tarif corrigé vaut aussi pour le passé.

Sans compteur actif (tests, scripts) tous les appels sont des no-op.
"""

import contextvars
import math
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone

MAX_TOKENS = 10_000_000  # une valeur absurde venue d'un fournisseur ne doit pas fausser les totaux
MAX_NAME = 64

KIND_ACTION = "action"  # une action d'utilisateur (une vérification, un message de salon…)
KIND_LLM = "llm"
KIND_SEARCH = "search"

_operation: contextvars.ContextVar[str | None] = contextvars.ContextVar("facts_operation", default=None)


@dataclass
class Counts:
    calls: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    credits: int = 0

    def add(self, other: "Counts") -> None:
        self.calls += other.calls
        self.errors += other.errors
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.credits += other.credits


Key = tuple[date, str, str, str, str]  # (jour UTC, profil, opération, nature, nom)


def _clean_name(value: str) -> str:
    return "".join(c for c in value if c.isprintable())[:MAX_NAME] or "?"


def _clamp(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float) or (isinstance(value, float) and not math.isfinite(value)):
        return 0
    return max(0, min(int(value), MAX_TOKENS))


class UsageMeter:
    def __init__(self, profile: str = "beta", clock: Callable[[], datetime] | None = None) -> None:
        self.profile = profile
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._pending: dict[Key, Counts] = defaultdict(Counts)

    def _key(self, kind: str, name: str) -> Key:
        return (self._clock().date(), self.profile, _operation.get() or "other", kind, _clean_name(name))

    def action(self, operation_name: str) -> None:
        key = (self._clock().date(), self.profile, _clean_name(operation_name), KIND_ACTION, "-")
        self._pending[key].calls += 1

    def llm(self, model: str, prompt_tokens: object = 0, completion_tokens: object = 0, *, error: bool = False) -> None:
        c = self._pending[self._key(KIND_LLM, model)]
        if error:
            c.errors += 1
            return
        c.calls += 1
        c.prompt_tokens += _clamp(prompt_tokens)
        c.completion_tokens += _clamp(completion_tokens)

    def search(self, provider: str, credits: int = 0, *, error: bool = False) -> None:
        c = self._pending[self._key(KIND_SEARCH, provider)]
        if error:
            c.errors += 1
            return
        c.calls += 1
        c.credits += _clamp(credits)

    def take(self) -> dict[Key, Counts]:
        """Vide et renvoie les compteurs en attente (l'appelant doit les `restore` si l'écriture échoue)."""
        taken, self._pending = dict(self._pending), defaultdict(Counts)
        return taken

    def restore(self, taken: dict[Key, Counts]) -> None:
        for key, counts in taken.items():
            self._pending[key].add(counts)

    def __len__(self) -> int:
        return len(self._pending)


_meter: UsageMeter | None = None


def set_meter(meter: UsageMeter | None) -> None:
    global _meter
    _meter = meter


def get_meter() -> UsageMeter | None:
    return _meter


def record_llm(model: str, prompt_tokens: object = 0, completion_tokens: object = 0, *, error: bool = False) -> None:
    if _meter is not None:
        _meter.llm(model, prompt_tokens, completion_tokens, error=error)


def record_search(provider: str, credits: int = 0, *, error: bool = False) -> None:
    if _meter is not None:
        _meter.search(provider, credits, error=error)


@contextmanager
def operation(name: str, *, count_action: bool = True) -> Iterator[None]:
    """Étiquette les appels faits dans ce bloc (y compris dans les tâches lancées depuis lui)."""
    token = _operation.set(name)
    if count_action and _meter is not None:
        _meter.action(name)
    try:
        yield
    finally:
        _operation.reset(token)


@contextmanager
def default_operation(name: str) -> Iterator[None]:
    """Comme `operation`, mais sans écraser une étiquette déjà posée par l'appelant."""
    if _operation.get() is not None:
        yield
        return
    with operation(name):
        yield
