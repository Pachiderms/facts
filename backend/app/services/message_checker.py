"""Vérification d'un message de débat : réutilise le pipeline du chatbot."""

import re
from typing import Literal, Protocol

from pydantic import BaseModel

from app.core.security import InvalidInputError
from app.core.text import fit_sentences
from app.services.factcheck import FactCheckService

NOTE_MAX_CHARS = 300

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


def is_checkable(text: str) -> bool:
    return bool(_CHECKABLE_RE.search(text))


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
        return cls(status="no_claim", badge_type="gray", badge_text="ARGUMENT", note="Aucun fait chiffré à vérifier.")

    @classmethod
    def unchecked(cls, reason: str) -> "MessageCheck":
        return cls(status="unchecked", badge_type="gray", badge_text=reason)


class MessageChecker(Protocol):
    async def check(self, text: str) -> MessageCheck: ...


_VERDICT_MAP: dict[str, tuple[str, BadgeType, str]] = {
    "VRAI": ("verified", "green", "VÉRIFIÉ"),
    "À NUANCER": ("nuanced", "amber", "À NUANCER"),
    "FAUX": ("false", "red", "ERRONÉ"),
    "NON VÉRIFIABLE": ("unsourced", "amber", "NON ÉTAYÉ"),
}


class FactCheckMessageChecker:
    def __init__(self, service: FactCheckService) -> None:
        self._service = service

    async def check(self, text: str) -> MessageCheck:
        try:
            response = await self._service.check(text, institutional_filter=True)
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
