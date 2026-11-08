"""Salons de débat : état, rôles, diffusion et vérification asynchrone des messages.

Cette couche ne connaît pas WebSocket : un `Client` est juste un identifiant, un rôle et une
fonction `send`. On la teste donc sans socket, et on pourra la brancher plus tard sur
Redis pub/sub pour passer à plusieurs instances (aujourd'hui : mémoire, 1 instance).
"""

import asyncio
import copy
import logging
import secrets
import time
import unicodedata
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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


class TooManyRoomsError(RoomError):
    pass


class SpectatorsNotAllowedError(RoomError):
    pass


class RoomNotFoundError(RoomError):
    pass


class RoomNotEmptyError(RoomError):
    pass


THEMES: dict[str, str] = {  # theme_category -> libellé par défaut de la catégorie
    "social": "Économie & Emploi",
    "souverain": "Énergie & Souveraineté",
    "ecologie": "Transition écologique",
    "techno": "Institutions & droit",
}
ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # sans caractères ambigus (i, l, o, 0, 1)
ID_LENGTH, CODE_LENGTH = 8, 6
SEAT_LETTERS = "ABCDEF"  # un siège par lettre : de 2 à 6 intervenants par salon
MIN_PARTICIPANTS, MAX_PARTICIPANTS = 2, len(SEAT_LETTERS)
MAX_SPECTATORS = 20


@dataclass
class Client:
    id: str
    role: str  # une lettre de siège ("A"...) ou "spectator" : attribué par le SERVEUR, jamais choisi par le client
    send: SendFn
    participant_id: str = ""
    close: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)


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
        visibility: str = "public",
        access_code: str | None = None,
        owner_id: str | None = None,
        permanent: bool = False,
        max_participants: int = 2,
        spectators_allowed: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.id, self.title, self.category, self.theme_category = room_id, title, category, theme_category
        self.visibility, self._access_code, self.owner_id, self.permanent = visibility, access_code, owner_id, permanent
        if not MIN_PARTICIPANTS <= max_participants <= MAX_PARTICIPANTS:
            raise ValueError("max_participants hors limites")
        self.max_participants, self.spectators_allowed = max_participants, spectators_allowed
        self.seats = SEAT_LETTERS[:max_participants]
        self._clock = clock
        self.last_activity = clock()
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
        roles = [c.role for c in self.clients.values()]
        return {
            "type": "presence",
            "seats": [seat for seat in self.seats if seat in roles],  # sièges occupés, dans l'ordre
            "max_participants": self.max_participants,
            "spectators": roles.count("spectator"),
        }

    def summary(self) -> dict[str, Any]:
        roles = [c.role for c in self.clients.values()]
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "theme_category": self.theme_category,
            "visibility": self.visibility,
            "trust_score": self.trust_score,
            "message_count": self.total_messages,
            "max_participants": self.max_participants,
            "spectators_allowed": self.spectators_allowed,
            "participants": sum(1 for r in roles if r != "spectator"),
            "spectators": roles.count("spectator"),
        }

    def snapshot(self, role: str, participant: str = "") -> dict[str, Any]:
        room = self.summary()
        room["is_owner"] = self.is_owner(participant)  # permet d'afficher « Supprimer » au seul créateur
        if room["is_owner"] and self._access_code:
            room["access_code"] = self._access_code  # visible du seul propriétaire, pour le partager
        return {"type": "snapshot", "role": role, "room": room, "messages": copy.deepcopy(list(self.messages))}

    # ---------- accès ----------
    def is_owner(self, participant: str) -> bool:
        return bool(participant) and self.owner_id is not None and secrets.compare_digest(participant, self.owner_id)

    def requires_code(self) -> bool:
        return self.visibility == "private"

    def check_code(self, code: str | None) -> bool:
        """Comparaison à temps constant ; insensible à la casse et aux espaces."""
        if not self.requires_code():
            return True
        if not code or self._access_code is None:
            return False
        return secrets.compare_digest(code.strip().lower().encode(), self._access_code.encode())

    @property
    def access_code(self) -> str | None:
        return self._access_code

    @property
    def idle_seconds(self) -> float:
        return self._clock() - self.last_activity

    # ---------- connexions ----------
    def join(
        self, send: SendFn, participant_id: str | None = None, close: Callable[[], Awaitable[None]] | None = None
    ) -> tuple[Client, Client | None]:
        """Synchrone et sans `await` : l'attribution des rôles est atomique (pas de course).

        Une même personne ne tient jamais deux sièges : si son identité est déjà connectée dans ce
        salon (autre onglet, reconnexion avant que l'ancienne socket ne soit détectée morte), la
        nouvelle connexion REMPLACE l'ancienne et hérite de son rôle. Renvoie (client, remplacé).
        """
        pid = participant_id or secrets.token_hex(8)
        replaced = next((c for c in self.clients.values() if c.participant_id == pid), None)
        if replaced is None and len(self.clients) >= self._max_clients:
            raise RoomFullError("Salon complet.")
        if replaced is not None:
            del self.clients[replaced.id]
            role = replaced.role
        else:
            taken = {c.role for c in self.clients.values()}
            free_seat = next((seat for seat in self.seats if seat not in taken), None)
            if free_seat is not None:
                role = free_seat
            elif not self.spectators_allowed:
                raise SpectatorsNotAllowedError("Les spectateurs ne sont pas admis dans ce salon.")
            elif sum(1 for c in self.clients.values() if c.role == "spectator") >= MAX_SPECTATORS:
                raise RoomFullError("Salon complet.")
            else:
                role = "spectator"
        client = Client(id=secrets.token_hex(8), role=role, send=send, participant_id=pid, close=close)
        self.clients[client.id] = client
        self.last_activity = self._clock()
        return client, replaced

    async def leave(self, client_id: str) -> None:
        if self.clients.pop(client_id, None) is not None:
            self.last_activity = self._clock()
            await self.broadcast(self._presence())

    async def shutdown(self, code: str, detail: str) -> None:
        """Ferme proprement toutes les connexions (salon supprimé) puis les tâches de vérification."""
        clients = list(self.clients.values())
        self.clients.clear()
        for client in clients:
            try:
                await client.send({"type": "error", "code": code, "detail": detail})
                if client.close is not None:
                    await client.close()
            except Exception:
                pass  # connexion déjà morte
        await self.aclose()

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
        if client.role == "spectator":
            raise NotAllowedError("Les spectateurs ne peuvent pas intervenir.")
        clean = sanitize_text(text, self._max_chars)  # lève InvalidInputError si vide / trop long
        self.last_activity = self._clock()

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


