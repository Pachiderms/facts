"""GET /api/v1/usage : où en est la personne de ses quotas du jour, et l'état (dégradé ou non) du service.

Identité : session facultative (compte gratuit) ; sans session, quota par IP. Lecture seule : ne consomme rien.
"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import enforce_read_rate_limit, quota_who

router = APIRouter(prefix="/api/v1", tags=["usage"])


@router.get("/usage", dependencies=[Depends(enforce_read_rate_limit)])
async def usage(request: Request) -> dict:
    state = request.app.state
    data = await state.quota_policy.usage(await quota_who(request))
    llm = getattr(state, "llm", None)
    data["degraded"] = bool(llm is not None and getattr(llm, "degraded", False))
    return data
