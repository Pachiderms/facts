"""Contrats de données de l'API (entrée utilisateur et sortie de l'agent).

Le schéma de sortie reprend celui du prompt système de Guidelines.md. Il sert
aussi à VALIDER la réponse du LLM : tout JSON hors contrat est rejeté.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Verdict = Literal["VRAI", "FAUX", "À NUANCER", "NON VÉRIFIABLE"]


class CheckRequest(BaseModel):
    """Corps de POST /api/v1/check."""

    model_config = ConfigDict(extra="forbid")

    assertion: str = Field(min_length=10, max_length=500)
    institutional_filter: bool = True

    @field_validator("assertion", mode="before")
    @classmethod
    def _strip(cls, v):
        # Strip AVANT les contraintes de longueur : "          " n'est pas une assertion.
        return v.strip() if isinstance(v, str) else v


class View(BaseModel):
    title: str = Field(max_length=120)
    points: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("points")
    @classmethod
    def _point_length(cls, points: list[str]) -> list[str]:
        if any(len(p) > 500 for p in points):
            raise ValueError("point trop long")
        return points


class Source(BaseModel):
    title: str = Field(max_length=200)
    url: str = Field(max_length=500)
    domain: str = Field(max_length=100)
    trust_score: int = Field(ge=0, le=100)

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        # Bloque javascript:, data:, file:... qui finiraient dans un <a href> du front.
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("l'URL doit être http(s)")
        return v


class LLMSourceRef(BaseModel):
    """Source citée par le LLM. Seule l'URL compte : titre, domaine et score de confiance
    sont RECALCULÉS côté serveur à partir des résultats de recherche (le LLM peut mentir)."""

    url: str = Field(max_length=500)
    title: str = Field(default="", max_length=300)
    domain: str = Field(default="", max_length=100)
    trust_score: int = Field(default=0, ge=0, le=100)


class LLMAnalysis(BaseModel):
    """Ce que le LLM doit produire. Champs inconnus ignorés (tolérance aux ajouts)."""

    verdict: Verdict
    confidence_score: int = Field(ge=0, le=100)
    # Marge côté modèle : le serveur raccourcit à 600 en phrases entières (voir factcheck.py).
    summary: str = Field(max_length=2000)
    liberal_institutional_view: View
    heterodox_social_view: View
    verified_sources: list[LLMSourceRef] = Field(default_factory=list, max_length=10)


class CheckResponse(LLMAnalysis):
    """Réponse publique de POST /api/v1/check (sources revalidées par le serveur)."""

    summary: str = Field(max_length=600)
    verified_sources: list[Source] = Field(default_factory=list, max_length=10)
    cached: bool = False
