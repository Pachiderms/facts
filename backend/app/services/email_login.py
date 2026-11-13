"""Connexion par e-mail : code à 6 chiffres à usage unique.

Sécurité :
- code tiré avec `secrets` ; seule son empreinte salée (HMAC) est stockée, liée à l'adresse ;
- un seul code actif par adresse (un nouvel envoi remplace l'ancien), durée courte, tentatives plafonnées
  (le code est détruit au-delà), détruit dès qu'il sert (aucun rejeu) ;
- même réponse que l'adresse soit connue ou non : on n'interroge jamais la table des comptes avant la vérification ;
- plafonds d'envoi par adresse, par IP et au total (le total reste sous l'offre gratuite du fournisseur).
"""

import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.adapters.email import EmailError, EmailSender
from app.core.config import Settings
from app.core.quotas import make_key
from app.db.engine import Database
from app.db.schema import login_codes
from app.services.accounts import AccountService, User
from app.services.quota_policy import QuotaPolicy

logger = logging.getLogger("facts.email_login")

# ASCII uniquement, une seule arobase, pas d'espace ni de caractère de contrôle (aucune injection possible).
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63})+")
CODE_RE = re.compile(r"[0-9]{6}")


def normalize_email(raw: str) -> str | None:
    email = raw.strip().lower()
    return email if len(email) <= 254 and EMAIL_RE.fullmatch(email) else None


class EmailLoginUnavailable(Exception):
    """Plafond global ou par IP atteint, ou envoi impossible."""


class EmailLoginService:
    def __init__(
        self,
        db: Database,
        accounts: AccountService,
        sender: EmailSender,
        policy: QuotaPolicy,
        settings: Settings,
        salt: str,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._db, self._accounts, self._sender, self._policy = db, accounts, sender, policy
        self._s, self._salt, self._clock = settings, salt, clock

    def _code_hash(self, email: str, code: str) -> str:
        return hmac.new(self._salt.encode("utf-8"), f"login:{email}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()

    async def request(self, email: str, ip: str) -> bool:
        """Envoie un code. Renvoie False si l'adresse a atteint son plafond (réponse identique côté API : pas d'énumération).

        Lève EmailLoginUnavailable pour les plafonds qui ne dépendent pas de l'adresse (IP, total) ou un échec d'envoi.
        """
        s = self._s
        if not await self._policy.store.consume("email_ip", make_key(self._salt, "ip:" + ip), s.email_daily_per_ip):
            raise EmailLoginUnavailable("ip")
        if not await self._policy.store.consume("email_addr", make_key(self._salt, "mail:" + email), s.email_daily_per_address):
            return False
        now = self._clock()
        async with self._db.session() as session:
            await session.execute(delete(login_codes).where(login_codes.c.expires_at < now))  # purge au passage
            created = (
                await session.execute(select(login_codes.c.created_at).where(login_codes.c.email == email))
            ).scalar_one_or_none()
            if created is not None and now - created < timedelta(seconds=s.email_resend_cooldown_seconds):
                return False  # délai minimal entre deux envois : le code précédent reste valable
        if not await self._policy.store.consume("email_global", "all", s.email_daily_global):
            raise EmailLoginUnavailable("global")
        code = f"{secrets.randbelow(10**6):06d}"
        values = {
            "code_hash": self._code_hash(email, code),
            "attempts": 0,
            "expires_at": now + timedelta(seconds=s.email_code_ttl_seconds),
            "created_at": now,
        }
        async with self._db.session() as session:
            await session.execute(
                pg_insert(login_codes).values(email=email, **values).on_conflict_do_update(index_elements=[login_codes.c.email], set_=values)
            )
        try:
            await self._sender.send_login_code(email, code, max(1, s.email_code_ttl_seconds // 60))
        except EmailError:
            async with self._db.session() as session:  # code non délivré : inutile de le garder
                await session.execute(delete(login_codes).where(login_codes.c.email == email))
            logger.warning("envoi du code de connexion impossible")
            raise EmailLoginUnavailable("send") from None
        return True

    async def verify(self, email: str, code: str, participant_token: str | None = None) -> tuple[str, User] | None:
        """Session si le code est le bon, sinon None (même résultat : absent, expiré, faux, trop de tentatives)."""
        if not CODE_RE.fullmatch(code or ""):
            return None
        now = self._clock()
        ok = False
        async with self._db.session() as session:
            row = (
                await session.execute(select(login_codes).where(login_codes.c.email == email).with_for_update())
            ).mappings().first()
            if row is None:
                return None
            if row["expires_at"] < now or row["attempts"] >= self._s.email_code_max_attempts:
                await session.execute(delete(login_codes).where(login_codes.c.email == email))
                return None
            if hmac.compare_digest(row["code_hash"], self._code_hash(email, code)):
                await session.execute(delete(login_codes).where(login_codes.c.email == email))  # usage unique
                ok = True
            else:
                await session.execute(update(login_codes).where(login_codes.c.email == email).values(attempts=row["attempts"] + 1))
        if not ok:
            return None
        return await self._accounts.login_email(email, participant_token)
