"""Point d'entrée : `uvicorn app.main:app`. La fabrique `create_app` sert aussi aux tests."""

import asyncio
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.llm import OpenAICompatibleLLM
from app.adapters.stt import GroqWhisper, SpeechToText
from app.adapters.search_chain import FallbackSearch, build_search_chain
from app.api import auth as auth_api
from app.api import check as check_api
from app.api.deps import enforce_read_rate_limit
from app.api import rooms as rooms_api
from app.api import voice as voice_api
from app.core.cache import TTLCache
from app.db.engine import Database
from app.core.config import Settings, get_settings
from app.core.security import DailyBudget, SlidingWindowRateLimiter
from app.services.accounts import AccountService
from app.services.factcheck import FactCheckService
from app.services.google_auth import GoogleVerifier
from app.services.claim_triage import ClaimExtractor
from app.services.message_checker import FactCheckMessageChecker, TriagingMessageChecker, is_candidate
from app.services.moderation import ModerationLedger, Moderator
from app.services.reformulation import ThemeReformulator
from app.services.retrieval import Retriever
from app.services.rooms import RoomRegistry

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def build_service(settings: Settings) -> tuple[FactCheckService, OpenAICompatibleLLM, FallbackSearch]:
    local = any(h in settings.llm_base_url for h in ("localhost", "127.0.0.1"))
    if not settings.llm_api_key and not local:
        raise RuntimeError("FACTS_LLM_API_KEY manquante (obligatoire pour un fournisseur LLM distant).")
    llm = OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        reasoning_effort=settings.llm_reasoning_effort,
    )
    search = build_search_chain(settings)
    retriever = Retriever(search, max_results=settings.search_max_results)
    cache = TTLCache(settings.cache_ttl_seconds, settings.cache_max_entries)
    return FactCheckService(llm, retriever, cache, settings.assertion_max_chars), llm, search


def build_reformulator(settings: Settings, llm: OpenAICompatibleLLM) -> ThemeReformulator:
    return ThemeReformulator(llm, title_min=settings.room_title_min_chars, title_max=settings.room_title_max_chars)


def build_moderator(settings: Settings, llm: OpenAICompatibleLLM | None) -> Moderator:
    ledger = ModerationLedger(ban_seconds=settings.moderation_ban_seconds, strike_ttl_seconds=settings.moderation_strike_ttl_seconds)
    return Moderator(llm, ledger, timeout_seconds=settings.moderation_timeout_seconds)


def build_rooms(
    settings: Settings, service: FactCheckService, moderator: Moderator | None = None, llm: OpenAICompatibleLLM | None = None
) -> RoomRegistry:
    checker = FactCheckMessageChecker(service)
    if settings.claim_triage and llm is not None:
        extractor = ClaimExtractor(llm, timeout_seconds=settings.claim_triage_timeout_seconds)
        return RoomRegistry.seeded(TriagingMessageChecker(checker, extractor), settings, moderator, checkable=is_candidate)
    return RoomRegistry.seeded(checker, settings, moderator)


