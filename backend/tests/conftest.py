"""Doublures de test partagées : aucune requête réseau réelle dans la suite."""

import json

import pytest

from app.adapters.llm import LLMError
from app.adapters.search import SearchResult


class ScriptedLLM:
    """LLM factice : renvoie les réponses prévues dans l'ordre et enregistre les prompts."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, system, user, *, json_mode=False, max_tokens=1200, temperature=0.0):
        self.calls.append({"system": system, "user": user, "json_mode": json_mode})
        if not self.responses:
            raise AssertionError("appel LLM inattendu")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


class StaticProvider:
    """Fournisseur de recherche factice."""

    def __init__(self, results=None, error=None):
        self.results, self.error, self.calls = results or [], error, []

    async def search(self, query, max_results):
        self.calls.append((query, max_results))
        if self.error:
            raise self.error
        return list(self.results)


def result(url, trust, title="Titre", snippet="Extrait."):
    return SearchResult(title, url, snippet, url.split("/")[2].removeprefix("www."), trust)


OFCE = result("https://www.ofce.sciences-po.fr/pbrief102.pdf", 80, "Impact de la hausse du SMIC")
IFRAP = result("https://www.ifrap.org/smic-1700", 80, "Évaluation de l'iFRAP")
BLOG = result("https://blog.example.com/smic", 40, "Mon avis")

QUERIES = {"queries": ["impact SMIC 1700 euros économie France OFCE"]}


def analysis(sources=("https://www.ofce.sciences-po.fr/pbrief102.pdf",), **over):
    base = {
        "verdict": "À NUANCER",
        "confidence_score": 85,
        "summary": "L'impact divise les économistes.",
        "liberal_institutional_view": {"title": "Risques", "points": ["Frein à l'embauche."]},
        "heterodox_social_view": {"title": "Leviers", "points": ["Soutien à la consommation."]},
        "verified_sources": [{"url": u} for u in sources],
    }
    base.update(over)
    return base


@pytest.fixture
def llm_error():
    return LLMError("boom")
