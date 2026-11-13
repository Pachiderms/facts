"""Doublures pour Google : une paire de clés RSA locale, un JWKS factice et un fabricant de jetons signés."""

import json
import time

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
NOW = 1_800_000_000.0


class Keys:
    def __init__(self, kid: str = "key-1"):
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwk(self) -> dict:
        data = json.loads(RSAAlgorithm.to_jwk(self.private.public_key()))
        return {**data, "kid": self.kid, "alg": "RS256", "use": "sig"}

    def token(self, **over) -> str:
        claims = {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": "1234567890",
            "email": "Alice@Example.com",
            "email_verified": True,
            "iat": int(NOW) - 10,
            "exp": int(NOW) + 3000,
        }
        claims.update(over)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": self.kid})


class FakeGoogle:
    """Serveur JWKS factice : compte les téléchargements et permet de faire « tourner » les clés."""

    def __init__(self, *keys: Keys):
        self.keys, self.fetches, self.fail = list(keys), 0, False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.fetches += 1
        if self.fail:
            return httpx.Response(500)
        return httpx.Response(200, json={"keys": [k.jwk() for k in self.keys]})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class Clock:
    def __init__(self, now: float = NOW):
        self.now = now

    def __call__(self) -> float:
        return self.now
