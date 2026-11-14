"""Administration (jeton FACTS_ADMIN_TOKEN) : coûts réels et licences Edu. Fermée (404) tant que le jeton n'est pas défini."""

import hmac

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import parse_prices
from app.core.security import get_client_ip
from app.services.plans import UnknownAccountError

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_admin(request: Request) -> None:
    app = request.app
    settings = app.state.settings
    expected = settings.admin_token.get_secret_value()
    if not expected:
        raise HTTPException(status_code=404, detail="Not Found")  # indiscernable d'une route inexistante
    ip = get_client_ip(request, settings.trust_proxy_headers, settings.proxy_hops)
    limiter = app.state.login_limiter  # même garde que les connexions : freine la force brute du jeton
    if not limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Trop de tentatives.", headers={"Retry-After": str(limiter.retry_after(ip))})
    auth = request.headers.get("authorization", "")
    given = auth[7:] if auth[:7].lower() == "bearer " else ""
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Non autorisé.", headers={"WWW-Authenticate": "Bearer"})


@router.get("/costs", dependencies=[Depends(require_admin)])
async def costs(request: Request, days: int = Query(7, ge=1, le=90)) -> dict:
    app = request.app
    recorder = app.state.costs
    if recorder is None:
        raise HTTPException(status_code=404, detail="Not Found")
    await recorder.flush()  # chiffres à jour, y compris ce qui est encore en mémoire
    return {"profile": app.state.settings.profile, **await recorder.report(days, parse_prices(app.state.settings.cost_prices))}


# ---------- licences accordées à la main (plan Edu) ----------
class GrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    plan: Literal["edu"] = "edu"
    check_pool: int | None = Field(default=None, ge=1, le=10_000_000, description="vérifications par mois ; vide = valeur par défaut")
    days: int | None = Field(default=None, ge=1, le=3650, description="durée en jours ; vide = sans fin")
    note: str | None = Field(default=None, max_length=200, description="ex. nom de l'établissement ; jamais de donnée sensible")

    @field_validator("note")
    @classmethod
    def _printable(cls, v: str | None) -> str | None:
        if v is not None and not v.isprintable():
            raise ValueError("caractères non imprimables")
        return v


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")


def _plans(request: Request):
    plans = request.app.state.plans
    if plans is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible.")
    return plans


@router.get("/plans", dependencies=[Depends(require_admin)])
async def list_plans(request: Request) -> dict:
    return {"grants": await _plans(request).listing()}


@router.post("/plans/grant", dependencies=[Depends(require_admin)])
async def grant_plan(request: Request, body: GrantRequest) -> dict:
    try:
        return await _plans(request).grant(body.email, body.plan, check_pool=body.check_pool, days=body.days, note=body.note)
    except UnknownAccountError:
        raise HTTPException(status_code=404, detail="Aucun compte avec cet e-mail : la personne doit d'abord se connecter une fois.") from None


@router.post("/plans/revoke", dependencies=[Depends(require_admin)])
async def revoke_plan(request: Request, body: RevokeRequest) -> dict:
    return {"revoked": await _plans(request).revoke(body.email)}
