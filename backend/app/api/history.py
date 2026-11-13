"""Historique « Mes salons » synchronisé : GET/POST /api/v1/me/history (POST remplace la liste : le CORS du projet n'autorise que GET et POST) (session requise)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import current_user
from app.api.deps import enforce_read_rate_limit
from app.services.accounts import User
from app.services.history import HISTORY_MAX, HistoryEntry

router = APIRouter(prefix="/api/v1/me", tags=["history"])


def _service(request: Request):
    service = getattr(request.app.state, "history", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Les comptes sont indisponibles.")
    return service


class HistoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[HistoryEntry] = Field(max_length=HISTORY_MAX)


@router.get("/history", dependencies=[Depends(enforce_read_rate_limit)])
async def get_history(request: Request, user: User = Depends(current_user)) -> dict:
    return {"entries": await _service(request).get(user.id)}


@router.post("/history", dependencies=[Depends(enforce_read_rate_limit)])
async def replace_history(request: Request, body: HistoryBody, user: User = Depends(current_user)) -> dict:
    service = _service(request)
    await service.replace(user.id, body.entries)
    return {"entries": await service.get(user.id)}
