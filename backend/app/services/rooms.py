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
from app.core.security import InvalidInputError, sanitize_text
from app.services.message_checker import MessageCheck, MessageChecker, is_checkable, reply_context, reply_preview
from app.services.moderation import MAX_STRIKES, REMOVED_TEXT, Moderator, Sanction
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


class KickedError(RoomError):
    """Cette identité a été exclue de ce salon."""


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
MAX_REMEMBERED_PARTICIPANTS = 500  # mémoire bornée dans un salon permanent
KICK_THRESHOLD_MIN, KICK_THRESHOLD_MAX, KICK_THRESHOLD_DEFAULT = 20, 40, 30
MIN_CHECKED_FOR_KICK = 3  # il faut au moins 3 messages vérifiés pour qu'un score individuel compte
KICK_VOTE_SECONDS = 45.0
AUTO_KICK_THRESHOLD = 20  # salons sans créateur : en dessous, exclusion automatique (pas de vote)
KICK_COOLDOWN_SECONDS = 300.0  # après un vote perdu, on ne peut pas viser tout de suite la même personne


@dataclass
class Client:
    id: str
    role: str  # une lettre de siège ("A"...) ou "spectator" : attribué par le SERVEUR, jamais choisi par le client
    send: SendFn
    participant_id: str = ""
    number: int | None = None  # « Participant N » : stable pour toute la vie du salon ; None pour un spectateur
    close: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)


