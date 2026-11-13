"""Comptes : POST /auth/google, GET /auth/me, POST /auth/logout, /auth/logout-all, GET /auth/export, POST /auth/delete.

Session = en-tête `Authorization: Bearer <jeton>` (pas de cookie : le site et l'API sont sur deux domaines).
Toutes les réponses sont `Cache-Control: no-store`. Erreurs génériques : on ne dit jamais POURQUOI un jeton est refusé.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import enforce_read_rate_limit
from app.core.identity import is_valid_token
from app.core.security import get_client_ip
from app.services.accounts import AccountError, AccountService, User
from app.services.google_auth import AuthError, GoogleVerifier

logger = logging.getLogger("facts.auth")


# `Cache-Control: no-store` est posé sur TOUTES les réponses par le middleware de main.py (testé ici).
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class GoogleLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential: Annotated[str, Field(min_length=20, max_length=4096)]
    participant_token: str | None = None

    @field_validator("participant_token")
    @classmethod
    def _token(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_token(v):
            raise ValueError("jeton invalide")
        return v


class DeleteAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool  # doit être vrai : évite une suppression par un POST vide


def _service(request: Request) -> AccountService:
    service = request.app.state.accounts
    if service is None:
        raise HTTPException(status_code=503, detail="Les comptes sont indisponibles.")
    return service


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


async def current_user(request: Request) -> User:
    user = await _service(request).authenticate(_bearer(request))
    if user is None:
        raise HTTPException(status_code=401, detail="Session expirée ou invalide.", headers={"WWW-Authenticate": "Bearer"})
    return user


def _public(user: User) -> dict[str, str]:
    return {"id": str(user.id), "email": user.email, "created_at": user.created_at.isoformat()}


@router.post("/google")
async def login_google(request: Request, body: GoogleLogin) -> dict:
    settings = request.app.state.settings
    service, verifier = _service(request), request.app.state.google
    ip = get_client_ip(request, settings.trust_proxy_headers, settings.proxy_hops)
    limiter = request.app.state.login_limiter
    if not limiter.allow(ip):  # avant toute vérification : le contrôle coûte du calcul et un appel réseau
        raise HTTPException(
            status_code=429, detail="Trop de tentatives. Réessayez plus tard.", headers={"Retry-After": str(limiter.retry_after(ip))}
        )
    try:
        identity = await verifier.verify(body.credential)
        token, user = await service.login_google(identity, body.participant_token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    except AccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"session_token": token, "user": _public(user)}


@router.get("/me", dependencies=[Depends(enforce_read_rate_limit)])
async def me(user: User = Depends(current_user)) -> dict:
    return {"user": _public(user)}


@router.post("/logout")
async def logout(request: Request, user: User = Depends(current_user)) -> dict:
    await _service(request).logout(_bearer(request))
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(request: Request, user: User = Depends(current_user)) -> dict:
    return {"revoked": await _service(request).logout_everywhere(user.id)}


@router.get("/export", dependencies=[Depends(enforce_read_rate_limit)])
async def export(request: Request, user: User = Depends(current_user)) -> dict:
    return await _service(request).export(user.id)


@router.post("/delete")
async def delete_account(request: Request, body: DeleteAccount, user: User = Depends(current_user)) -> dict:
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Confirmation requise.")
    billing = getattr(request.app.state, "billing", None)
    if billing is not None:
        info = await billing.status(user.id)
        if info["active"] and info["status"] != "cancelled":
            # La suppression n'annule pas la facturation chez le prestataire : on évite de faire payer un compte disparu.
            raise HTTPException(status_code=409, detail="Résiliez d'abord votre abonnement Pro (page Tarifs), puis supprimez le compte.")
    await _service(request).delete_account(user.id)
    logger.info("compte supprimé")  # jamais l'e-mail dans les journaux
    return {"deleted": True}
