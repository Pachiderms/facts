"""Saisie vocale : validations d'entrée, plafonds, filtrage des hallucinations, aucune fuite."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.stt import GroqWhisper, SpeechRateLimitError, SpeechToTextError, Transcript, clean_segments
from app.core.audio import sniff_audio
from app.core.config import Settings
from app.core.security import DailyBudget
from app.main import create_app

URL = "/api/v1/transcribe"
TOKEN = "a" * 32
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


class FakeSTT:
    def __init__(self, text="Le SMIC a augmenté de 10 %.", duration=5.0, error=None):
        self.text, self.duration, self.error, self.calls = text, duration, error, []

    async def transcribe(self, audio, filename, content_type):
        self.calls.append((len(audio), filename, content_type))
        if self.error:
            raise self.error
        return Transcript(self.text, self.duration)


def make(stt=None, **kw):
    settings = Settings(_env_file=None, **kw)
    stt = stt if stt is not None else FakeSTT()
    client = TestClient(create_app(settings, stt=stt))
    client.stt = stt
    return client


def post(client, body=WEBM, token=TOKEN, ctype="audio/webm;codecs=opus", **headers):
    h = {"Content-Type": ctype, **headers}
    if token is not None:
        h["X-Participant-Token"] = token
    return client.post(URL, content=body, headers=h)


def test_transcribes_and_returns_text():
    client = make()
    r = post(client)
    assert r.status_code == 200
    assert r.json() == {"text": "Le SMIC a augmenté de 10 %.", "duration_seconds": 5.0}
    assert client.stt.calls == [(len(WEBM), "voice.webm", "audio/webm")]


def test_features_reports_voice_flag():
    assert make().get("/api/v1/features").json() == {"voice": True, "accounts": False, "google_client_id": None}
    off = TestClient(create_app(Settings(_env_file=None)))
    assert off.get("/api/v1/features").json()["voice"] is False


def test_disabled_without_provider_returns_503():
    off = TestClient(create_app(Settings(_env_file=None)))
    assert post(off).status_code == 503


@pytest.mark.parametrize("token", [None, "", "court", "x" * 200])
def test_requires_valid_participant_token(token):
    client = make()
    assert post(client, token=token).status_code == 401
    assert client.stt.calls == []


def test_rejects_non_audio_content_type():
    client = make()
    assert post(client, ctype="application/json").status_code == 415
    assert client.stt.calls == []


def test_rejects_fake_audio_by_magic_bytes():
    client = make()
    assert post(client, body=b"<html>" + b"x" * 50).status_code == 415
    assert post(client, body=b"").status_code == 415
    assert client.stt.calls == []


@pytest.mark.parametrize(
    "data,ext",
    [
        (b"\x1a\x45\xdf\xa3....", "webm"),
        (b"OggS....", "ogg"),
        (b"\x00\x00\x00\x20ftypM4A ", "mp4"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav"),
        (b"ID3\x04....", "mp3"),
    ],
)
def test_sniff_audio_formats(data, ext):
    assert sniff_audio(data)[0] == ext


def test_oversized_body_rejected_before_provider_call():
    client = make(stt_max_bytes=1000)
    assert post(client, body=WEBM + b"\x00" * 2000).status_code == 413
    assert client.stt.calls == []


def test_oversized_chunked_body_rejected_without_content_length():
    client = make(stt_max_bytes=1000)

    def chunks():
        yield WEBM
        for _ in range(5):
            yield b"\x00" * 400

    r = client.post(URL, content=chunks(), headers={"Content-Type": "audio/webm", "X-Participant-Token": TOKEN})
    assert r.status_code == 413
    assert client.stt.calls == []


def test_other_routes_keep_small_body_limit():
    client = make()
    r = client.post("/api/v1/check", content=b"x" * 20_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_per_person_daily_cap():
    client = make(stt_daily_per_person=2, stt_per_minute=100)
    assert post(client).status_code == 200
    assert post(client).status_code == 200
    r = post(client)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert len(client.stt.calls) == 2
    assert post(client, token="b" * 32).status_code == 200  # une autre personne n'est pas touchée


def test_per_minute_cap_by_ip():
    client = make(stt_per_minute=1)
    assert post(client).status_code == 200
    assert post(client, token="b" * 32).status_code == 429


def test_per_ip_daily_cap_blocks_token_rotation():
    client = make(stt_daily_per_ip=2, stt_per_minute=100)
    assert post(client, token="a" * 32).status_code == 200
    assert post(client, token="b" * 32).status_code == 200
    assert post(client, token="c" * 32).status_code == 429
    assert len(client.stt.calls) == 2


def test_global_audio_budget_closes_feature():
    client = make(stt_global_daily_seconds=25, stt_per_minute=100)
    assert post(client, token="a" * 32).status_code == 200  # facturé 10 s minimum
    assert post(client, token="b" * 32).status_code == 200
    r = post(client, token="c" * 32)  # il reste 5 s < minimum facturé
    assert r.status_code == 503
    assert len(client.stt.calls) == 2


def test_too_long_audio_rejected():
    client = make(stt=FakeSTT(duration=90.0))
    r = post(client)
    assert r.status_code == 413


def test_silence_returns_422():
    client = make(stt=FakeSTT(text="  "))
    assert post(client).status_code == 422


def test_transcript_is_sanitized_and_capped():
    client = make(stt=FakeSTT(text="<script>alert(1)</script> bonjour​ tout le monde " + "a" * 5000))
    body = post(client).json()
    assert "<" not in body["text"] and "​" not in body["text"]
    assert len(body["text"]) <= 2000


def test_provider_rate_limit_maps_to_503_without_leak():
    client = make(stt=FakeSTT(error=SpeechRateLimitError("secret-key gsk_123")))
    r = post(client)
    assert r.status_code == 503 and "gsk_123" not in r.text


def test_provider_failure_maps_to_502_without_leak():
    client = make(stt=FakeSTT(error=SpeechToTextError("https://api.groq.com gsk_123")))
    r = post(client)
    assert r.status_code == 502 and "groq" not in r.text and "gsk_123" not in r.text


def test_cors_allows_participant_token_header():
    client = make(cors_origins="https://site.example")
    r = client.options(
        URL,
        headers={
            "Origin": "https://site.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-participant-token,content-type",
        },
    )
    assert r.status_code == 200


def test_settings_voice_availability():
    assert not Settings(_env_file=None).voice_available
    assert Settings(_env_file=None, llm_api_key="k").voice_available
    assert Settings(_env_file=None, stt_api_key="k").voice_available
    assert not Settings(_env_file=None, llm_api_key="k", stt_enabled=False).voice_available


# --- filtrage Whisper ---------------------------------------------------------------------------------------------


def test_clean_segments_drops_silence_and_known_hallucinations():
    payload = {
        "segments": [
            {"text": " Le chômage baisse.", "no_speech_prob": 0.01, "avg_logprob": -0.2},
            {"text": " Sous-titres réalisés par la communauté d'Amara.org", "no_speech_prob": 0.1, "avg_logprob": -0.3},
            {"text": " blabla", "no_speech_prob": 0.9, "avg_logprob": -1.8},
        ]
    }
    assert clean_segments(payload) == "Le chômage baisse."


def test_clean_segments_keeps_uncertain_but_spoken_segment():
    payload = {"segments": [{"text": " Euh oui.", "no_speech_prob": 0.7, "avg_logprob": -0.4}]}
    assert clean_segments(payload) == "Euh oui."


def test_clean_segments_ignores_malformed():
    assert clean_segments({"segments": [None, {"text": 3}, "x"]}) == ""
    assert clean_segments({"text": "Merci d'avoir regardé cette vidéo"}) == ""


# --- adaptateur HTTP ----------------------------------------------------------------------------------------------


def adapter(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GroqWhisper("https://stt.test/v1", "sk-test", client=client)


async def test_adapter_sends_expected_request():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], request.content
        return httpx.Response(200, json={"duration": 4.2, "segments": [{"text": "Bonjour", "no_speech_prob": 0, "avg_logprob": 0}]})

    out = await adapter(handler).transcribe(b"AUDIO", "voice.webm", "audio/webm")
    assert out == Transcript("Bonjour", 4.2)
    assert seen["url"] == "https://stt.test/v1/audio/transcriptions" and seen["auth"] == "Bearer sk-test"
    for part in (b"whisper-large-v3-turbo", b'name="language"', b"fr", b"verbose_json", b"AUDIO"):
        assert part in seen["body"]


async def test_adapter_maps_errors():
    with pytest.raises(SpeechRateLimitError):
        await adapter(lambda r: httpx.Response(429)).transcribe(b"x", "v.webm", "audio/webm")
    with pytest.raises(SpeechToTextError):
        await adapter(lambda r: httpx.Response(500, text="secret")).transcribe(b"x", "v.webm", "audio/webm")
    with pytest.raises(SpeechToTextError):
        await adapter(lambda r: httpx.Response(200, text="pas du json")).transcribe(b"x", "v.webm", "audio/webm")

    def boom(request):
        raise httpx.ConnectError("sk-test leaked")

    with pytest.raises(SpeechToTextError) as e:
        await adapter(boom).transcribe(b"x", "v.webm", "audio/webm")
    assert "sk-test" not in str(e.value)


# --- budget -------------------------------------------------------------------------------------------------------


def test_daily_budget_rolls_over():
    now = [0.0]
    b = DailyBudget(100, 1000, clock=lambda: now[0])
    b.spend(80)
    assert b.remaining() == 20
    now[0] = 1001
    assert b.remaining() == 100