def create_app(
    settings: Settings | None = None,
    service: FactCheckService | None = None,
    limiter: SlidingWindowRateLimiter | None = None,
    rooms: RoomRegistry | None = None,
    reformulator: ThemeReformulator | None = None,
    stt: SpeechToText | None = None,
    db: Database | None = None,
    google: GoogleVerifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        llm = search = None
        if app.state.service is None:
            app.state.service, llm, search = build_service(settings)
            if app.state.reformulator is None:
                app.state.reformulator = build_reformulator(settings, llm)
        if app.state.rooms is None:
            app.state.rooms = build_rooms(settings, app.state.service, build_moderator(settings, llm), llm)
        db_owned = None
        if app.state.db is None and settings.database_url.get_secret_value():
            app.state.db = db_owned = Database(
                settings.database_url.get_secret_value(),
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
            )
        google_owned = None
        if app.state.accounts is None and app.state.db is not None and settings.google_client_id.strip():
            if app.state.google is None:
                app.state.google = google_owned = GoogleVerifier(
                    settings.google_client_id.strip(), max_token_age_seconds=settings.google_max_token_age_seconds
                )
            app.state.accounts = AccountService(
                app.state.db, session_ttl_days=settings.session_ttl_days, max_sessions=settings.max_sessions_per_user
            )
        stt_owned = None
        if app.state.stt is None and settings.voice_available:
            app.state.stt = stt_owned = GroqWhisper(
                settings.stt_base_url, settings.stt_key, settings.stt_model, timeout_seconds=settings.stt_timeout_seconds
            )
        yield
        if stt_owned is not None:
            await stt_owned.aclose()
        if google_owned is not None:
            await google_owned.aclose()
        if db_owned is not None:
            await db_owned.aclose()
        await app.state.rooms.aclose()  # annule les vérifications en cours
        if llm is not None:
            await llm.aclose()
        if search is not None:
            await search.aclose()

    prod = settings.env == "prod"
    app = FastAPI(
        title="Facts API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if prod else "/docs",  # pas de doc interactive exposée en production
        redoc_url=None,
        openapi_url=None if prod else "/openapi.json",
    )
    app.state.settings = settings
    app.state.service = service
    app.state.reformulator = reformulator
    app.state.limiter = limiter or SlidingWindowRateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )
    app.state.read_limiter = SlidingWindowRateLimiter(
        settings.read_rate_limit_requests, settings.rate_limit_window_seconds
    )
    app.state.rooms = rooms or (build_rooms(settings, service) if service is not None else None)
    app.state.ws_connections = Counter()  # connexions WebSocket ouvertes, par IP
    app.state.ws_limiter = SlidingWindowRateLimiter(settings.ws_messages_per_minute, 60)
    app.state.daily_check_limiter = SlidingWindowRateLimiter(settings.daily_check_limit, 86_400)
    app.state.daily_ws_limiter = SlidingWindowRateLimiter(settings.daily_ws_message_limit, 86_400)
    app.state.daily_room_limiter = SlidingWindowRateLimiter(settings.daily_room_creation_limit, 86_400)
    app.state.report_review_limiter = SlidingWindowRateLimiter(settings.daily_report_review_limit, 86_400)
    app.state.daily_reformulation_limiter = SlidingWindowRateLimiter(settings.daily_reformulation_limit, 86_400)
    app.state.stt = stt
    app.state.db = db
    app.state.google = google
    app.state.accounts = None
    if db is not None and google is not None and settings.google_client_id.strip():
        app.state.accounts = AccountService(db, session_ttl_days=settings.session_ttl_days, max_sessions=settings.max_sessions_per_user)
    app.state.login_limiter = SlidingWindowRateLimiter(settings.login_attempts_per_window, settings.login_window_seconds)
    app.state.stt_minute_limiter = SlidingWindowRateLimiter(settings.stt_per_minute, 60)
    app.state.stt_person_limiter = SlidingWindowRateLimiter(settings.stt_daily_per_person, 86_400)
    app.state.stt_ip_limiter = SlidingWindowRateLimiter(settings.stt_daily_per_ip, 86_400)
    app.state.stt_budget = DailyBudget(settings.stt_global_daily_seconds)
    app.state.code_limiter = SlidingWindowRateLimiter(settings.room_code_max_failures, settings.room_code_window_seconds)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,  # liste blanche explicite, jamais "*"
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Participant-Token", "Authorization"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        declared = request.headers.get("content-length", "")
        # Seule la route audio accepte un corps volumineux ; elle le plafonne elle-même en le lisant.
        limit = settings.stt_max_bytes if request.url.path == "/api/v1/transcribe" else settings.max_body_bytes
        if declared.isdigit() and int(declared) > limit:
            response = JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    app.state.started = time.monotonic()

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str | int]:
        # Durée depuis le démarrage : une valeur qui retombe à ~0 trahit un redémarrage (et donc des salons perdus).
        return {"status": "ok", "uptime_seconds": int(time.monotonic() - app.state.started)}

    @app.get("/health/db", include_in_schema=False, dependencies=[Depends(enforce_read_rate_limit)])
    async def health_db() -> JSONResponse:
        """Sonde de la base. À NE PAS donner au pinger : chaque appel réveille la base (Neon : heures de calcul)."""
        database = app.state.db
        if database is None:
            return JSONResponse({"db": "disabled"})
        try:
            await asyncio.wait_for(database.ping(), 10)
        except Exception:  # noqa: BLE001 - le détail (hôte, mot de passe) ne doit jamais sortir
            logging.getLogger("facts.db").warning("base de données injoignable")
            return JSONResponse({"db": "down"}, status_code=503)
        return JSONResponse({"db": "ok"})

    app.include_router(check_api.router)
    app.include_router(rooms_api.router)
    app.include_router(voice_api.router)
    app.include_router(auth_api.router)
    return app


app = create_app()
