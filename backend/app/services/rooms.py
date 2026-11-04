"""Salons de débat : état, rôles, diffusion et vérification asynchrone des messages.

Cette couche ne connaît pas WebSocket : un `Client` est juste un identifiant, un rôle et une
fonction `send`. On la teste donc sans socket, et on pourra la brancher plus tard sur
Redis pub/sub pour passer à plusieurs instances (aujourd'hui : mémoire, 1 instance).
"""

import asyncio
import copy
import logging
import secrets
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.core.security import sanitize_text
from app.services.message_checker import MessageCheck, MessageChecker, is_checkable
from app.services.trust import WEIGHTS, compute_trust_score, trust_delta

logger = logging.getLogger("facts.rooms")

SEND_TIMEOUT_SECONDS = 2.0  # un client lent ne doit pas bloquer la diffusion aux autres
MAX_HISTORY = 200  # mémoire bornée par salon
SendFn = Callable[[dict[str, Any]], Awaitable[None]]


class RoomError(Exception):
    pass


class RoomFullError(RoomError):
    pass


class NotAllowedError(RoomError):
    pass


@dataclass
class Client:
    id: str
    role: str  # "A", "B" ou "spectator" : attribué par le SERVEUR, jamais choisi par le client
    send: SendFn


class CheckLimits:
    """Plafonds partagés par tous les salons : protègent les quotas gratuits de recherche/LLM."""

    def __init__(self, max_concurrent: int, max_pending: int, timeout_seconds: float) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_pending = max_pending
        self.timeout = timeout_seconds
        self.pending = 0


