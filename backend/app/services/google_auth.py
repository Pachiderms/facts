"""Vérification d'un jeton d'identité Google (« Se connecter avec Google »).

Le navigateur envoie un JWT signé par Google ; on ne lui fait JAMAIS confiance sans le vérifier ici :
  * signature RS256 contrôlée avec les clés publiques de Google (JWKS), algorithme imposé (jamais `none`/HS256) ;
  * `aud` = NOTRE identifiant client (un jeton émis pour un autre site est refusé) et `iss` = Google ;
  * `exp` non dépassé et `iat` récent (un jeton volé ne sert pas longtemps) ;
  * e-mail présent ET vérifié par Google.
Toute erreur devient `AuthError` au message générique : jamais de détail sur ce qui a échoué.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

logger = logging.getLogger("facts.auth")

JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
JWKS_TTL_SECONDS = 3600
JWKS_MIN_REFRESH_SECONDS = 60  # un « kid » inconnu ne peut pas déclencher plus d'un téléchargement par minute
CLOCK_LEEWAY_SECONDS = 60
MAX_CREDENTIAL_CHARS = 4096
_EMAIL_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,255}")


class AuthError(Exception):
    """Authentification refusée. Le message est volontairement générique."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str


class GoogleVerifier:
    def __init__(
        self,
        client_id: str,
        *,
        max_token_age_seconds: int = 600,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
        jwks_url: str = JWKS_URL,
    ) -> None:
        self._client_id = client_id
        self._max_age = max_token_age_seconds
        self._http = client or httpx.AsyncClient(timeout=5.0)
        self._owns_client = client is None
        self._clock = clock
        self._jwks_url = jwks_url
        self._keys: dict[str, Any] = {}
        self._fetched_at = float("-inf")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def _refresh(self) -> None:
        try:
            response = await self._http.get(self._jwks_url)
            response.raise_for_status()
            keys = {
                k["kid"]: RSAAlgorithm.from_jwk(k)
                for k in response.json()["keys"]
                if k.get("kty") == "RSA" and k.get("kid")
            }
        except Exception:  # noqa: BLE001 - réseau, JSON ou clé invalide : même traitement
            logger.warning("clés publiques Google indisponibles")
            raise AuthError("Connexion Google indisponible.") from None
        if not keys:
            raise AuthError("Connexion Google indisponible.")
        self._keys, self._fetched_at = keys, self._clock()

    async def _key_for(self, kid: str) -> Any:
        now = self._clock()
        if now - self._fetched_at > JWKS_TTL_SECONDS:
            await self._refresh()
        if kid not in self._keys and now - self._fetched_at > JWKS_MIN_REFRESH_SECONDS:
            await self._refresh()  # rotation des clés de Google
        key = self._keys.get(kid)
        if key is None:
            raise AuthError("Jeton Google invalide.")
        return key

    async def verify(self, credential: str) -> GoogleIdentity:
        if not isinstance(credential, str) or not 20 <= len(credential) <= MAX_CREDENTIAL_CHARS:
            raise AuthError("Jeton Google invalide.")
        try:
            header = jwt.get_unverified_header(credential)
        except jwt.PyJWTError:
            raise AuthError("Jeton Google invalide.") from None
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str):
            raise AuthError("Jeton Google invalide.")  # écarte `none`, HS256 (confusion de clé), etc.
        key = await self._key_for(kid)
        try:
            claims = jwt.decode(
                credential,
                key,
                algorithms=["RS256"],
                audience=self._client_id,
                # Dates contrôlées ci-dessous avec NOTRE horloge (injectable en test), pas celle de la bibliothèque.
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_exp": False, "verify_iat": False, "verify_nbf": False},
            )
        except jwt.PyJWTError:
            raise AuthError("Jeton Google invalide.") from None
        now = self._clock()
        iat, exp = claims["iat"], claims["exp"]
        if (
            claims["iss"] not in ISSUERS
            or not isinstance(iat, (int, float))
            or not isinstance(exp, (int, float))
            or exp < now - CLOCK_LEEWAY_SECONDS  # expiré
            or iat > now + CLOCK_LEEWAY_SECONDS  # émis dans le futur
            or now - iat > self._max_age  # trop ancien : un jeton volé ne sert pas longtemps
        ):
            raise AuthError("Jeton Google invalide.")
        sub, email = claims["sub"], claims.get("email")
        if not isinstance(sub, str) or not 1 <= len(sub) <= 255:
            raise AuthError("Jeton Google invalide.")
        if claims.get("email_verified") is not True or not isinstance(email, str) or not _EMAIL_RE.fullmatch(email):
            raise AuthError("Adresse e-mail non vérifiée par Google.")
        return GoogleIdentity(sub=sub, email=email.strip().lower()[:320])
