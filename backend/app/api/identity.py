"""Résolution de l'identité d'une requête : compte connecté (si session valide) ou jeton anonyme.

Un visiteur connecté garde son jeton anonyme comme *alias* : son siège, ses sanctions et la propriété
de ses salons créés avant la connexion lui restent attachés (voir `Room.canonical`, `ModerationLedger.link`).
Une session absente, invalide ou inutilisable (base indisponible) ne bloque jamais : on retombe sur
l'identité anonyme, comme avant l'introduction des comptes.
"""

import logging
from typing import NamedTuple

from fastapi import FastAPI, Request

from app.core.identity import account_identity, participant_id

logger = logging.getLogger("facts.identity")


class Identity(NamedTuple):
    id: str  # identité principale (compte si connecté, sinon empreinte anonyme)
    aliases: tuple[str, ...]  # identités à rattacher (empreinte anonyme du navigateur)


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


async def resolve_identity(app: FastAPI, participant_token: str, session_token: str | None) -> Identity:
    anon = participant_id(participant_token)
    service = getattr(app.state, "accounts", None)
    if service is None or not session_token:
        return Identity(anon, ())
    try:
        user = await service.authenticate(session_token)
    except Exception:  # base indisponible : repli anonyme, jamais d'erreur côté salon
        logger.warning("authentification indisponible : repli sur l'identité anonyme")
        return Identity(anon, ())
    if user is None:
        return Identity(anon, ())
    return Identity(account_identity(user.id), (anon,))
