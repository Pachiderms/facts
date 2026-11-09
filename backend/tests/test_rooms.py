import asyncio

import pytest

from app.core.security import InvalidInputError
from app.services.message_checker import MessageCheck
from app.services.rooms import CheckLimits, NotAllowedError, Room, RoomFullError


class Recorder:
    """Faux client : enregistre ce qu'il reçoit."""

    def __init__(self, fail=False, delay=0.0):
        self.events, self.fail, self.delay = [], fail, delay

    async def send(self, event):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("socket fermée")
        self.events.append(event)

    def of(self, type_):
        return [e for e in self.events if e["type"] == type_]


class FakeChecker:
    def __init__(self, status="verified", gate=None, error=None):
        self.status, self.gate, self.error, self.calls = status, gate, error, []

    async def check(self, text):
        self.calls.append(text)
        if self.gate:
            await self.gate.wait()
        if self.error:
            raise self.error
        badge = {"verified": "green", "false": "red"}.get(self.status, "amber")
        return MessageCheck(status=self.status, badge_type=badge, badge_text=self.status.upper())


def make_room(checker=None, **kw):
    limits = kw.pop("limits", None) or CheckLimits(2, 20, 5.0)
    return Room("r1", "Titre", "Cat", "social", checker or FakeChecker(), limits, **kw)


async def settle(room):
    await asyncio.gather(*room._tasks)


def joined(room, n=1):
    clients = []
    for _ in range(n):
        rec = Recorder()
        clients.append((room.join(rec.send)[0], rec))
    return clients


# ---------- rôles ----------
def test_roles_assigned_by_server_in_order_then_spectators():
    room = make_room()
    roles = [c.role for c, _ in joined(room, 4)]
    assert roles == ["A", "B", "spectator", "spectator"]


async def test_freed_role_is_reassigned():
    room = make_room()
    (a, _), (b, _) = joined(room, 2)
    await room.leave(a.id)
    newcomer, _ = joined(room)[0]
    assert newcomer.role == "A"


def test_room_capacity():
    room = make_room(max_clients=2)
    joined(room, 2)
    with pytest.raises(RoomFullError):
        room.join(Recorder().send)


async def test_spectator_cannot_post():
    room = make_room()
    clients = joined(room, 3)
    with pytest.raises(NotAllowedError):
        await room.post_message(clients[2][0], "Le chiffre est 12")
    assert room.total_messages == 0


# ---------- messages et vérification ----------
async def test_message_broadcast_then_check_result_updates_trust():
    room = make_room(FakeChecker("verified"))
    (a, rec_a), (b, rec_b) = joined(room, 2)
    await room.post_message(a, "Selon l'INSEE, l'inflation est de 2 %.")
    for rec in (rec_a, rec_b):  # les DEUX participants voient le message en attente
        msg = rec.of("message")[0]["message"]
        assert msg["speaker_name"] == "Participant A" and msg["check"]["status"] == "pending"
    await settle(room)
    result = rec_b.of("check_result")[0]
    assert result["check"]["status"] == "verified"
    assert result["trust_score"] == 67 and result["trust_delta"] == 17
    assert room.trust_score == 67


async def test_broadcast_message_is_a_snapshot_not_a_live_reference():
    room = make_room()
    (a, rec_a), = joined(room)
    await room.post_message(a, "Le chiffre est 12")
    await settle(room)
    assert rec_a.of("message")[0]["message"]["check"]["status"] == "pending"  # n'a pas été muté après coup


async def test_opinion_without_figures_skips_the_checker_entirely():
    checker = FakeChecker()
    room = make_room(checker)
    (a, rec), = joined(room)
    msg = await room.post_message(a, "Je ne suis pas d'accord.")
    assert msg["check"]["status"] == "no_claim" and checker.calls == []
    assert room.trust_score is None and not room._tasks


async def test_false_claim_lowers_score_with_negative_delta():
    room = make_room(FakeChecker("verified"))
    (a, rec), = joined(room)
    await room.post_message(a, "Le chiffre est 12")
    await settle(room)
    room._checker = FakeChecker("false")
    await room.post_message(a, "Un autre chiffre : 99")
    await settle(room)
    last = rec.of("check_result")[-1]
    assert last["trust_score"] == 50 and last["trust_delta"] == -17


