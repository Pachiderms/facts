"""Endpoints du mode débat : salons (REST : liste, recherche, création) et salon en direct (WebSocket).

Protocole WebSocket (JSON) :
  client -> serveur : {"type": "hello", "token": "...", "code": "..."}   (PREMIER message, obligatoire)
                      {"type": "message", "text": "..."}
                      {"type": "report", "message_id": N}
  serveur -> client : snapshot | presence | message | check_result | moderation | message_removed
                      | report_result | error
"""

import asyncio
import logging
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, ValidationError, field_validator

from app.adapters.llm import LLMError, LLMRateLimitError
from app.api.deps import enforce_rate_limit, enforce_read_rate_limit
from app.api.identity import bearer_token, resolve_identity
from app.core.config import Settings
from app.core.identity import is_valid_token
from app.core.security import InvalidInputError, get_client_ip, looks_like_prompt_injection, sanitize_text
from app.services.reformulation import ReformulationError, ReformulationRefused
from app.services.rooms import (
    MAX_PARTICIPANTS,
    MIN_PARTICIPANTS,
    THEMES,
    KICK_THRESHOLD_DEFAULT,
    KICK_THRESHOLD_MAX,
    KICK_THRESHOLD_MIN,
    KickedError,
    NotAllowedError,
    RoomFullError,
    RoomNotEmptyError,
    RoomNotFoundError,
    SpectatorsNotAllowedError,
    TooManyRoomsError,
)

logger = logging.getLogger("facts.api")
router = APIRouter(prefix="/api/v1", tags=["rooms"])

ROOM_ID_RE = re.compile(r"[a-z0-9-]{1,64}")
MAX_STRIKES = 10  # erreurs / dépassements tolérés avant déconnexion

WS_POLICY_VIOLATION = 1008
WS_MESSAGE_TOO_BIG = 1009
WS_TRY_AGAIN_LATER = 1013
WS_REPLACED = 4000  # même identité connectée ailleurs : cette connexion cède sa place
HELLO_MAX_CHARS = 400


class RoomSummary(BaseModel):
    id: str
    title: str
    category: str
    theme_category: str
    visibility: Literal["public", "private"]
    max_participants: int
    spectators_allowed: bool
    kick_threshold: int
    trust_score: int | None
    message_count: int
    participants: int
    spectators: int


class MessageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["message"]
    text: str = Field(max_length=2000)
    # Identifiant du message auquel on répond (le serveur vérifie qu'il existe et reprend lui-même son texte).
    reply_to: Annotated[int, Field(strict=True, ge=1, le=10_000_000)] | None = None


class ReportEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["report"]
    message_id: Annotated[int, Field(strict=True, ge=1, le=10_000_000)]


class KickEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["kick"]
    target: Annotated[int, Field(strict=True, ge=1, le=10_000_000)]


class VoteEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["vote"]
    approve: Annotated[bool, Field(strict=True)]


class TakeSeatEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["take_seat"]


ClientEvent: TypeAdapter = TypeAdapter(
    Annotated[MessageEvent | ReportEvent | KickEvent | VoteEvent | TakeSeatEvent, Field(discriminator="type")]
)


class HelloEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["hello"]
    token: str
    code: str | None = Field(default=None, max_length=16)
    # Rejoindre en spectateur même s'il reste des places d'intervenant.
    spectate: StrictBool = False
    # Jeton de session (compte) : facultatif, les WebSockets des navigateurs ne peuvent pas envoyer d'en-tête.
    session: str | None = Field(default=None, max_length=64)

    @field_validator("token")
    @classmethod
    def _token_format(cls, v: str) -> str:
        if not is_valid_token(v):
            raise ValueError("jeton invalide")
        return v


class CreateRoomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=400)  # borne large : la vraie limite (120) est appliquée après nettoyage
    theme_category: str
    visibility: Literal["public", "private"] = "public"
    # strict : « 3 », 3.0 ou true ne sont pas acceptés comme nombre de participants
    max_participants: Annotated[int, Field(strict=True, ge=MIN_PARTICIPANTS, le=MAX_PARTICIPANTS)] = 2
    spectators_allowed: Annotated[bool, Field(strict=True)] = True
    # Score individuel sous lequel le créateur peut proposer une exclusion (20 à 40, 30 par défaut).
    kick_threshold: Annotated[int, Field(strict=True, ge=KICK_THRESHOLD_MIN, le=KICK_THRESHOLD_MAX)] = KICK_THRESHOLD_DEFAULT
    participant_token: str

    @field_validator("participant_token")
    @classmethod
    def _token_format(cls, v: str) -> str:
        if not is_valid_token(v):
            raise ValueError("jeton invalide")
        return v

    @field_validator("theme_category")
    @classmethod
    def _theme_known(cls, v: str) -> str:
        if v not in THEMES:
            raise ValueError("thème inconnu")
        return v


class ReformulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=400)


class Reformulated(BaseModel):
    title: str
    theme_category: str


class CreatedRoom(BaseModel):
    id: str
    visibility: Literal["public", "private"]
    access_code: str | None = None  # affiché une seule fois ; le propriétaire le retrouve dans son salon


class DeleteRoomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participant_token: str

    @field_validator("participant_token")
    @classmethod
    def _token_format(cls, v: str) -> str:
        if not is_valid_token(v):
            raise ValueError("jeton invalide")
        return v


class RoomStatuses(BaseModel):
    existing: list[str]


MAX_STATUS_IDS = 20


class RoomLookup(BaseModel):
    """Résultat d'une recherche par ID. Un salon privé ne révèle ni titre ni contenu."""

    id: str
    visibility: Literal["public", "private"]
    requires_code: bool
    room: RoomSummary | None = None


@router.get("/rooms", response_model=list[RoomSummary], dependencies=[Depends(enforce_read_rate_limit)])
async def list_rooms(request: Request, q: str | None = Query(default=None, max_length=60)):
    registry = request.app.state.rooms
    await registry.purge_idle()
    return registry.summaries(q)


@router.get("/rooms/status", response_model=RoomStatuses, dependencies=[Depends(enforce_read_rate_limit)])
async def rooms_status(request: Request, ids: str = Query(max_length=1500)):
    """Quels salons de l'historique existent encore ? Une seule requête pour toute la liste."""
    wanted = [i for i in ids.split(",") if i]
    if not wanted or len(wanted) > MAX_STATUS_IDS or not all(ROOM_ID_RE.fullmatch(i) for i in wanted):
        raise HTTPException(status_code=422, detail="Liste d'identifiants invalide.")
    return RoomStatuses(existing=request.app.state.rooms.existing(wanted))


@router.get("/rooms/{room_id}", response_model=RoomLookup, dependencies=[Depends(enforce_read_rate_limit)])
async def lookup_room(request: Request, room_id: str):
    room = request.app.state.rooms.get(room_id) if ROOM_ID_RE.fullmatch(room_id) else None
    if room is None:
        raise HTTPException(status_code=404, detail="Salon introuvable.")
    if room.requires_code():
        return RoomLookup(id=room.id, visibility="private", requires_code=True)
    return RoomLookup(id=room.id, visibility="public", requires_code=False, room=room.summary())


