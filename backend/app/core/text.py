"""Raccourcissement de textes SANS jamais laisser une phrase coupée."""

import re

_SENTENCE_RE = re.compile(r".+?(?:[.!?…]+(?=\s|$)|$)", re.DOTALL)
_TERMINAL = (".", "!", "?", "…", ")", "»", '"')


def _sentences(text: str) -> list[str]:
    return [m.group(0).strip() for m in _SENTENCE_RE.finditer(text) if m.group(0).strip()]


def is_complete(text: str) -> bool:
    """Vrai si le texte se termine par une ponctuation finale (pas par un fragment)."""
    return text.rstrip().endswith(_TERMINAL)


def fit_sentences(text: str, limit: int) -> str:
    """Renvoie au plus `limit` caractères, en ne gardant que des phrases entières.

    - texte déjà assez court et complet : renvoyé tel quel ;
    - trop long : on garde les premières phrases entières qui tiennent ;
    - aucune phrase entière ne tient (ou le texte finit en fragment sans ponctuation) :
      coupe à la limite d'un mot, retire la ponctuation orpheline et ajoute « … ».
    """
    text = " ".join(text.split())
    if not text:
        return ""
    if len(text) <= limit and is_complete(text):
        return text

    kept = ""
    for sentence in _sentences(text):
        if not is_complete(sentence):
            break  # fragment final (sortie du modèle coupée) : on ne le garde pas
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > limit:
            break
        kept = candidate
    if kept:
        return kept

    # Une seule phrase, trop longue ou non terminée : coupe propre au dernier mot entier.
    room = max(limit - 1, 1)
    cut = text[:room]
    if len(text) > room and not text[room].isspace():
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    cut = cut.rstrip(" ,;:-–—(«\"'")
    return f"{cut}…" if cut else "…"
