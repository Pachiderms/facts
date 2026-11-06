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


def enforce_daily_check_limit(request: Request) -> None:
    """Plafond par visiteur et par jour : protège les crédits de recherche et les quotas LLM gratuits."""
    limiter = request.app.state.daily_check_limiter
    ip = get_client_ip(request, request.app.state.settings.trust_proxy_headers)
    if not limiter.allow(ip):
        raise HTTPException(
            status_code=429,
            detail="Limite quotidienne de vérifications atteinte. Revenez demain.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )
