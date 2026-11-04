"""Score de confiance par domaine.

Ces scores sont une HEURISTIQUE par type de source (institution publique, recherche,
presse, autre), pas un jugement politique : la liste « recherche / think tanks » mélange
volontairement des organismes de sensibilités différentes. Elle est publique et
modifiable ici ; un score n'est jamais la preuve qu'une affirmation est vraie.
"""

from urllib.parse import urlparse

TIER_INSTITUTIONAL = 95
TIER_RESEARCH = 80
TIER_PRESS = 70
TIER_OTHER = 40

# Statistique publique, audit, régulateurs, organisations internationales.
INSTITUTIONAL_DOMAINS = {
    "insee.fr", "banque-france.fr", "ccomptes.fr", "cor-retraites.fr", "hcfp.fr",
    "rte-france.com", "cre.fr", "vie-publique.fr", "legifrance.gouv.fr", "service-public.fr",
    "assemblee-nationale.fr", "senat.fr", "conseil-constitutionnel.fr", "haut-conseil-climat.fr",
    "dares.travail-emploi.gouv.fr", "drees.solidarites-sante.gouv.fr", "strategie.gouv.fr",
    "iea.org", "oecd.org", "imf.org", "ilo.org", "worldbank.org", "ecb.europa.eu",
    "eurostat.ec.europa.eu", "europa.eu", "un.org",
}

# Recherche académique et centres d'étude de différentes sensibilités.
RESEARCH_DOMAINS = {
    "ofce.sciences-po.fr", "sciencespo.fr", "cnrs.fr", "ires.fr", "cepremap.fr", "cepii.fr",
    "ifrap.org", "institutmontaigne.fr", "fondapol.org", "terra-nova.fr", "fondation-jean-jaures.org",
    "atterres.org", "iesf.fr", "bruegel.org", "ifs.org.uk", "nber.org", "cairn.info", "hal.science",
}

PRESS_DOMAINS = {
    "lemonde.fr", "lefigaro.fr", "liberation.fr", "lesechos.fr", "francetvinfo.fr", "la-croix.com",
    "humanite.fr", "latribune.fr", "afp.com", "reuters.com", "apnews.com", "bbc.com", "franceinfo.fr",
    "radiofrance.fr", "mediapart.fr", "lexpress.fr", "lepoint.fr", "marianne.net", "alternatives-economiques.fr",
}

_INSTITUTIONAL_SUFFIXES = (".gouv.fr", ".europa.eu", ".gov", ".gouv.qc.ca")
_RESEARCH_SUFFIXES = (".edu", ".ac.uk", ".univ-paris1.fr")


def extract_domain(url: str) -> str:
    """Nom de domaine normalisé (minuscules, sans 'www.'), '' si l'URL est inexploitable."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _matches(domain: str, known: set[str]) -> bool:
    # "x.insee.fr" doit matcher "insee.fr", mais pas "fakeinsee.fr" ni "insee.fr.evil.com".
    return any(domain == k or domain.endswith("." + k) for k in known)


def domain_trust_score(domain: str) -> int:
    if not domain:
        return 0
    if _matches(domain, INSTITUTIONAL_DOMAINS) or domain.endswith(_INSTITUTIONAL_SUFFIXES):
        return TIER_INSTITUTIONAL
    if _matches(domain, RESEARCH_DOMAINS) or domain.endswith(_RESEARCH_SUFFIXES):
        return TIER_RESEARCH
    if _matches(domain, PRESS_DOMAINS):
        return TIER_PRESS
    return TIER_OTHER
