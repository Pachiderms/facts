"""Numéros de participants stables : un siège (A, B…) se réattribue, pas un numéro."""

import asyncio

import pytest

from app.services.moderation import ModerationLedger, Moderator
from app.services.rooms import MAX_REMEMBERED_PARTICIPANTS, CheckLimits, Room
from tests.test_moderation import FakeLLM, FINE, ILLEGAL, Sink
from tests.test_rooms_create import NullChecker
from tests.test_api_rooms import connect, recv_until
from tests.test_moderation import ws_client


def make_room(**kw):
    return Room("r", "Titre", "Cat", "social", NullChecker(), CheckLimits(2, 20, 5.0), **kw)


async def test_numbers_follow_the_order_of_arrival():
    r = make_room(max_participants=3)
    clients = [r.join(Sink().send, f"p{i}")[0] for i in range(3)]
    assert [c.number for c in clients] == [1, 2, 3]
    assert [c.role for c in clients] == ["A", "B", "C"]


async def test_the_scenario_a_and_b_leave_then_b_returns_keeps_his_number():
    """Reproduit le défaut : B revenait en « A » et ses anciens messages étaient mal attribués."""
    r = make_room()
    a, _x = r.join(Sink().send, "alice")
    b, _y = r.join(Sink().send, "bob")
    ma = await r.post_message(a, "Message de A sans chiffre.")
    mb = await r.post_message(b, "Message de B sans chiffre.")
    await r.leave(a.id)
    await r.leave(b.id)

    b2, _z = r.join(Sink().send, "bob")  # B revient seul : il prend le siège A…
    assert b2.role == "A"
    assert b2.number == 2  # …mais reste « Participant 2 »
    mb2 = await r.post_message(b2, "B de retour sans chiffre.")
    assert [m["speaker"] for m in r.messages] == [ma["speaker"], mb["speaker"], mb2["speaker"]] == [1, 2, 2]


async def test_a_newcomer_never_takes_over_an_absent_participants_number():
    r = make_room()
    a, _x = r.join(Sink().send, "alice")
    b, _y = r.join(Sink().send, "bob")
    await r.post_message(b, "Message de B sans chiffre.")
    await r.leave(b.id)
    c, _z = r.join(Sink().send, "carol")
    assert c.role == "B" and c.number == 3  # le siège B est libre, le numéro 2 reste à Bob
    assert r.messages[0]["speaker"] == 2


async def test_returning_participant_is_attributed_the_same_number_even_after_many_others_passed():
    r = make_room()
    first, _x = r.join(Sink().send, "first")
    await r.leave(first.id)
    for i in range(5):
        c, _y = r.join(Sink().send, f"other{i}")
        await r.leave(c.id)
    assert r.join(Sink().send, "first")[0].number == 1


async def test_two_tabs_of_the_same_person_share_one_number():
    r = make_room()
    a, _x = r.join(Sink().send, "alice")
    a2, replaced = r.join(Sink().send, "alice")
    assert replaced is a and a2.number == a.number == 1


async def test_spectators_have_no_number_and_do_not_consume_one():
    r = make_room(max_participants=2)
    r.join(Sink().send, "a")
    r.join(Sink().send, "b")
    s, _x = r.join(Sink().send, "s")
    assert s.role == "spectator" and s.number is None
    w, _y = r.join(Sink().send, "w", spectate=True)
    assert w.number is None
    await r.leave(r.join(Sink().send, "a")[0].id)  # a (remplacé) puis parti
    assert r._next_number == 2  # ni s ni w n'ont fait avancer le compteur


async def test_presence_lists_connected_numbers_not_seat_letters():
    r = make_room(max_participants=3)
    a, _x = r.join(Sink().send, "a")
    b, _y = r.join(Sink().send, "b")
    c, _z = r.join(Sink().send, "c")
    await r.leave(b.id)
    assert r._presence() == {"type": "presence", "present": [1, 3], "max_participants": 3, "spectators": 0, "scores": {"1": None, "3": None}}


async def test_snapshot_tells_each_viewer_their_own_number():
    r = make_room()
    a, _x = r.join(Sink().send, "a")
    s, _y = r.join(Sink().send, "b", spectate=True)
    assert r.snapshot(a.role, "a", a.number)["you"] == 1
    assert r.snapshot(s.role, "b", s.number)["you"] is None


async def test_remembered_numbers_are_bounded_in_long_lived_rooms():
    r = make_room(max_participants=2)
    for i in range(MAX_REMEMBERED_PARTICIPANTS + 50):
        c, _x = r.join(Sink().send, f"p{i}")
        await r.leave(c.id)
    assert len(r._numbers) <= MAX_REMEMBERED_PARTICIPANTS
    assert r.join(Sink().send, "nouveau")[0].number == MAX_REMEMBERED_PARTICIPANTS + 51  # jamais de doublon


async def test_reporting_an_absent_former_participants_message_works_for_a_newcomer():
    """Cas C : C prend le siège de l'ancien B et doit pouvoir signaler les messages de B."""
    moderator = Moderator(FakeLLM(ILLEGAL), ModerationLedger())
    r = make_room(moderator=moderator)
    a, _x = r.join(Sink().send, "alice")
    b, _y = r.join(Sink().send, "bob")
    mb = await r.post_message(b, "Un message anodin pour le filtre")
    await r.leave(b.id)
    c_sink = Sink()
    c, _z = r.join(c_sink.send, "carol")
    assert c.role == "B" and c.number == 3  # même siège que Bob avait, autre personne
    assert await r.report(c, mb["id"]) == "removed"  # l'auteur est retrouvé par identité, pas par siège


async def test_author_of_a_reported_message_is_still_sanctioned_when_absent():
    moderator = Moderator(FakeLLM(ILLEGAL), ModerationLedger())
    r = make_room(moderator=moderator)
    r.join(Sink().send, "alice")
    b, _y = r.join(Sink().send, "bob")
    mb = await r.post_message(b, "Un message anodin pour le filtre")
    await r.leave(b.id)
    reporter, _z = r.join(Sink().send, "carol")
    await r.report(reporter, mb["id"])
    assert moderator.ledger.strikes("bob") == 1


def test_ws_numbers_survive_a_disconnect_and_reconnect():
    with ws_client() as c:
        with connect(c, "room-1", 91) as a, connect(c, "room-1", 92) as b:
            assert recv_until(a, "snapshot")["you"] == 1
            assert recv_until(b, "snapshot")["you"] == 2
            b.send_json({"type": "message", "text": "Message de B sans chiffre."})
            assert recv_until(a, "message")["message"]["speaker"] == 2
        with connect(c, "room-1", 92) as b2:  # B revient seul : siège A, numéro 2
            snap = recv_until(b2, "snapshot")
            assert snap["role"] == "A" and snap["you"] == 2
            assert [m["speaker"] for m in snap["messages"]] == [2]
        with connect(c, "room-1", 93) as c3:  # un nouveau n'hérite d'aucun ancien numéro
            assert recv_until(c3, "snapshot")["you"] == 3
