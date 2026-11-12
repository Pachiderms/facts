"""Port + adaptateur de transcription vocale (Groq Whisper, API compatible OpenAI).

L'audio n'est jamais écrit sur disque ni conservé : il traverse la mémoire le temps de l'appel.
Le texte renvoyé est une donnée non fiable (comme toute sortie de modèle) : l'appelant le nettoie.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class SpeechToTextError(RuntimeError):
    """Échec de la transcription (réseau, HTTP, réponse inexploitable)."""


class SpeechRateLimitError(SpeechToTextError):
    """Quota du fournisseur atteint (HTTP 429). Jamais réessayé automatiquement."""


@dataclass(frozen=True)
class Transcript:
    text: str
    duration_seconds: float


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> Transcript: ...


# Phrases que Whisper « invente » sur du silence ou du bruit (artefacts connus de ses données d'entraînement).
HALLUCINATIONS = (
    "sous-titres réalisés par",
    "sous-titrage",
    "amara.org",
    "merci d'avoir regardé",
    "merci d'avoir visionné",
    "n'oubliez pas de vous abonner",
    "abonnez-vous",
)
NO_SPEECH_PROB = 0.6
MIN_AVG_LOGPROB = -1.0
MAX_RESPONSE_BYTES = 200_000


def clean_segments(payload: dict[str, Any]) -> str:
    """Assemble le texte en écartant les segments qui ressemblent à du silence ou à une hallucination."""
    segments = payload.get("segments")
    if not isinstance(segments, list):
        text = payload.get("text")
        return _drop_hallucination(text) if isinstance(text, str) else ""
    kept: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict) or not isinstance(seg.get("text"), str):
            continue
        no_speech = seg.get("no_speech_prob")
        logprob = seg.get("avg_logprob")
        if (
            isinstance(no_speech, (int, float))
            and isinstance(logprob, (int, float))
            and no_speech > NO_SPEECH_PROB
            and logprob < MIN_AVG_LOGPROB
        ):
            continue
        text = _drop_hallucination(seg["text"])
        if text:
            kept.append(text)
    return " ".join(kept).strip()


def _drop_hallucination(text: str) -> str:
    low = text.lower()
    return "" if any(h in low for h in HALLUCINATIONS) else text.strip()


class GroqWhisper:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "whisper-large-v3-turbo",
        language: str = "fr",
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._api_key = api_key
        self._model = model
        self._language = language
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> Transcript:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        data = {
            "model": self._model,
            "language": self._language,  # fixé : évite que le bruit soit « détecté » comme une autre langue
            "response_format": "verbose_json",
            "temperature": "0",
        }
        try:
            response = await self._client.post(
                self._url, headers=headers, data=data, files={"file": (filename, audio, content_type)}
            )
        except httpx.HTTPError as exc:
            raise SpeechToTextError(f"requête échouée ({type(exc).__name__})") from None
        if response.status_code == 429:
            raise SpeechRateLimitError("quota du fournisseur atteint")
        if response.status_code != 200:
            raise SpeechToTextError(f"HTTP {response.status_code}")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise SpeechToTextError("réponse trop volumineuse")
        try:
            payload = response.json()
            duration = float(payload.get("duration", 0))
        except (ValueError, TypeError, AttributeError):
            raise SpeechToTextError("réponse inexploitable") from None
        if not isinstance(payload, dict) or duration < 0:
            raise SpeechToTextError("réponse inexploitable")
        return Transcript(text=clean_segments(payload), duration_seconds=duration)
