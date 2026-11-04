"""Trust meter : score de fiabilité factuelle d'un salon.

Principe : le LLM ne fait que CLASSER chaque message (vérifié / à nuancer / ...).
Le score, lui, est calculé par une formule déterministe et testable, pas par le LLM.
Il mesure la rigueur FACTUELLE des échanges, jamais le camp politique des intervenants.
"""

from collections.abc import Mapping

# Poids de chaque verdict dans le score. Seuls ces statuts « comptent » ; les autres
# (argument sans chiffre, vérification indisponible...) n'influencent pas le score.
WEIGHTS: dict[str, float] = {
    "verified": 1.0,
    "nuanced": 0.5,
    "unsourced": 0.25,
    "false": 0.0,
}

# Lissage bayésien : le score démarre à 50 et un seul message ne peut pas le mettre à 0 ou 100.
# PRIOR_WEIGHT = poids de l'a priori, exprimé en nombre de messages « neutres » (0,5).
PRIOR_WEIGHT = 2.0
NEUTRAL = 0.5


def compute_trust_score(counts: Mapping[str, int]) -> int | None:
    """Score 0-100, ou None tant qu'aucun message vérifiable n'a été évalué."""
    n = sum(counts.get(s, 0) for s in WEIGHTS)
    if n == 0:
        return None
    total = sum(w * counts.get(s, 0) for s, w in WEIGHTS.items())
    return round(100 * (PRIOR_WEIGHT * NEUTRAL + total) / (PRIOR_WEIGHT + n))


def trust_delta(old: int | None, new: int | None) -> int:
    """Variation affichée à côté d'un message. Le point de départ implicite est 50."""
    if new is None:
        return 0
    return new - (50 if old is None else old)
