"""GET /api/v1/usage : où en est la personne de ses quotas du jour, et l'état (dégradé ou non) du service.

Identité : session facultative (compte gratuit) ; sans session, quota par IP. Lecture seule : ne consomme rien.
"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import enforce_read_rate_limit, optional_user
from app.core.security import get_client_ip

router = APIRouter(prefix="/api/v1", tags=["usage"])


@router.get("/usage", dependencies=[Depends(enforce_read_rate_limit)])
async def usage(request: Request) -> dict:
    state = request.app.state
    user = await optional_user(request)
    if user is not None:
        limiter, key, plan = state.account_check_limiter, str(user.id), "free"
    else:
        limiter, key, plan = state.daily_check_limiter, get_client_ip(request, state.settings.trust_proxy_headers), "anonymous"
    used = limiter.used(key)
    llm = getattr(state, "llm", None)
    return {
        "plan": plan,
        "checks": {"used": used, "limit": limiter.max_requests, "remaining": max(0, limiter.max_requests - used)},
        "degraded": bool(llm is not None and getattr(llm, "degraded", False)),
    }
