"""Dépendances FastAPI partagées (service, rate limiting)."""

from fastapi import HTTPException, Request

from app.core.security import get_client_ip
from app.services.factcheck import FactCheckService


def get_service(request: Request) -> FactCheckService:
    return request.app.state.service


def enforce_rate_limit(request: Request) -> None:
    limiter = request.app.state.limiter
    ip = get_client_ip(request, request.app.state.settings.trust_proxy_headers)
    if not limiter.allow(ip):
        raise HTTPException(
            status_code=429,
            detail="Trop de requêtes. Réessayez dans un instant.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )


def enforce_read_rate_limit(request: Request) -> None:
    """Lectures sans coût (liste des salons) : plafond plus large, compteur indépendant de /check."""
    limiter = request.app.state.read_limiter
    ip = get_client_ip(request, request.app.state.settings.trust_proxy_headers)
    if not limiter.allow(ip):
        raise HTTPException(
            status_code=429,
            detail="Trop de requêtes. Réessayez dans un instant.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )


async def optional_user(request: Request):
    """Compte de la session `Authorization: Bearer`, ou None (absente, invalide, comptes indisponibles)."""
    service = getattr(request.app.state, "accounts", None)
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if service is None or scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        return await service.authenticate(token.strip())
    except Exception:  # base indisponible : on traite la requête comme anonyme
        return None


async def enforce_daily_check_limit(request: Request) -> None:
    """Plafond par jour : protège les crédits de recherche et les quotas LLM gratuits.

    Sans compte : par IP. Avec un compte : par compte (plafond plus haut), l'IP gardant un plafond large
    pour qu'une personne ne multiplie pas ses quotas en créant des comptes depuis une même connexion.
    """
    state = request.app.state
    ip = get_client_ip(request, state.settings.trust_proxy_headers)
    user = await optional_user(request)
    if user is not None:
        if state.account_check_limiter.allow(str(user.id)) and state.ip_backstop_limiter.allow(ip):
            return
        limiter, key = state.account_check_limiter, str(user.id)
        if limiter.used(key) < limiter.max_requests:  # c'est le filet par IP qui a refusé
            limiter, key = state.ip_backstop_limiter, ip
        raise HTTPException(
            status_code=429,
            detail="Limite quotidienne de vérifications atteinte. Revenez demain.",
            headers={"Retry-After": str(limiter.retry_after(key))},
        )
    limiter = state.daily_check_limiter
    if not limiter.allow(ip):
        raise HTTPException(
            status_code=429,
            detail="Limite quotidienne de vérifications atteinte. Revenez demain.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )
