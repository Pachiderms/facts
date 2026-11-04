import pytest
from pydantic import ValidationError

from app.core.schemas import CheckRequest, CheckResponse, LLMAnalysis, Source

VALID_ANALYSIS = {
    "verdict": "À NUANCER",
    "confidence_score": 85,
    "summary": "Synthèse neutre.",
    "liberal_institutional_view": {"title": "Risques", "points": ["a"]},
    "heterodox_social_view": {"title": "Leviers", "points": ["b"]},
    "verified_sources": [
        {"title": "OFCE", "url": "https://www.ofce.sciences-po.fr/x.pdf", "domain": "ofce.sciences-po.fr", "trust_score": 95}
    ],
}


# ---------- Fonctionnel ----------
def test_request_is_stripped():
    r = CheckRequest(assertion="   Le SMIC à 1700 euros est dangereux   ")
    assert r.assertion == "Le SMIC à 1700 euros est dangereux"


def test_request_defaults_to_institutional_filter():
    assert CheckRequest(assertion="Une assertion assez longue").institutional_filter is True


def test_valid_analysis_roundtrip():
    r = CheckResponse(**VALID_ANALYSIS)
    assert r.cached is False
    assert r.verdict == "À NUANCER"


def test_llm_extra_fields_are_ignored():
    a = LLMAnalysis(**VALID_ANALYSIS, bonus="champ inattendu")
    assert not hasattr(a, "bonus")


# ---------- Sécurité / robustesse ----------
def test_request_rejects_too_short_and_whitespace_only():
    with pytest.raises(ValidationError):
        CheckRequest(assertion="court")
    with pytest.raises(ValidationError):
        CheckRequest(assertion=" " * 50)


def test_request_rejects_too_long():
    with pytest.raises(ValidationError):
        CheckRequest(assertion="x" * 501)


def test_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        CheckRequest(assertion="Une assertion assez longue", is_admin=True)


def test_request_rejects_non_string():
    with pytest.raises(ValidationError):
        CheckRequest(assertion=12345678901234)


@pytest.mark.parametrize("verdict", ["TRUE", "peut-être", "", "vrai"])
def test_invalid_verdict_rejected(verdict):
    with pytest.raises(ValidationError):
        LLMAnalysis(**{**VALID_ANALYSIS, "verdict": verdict})


@pytest.mark.parametrize("score", [-1, 101, 1000])
def test_confidence_bounds(score):
    with pytest.raises(ValidationError):
        LLMAnalysis(**{**VALID_ANALYSIS, "confidence_score": score})


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>", "file:///etc/passwd", "ftp://x.org"])
def test_source_url_must_be_http(url):
    with pytest.raises(ValidationError):
        Source(title="x", url=url, domain="x.org", trust_score=50)


def test_too_many_points_rejected():
    bad = {**VALID_ANALYSIS, "liberal_institutional_view": {"title": "t", "points": ["p"] * 7}}
    with pytest.raises(ValidationError):
        LLMAnalysis(**bad)