@router.post("/rooms/reformulate", response_model=Reformulated, dependencies=[Depends(enforce_rate_limit)])
async def reformulate_room_title(request: Request, body: ReformulateRequest):
    """Propose une question neutre + un thème pour un sujet saisi. Un appel LLM, plafonné par jour."""
    app = request.app
    settings: Settings = app.state.settings
    reformulator = app.state.reformulator
    if reformulator is None:
        raise HTTPException(status_code=503, detail="Reformulation indisponible.")
    try:
        sanitize_text(body.title, 400)
    except InvalidInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None  # sans coût : avant le quota

    ip = get_client_ip(request, settings.trust_proxy_headers, settings.proxy_hops)
    limiter = app.state.daily_reformulation_limiter
    if not limiter.allow(ip):
        raise HTTPException(
            status_code=429,
            detail="Limite quotidienne de reformulations atteinte. Saisissez votre titre directement.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )
    try:
        result = await reformulator.reformulate(body.title)
    except ReformulationRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except InvalidInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except LLMRateLimitError:
        raise HTTPException(status_code=503, detail="Service momentanément saturé, réessayez plus tard.", headers={"Retry-After": "30"}) from None
    except (LLMError, ReformulationError):
        logger.warning("reformulation indisponible")
        raise HTTPException(status_code=502, detail="La reformulation est momentanément indisponible.") from None
    return Reformulated(title=result.title, theme_category=result.theme_category)


async def _ensure_relevant(request: Request, title: str, ip: str) -> None:
    """Refuse (422) un sujet que l'IA juge hors débat ou illégal.

    Ouvert en cas de panne : si l'IA est indisponible, saturée ou si le quota de contrôles du jour
    est épuisé, la création reste possible (au pire 3 salons par jour et par visiteur, supprimés après
    30 min d'inactivité). Un titre déjà approuvé (reformulation acceptée) n'appelle pas l'IA.
    """
    reformulator = request.app.state.reformulator
    if reformulator is None or reformulator.is_approved(title):
        return
    if not request.app.state.daily_reformulation_limiter.allow(ip):
        logger.warning("contrôle de pertinence ignoré : quota quotidien atteint")
        return
    try:
        await reformulator.reformulate(title)
    except ReformulationRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except InvalidInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except (LLMError, ReformulationError):
        logger.warning("contrôle de pertinence indisponible : création autorisée")


@router.post("/rooms", response_model=CreatedRoom, status_code=201, dependencies=[Depends(enforce_rate_limit)])
async def create_room(request: Request, body: CreateRoomRequest):
    app = request.app
    settings: Settings = app.state.settings
    try:
        title = sanitize_text(body.title, settings.room_title_max_chars)
    except InvalidInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if len(title) < settings.room_title_min_chars:
        raise HTTPException(status_code=422, detail=f"Titre trop court (min {settings.room_title_min_chars} caractères).")
    if looks_like_prompt_injection(title):
        raise HTTPException(status_code=422, detail="Titre refusé.")

    # Pertinence du sujet : le bouton « reformuler » est facultatif, donc le contrôle est aussi côté
    # serveur (sinon il suffirait de ne pas cliquer pour créer un salon poubelle). Avant le quota de
    # création : un sujet refusé ne coûte rien à l'utilisateur.
    ip = get_client_ip(request, settings.trust_proxy_headers, settings.proxy_hops)
    await _ensure_relevant(request, title, ip)

    # Après la validation : une requête invalide ne consomme pas le quota quotidien.
    limiter = app.state.daily_room_limiter
    if not limiter.allow(ip):
        raise HTTPException(
            status_code=429,
            detail="Limite quotidienne de création de salons atteinte. Revenez demain.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )
    who = await resolve_identity(app, body.participant_token, bearer_token(request))
    try:
        room = await app.state.rooms.create(
            title=title,
            theme_category=body.theme_category,
            visibility=body.visibility,
            owner_id=who.id,
            owner_aliases=who.aliases,
            max_participants=body.max_participants,
            spectators_allowed=body.spectators_allowed,
            kick_threshold=body.kick_threshold,
        )
    except TooManyRoomsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return CreatedRoom(id=room.id, visibility=room.visibility, access_code=room.access_code)


def _origin_allowed(ws: WebSocket, settings: Settings) -> bool:
    """CORS ne protège PAS les WebSockets : on vérifie l'en-tête Origin nous-mêmes.

    Sans Origin (client non-navigateur), on n'accepte qu'en développement.
    """
    origin = ws.headers.get("origin")
    if origin is None:
        return settings.env != "prod"
    return origin in settings.cors_origin_list


async def _error(ws: WebSocket, code: str, detail: str) -> None:
    await ws.send_json({"type": "error", "code": code, "detail": detail})


@router.post("/rooms/{room_id}/delete", status_code=204, dependencies=[Depends(enforce_rate_limit)])
async def delete_room(request: Request, room_id: str, body: DeleteRoomRequest):
    """Suppression par le créateur d'un salon vide. (POST : le CORS du projet n'autorise que GET et POST.)"""
    if not ROOM_ID_RE.fullmatch(room_id):
        raise HTTPException(status_code=404, detail="Salon introuvable.")
    try:
        who = await resolve_identity(request.app, body.participant_token, bearer_token(request))
        await request.app.state.rooms.delete(room_id, who.id, who.aliases)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except NotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except RoomNotEmptyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.websocket("/rooms/{room_id}/ws")
async def room_ws(ws: WebSocket, room_id: str) -> None:
    app = ws.app
    settings: Settings = app.state.settings
    ip = get_client_ip(ws, settings.trust_proxy_headers, settings.proxy_hops)

    room = app.state.rooms.get(room_id) if ROOM_ID_RE.fullmatch(room_id) else None
    if room is None or not _origin_allowed(ws, settings):
        await ws.close(code=WS_POLICY_VIOLATION)  # avant accept() : le handshake est refusé
        return

    connections = app.state.ws_connections
    if connections[ip] >= settings.ws_max_connections_per_ip:
        await ws.close(code=WS_TRY_AGAIN_LATER)
        return

    connections[ip] += 1
    client = None
    try:
        await ws.accept()
        hello = await _read_hello(ws, settings)
        if hello is None:
            return
        who = await resolve_identity(app, hello.token, hello.session)
        pid = who.id

        moderator = room.moderator
        if moderator is not None and who.aliases:
            moderator.ledger.link(pid, who.aliases)  # un bannissement suit la personne, connectée ou non
        if moderator is not None and (left := moderator.ledger.ban_remaining(pid)):
            await ws.send_json({"type": "error", "code": "banned", "retry_after": left,
                                "detail": "Vous êtes temporairement exclu des salons pour non-respect des règles."})
            await ws.close(code=WS_POLICY_VIOLATION)
            return

        if room.requires_code() and not (room.is_owner(pid) or any(room.is_owner(a) for a in who.aliases)):
            code_limiter = app.state.code_limiter
            if code_limiter.retry_after(ip) > 0:  # on vérifie AVANT de tester le code : pas d'oracle une fois bloqué
                await _reject(ws, "too_many_attempts", "Trop de codes erronés. Réessayez plus tard.")
                return
            if not room.check_code(hello.code):
                code_limiter.allow(ip)  # seuls les échecs consomment le quota
                await _reject(ws, "invalid_code", "Code d'accès invalide.")
                return

        try:
            client, replaced = room.join(ws.send_json, pid, close=lambda: ws.close(code=WS_REPLACED), spectate=hello.spectate, aliases=who.aliases)
        except SpectatorsNotAllowedError as exc:
            await _reject(ws, "spectators_not_allowed", str(exc))
            return
        except KickedError as exc:
            await _reject(ws, "kicked", str(exc))
            return
        except RoomFullError:
            await _error(ws, "room_full", "Salon complet. Nouvelle tentative automatique.")
            await ws.close(code=WS_TRY_AGAIN_LATER)
            return
        if replaced is not None:
            await _evict_replaced(replaced)
        await ws.send_json(room.snapshot(client.role, client.participant_id, client.number))
        await room.broadcast_presence()
        quota = app.state.quota_policy
        who_q = quota.account(who.id, ip) if who.id.startswith("u:") else quota.anonymous(ip)
        await _receive_loop(ws, room, client, ip, settings, lambda: quota.consume_debate(who_q))
    except RuntimeError:
        pass  # socket déjà fermée côté client pendant un envoi
    finally:
        connections[ip] -= 1
        if connections[ip] <= 0:
            del connections[ip]
        if client is not None:
            await room.leave(client.id)


async def _reject(ws: WebSocket, code: str, detail: str) -> None:
    await _error(ws, code, detail)
    await ws.close(code=WS_POLICY_VIOLATION)


async def _read_hello(ws: WebSocket, settings: Settings) -> HelloEvent | None:
    """Premier message obligatoire : identité (jeton) et, pour un salon privé, le code d'accès."""
    try:
        incoming = await asyncio.wait_for(ws.receive(), settings.ws_hello_timeout_seconds)
    except asyncio.TimeoutError:
        await ws.close(code=WS_POLICY_VIOLATION)
        return None
    raw = incoming.get("text")
    if incoming["type"] == "websocket.disconnect":
        return None
    if raw is None or len(raw) > HELLO_MAX_CHARS:
        await ws.close(code=WS_POLICY_VIOLATION)
        return None
    try:
        return HelloEvent.model_validate_json(raw)
    except ValidationError:
        await _reject(ws, "invalid_hello", "Identification invalide.")
        return None


async def _evict_replaced(old) -> None:
    """L'ancienne connexion de la même identité cède sa place (reconnexion ou second onglet)."""
    try:
        await old.send({"type": "error", "code": "session_replaced", "detail": "Ouvert depuis un autre onglet."})
        if old.close is not None:
            await old.close()
    except Exception:
        pass  # déjà morte : rien à faire


async def _receive_loop(ws: WebSocket, room, client, ip: str, settings: Settings, allow_check=None) -> None:
    limiter = ws.app.state.ws_limiter
    hard_limit = settings.ws_max_message_chars * 6 + 200  # place pour l'échappement JSON
    strikes = 0

    while True:
        incoming = await ws.receive()
        if incoming["type"] == "websocket.disconnect":
            return
        raw = incoming.get("text")

        if raw is not None and len(raw) > hard_limit:
            await ws.close(code=WS_MESSAGE_TOO_BIG)
            return

        problem: tuple[str, str] | None = None
        if raw is None:
            problem = ("unsupported", "Les messages binaires ne sont pas acceptés.")
        elif not limiter.allow(ip):
            problem = ("rate_limited", "Trop de messages, ralentissez.")
        elif not ws.app.state.daily_ws_limiter.allow(ip):
            problem = ("daily_limit", "Limite quotidienne de messages atteinte. Revenez demain.")
        else:
            try:
                event = ClientEvent.validate_json(raw)
                if isinstance(event, ReportEvent):
                    if not ws.app.state.report_review_limiter.allow(client.participant_id or client.id):
                        outcome = "unavailable"  # quota de signalements jugés atteint
                    else:
                        outcome = await room.report(client, event.message_id)
                    await client.send({"type": "report_result", "message_id": event.message_id, "outcome": outcome})
                elif isinstance(event, KickEvent):
                    await room.start_kick(client, event.target)
                elif isinstance(event, VoteEvent):
                    await room.vote(client, event.approve)
                elif isinstance(event, TakeSeatEvent):
                    await room.take_seat(client)
                else:
                    await room.post_message(client, event.text, event.reply_to, allow_check)
                    if room.is_banned(client):  # 3e message illégal : la connexion est fermée
                        await ws.close(code=WS_POLICY_VIOLATION)
                        return
            except ValidationError:
                problem = ("invalid_event", "Format de message invalide.")
            except NotAllowedError as exc:
                problem = ("forbidden", str(exc))
            except InvalidInputError as exc:
                problem = ("invalid_message", str(exc))

        if problem is not None:
            strikes += 1
            await _error(ws, *problem)
            if strikes >= MAX_STRIKES:
                await ws.close(code=WS_POLICY_VIOLATION)
                return
