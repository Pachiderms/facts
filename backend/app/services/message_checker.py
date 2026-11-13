"""Vérification d'un message de débat : réutilise le pipeline du chatbot."""

import re
from typing import Literal, Protocol

from pydantic import BaseModel

from app.core.security import InvalidInputError, looks_like_prompt_injection, sanitize_text
from app.core.text import fit_sentences
from app.services.claim_triage import FIGURE_RE, OPINION_RE, ClaimExtractor, is_triage_candidate
from app.services.factcheck import FactCheckService
from app.core.metering import operation

NOTE_MAX_CHARS = 420  # un message à plusieurs chiffres demande une note qui les couvre tous

BadgeType = Literal["green", "amber", "red", "gray"]

# Contrôle des coûts : on ne lance la recherche web + le LLM que si le message contient de quoi
# vérifier : un chiffre, un pourcentage, une quantité écrite en lettres (« plusieurs dizaines de
# milliards », « la moitié »), une comparaison chiffrée ou une référence à une source. Heuristique
# volontairement simple et remplaçable ; un message sans rien de tel reste « argument ».
_CHECKABLE_RE = re.compile(
    r"\d|%"
    r"|\b(?:milliards?|millions?|milliers?|mille|dizaines?|centaines?|pourcent\w*|taux|moiti[ée]|tiers|quarts?)\b"
    r"|\b(?:deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|quinze|vingt|trente|quarante|cinquante|soixante|cent)s?\b"
    r"|\bfois\s+(?:plus|moins)\b|\b(?:doubl|tripl)\w*"
    r"|\bselon\b|d['’]après|\b[ée]tudes?\b|\brapports?\b|\binsee\b|\bofce\b|\btr[ée]sor\b|cour des comptes",
    re.IGNORECASE,
)


# FIGURE_RE et OPINION_RE vivent dans claim_triage (partagés avec l'élargissement des extraits).
_FIGURE_RE, _OPINION_RE = FIGURE_RE, OPINION_RE


def is_quantified_assertion(text: str) -> bool:
    """Chiffre ou quantité avancés sans formule d'opinion : ne doit pas être écarté sur un simple « doute » du tri."""
    return bool(_FIGURE_RE.search(text)) and not _OPINION_RE.search(text)


def is_checkable(text: str) -> bool:
    return bool(_CHECKABLE_RE.search(text))


def is_candidate(text: str) -> bool:
    """Le message part en vérification : soit la règle le retient, soit il mérite un second avis du LLM (tri)."""
    return is_checkable(text) or is_triage_candidate(text)


class MessageCheck(BaseModel):
    status: Literal["pending", "verified", "nuanced", "false", "unsourced", "unchecked", "no_claim"]
    badge_type: BadgeType
    badge_text: str
    note: str = ""
    sources: list[dict[str, str]] = []

    @classmethod
    def pending(cls) -> "MessageCheck":
        return cls(status="pending", badge_type="gray", badge_text="VÉRIFICATION EN COURS")

    @classmethod
    def no_claim(cls) -> "MessageCheck":
        return cls(status="no_claim", badge_type="gray", badge_text="ARGUMENT", note="Aucun fait vérifiable.")

    @classmethod
    def unchecked(cls, reason: str) -> "MessageCheck":
        return cls(status="unchecked", badge_type="gray", badge_text=reason)


PREVIEW_CHARS = 120
CONTEXT_CHARS = 300


def reply_preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    """Aperçu affiché dans une réponse : texte du message cité, espaces réduits, coupé proprement."""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def reply_context(text: str, limit: int = CONTEXT_CHARS) -> str | None:
    """Message cité transmis comme CONTEXTE à la vérification : nettoyé, borné, jamais s'il ressemble à une injection.

    Ce texte vient d'un autre participant : c'est une donnée non fiable, qui ne sert qu'à comprendre les références
    (« cela », « cette loi ») de la réponse. Il n'est ni vérifié, ni utilisé comme source.
    """
    try:
        clean = sanitize_text(reply_preview(text, limit), limit)
    except InvalidInputError:
        return None
    return None if looks_like_prompt_injection(clean) else clean


class MessageChecker(Protocol):
    async def check(self, text: str, context: str | None = None) -> MessageCheck: ...


_VERDICT_MAP: dict[str, tuple[str, BadgeType, str]] = {
    "VRAI": ("verified", "green", "VÉRIFIÉ"),
    "À NUANCER": ("nuanced", "amber", "À NUANCER"),
    "FAUX": ("false", "red", "ERRONÉ"),
    "NON VÉRIFIABLE": ("unsourced", "amber", "NON ÉTAYÉ"),
}


class FactCheckMessageChecker:
    def __init__(self, service: FactCheckService) -> None:
        self._service = service

    async def check(self, text: str, context: str | None = None) -> MessageCheck:
        try:
            with operation("room_check"):
                if context is None:
                    response = await self._service.check(text, institutional_filter=True)
                else:
                    response = await self._service.check(text, institutional_filter=True, context=context)
        except InvalidInputError:
            # Inclut les tentatives d'injection : le message reste visible, mais n'est pas évalué.
            return MessageCheck.unchecked("NON ÉVALUÉ")
        status, badge_type, badge_text = _VERDICT_MAP[response.verdict]
        return MessageCheck(
            status=status,  # type: ignore[arg-type]
            badge_type=badge_type,
            badge_text=badge_text,
            note=fit_sentences(response.summary, NOTE_MAX_CHARS),
            sources=[{"title": s.title, "url": s.url, "domain": s.domain} for s in response.verified_sources[:3]],
        )


class TriagingMessageChecker:
    """Le LLM décide s'il y a un fait dans le message, et c'est ce fait (extrait littéral) qu'on vérifie.

    Une question n'est jamais triée : seule la règle simple la retient (comme avant).
    Si le tri est indisponible, la règle simple sert de filet : un message qu'elle retient est vérifié en entier,
    les autres ne sont pas évalués (jamais pénalisés sur une panne).
    """

    def __init__(self, inner: MessageChecker, extractor: ClaimExtractor) -> None:
        self._inner, self._extractor = inner, extractor

    @staticmethod
    def _triaged(text: str) -> bool:
        """Tout message long, et tout message court que la règle retient (« Selon moi… » compris) ; jamais une question."""
        return not text.strip().endswith("?") and (is_triage_candidate(text) or is_checkable(text))

    async def check(self, text: str, context: str | None = None) -> MessageCheck:
        if not self._triaged(text):
            return await self._call(text, context)
        result = await self._extractor.triage(text, context=context)
        if result.outcome == "claim" and result.claim:
            return await self._call(result.claim, context)
        if result.outcome == "unavailable":
            return await self._call(text, context) if is_checkable(text) else MessageCheck.unchecked("NON ÉVALUÉ")
        if is_quantified_assertion(text):
            # Filet : le modèle de tri est un second avis, pas un veto sur un chiffre (ex. « Cela pourrait entraîner
            # une baisse de 50 % des recettes »). Le vérificateur dira « non vérifiable » si rien n'est confrontable.
            return await self._call(text, context)
        return MessageCheck.no_claim()

    async def _call(self, text: str, context: str | None) -> MessageCheck:
        return await (self._inner.check(text) if context is None else self._inner.check(text, context=context))
