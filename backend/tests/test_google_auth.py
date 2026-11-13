"""Vérification du jeton Google : tout ce qui n'est pas parfaitement valide est refusé, sans détail."""

import base64
import json

import jwt
import pytest

from app.services.google_auth import AuthError, GoogleIdentity, GoogleVerifier
from tests.google_helpers import CLIENT_ID, NOW, Clock, FakeGoogle, Keys

KEYS = Keys()


def verifier(fake: FakeGoogle | None = None, clock: Clock | None = None, **kw) -> tuple[GoogleVerifier, FakeGoogle, Clock]:
    fake = fake or FakeGoogle(KEYS)
    clock = clock or Clock()
    return GoogleVerifier(CLIENT_ID, client=fake.client(), clock=clock, **kw), fake, clock


async def test_valid_token_gives_a_normalised_identity():
    v, _, _ = verifier()
    assert await v.verify(KEYS.token()) == GoogleIdentity(sub="1234567890", email="alice@example.com")


@pytest.mark.parametrize(
    "over",
    [
        {"aud": "un-autre-site.apps.googleusercontent.com"},  # jeton émis pour une autre application
        {"iss": "https://evil.example.com"},
        {"exp": int(NOW) - 600},  # expiré (au-delà de la tolérance d'horloge)
        {"iat": int(NOW) - 3600},  # trop ancien : un jeton volé ne sert pas
        {"iat": None},
        {"exp": None},
        {"sub": None},
        {"sub": ""},
        {"sub": 12345},
        {"email": None},
        {"email": "pas-un-email"},
        {"email": "a@b@c.fr"},
        {"email_verified": False},
        {"email_verified": "true"},  # une chaîne n'est pas un booléen vérifié
        {"email_verified": None},
    ],
)
async def test_invalid_claims_are_rejected(over):
    v, _, _ = verifier()
    with pytest.raises(AuthError):
        await v.verify(KEYS.token(**over))


async def test_both_google_issuer_spellings_are_accepted():
    v, _, _ = verifier()
    assert (await v.verify(KEYS.token(iss="accounts.google.com"))).sub == "1234567890"


async def test_token_signed_with_another_key_is_rejected():
    v, _, _ = verifier()
    forger = Keys(kid=KEYS.kid)  # même identifiant de clé, autre clé privée
    with pytest.raises(AuthError):
        await v.verify(forger.token())


async def test_tampered_payload_is_rejected():
    v, _, _ = verifier()
    head, payload, sig = KEYS.token().split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["email"] = "admin@example.com"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(AuthError):
        await v.verify(f"{head}.{forged}.{sig}")


async def test_alg_none_is_rejected():
    v, _, _ = verifier()
    token = jwt.encode(
        {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1", "email": "a@b.fr", "email_verified": True, "iat": int(NOW), "exp": int(NOW) + 60},
        key=None,
        algorithm="none",
        headers={"kid": KEYS.kid},
    )
    with pytest.raises(AuthError):
        await v.verify(token)


async def test_hs256_key_confusion_is_rejected():
    """Classique : signer en HS256 avec la clé PUBLIQUE comme secret. L'algorithme est imposé, donc refusé."""
    import hashlib
    import hmac

    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    v, _, _ = verifier()
    public_pem = KEYS.private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KEYS.kid}).encode())
    body = b64(json.dumps({"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1", "email": "a@b.fr", "email_verified": True, "iat": int(NOW), "exp": int(NOW) + 60}).encode())
    sig = b64(hmac.new(public_pem, f"{head}.{body}".encode(), hashlib.sha256).digest())
    with pytest.raises(AuthError):
        await v.verify(f"{head}.{body}.{sig}")


@pytest.mark.parametrize("junk", ["", "pas.un.jwt", "a" * 50, "x" * 5000, None, 42])
async def test_garbage_is_rejected_without_network(junk):
    v, fake, _ = verifier()
    with pytest.raises(AuthError):
        await v.verify(junk)
    assert fake.fetches == 0


async def test_token_without_kid_is_rejected():
    v, _, _ = verifier()
    token = jwt.encode({"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1", "iat": int(NOW), "exp": int(NOW) + 60}, KEYS.private, algorithm="RS256")
    with pytest.raises(AuthError):
        await v.verify(token)


async def test_errors_are_generic_and_never_echo_the_token():
    v, _, _ = verifier()
    bad = KEYS.token(aud="autre")
    with pytest.raises(AuthError) as e:
        await v.verify(bad)
    assert bad not in str(e.value) and CLIENT_ID not in str(e.value) and "aud" not in str(e.value).lower()


# ---------- clés publiques de Google (JWKS) ----------
async def test_keys_are_cached_between_verifications():
    v, fake, _ = verifier()
    await v.verify(KEYS.token())
    await v.verify(KEYS.token())
    assert fake.fetches == 1


async def test_rotated_key_triggers_one_refresh():
    old, new = Keys("old"), Keys("new")
    fake = FakeGoogle(old)
    v, _, clock = verifier(fake)
    await v.verify(old.token())
    fake.keys = [new]  # Google fait tourner ses clés
    clock.now += 120
    assert (await v.verify(new.token())).sub == "1234567890"
    assert fake.fetches == 2


async def test_unknown_kid_cannot_force_repeated_downloads():
    v, fake, clock = verifier()
    await v.verify(KEYS.token())
    stranger = Keys("inconnue")
    for _ in range(5):
        with pytest.raises(AuthError):
            await v.verify(stranger.token())
    assert fake.fetches == 1  # moins d'une minute : pas de nouveau téléchargement
    clock.now += 61
    with pytest.raises(AuthError):
        await v.verify(stranger.token())
    assert fake.fetches == 2


async def test_cache_expires_after_an_hour():
    v, fake, clock = verifier()
    await v.verify(KEYS.token())
    clock.now += 3601
    await v.verify(KEYS.token(iat=int(clock.now) - 5, exp=int(clock.now) + 3000))
    assert fake.fetches == 2


async def test_google_outage_is_an_auth_error_not_a_crash():
    fake = FakeGoogle(KEYS)
    fake.fail = True
    v, _, _ = verifier(fake)
    with pytest.raises(AuthError):
        await v.verify(KEYS.token())
