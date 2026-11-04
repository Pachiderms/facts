import pytest

from app.core.domains import (
    TIER_INSTITUTIONAL,
    TIER_OTHER,
    TIER_PRESS,
    TIER_RESEARCH,
    domain_trust_score,
    extract_domain,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.INSEE.fr/fr/statistiques/123", "insee.fr"),
        ("http://tresor.economie.gouv.fr/x", "tresor.economie.gouv.fr"),
        ("https://exemple.org.:443/a", "exemple.org"),
        ("pas une url", ""),
        ("", ""),
    ],
)
def test_extract_domain(url, expected):
    assert extract_domain(url) == expected


@pytest.mark.parametrize(
    "domain,tier",
    [
        ("insee.fr", TIER_INSTITUTIONAL),
        ("tresor.economie.gouv.fr", TIER_INSTITUTIONAL),  # suffixe .gouv.fr
        ("blog.insee.fr", TIER_INSTITUTIONAL),  # sous-domaine d'un domaine connu
        ("ofce.sciences-po.fr", TIER_RESEARCH),
        ("ifrap.org", TIER_RESEARCH),
        ("atterres.org", TIER_RESEARCH),  # pluralisme : sensibilités différentes au même niveau
        ("lemonde.fr", TIER_PRESS),
        ("monblog-politique.com", TIER_OTHER),
        ("", 0),
    ],
)
def test_trust_tiers(domain, tier):
    assert domain_trust_score(domain) == tier


@pytest.mark.parametrize(
    "domain",
    ["fakeinsee.fr", "insee.fr.evil.com", "insee-fr.com", "gouv.fr.arnaque.net", "evil-gouv.fr"],
)
def test_lookalike_domains_do_not_get_institutional_trust(domain):
    """Sécurité : un faux domaine ne doit pas hériter du score d'une vraie institution."""
    assert domain_trust_score(domain) == TIER_OTHER


def test_pluralism_left_and_right_think_tanks_same_tier():
    assert domain_trust_score("ifrap.org") == domain_trust_score("atterres.org")
