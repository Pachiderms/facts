"""Dépendances FastAPI partagées (service, rate limiting)."""

from fastapi import HTTPException, Request

from app.core.identity import account_identity
from app.core.security import get_client_ip
from app.services.factcheck import FactCheckService


def get_service(request: Request) -> FactCheckService:
    return request.app.state.service


def enforce_rate_limit(request: Request) -> None:
    limiter = request.app.state.limiter
    ip = get_client_ip(request, request.app.state.settings.trust_proxy_headers, request.app.state.settings.proxy_hops)
    if not limiter.allow(ip):
        raise HTTPException(
            status_code=429,
            detail="Trop de requêtes. Réessayez dans un instant.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )


def enforce_read_rate_limit(request: Request) -> None:
    """Lectures sans coût (liste des salons) : plafond plus large, compteur indépendant de /check."""
    limiter = request.app.state.read_limiter
    ip = get_client_ip(request, request.app.state.settings.trust_proxy_headers, request.app.state.settings.proxy_hops)
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


async def account_plan(app, user_id) -> str:
    """« pro » pour un abonné actif, « free » sinon (et si le paiement n'est pas activé ou la base indisponible)."""
    billing = getattr(app.state, "billing", None)
    return await billing.plan_of(user_id) if billing is not None else "free"


async def quota_who(request: Request):
    """Qui consomme : compte (session valide) ou visiteur anonyme (IP). Voir QuotaPolicy."""
    state = request.app.state
    ip = get_client_ip(request, state.settings.trust_proxy_headers, state.settings.proxy_hops)
    user = await optional_user(request)
    if user is None:
        return state.quota_policy.anonymous(ip)
    plan = await account_plan(request.app, user.id)
    return state.quota_policy.account(account_identity(user.id), ip, plan)  # même clé que le débat (WebSocket)


async def enforce_daily_check_limit(request: Request) -> None:
    """Plafond par jour : protège les crédits de recherche et les quotas LLM gratuits.

    Sans compte : par IP. Avec un compte : par compte (plafond plus haut), l'IP gardant un plafond large
    pour qu'une personne ne multiplie pas ses quotas en créant des comptes depuis une même connexion.
    Compteurs durables (base) : un redémarrage du serveur ne les remet pas à zéro.
    """
    policy = request.app.state.quota_policy
    if not await policy.consume_check(await quota_who(request)):
        raise HTTPException(
            status_code=429,
            detail="Limite quotidienne de vérifications atteinte. Revenez demain.",
            headers={"Retry-After": str(policy.store.retry_after())},
        )
