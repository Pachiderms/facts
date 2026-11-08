"""Point d'entrée : `uvicorn app.main:app`. La fabrique `create_app` sert aussi aux tests."""

from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.llm import OpenAICompatibleLLM
from app.adapters.search_chain import FallbackSearch, build_search_chain
from app.api import check as check_api
from app.api import rooms as rooms_api
from app.core.cache import TTLCache
from app.core.config import Settings, get_settings
from app.core.security import SlidingWindowRateLimiter
from app.services.factcheck import FactCheckService
from app.services.message_checker import FactCheckMessageChecker
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


def build_rooms(settings: Settings, service: FactCheckService, moderator: Moderator | None = None) -> RoomRegistry:
    return RoomRegistry.seeded(FactCheckMessageChecker(service), settings, moderator)


def create_app(
    settings: Settings | None = None,
    service: FactCheckService | None = None,
    limiter: SlidingWindowRateLimiter | None = None,
    rooms: RoomRegistry | None = None,
    reformulator: ThemeReformulator | None = None,
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
            app.state.rooms = build_rooms(settings, app.state.service, build_moderator(settings, llm))
        yield
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
    app.state.code_limiter = SlidingWindowRateLimiter(settings.room_code_max_failures, settings.room_code_window_seconds)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,  # liste blanche explicite, jamais "*"
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > settings.max_body_bytes:
            response = JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(check_api.router)
    app.include_router(rooms_api.router)
    return app


app = create_app()