def _fold(text: str) -> str:
    """Minuscules sans accents : « Électricité » doit correspondre à « electricite »."""
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn")


class RoomRegistry:
    def __init__(
        self,
        rooms: list[Room],
        *,
        factory: Callable[..., Room] | None = None,
        max_rooms: int = 50,
        idle_ttl_seconds: float = 1_800,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rooms = {r.id: r for r in rooms}
        self._factory, self._max_rooms, self._idle_ttl, self._clock = factory, max_rooms, idle_ttl_seconds, clock

    def get(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def __len__(self) -> int:
        return len(self._rooms)

    def summaries(self, query: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Salons PUBLICS uniquement (un salon privé ne se découvre jamais par la liste ni la recherche)."""
        needle = _fold(query.strip()) if query else ""
        rooms = [r for r in self._rooms.values() if r.visibility == "public"]
        if needle:
            rooms = [r for r in rooms if needle in _fold(r.title) or needle in _fold(r.category) or needle == r.id]
        # Salons par défaut d'abord, puis les plus récemment actifs.
        rooms.sort(key=lambda r: (not r.permanent, 0.0 if r.permanent else -r.last_activity))  # tri stable
        return [r.summary() for r in rooms[:limit]]

    async def purge_idle(self) -> int:
        """Supprime les salons non permanents, vides, inactifs depuis trop longtemps."""
        stale = [
            r for r in self._rooms.values()
            if not r.permanent and not r.clients and r.idle_seconds >= self._idle_ttl
        ]
        for room in stale:
            del self._rooms[room.id]
        await asyncio.gather(*(r.aclose() for r in stale))
        return len(stale)

    def existing(self, ids: list[str]) -> list[str]:
        """Parmi `ids`, ceux qui existent encore (historique « Mes salons » : repérer les salons expirés)."""
        return [i for i in dict.fromkeys(ids) if i in self._rooms]

    async def delete(self, room_id: str, requester_id: str) -> None:
        """Suppression par le créateur, uniquement si personne d'autre n'est connecté."""
        room = self._rooms.get(room_id)
        if room is None:
            raise RoomNotFoundError("Salon introuvable.")
        if room.permanent or not room.is_owner(requester_id):
            raise NotAllowedError("Seul le créateur peut supprimer ce salon.")
        if any(c.participant_id != requester_id for c in room.clients.values()):
            raise RoomNotEmptyError("D'autres personnes sont connectées : le salon ne peut pas être supprimé maintenant.")
        del self._rooms[room_id]
        await room.shutdown("room_deleted", "Ce salon a été supprimé par son créateur.")

    async def create(
        self,
        *,
        title: str,
        theme_category: str,
        visibility: str,
        owner_id: str,
        max_participants: int = 2,
        spectators_allowed: bool = True,
    ) -> Room:
        if self._factory is None:
            raise RuntimeError("Création de salons non configurée.")
        await self.purge_idle()
        if len(self._rooms) >= self._max_rooms:
            raise TooManyRoomsError("Le nombre maximal de salons est atteint. Réessayez plus tard.")
        room_id = self._new_id()
        code = "".join(secrets.choice(ID_ALPHABET) for _ in range(CODE_LENGTH)) if visibility == "private" else None
        room = self._factory(
            room_id=room_id, title=title, category=THEMES[theme_category], theme_category=theme_category,
            visibility=visibility, access_code=code, owner_id=owner_id,
            max_participants=max_participants, spectators_allowed=spectators_allowed,
        )
        self._rooms[room_id] = room
        return room

    def _new_id(self) -> str:
        while True:  # collision quasi impossible (31^8), mais on la gère
            room_id = "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
            if room_id not in self._rooms:
                return room_id

    async def aclose(self) -> None:
        await asyncio.gather(*(r.aclose() for r in self._rooms.values()))

    @classmethod
    def seeded(cls, checker: MessageChecker, settings: Settings) -> "RoomRegistry":
        limits = CheckLimits(
            settings.ws_max_concurrent_checks, settings.ws_max_pending_checks, settings.ws_check_timeout_seconds
        )

        def factory(**kw: Any) -> Room:
            return Room(
                checker=checker, limits=limits,
                max_message_chars=settings.ws_max_message_chars, max_clients=settings.ws_max_room_connections, **kw,
            )

        rooms = [
            factory(room_id=rid, title=title, category=category, theme_category=theme, permanent=True)
            for rid, title, category, theme in SEED_ROOMS
        ]
        return cls(rooms, factory=factory, max_rooms=settings.max_rooms, idle_ttl_seconds=settings.room_idle_ttl_seconds)
