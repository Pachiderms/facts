"""Saisie vocale : POST /api/v1/transcribe (audio brut en corps de requête) et GET /api/v1/features."""

import logging

from fastapi import APIRouter, HTTPException, Request

from app.adapters.stt import SpeechRateLimitError, SpeechToTextError
from app.core.audio import sniff_audio
from app.core.identity import is_valid_token, participant_id
from app.core.security import InvalidInputError, get_client_ip, sanitize_text

logger = logging.getLogger("facts.voice")
router = APIRouter(prefix="/api/v1", tags=["voice"])

MAX_TRANSCRIPT_CHARS = 2000
MIN_BILLED_SECONDS = 10.0  # Groq facture au minimum 10 s par requête
DURATION_TOLERANCE = 3.0  # le navigateur coupe à 30 s, avec un léger dépassement possible


def _limited(limiter, key: str, detail: str) -> None:
    if not limiter.allow(key):
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(limiter.retry_after(key))})


async def _read_body(request: Request, max_bytes: int) -> bytes:
    """Lit le corps en s'arrêtant au plafond : Content-Length peut mentir ou être absent (chunked)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise HTTPException(status_code=413, detail="Enregistrement trop volumineux.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="Enregistrement trop volumineux.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/features")
async def features(request: Request) -> dict:
    """Fonctions optionnelles disponibles : le front masque le micro / la connexion si elles sont coupées.
    `google_client_id` est PUBLIC (il figure déjà dans le bouton de connexion) : jamais un secret."""
    app = request.app
    accounts = app.state.accounts is not None
    return {
        "voice": app.state.stt is not None,
        "accounts": accounts,
        "google_client_id": app.state.settings.google_client_id.strip() if accounts and app.state.google is not None else None,
        "email_login": getattr(app.state, "email_login", None) is not None,
    }


@router.post("/transcribe")
async def transcribe(request: Request) -> dict[str, str | float]:
    app = request.app
    settings = app.state.settings
    stt = app.state.stt
    if stt is None:
        raise HTTPException(status_code=503, detail="La saisie vocale est indisponible.")

    token = request.headers.get("x-participant-token", "")
    if not is_valid_token(token):
        raise HTTPException(status_code=401, detail="Identité manquante ou invalide.")
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if not ctype.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Format non pris en charge.")

    ip = get_client_ip(request, settings.trust_proxy_headers, settings.proxy_hops)
    pid = participant_id(token)
    # Plafonds contrôlés AVANT de lire le corps et d'appeler le fournisseur.
    _limited(app.state.stt_minute_limiter, ip, "Trop de requêtes. Réessayez dans un instant.")
    if app.state.stt_budget.remaining() < MIN_BILLED_SECONDS:
        raise HTTPException(status_code=503, detail="La saisie vocale est saturée aujourd'hui. Écrivez votre message.")
    _limited(app.state.stt_person_limiter, pid, "Limite quotidienne de messages vocaux atteinte. Écrivez votre message.")
    _limited(app.state.stt_ip_limiter, ip, "Limite quotidienne de messages vocaux atteinte pour cette connexion.")

    audio = await _read_body(request, settings.stt_max_bytes)
    kind = sniff_audio(audio) if len(audio) >= 12 else None
    if kind is None:
        raise HTTPException(status_code=415, detail="Format audio non reconnu.")
    ext, mime = kind

    try:
        result = await stt.transcribe(audio, f"voice.{ext}", mime)
    except SpeechRateLimitError:
        logger.warning("transcription : quota fournisseur atteint")
        raise HTTPException(status_code=503, detail="La saisie vocale est saturée. Écrivez votre message.", headers={"Retry-After": "60"}) from None
    except SpeechToTextError:
        logger.warning("transcription indisponible")
        raise HTTPException(status_code=502, detail="La transcription est momentanément indisponible.") from None

    app.state.stt_budget.spend(max(result.duration_seconds, MIN_BILLED_SECONDS))
    if result.duration_seconds > settings.stt_max_seconds + DURATION_TOLERANCE:
        raise HTTPException(status_code=413, detail=f"Enregistrement trop long ({int(settings.stt_max_seconds)} s maximum).")
    try:
        text = sanitize_text(result.text[:MAX_TRANSCRIPT_CHARS], MAX_TRANSCRIPT_CHARS)
    except InvalidInputError:  # vide après nettoyage : silence, bruit ou hallucination écartée
        raise HTTPException(status_code=422, detail="Aucune parole détectée. Réessayez plus près du micro.") from None
    return {"text": text, "duration_seconds": round(result.duration_seconds, 1)}
