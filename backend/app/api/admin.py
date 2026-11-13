"""Lecture des coûts réels : GET /api/v1/admin/costs. Fermé (404) tant que FACTS_ADMIN_TOKEN n'est pas défini."""

import hmac

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.config import parse_prices
from app.core.security import get_client_ip

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/costs")
async def costs(request: Request, days: int = Query(7, ge=1, le=90)) -> dict:
    app = request.app
    settings = app.state.settings
    expected = settings.admin_token.get_secret_value()
    recorder = app.state.costs
    if not expected or recorder is None:
        raise HTTPException(status_code=404, detail="Not Found")  # indiscernable d'une route inexistante
    ip = get_client_ip(request, settings.trust_proxy_headers, settings.proxy_hops)
    limiter = app.state.login_limiter  # même garde que les connexions : freine la force brute du jeton
    if not limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Trop de tentatives.", headers={"Retry-After": str(limiter.retry_after(ip))})
    auth = request.headers.get("authorization", "")
    given = auth[7:] if auth[:7].lower() == "bearer " else ""
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Non autorisé.", headers={"WWW-Authenticate": "Bearer"})
    await recorder.flush()  # chiffres à jour, y compris ce qui est encore en mémoire
    return {"profile": settings.profile, **await recorder.report(days, parse_prices(settings.cost_prices))}