class Room:
    def __init__(
        self,
        room_id: str,
        title: str,
        category: str,
        theme_category: str,
        checker: MessageChecker,
        limits: CheckLimits,
        max_message_chars: int = 500,
        max_clients: int = 100,
        checkable: Callable[[str], bool] = is_checkable,
    ) -> None:
        self.id, self.title, self.category, self.theme_category = room_id, title, category, theme_category
        self._checker, self._limits = checker, limits
        self._max_chars, self._max_clients = max_message_chars, max_clients
        self._checkable = checkable
        self.clients: dict[str, Client] = {}
        self.messages: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY)
        self.counts: Counter[str] = Counter()
        self.total_messages = 0
        self._next_id = 0
        self._tasks: set[asyncio.Task] = set()

    # ---------- état ----------
    @property
    def trust_score(self) -> int | None:
        return compute_trust_score(self.counts)

    def _presence(self) -> dict[str, Any]:
        roles = {c.role for c in self.clients.values()}
        return {
            "type": "presence",
            "A": "A" in roles,
            "B": "B" in roles,
            "spectators": sum(1 for c in self.clients.values() if c.role == "spectator"),
        }

    def summary(self) -> dict[str, Any]:
        roles = [c.role for c in self.clients.values()]
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "theme_category": self.theme_category,
            "trust_score": self.trust_score,
            "message_count": self.total_messages,
            "participants": sum(1 for r in roles if r in ("A", "B")),
            "spectators": sum(1 for r in roles if r == "spectator"),
        }

    def snapshot(self, role: str) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "role": role,
            "room": self.summary(),
            "messages": copy.deepcopy(list(self.messages)),
        }

    # ---------- connexions ----------
    def join(self, send: SendFn) -> Client:
        """Synchrone et sans `await` : l'attribution des rôles est atomique (pas de course)."""
        if len(self.clients) >= self._max_clients:
            raise RoomFullError("Salon complet.")
        taken = {c.role for c in self.clients.values()}
        role = "A" if "A" not in taken else "B" if "B" not in taken else "spectator"
        client = Client(id=secrets.token_hex(8), role=role, send=send)
        self.clients[client.id] = client
        return client

    async def leave(self, client_id: str) -> None:
        if self.clients.pop(client_id, None) is not None:
            await self.broadcast(self._presence())

    async def broadcast_presence(self) -> None:
        await self.broadcast(self._presence())

    async def broadcast(self, event: dict[str, Any]) -> None:
        clients = list(self.clients.values())
        outcomes = await asyncio.gather(*(self._safe_send(c, event) for c in clients))
        for client, ok in zip(clients, outcomes):
            if not ok:
                self.clients.pop(client.id, None)  # client mort ou trop lent : on l'éjecte

    @staticmethod
    async def _safe_send(client: Client, event: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(client.send(event), SEND_TIMEOUT_SECONDS)
            return True
        except Exception:
            return False

    # ---------- messages ----------
    async def post_message(self, client: Client, text: str) -> dict[str, Any]:
        if client.role not in ("A", "B"):
            raise NotAllowedError("Les spectateurs ne peuvent pas intervenir.")
        clean = sanitize_text(text, self._max_chars)  # lève InvalidInputError si vide / trop long

        needs_check = self._checkable(clean)
        self._next_id += 1
        self.total_messages += 1
        message = {
            "id": self._next_id,
            "speaker": client.role,
            "speaker_name": f"Participant {client.role}",  # anonymes : aucune étiquette politique
            "text": clean,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "check": (MessageCheck.pending() if needs_check else MessageCheck.no_claim()).model_dump(),
        }
        self.messages.append(message)
        # Copie profonde : le message sera modifié quand la vérification se terminera.
        await self.broadcast({"type": "message", "message": copy.deepcopy(message), "trust_score": self.trust_score})

        if needs_check:
            task = asyncio.create_task(self._run_check(message))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return message

    async def _run_check(self, message: dict[str, Any]) -> None:
        limits = self._limits
        if limits.pending >= limits.max_pending:
            check = MessageCheck.unchecked("FILE D'ATTENTE PLEINE")
        else:
            limits.pending += 1
            try:
                async with limits.semaphore:
                    check = await asyncio.wait_for(self._checker.check(message["text"]), limits.timeout)
            except Exception:  # CancelledError n'est pas une Exception : l'arrêt propre reste possible
                logger.warning("vérification du message %s indisponible", message["id"])
                check = MessageCheck.unchecked("VÉRIFICATION INDISPONIBLE")
            finally:
                limits.pending -= 1

        message["check"] = check.model_dump()
        old = self.trust_score
        if check.status in WEIGHTS:
            self.counts[check.status] += 1
        new = self.trust_score
        await self.broadcast(
            {
                "type": "check_result",
                "message_id": message["id"],
                "check": copy.deepcopy(message["check"]),
                "trust_score": new,
                "trust_delta": trust_delta(old, new) if check.status in WEIGHTS else 0,
            }
        )

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


SEED_ROOMS = [
    ("room-1", "Augmentation du SMIC net à 1 700 € : impact sur l'emploi et l'inflation", "Économie & Emploi", "social"),
    ("room-2", "Marché européen de l'électricité : faut-il réformer la fixation des prix ?", "Énergie & Souveraineté", "souverain"),
    ("room-3", "Fin des ventes de véhicules thermiques en 2035 : calendrier et faisabilité", "Transition écologique", "ecologie"),
]


class RoomRegistry:
    def __init__(self, rooms: list[Room]) -> None:
        self._rooms = {r.id: r for r in rooms}

    def get(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def summaries(self) -> list[dict[str, Any]]:
        return [r.summary() for r in self._rooms.values()]

    async def aclose(self) -> None:
        await asyncio.gather(*(r.aclose() for r in self._rooms.values()))

    @classmethod
    def seeded(cls, checker: MessageChecker, settings: Settings) -> "RoomRegistry":
        limits = CheckLimits(
            settings.ws_max_concurrent_checks, settings.ws_max_pending_checks, settings.ws_check_timeout_seconds
        )
        rooms = [
            Room(
                rid, title, category, theme, checker, limits,
                max_message_chars=settings.ws_max_message_chars,
                max_clients=settings.ws_max_room_connections,
            )
            for rid, title, category, theme in SEED_ROOMS
        ]
        return cls(rooms)
