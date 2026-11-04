"""Endpoints du mode débat : liste des salons (REST) et salon en direct (WebSocket).

Protocole WebSocket (JSON) :
  client -> serveur : {"type": "message", "text": "..."}
  serveur -> client : snapshot | presence | message | check_result | error
"""

import re
from typing import Literal

from fastapi import APIRouter, Depends, Request, WebSocket
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.deps import enforce_rate_limit
from app.core.config import Settings
from app.core.security import InvalidInputError, get_client_ip
from app.services.rooms import NotAllowedError, RoomFullError

router = APIRouter(prefix="/api/v1", tags=["rooms"])

ROOM_ID_RE = re.compile(r"[a-z0-9-]{1,64}")
MAX_STRIKES = 10  # erreurs / dépassements tolérés avant déconnexion

WS_POLICY_VIOLATION = 1008
WS_MESSAGE_TOO_BIG = 1009
WS_TRY_AGAIN_LATER = 1013


class RoomSummary(BaseModel):
    id: str
    title: str
    category: str
    theme_category: str
    trust_score: int | None
    message_count: int
    participants: int
    spectators: int


class ClientEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["message"]
    text: str = Field(max_length=2000)


@router.get("/rooms", response_model=list[RoomSummary], dependencies=[Depends(enforce_rate_limit)])
async def list_rooms(request: Request):
    return request.app.state.rooms.summaries()


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


@router.websocket("/rooms/{room_id}/ws")
async def room_ws(ws: WebSocket, room_id: str) -> None:
    app = ws.app
    settings: Settings = app.state.settings
    ip = get_client_ip(ws, settings.trust_proxy_headers)

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
        try:
            client = room.join(ws.send_json)
        except RoomFullError:
            await ws.close(code=WS_TRY_AGAIN_LATER)
            return
        await ws.send_json(room.snapshot(client.role))
        await room.broadcast_presence()
        await _receive_loop(ws, room, client, ip, settings)
    except RuntimeError:
        pass  # socket déjà fermée côté client pendant un envoi
    finally:
        connections[ip] -= 1
        if connections[ip] <= 0:
            del connections[ip]
        if client is not None:
            await room.leave(client.id)


async def _receive_loop(ws: WebSocket, room, client, ip: str, settings: Settings) -> None:
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
        else:
            try:
                event = ClientEvent.model_validate_json(raw)
                await room.post_message(client, event.text)
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
