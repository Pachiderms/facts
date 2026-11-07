"""Identité anonyme : un jeton aléatoire généré par le navigateur, jamais renvoyé par le serveur.

Le serveur n'en garde que l'empreinte (SHA-256 tronqué) : propriétaire d'un salon, un seul siège
d'intervenant par personne, et base des futurs avertissements / exclusions. Ce n'est PAS un
compte : un visiteur qui vide son navigateur change d'identité (limite assumée, voir README).
"""

import hashlib
import re

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{22,64}")


def is_valid_token(token: object) -> bool:
    return isinstance(token, str) and TOKEN_RE.fullmatch(token) is not None


def participant_id(token: str) -> str:
    """Empreinte stable et non réversible du jeton (16 hex = 64 bits : largement assez ici)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
