"""Comptes et sessions (PostgreSQL). Le compte est OPTIONNEL : sans lui, l'identité reste le jeton anonyme.

Sessions : jeton opaque aléatoire (256 bits) renvoyé une seule fois ; seule son empreinte SHA-256 est stockée,
donc une fuite de la base ne donne accès à aucune session, et chaque session se révoque individuellement.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.identity import is_valid_token, participant_id
from app.db.engine import Database
from app.db.schema import sessions, user_participants, user_rooms, users
from app.services.google_auth import GoogleIdentity

SESSION_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")  # token_urlsafe(32)
TOUCH_INTERVAL = timedelta(hours=1)  # last_seen mis à jour au plus une fois par heure (peu d'écritures)


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    created_at: datetime


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AccountError(Exception):
    pass


class AccountService:
    def __init__(self, db: Database, *, session_ttl_days: int = 30, max_sessions: int = 10) -> None:
        self._db, self._ttl, self._max_sessions = db, timedelta(days=session_ttl_days), max_sessions

    async def login_google(self, identity: GoogleIdentity, participant_token: str | None = None) -> tuple[str, User]:
        """Crée ou retrouve le compte (clé = identifiant Google), ouvre une session, rattache l'identité anonyme."""
        now = _now()
        token = secrets.token_urlsafe(32)
        async with self._db.session() as s:
            row = (await s.execute(select(users).where(users.c.google_sub == identity.sub))).mappings().first()
            if row is None:
                stmt = (
                    pg_insert(users)
                    .values(google_sub=identity.sub, email=identity.email)
                    .on_conflict_do_nothing()  # e-mail déjà pris par un autre compte, ou course entre deux connexions
                    .returning(users)
                )
                row = (await s.execute(stmt)).mappings().first()
                if row is None:  # course : l'autre connexion a créé le compte entre-temps
                    row = (await s.execute(select(users).where(users.c.google_sub == identity.sub))).mappings().first()
                if row is None:
                    raise AccountError("Adresse déjà associée à un autre compte.")
            else:
                try:
                    async with s.begin_nested():
                        await s.execute(
                            update(users).where(users.c.id == row["id"]).values(last_login_at=now, email=identity.email)
                        )
                except IntegrityError:  # sa nouvelle adresse Google appartient déjà à un autre compte
                    raise AccountError("Adresse déjà associée à un autre compte.") from None
            user_id = row["id"]
            await s.execute(
                pg_insert(sessions).values(user_id=user_id, token_hash=hash_token(token), expires_at=now + self._ttl)
            )
            # Plafond de sessions par compte : les plus anciennes sautent (un jeton volé ne s'accumule pas).
            keep = select(sessions.c.id).where(sessions.c.user_id == user_id).order_by(sessions.c.created_at.desc()).limit(self._max_sessions)
            await s.execute(delete(sessions).where(sessions.c.user_id == user_id, sessions.c.id.not_in(keep)))
            if participant_token is not None and is_valid_token(participant_token):
                await s.execute(
                    pg_insert(user_participants)
                    .values(participant_id=participant_id(participant_token), user_id=user_id)
                    .on_conflict_do_nothing()  # une identité déjà liée à un autre compte reste à ce compte
                )
            created = row["created_at"]
        return token, User(user_id, identity.email, created)

    async def authenticate(self, token: str) -> User | None:
        if not SESSION_TOKEN_RE.fullmatch(token or ""):
            return None  # format invalide : aucune requête en base
        now = _now()
        async with self._db.session() as s:
            row = (
                await s.execute(
                    select(users.c.id, users.c.email, users.c.created_at, sessions.c.id.label("sid"), sessions.c.last_seen_at)
                    .join(sessions, sessions.c.user_id == users.c.id)
                    .where(sessions.c.token_hash == hash_token(token), sessions.c.expires_at > now)
                )
            ).mappings().first()
            if row is None:
                return None
            if now - row["last_seen_at"] > TOUCH_INTERVAL:
                await s.execute(update(sessions).where(sessions.c.id == row["sid"]).values(last_seen_at=now))
            return User(row["id"], row["email"], row["created_at"])

    async def logout(self, token: str) -> None:
        async with self._db.session() as s:
            await s.execute(delete(sessions).where(sessions.c.token_hash == hash_token(token)))

    async def logout_everywhere(self, user_id: UUID) -> int:
        async with self._db.session() as s:
            result = await s.execute(delete(sessions).where(sessions.c.user_id == user_id))
            return result.rowcount or 0

    async def export(self, user_id: UUID) -> dict[str, Any]:
        """Toutes les données conservées sur la personne (RGPD, droit d'accès). Jamais d'empreinte de jeton."""
        async with self._db.session() as s:
            user = (await s.execute(select(users).where(users.c.id == user_id))).mappings().one()
            session_rows = (
                await s.execute(
                    select(sessions.c.created_at, sessions.c.expires_at, sessions.c.last_seen_at)
                    .where(sessions.c.user_id == user_id)
                    .order_by(sessions.c.created_at)
                )
            ).mappings().all()
            rooms_rows = (await s.execute(select(user_rooms).where(user_rooms.c.user_id == user_id))).mappings().all()
            linked = (
                await s.execute(select(func.count()).select_from(user_participants).where(user_participants.c.user_id == user_id))
            ).scalar_one()
        return {
            "account": {
                "id": str(user["id"]),
                "email": user["email"],
                "created_at": user["created_at"].isoformat(),
                "last_login_at": user["last_login_at"].isoformat(),
                "login_method": "google",
            },
            "sessions": [{k: v.isoformat() for k, v in r.items()} for r in session_rows],
            "linked_anonymous_identities": linked,
            "rooms_history": [
                {"id": r["room_id"], "title": r["title"], "visibility": r["visibility"], "owner": r["owner"],
                 "pinned": r["pinned"], "last_visit_ms": r["last_visit"]}
                for r in rooms_rows
            ],
        }

    async def delete_account(self, user_id: UUID) -> None:
        """Suppression définitive : le compte, ses sessions et ses rattachements (cascade en base)."""
        async with self._db.session() as s:
            await s.execute(delete(users).where(users.c.id == user_id))