@dataclass
class KickVote:
    """Vote d'exclusion en cours : le créateur vote « oui » d'office, les spectateurs tranchent."""

    target: int  # numéro du participant visé
    target_pid: str
    score: int
    ends_at: float
    yes: set[str] = field(default_factory=set)  # identités ayant approuvé (créateur inclus)
    no: set[str] = field(default_factory=set)
    task: asyncio.Task | None = field(default=None, repr=False)


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
        moderator: Moderator | None = None,
        kick_threshold: int = KICK_THRESHOLD_DEFAULT,
        kick_vote_seconds: float = KICK_VOTE_SECONDS,
    ) -> None:
        if not KICK_THRESHOLD_MIN <= kick_threshold <= KICK_THRESHOLD_MAX:
            raise ValueError("kick_threshold hors limites")
        self.kick_threshold, self._kick_vote_seconds = kick_threshold, kick_vote_seconds
        self._canon: dict[str, str] = {}  # identité (jeton anonyme ou compte) -> identité canonique de la personne
        self._kicked: set[str] = set()  # identités exclues de CE salon, pour sa durée de vie
        self._pcounts: dict[int, Counter[str]] = {}  # numéro -> verdicts de ses messages (score individuel)
        self._vote: KickVote | None = None
        self._kick_cooldown: dict[str, float] = {}  # identité visée -> fin du délai de grâce
        self._moderator = moderator
        self._authors: dict[int, str] = {}  # id de message -> identité de l'auteur (jamais diffusé)
        self._reports: set[tuple[int, str]] = set()  # (message, signaleur) : un signalement par personne
        self._reviewed: set[int] = set()  # messages déjà revus après signalement : un seul appel LLM
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
        # Numéro de chaque personne (par identité) : un siège (A, B…) se libère et se réattribue, pas un numéro.
        self._numbers: dict[str, int] = {}
        self._next_number = 0

    # ---------- état ----------
    @property
    def trust_score(self) -> int | None:
        return compute_trust_score(self.counts)

    def _presence(self) -> dict[str, Any]:
        roles = [c.role for c in self.clients.values()]
        return {
            "type": "presence",
            "present": sorted(c.number for c in self.clients.values() if c.number is not None),  # numéros connectés
            "max_participants": self.max_participants,
            "spectators": roles.count("spectator"),
            # Score individuel des connectés (None tant que < 3 messages vérifiés) : base de l'exclusion.
            "scores": {str(c.number): self.individual_score(c.number) for c in self.clients.values() if c.number is not None},
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
            "kick_threshold": self.kick_threshold,
            "participants": sum(1 for r in roles if r != "spectator"),
            "spectators": roles.count("spectator"),
        }

    def _number_for(self, pid: str) -> int:
        """Numéro stable de cette identité dans ce salon (attribué à la première prise de siège)."""
        number = self._numbers.get(pid)
        if number is None:
            self._next_number += 1
            number = self._next_number
            if len(self._numbers) < MAX_REMEMBERED_PARTICIPANTS:
                self._numbers[pid] = number
        return number

    def snapshot(self, role: str, participant: str = "", number: int | None = None) -> dict[str, Any]:
        room = self.summary()
        room["is_owner"] = self.is_owner(participant)  # permet d'afficher « Supprimer » au seul créateur
        if room["is_owner"] and self._access_code:
            room["access_code"] = self._access_code  # visible du seul propriétaire, pour le partager
        # `you` : mon numéro (None pour un spectateur) ; c'est lui, et non la lettre du siège, qui désigne mes messages.
        return {
            "type": "snapshot", "role": role, "you": number, "room": room, "messages": copy.deepcopy(list(self.messages)),
            "kick_vote": self._vote_event() if self._vote is not None else None,
            "scores": self._presence()["scores"],
        }

    # ---------- accès ----------
    def canonical(self, pid: str, aliases: tuple[str, ...] | list[str] = ()) -> str:
        """Identité stable d'une personne dans ce salon, qu'elle soit anonyme, connectée, ou sur un autre appareil.

        La première identité connue du salon sert de référence ; les autres (jeton anonyme avant connexion,
        compte après) y sont rattachées. Un siège, un numéro, une exclusion ou la propriété du salon
        survivent donc à une connexion. Table bornée : au-delà, on ne mémorise plus de nouveaux alias.
        """
        candidates = [pid, *aliases]
        known = next((self._canon[c] for c in candidates if c in self._canon), None)
        canon = known if known is not None else pid
        for c in candidates:
            if c not in self._canon and len(self._canon) < MAX_REMEMBERED_PARTICIPANTS * 2:
                self._canon[c] = canon
        return canon

    def is_owner(self, participant: str) -> bool:
        if not participant or self.owner_id is None:
            return False
        mine, owner = self._canon.get(participant, participant), self._canon.get(self.owner_id, self.owner_id)
        return secrets.compare_digest(mine, owner)

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
        self,
        send: SendFn,
        participant_id: str | None = None,
        close: Callable[[], Awaitable[None]] | None = None,
        spectate: bool = False,
        aliases: tuple[str, ...] = (),
    ) -> tuple[Client, Client | None]:
        """Synchrone et sans `await` : l'attribution des rôles est atomique (pas de course).

        Une même personne ne tient jamais deux sièges : si son identité est déjà connectée dans ce
        salon (autre onglet, reconnexion avant que l'ancienne socket ne soit détectée morte), la
        nouvelle connexion REMPLACE l'ancienne et hérite de son rôle. Renvoie (client, remplacé).

        `spectate=True` : la personne choisit de regarder, même s'il reste des places d'intervenant
        (elle ne prend alors aucun siège). Sans effet pour qui tient déjà un rôle dans le salon.
        """
        pid = self.canonical(participant_id or secrets.token_hex(8), aliases)
        if pid in self._kicked:
            raise KickedError("Vous avez été exclu de ce salon.")
        if self._auto_kick_due(self._numbers.get(pid)):  # exclu automatiquement alors qu'il était absent
            self._kicked.add(pid)
            raise KickedError("Vous avez été exclu de ce salon.")
        replaced = next((c for c in self.clients.values() if c.participant_id == pid), None)
        if replaced is None and len(self.clients) >= self._max_clients:
            raise RoomFullError("Salon complet.")
        if replaced is not None:
            del self.clients[replaced.id]
            role = replaced.role
        else:
            taken = {c.role for c in self.clients.values()}
            free_seat = None if spectate else next((seat for seat in self.seats if seat not in taken), None)
            if free_seat is not None:
                role = free_seat
            elif not self.spectators_allowed:
                raise SpectatorsNotAllowedError("Les spectateurs ne sont pas admis dans ce salon.")
            elif sum(1 for c in self.clients.values() if c.role == "spectator") >= MAX_SPECTATORS:
                raise RoomFullError("Salon complet.")
            else:
                role = "spectator"
        number = None if role == "spectator" else self._number_for(pid)
        client = Client(id=secrets.token_hex(8), role=role, send=send, participant_id=pid, number=number, close=close)
        self.clients[client.id] = client
        self.last_activity = self._clock()
        return client, replaced

    async def leave(self, client_id: str) -> None:
        gone = self.clients.pop(client_id, None)
        if gone is not None:
            self.last_activity = self._clock()
            vote = self._vote
            if vote is not None and gone.number == vote.target and not self._client_by_number(vote.target):
                await self._resolve(vote, cancel=True)  # la personne visée est partie : plus rien à voter
            await self.broadcast(self._presence())

    # ---------- exclusion (score individuel + vote) ----------
    def individual_score(self, number: int | None) -> int | None:
        """Score de confiance d'UNE personne ; None tant qu'elle n'a pas MIN_CHECKED_FOR_KICK messages vérifiés."""
        counts = self._pcounts.get(number) if number is not None else None
        if counts is None or sum(counts[s] for s in WEIGHTS) < MIN_CHECKED_FOR_KICK:
            return None
        return compute_trust_score(counts)

    def _auto_kick_due(self, number: int | None) -> bool:
        """Salon sans créateur (salons d'exemple) : personne pour proposer ni voter, la règle s'applique seule."""
        if self.owner_id is not None:
            return False
        score = self.individual_score(number)
        return score is not None and score < AUTO_KICK_THRESHOLD

    def _client_by_number(self, number: int) -> Client | None:
        return next((c for c in self.clients.values() if c.number == number), None)

    def _voter_ids(self) -> set[str]:
        """Spectateurs présents, hors créateur (qui vote d'office)."""
        return {c.participant_id for c in self.clients.values() if c.role == "spectator" and not self.is_owner(c.participant_id)}

    def _vote_event(self) -> dict[str, Any]:
        v = self._vote
        assert v is not None
        return {
            "type": "kick_vote", "target": v.target, "score": v.score, "threshold": self.kick_threshold,
            "yes": len(v.yes), "no": len(v.no), "ends_in": max(0, int(v.ends_at - self._clock()) + 1),
            "voters": len(self._voter_ids()),
        }

    async def start_kick(self, client: Client, target: int) -> str:
        """Le créateur propose d'exclure `target`. Renvoie « kicked » (sans spectateur) ou « vote »."""
        if not self.is_owner(client.participant_id):
            raise NotAllowedError("Seul le créateur du salon peut proposer une exclusion.")
        if self._vote is not None:
            raise NotAllowedError("Un vote d'exclusion est déjà en cours.")
        victim = self._client_by_number(target)
        if victim is None:
            raise NotAllowedError("Ce participant n'est pas présent.")
        if self.is_owner(victim.participant_id):
            raise NotAllowedError("Le créateur ne peut pas être exclu.")
        score = self.individual_score(target)
        if score is None:
            raise NotAllowedError(f"Il faut au moins {MIN_CHECKED_FOR_KICK} messages vérifiés pour juger ce participant.")
        if score >= self.kick_threshold:
            raise NotAllowedError("Le score de ce participant est au-dessus du seuil d'exclusion.")
        if self._kick_cooldown.get(victim.participant_id, 0.0) > self._clock():
            raise NotAllowedError("Un vote vient d'échouer pour ce participant : réessayez plus tard.")
        if not self._voter_ids():  # personne pour voter : le créateur décide seul
            await self._apply_kick(victim)
            return "kicked"
        vote = KickVote(target, victim.participant_id, score, self._clock() + self._kick_vote_seconds, yes={client.participant_id})
        self._vote = vote
        vote.task = asyncio.create_task(self._vote_timer(vote))
        self._tasks.add(vote.task)
        vote.task.add_done_callback(self._tasks.discard)
        await self.broadcast(self._vote_event())
        return "vote"

    async def vote(self, client: Client, approve: bool) -> None:
        v = self._vote
        if v is None:
            raise NotAllowedError("Aucun vote en cours.")
        if client.role != "spectator" or self.is_owner(client.participant_id):
            raise NotAllowedError("Seuls les spectateurs peuvent voter.")
        pid = client.participant_id
        if pid in v.yes or pid in v.no:
            raise NotAllowedError("Vous avez déjà voté.")
        (v.yes if approve else v.no).add(pid)
        if len(v.yes) + len(v.no) - 1 >= len(self._voter_ids()):  # tout le monde a voté : on conclut tout de suite
            await self._resolve(v)
        else:
            await self.broadcast(self._vote_event())

    async def _vote_timer(self, vote: KickVote) -> None:
        await asyncio.sleep(self._kick_vote_seconds)
        await self._resolve(vote)

    async def _resolve(self, vote: KickVote, cancel: bool = False) -> None:
        if self._vote is not vote:  # déjà conclu
            return
        self._vote = None
        if vote.task is not None and vote.task is not asyncio.current_task():
            vote.task.cancel()
        victim = self._client_by_number(vote.target)
        score = self.individual_score(vote.target)
        if cancel or victim is None or score is None or score >= self.kick_threshold:
            outcome = "cancelled"  # cible partie ou redevenue acceptable pendant le vote
        elif len(vote.yes) > len(vote.no):
            await self._apply_kick(victim)
            return
        else:
            outcome = "kept"
            self._kick_cooldown[vote.target_pid] = self._clock() + KICK_COOLDOWN_SECONDS
            if len(self._kick_cooldown) > MAX_REMEMBERED_PARTICIPANTS:
                self._kick_cooldown.pop(next(iter(self._kick_cooldown)))
        await self.broadcast({"type": "kick_result", "target": vote.target, "outcome": outcome})

    async def _apply_kick(self, victim: Client) -> None:
        self._kicked.add(victim.participant_id)
        self.clients.pop(victim.id, None)  # le siège se libère immédiatement
        try:
            await victim.send({"type": "error", "code": "kicked", "detail": "Vous avez été exclu de ce salon."})
            if victim.close is not None:
                await victim.close()
        except Exception:
            pass  # connexion déjà morte
        self.last_activity = self._clock()
        await self.broadcast({"type": "kick_result", "target": victim.number, "outcome": "kicked"})
        await self.broadcast(self._presence())

    async def take_seat(self, client: Client) -> None:
        """Un spectateur prend une place libérée. Attribution synchrone : le premier arrivé est servi."""
        if client.role != "spectator":
            raise NotAllowedError("Vous avez déjà une place.")
        taken = {c.role for c in self.clients.values()}
        seat = next((x for x in self.seats if x not in taken), None)
        if seat is None:
            raise NotAllowedError("Aucune place n'est libre.")
        client.role = seat
        client.number = self._number_for(client.participant_id)
        self.last_activity = self._clock()
        await client.send({"type": "role", "role": seat, "you": client.number})
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
    async def post_message(
        self,
        client: Client,
        text: str,
        reply_to: int | None = None,
        allow_check: Callable[[], Awaitable[bool]] | None = None,
    ) -> dict[str, Any] | None:
        """Publie le message. Renvoie None s'il est refusé par la modération (l'auteur est prévenu)."""
        if client.role == "spectator":
            raise NotAllowedError("Les spectateurs ne peuvent pas intervenir.")
        clean = sanitize_text(text, self._max_chars)  # lève InvalidInputError si vide / trop long
        quoted = self._quoted(reply_to)  # lève InvalidInputError si le message cité n'existe plus
        self.last_activity = self._clock()

        if self._moderator is not None:
            who = client.participant_id or client.id
            remaining = self._moderator.ledger.ban_remaining(who)
            if remaining:  # exclu (même depuis un autre salon) : on ne publie rien
                await client.send(self._banned_event(remaining))
                return None
            verdict = await self._moderator.review(clean)
            if not verdict.allowed:
                if verdict.strike:
                    await self._sanction(client, who, verdict.category, verdict.message)
                else:  # vulgarité sans cible : refusé, mais aucun avertissement compté
                    await client.send({"type": "moderation", "level": "rephrase", "strikes": self._moderator.ledger.strikes(who),
                                       "max_strikes": MAX_STRIKES, "category": verdict.category, "detail": verdict.message})
                return None

        needs_check = self._checkable(clean)
        over_quota = False
        if needs_check and allow_check is not None and not await allow_check():
            needs_check, over_quota = False, True  # quota de vérifications du jour atteint : le message est publié sans vérification
        self._next_id += 1
        self.total_messages += 1
        message = {
            "id": self._next_id,
            "speaker": client.number,  # numéro stable, pas la lettre du siège (réattribuée quand quelqu'un part)
            "speaker_name": f"Participant {client.number}",  # anonymes : aucune étiquette politique
            "text": clean,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "check": (
                MessageCheck.pending() if needs_check else MessageCheck.unchecked("QUOTA DU JOUR ATTEINT") if over_quota else MessageCheck.no_claim()
            ).model_dump(),
            # Citation : numéro de l'auteur et aperçu repris du message d'origine par le SERVEUR (jamais fourni par le client).
            "reply_to": None if quoted is None else {"id": quoted["id"], "speaker": quoted["speaker"], "preview": reply_preview(quoted["text"])},
        }
        self.messages.append(message)
        self._authors[message["id"]] = client.participant_id or client.id
        if len(self._authors) > 2 * MAX_HISTORY:  # mémoire bornée : on ne garde que les messages encore visibles
            visible = {m["id"] for m in self.messages}
            self._authors = {k: v for k, v in self._authors.items() if k in visible}
        # Copie profonde : le message sera modifié quand la vérification se terminera.
        await self.broadcast({"type": "message", "message": copy.deepcopy(message), "trust_score": self.trust_score})

        if needs_check:
            context = reply_context(quoted["text"]) if quoted is not None else None
            task = asyncio.create_task(self._run_check(message, context))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return message

    def _quoted(self, reply_to: int | None) -> dict[str, Any] | None:
        """Le message cité : il doit exister dans l'historique du salon et ne pas avoir été retiré."""
        if reply_to is None:
            return None
        for m in self.messages:
            if m["id"] == reply_to:
                if m.get("removed"):
                    raise InvalidInputError("Ce message a été retiré : impossible d'y répondre.")
                return m
        raise InvalidInputError("Le message auquel vous répondez n'existe plus.")

    async def _run_check(self, message: dict[str, Any], context: str | None = None) -> None:
        limits = self._limits
        if limits.pending >= limits.max_pending:
            check = MessageCheck.unchecked("FILE D'ATTENTE PLEINE")
        else:
            limits.pending += 1
            try:
                async with limits.semaphore:
                    call = self._checker.check(message["text"]) if context is None else self._checker.check(message["text"], context=context)
                    check = await asyncio.wait_for(call, limits.timeout)
            except Exception:  # CancelledError n'est pas une Exception : l'arrêt propre reste possible
                logger.warning("vérification du message %s indisponible", message["id"])
                check = MessageCheck.unchecked("VÉRIFICATION INDISPONIBLE")
            finally:
                limits.pending -= 1

        if message.get("removed"):  # retiré par la modération pendant la vérification : on n'en tient plus compte
            return
        message["check"] = check.model_dump()
        old = self.trust_score
        if check.status in WEIGHTS:
            self.counts[check.status] += 1
            self._pcounts.setdefault(message["speaker"], Counter())[check.status] += 1
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
        if check.status in WEIGHTS:
            speaker = self._client_by_number(message["speaker"])
            if speaker is not None and self._auto_kick_due(speaker.number):
                await self._apply_kick(speaker)  # diffuse déjà la présence
            else:
                await self.broadcast(self._presence())  # les scores individuels ont bougé

    # ---------- modération ----------
    @property
    def moderator(self) -> Moderator | None:
        return self._moderator

    def is_banned(self, client: Client) -> bool:
        return self._moderator is not None and self._moderator.ledger.ban_remaining(client.participant_id or client.id) > 0

    @staticmethod
    def _banned_event(retry_after: int) -> dict[str, Any]:
        return {
            "type": "moderation",
            "level": "banned",
            "strikes": MAX_STRIKES,
            "max_strikes": MAX_STRIKES,
            "retry_after": retry_after,
            "detail": "Vous êtes exclu des salons pour une heure en raison de messages répétés enfreignant les règles.",
        }

    async def _sanction(self, client: Client | None, who: str, category: str | None, reason: str) -> Sanction:
        """Applique un avertissement (ou l'exclusion au 3e) et prévient la personne, si elle est connectée."""
        assert self._moderator is not None
        sanction = self._moderator.ledger.add_strike(who)
        if client is None:
            client = next((c for c in self.clients.values() if (c.participant_id or c.id) == who), None)
        if client is not None:
            if sanction.level == "banned":
                event = self._banned_event(sanction.retry_after or 0)
            else:
                final = sanction.level == "final_warning"
                event = {
                    "type": "moderation",
                    "level": sanction.level,
                    "strikes": sanction.strikes,
                    "max_strikes": MAX_STRIKES,
                    "category": category,
                    "detail": reason + (" Prochain message illégal : exclusion d'une heure." if final else " Ceci est un avertissement."),
                }
            try:
                await client.send(event)
            except Exception:
                pass  # connexion déjà fermée
        return sanction

    async def report(self, reporter: Client, message_id: int) -> str:
        """Signalement d'un message. Ne sanctionne jamais directement : un second avis (filtre + LLM) tranche.

        Retourne : removed | kept | unavailable | duplicate | own | unknown.
        """
        message = next((m for m in self.messages if m["id"] == message_id), None)
        if message is None or message.get("removed"):
            return "unknown"
        who = reporter.participant_id or reporter.id
        author = self._authors.get(message_id)
        if author is not None and author == who:
            return "own"
        if (message_id, who) in self._reports:
            return "duplicate"
        if len(self._reports) > 1_000:  # mémoire bornée : on ne garde que les messages encore visibles
            visible = {m["id"] for m in self.messages}
            self._reports = {r for r in self._reports if r[0] in visible}
            self._reviewed &= visible
        self._reports.add((message_id, who))
        if self._moderator is None:
            return "unavailable"
        if message_id in self._reviewed:
            return "kept"  # déjà revu et conservé : pas de nouvel appel
        verdict = await self._moderator.review_reported(message["text"])
        if verdict is None:
            self._reports.discard((message_id, who))  # impossible de juger : on pourra re-signaler plus tard
            return "unavailable"
        self._reviewed.add(message_id)
        if verdict.allowed:
            return "kept"

        old = self.trust_score
        status = message.get("check", {}).get("status")
        if status in WEIGHTS and self.counts[status] > 0:
            self.counts[status] -= 1
            pc = self._pcounts.get(message["speaker"])
            if pc is not None and pc[status] > 0:
                pc[status] -= 1
        message.update({"removed": True, "text": REMOVED_TEXT, "check": MessageCheck.no_claim().model_dump()})
        for other in self.messages:  # les réponses ne doivent pas continuer à afficher le propos retiré
            if other.get("reply_to") and other["reply_to"]["id"] == message_id:
                other["reply_to"]["preview"] = REMOVED_TEXT
        await self.broadcast(
            {"type": "message_removed", "message_id": message_id, "text": REMOVED_TEXT, "trust_score": self.trust_score,
             "trust_delta": trust_delta(old, self.trust_score)}
        )
        await self.broadcast(self._presence())
        if author is not None:
            await self._sanction(None, author, verdict.category, verdict.message)
        return "removed"

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

    async def delete(self, room_id: str, requester_id: str, aliases: tuple[str, ...] = ()) -> None:
        """Suppression par le créateur, uniquement si personne d'autre n'est connecté."""
        room = self._rooms.get(room_id)
        if room is None:
            raise RoomNotFoundError("Salon introuvable.")
        if room.permanent or not (room.is_owner(requester_id) or any(room.is_owner(a) for a in aliases)):
            raise NotAllowedError("Seul le créateur peut supprimer ce salon.")
        me = room.canonical(requester_id, aliases)
        if any(c.participant_id != me for c in room.clients.values()):
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
        kick_threshold: int = KICK_THRESHOLD_DEFAULT,
        owner_aliases: tuple[str, ...] = (),
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
            kick_threshold=kick_threshold,
        )
        room.canonical(owner_id, owner_aliases)  # le créateur reste propriétaire s'il se (dé)connecte ensuite
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
    def seeded(
        cls,
        checker: MessageChecker,
        settings: Settings,
        moderator: Moderator | None = None,
        checkable: Callable[[str], bool] | None = None,
    ) -> "RoomRegistry":
        limits = CheckLimits(
            settings.ws_max_concurrent_checks, settings.ws_max_pending_checks, settings.ws_check_timeout_seconds
        )

        def factory(**kw: Any) -> Room:
            extra = {"checkable": checkable} if checkable is not None else {}
            return Room(
                checker=checker, limits=limits, **extra,
                max_message_chars=settings.ws_max_message_chars, max_clients=settings.ws_max_room_connections, moderator=moderator, **kw,
            )

        rooms = [
            factory(room_id=rid, title=title, category=category, theme_category=theme, permanent=True)
            for rid, title, category, theme in SEED_ROOMS
        ]
        return cls(rooms, factory=factory, max_rooms=settings.max_rooms, idle_ttl_seconds=settings.room_idle_ttl_seconds)