async def test_checker_failure_is_isolated_and_does_not_affect_score():
    room = make_room(FakeChecker(error=RuntimeError("quota sk-SECRET")))
    (a, rec), = joined(room)
    await room.post_message(a, "Le chiffre est 12")
    await settle(room)
    result = rec.of("check_result")[0]
    assert result["check"]["status"] == "unchecked" and result["trust_score"] is None
    assert "sk-SECRET" not in str(rec.events)


async def test_checker_timeout():
    gate = asyncio.Event()  # jamais déclenché : la vérification pend
    room = make_room(FakeChecker(gate=gate), limits=CheckLimits(1, 5, 0.05))
    (a, rec), = joined(room)
    await room.post_message(a, "Le chiffre est 12")
    await settle(room)
    assert rec.of("check_result")[0]["check"]["status"] == "unchecked"


async def test_pending_queue_is_bounded():
    gate = asyncio.Event()
    room = make_room(FakeChecker(gate=gate), limits=CheckLimits(1, 2, 5.0))
    (a, rec), = joined(room)
    for i in range(4):
        await room.post_message(a, f"Chiffre {i}")
    await asyncio.sleep(0.01)
    full = [e for e in rec.of("check_result") if e["check"]["badge_text"] == "FILE D'ATTENTE PLEINE"]
    assert len(full) == 2  # 2 en attente max, les 2 suivants refusés sans appel externe
    gate.set()
    await settle(room)


async def test_concurrency_is_capped_by_semaphore():
    running, peak = 0, 0

    class Slow:
        async def check(self, text):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1
            return MessageCheck(status="verified", badge_type="green", badge_text="V")

    room = make_room(Slow(), limits=CheckLimits(2, 50, 5.0))
    (a, _), = joined(room)
    for i in range(6):
        await room.post_message(a, f"Chiffre {i}")
    await settle(room)
    assert peak == 2


# ---------- entrées hostiles ----------
async def test_message_text_is_sanitized_before_broadcast():
    room = make_room()
    (a, rec), = joined(room)
    await room.post_message(a, "Chiffre 12 <script>alert(1)</script> ‮ fin")
    text = rec.of("message")[0]["message"]["text"]
    assert "<" not in text and "‮" not in text


@pytest.mark.parametrize("bad", ["", "   ", "​​", "x" * 501])
async def test_empty_or_oversized_message_rejected(bad):
    room = make_room()
    (a, _), = joined(room)
    with pytest.raises(InvalidInputError):
        await room.post_message(a, bad)
    assert room.total_messages == 0


# ---------- robustesse de la diffusion ----------
async def test_dead_client_is_evicted_and_does_not_block_others():
    room = make_room()
    (a, rec_a), = joined(room)
    dead = Recorder(fail=True)
    room.join(dead.send)
    await room.post_message(a, "Le chiffre est 12")
    assert len(room.clients) == 1 and rec_a.of("message")


async def test_slow_client_is_evicted_after_timeout(monkeypatch):
    monkeypatch.setattr("app.services.rooms.SEND_TIMEOUT_SECONDS", 0.05)
    room = make_room()
    (a, rec_a), = joined(room)
    room.join(Recorder(delay=1.0).send)
    await room.post_message(a, "Le chiffre est 12")
    assert len(room.clients) == 1


async def test_history_is_bounded_but_counters_keep_going(monkeypatch):
    monkeypatch.setattr("app.services.rooms.MAX_HISTORY", 3)
    room = make_room()
    room.messages = type(room.messages)(maxlen=3)
    (a, _), = joined(room)
    for i in range(10):
        await room.post_message(a, f"Opinion sans chiffre {'x' * i}")
    assert len(room.messages) == 3 and room.total_messages == 10


async def test_snapshot_gives_new_joiner_the_history():
    room = make_room()
    (a, _), = joined(room)
    await room.post_message(a, "Opinion sans chiffre")
    snap = room.snapshot("spectator")
    assert snap["role"] == "spectator" and len(snap["messages"]) == 1 and snap["room"]["message_count"] == 1


async def test_aclose_cancels_running_checks():
    gate = asyncio.Event()
    room = make_room(FakeChecker(gate=gate))
    (a, _), = joined(room)
    await room.post_message(a, "Le chiffre est 12")
    await room.aclose()
    assert not room._tasks or all(t.done() for t in room._tasks)
