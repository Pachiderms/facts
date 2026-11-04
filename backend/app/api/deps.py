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
