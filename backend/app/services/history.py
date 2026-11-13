"""Historique « Mes salons » d'un compte : lecture et remplacement complet (le client fusionne avant d'envoyer)."""

import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.security import sanitize_text, InvalidInputError
from app.db.engine import Database
from app.db.schema import user_rooms

HISTORY_MAX = 20
ROOM_ID_RE = re.compile(r"[a-z0-9-]{1,64}")
MAX_MS = 4_102_444_800_000  # an 2100 : borne contre les valeurs absurdes


class HistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str = Field(max_length=400)
    visibility: str
    owner: StrictBool = False
    pinned: StrictBool = False
    last_visit: StrictInt = Field(ge=0, le=MAX_MS, alias="lastVisit")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ROOM_ID_RE.fullmatch(v):
            raise ValueError("identifiant de salon invalide")
        return v

    @field_validator("visibility")
    @classmethod
    def _visibility(cls, v: str) -> str:
        if v not in ("public", "private"):
            raise ValueError("visibilité invalide")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        try:
            return sanitize_text(v, 120)
        except InvalidInputError as exc:
            raise ValueError(str(exc)) from None


class HistoryService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, user_id: UUID) -> list[dict]:
        async with self._db.session() as s:
            rows = (
                await s.execute(
                    select(user_rooms)
                    .where(user_rooms.c.user_id == user_id)
                    .order_by(user_rooms.c.pinned.desc(), user_rooms.c.last_visit.desc())
                    .limit(HISTORY_MAX)
                )
            ).mappings().all()
        return [
            {"id": r["room_id"], "title": r["title"], "visibility": r["visibility"], "owner": r["owner"],
             "pinned": r["pinned"], "lastVisit": r["last_visit"]}
            for r in rows
        ]

    async def replace(self, user_id: UUID, entries: list[HistoryEntry]) -> None:
        """Remplace toute la liste dans une transaction (doublons : la visite la plus récente gagne)."""
        unique: dict[str, HistoryEntry] = {}
        for e in sorted(entries, key=lambda e: e.last_visit):
            unique[e.id] = e
        kept = sorted(unique.values(), key=lambda e: (e.pinned, e.last_visit), reverse=True)[:HISTORY_MAX]
        async with self._db.session() as s:
            await s.execute(delete(user_rooms).where(user_rooms.c.user_id == user_id))
            if kept:
                await s.execute(
                    pg_insert(user_rooms),
                    [{"user_id": user_id, "room_id": e.id, "title": e.title, "visibility": e.visibility,
                      "owner": e.owner, "pinned": e.pinned, "last_visit": e.last_visit} for e in kept],
                )
