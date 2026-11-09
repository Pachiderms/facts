"""Exclusion d'un participant : score individuel, vote des spectateurs, siège libéré. Fonctionnel + sécurité."""

import asyncio

import pytest
from pydantic import ValidationError

from app.services.rooms import (
    KICK_THRESHOLD_MAX, KICK_THRESHOLD_MIN, CheckLimits, KickedError, NotAllowedError, Room,
)
from tests.test_api_rooms import connect, make_client, recv_until, token
from tests.test_moderation import Sink
from tests.test_rooms_create import Clock, NullChecker, create

OWNER, BAD, GOOD = "owner", "bad", "good"


def make_room(owner=OWNER, clock=None, **kw):
    clock = clock or Clock()
    room = Room("r", "Titre", "Cat", "social", NullChecker(), CheckLimits(2, 20, 5.0),
                owner_id=owner, max_participants=3, clock=clock, **kw)
    return room, clock


def join(room, pid, spectate=False):
    sink = Sink()
    client, _ = room.join(sink.send, pid, spectate=spectate)
    return client, sink


def score_for(room, number, *statuses):
    """Simule des messages vérifiés d'un participant (verdicts imposés)."""
    for st in statuses:
        room._pcounts.setdefault(number, __import__("collections").Counter())[st] += 1


async def setup(spectators=0, bad_statuses=("false", "false", "false")):
    room, clock = make_room()
    owner, o_sink = join(room, OWNER)
    bad, b_sink = join(room, BAD)
    specs = [join(room, f"s{i}", spectate=True) for i in range(spectators)]
    score_for(room, bad.number, *bad_statuses)
    return room, clock, owner, bad, b_sink, specs


# ---------- score individuel ----------
async def test_individual_score_needs_three_checked_messages():
    room, *_ = await setup(bad_statuses=("false", "false"))
    assert room.individual_score(2) is None
    score_for(room, 2, "false")
    assert room.individual_score(2) == 20  # 3 messages faux : (prior 1.0 + 0) / 5


async def test_unverifiable_messages_do_not_count_toward_the_minimum():
    room, *_ = await setup(bad_statuses=("false", "false", "unverifiable", "no_claim"))
    assert room.individual_score(2) is None


# ---------- règles d'éligibilité ----------
async def test_only_the_creator_can_propose():
    room, _, owner, bad, _, specs = await setup()
    good, _ = join(room, GOOD)
    with pytest.raises(NotAllowedError):
        await room.start_kick(good, bad.number)


async def test_spectator_cannot_propose():
    room, *_ = await setup(spectators=1)
    spec = next(c for c in room.clients.values() if c.role == "spectator")
    with pytest.raises(NotAllowedError):
        await room.start_kick(spec, 2)


async def test_creator_cannot_be_kicked():
    room, _, owner, *_ = await setup()
    score_for(room, owner.number, "false", "false", "false")
    with pytest.raises(NotAllowedError):
        await room.start_kick(owner, owner.number)


async def test_not_enough_messages_blocks_kick():
    room, _, owner, *_ = await setup(bad_statuses=("false", "false"))
    with pytest.raises(NotAllowedError):
        await room.start_kick(owner, 2)


async def test_good_score_cannot_be_kicked():
    room, _, owner, *_ = await setup(bad_statuses=("verified",) * 4)
    with pytest.raises(NotAllowedError):
        await room.start_kick(owner, 2)


async def test_unknown_or_absent_target_is_refused():
    room, _, owner, *_ = await setup()
    with pytest.raises(NotAllowedError):
        await room.start_kick(owner, 99)


async def test_seed_room_without_owner_has_no_kick():
    room = Room("r", "T", "C", "social", NullChecker(), CheckLimits(2, 20, 5.0), max_participants=3)
    a, _ = join(room, "a")
    b, _ = join(room, "b")
    score_for(room, b.number, "false", "false", "false")
    with pytest.raises(NotAllowedError):
        await room.start_kick(a, b.number)


# ---------- sans spectateur : le créateur décide ----------
async def test_creator_alone_kicks_immediately_and_frees_the_seat():
    room, _, owner, bad, b_sink, _ = await setup()
    assert await room.start_kick(owner, bad.number) == "kicked"
    assert bad.id not in room.clients
    assert any(e.get("code") == "kicked" for e in b_sink.of("error"))
    assert BAD in room._kicked
    with pytest.raises(KickedError):
        join(room, BAD)
    assert join(room, "newcomer")[0].role == "B"  # le siège libéré est réutilisable


# ---------- vote ----------
async def test_vote_passes_with_majority_and_resolves_early():
    room, _, owner, bad, b_sink, specs = await setup(spectators=3)
    assert await room.start_kick(owner, bad.number) == "vote"
    s0, s1, s2 = (c for c, _ in specs)
    await room.vote(s0, True)
    await room.vote(s1, False)
    assert bad.id in room.clients  # pas encore conclu
    await room.vote(s2, True)  # tout le monde a voté : conclusion immédiate (créateur + 2 oui contre 1 non)
    assert bad.id not in room.clients and BAD in room._kicked


async def test_vote_fails_on_tie_or_majority_no_and_sets_cooldown():
    room, clock, owner, bad, _, specs = await setup(spectators=1)
    await room.start_kick(owner, bad.number)
    await room.vote(specs[0][0], False)  # 1 oui (créateur) contre 1 non : égalité => conservé
    assert bad.id in room.clients and BAD not in room._kicked
    assert room._vote is None
    with pytest.raises(NotAllowedError):
        await room.start_kick(owner, bad.number)  # délai de grâce
    clock.t += 301
    assert await room.start_kick(owner, bad.number) == "vote"


async def test_vote_timeout_decides_with_votes_cast():
    room, _, owner, bad, _, specs = await setup(spectators=2)
    room._kick_vote_seconds = 0.05
    await room.start_kick(owner, bad.number)
    room._vote.ends_at = room._clock() + 0.05
    await asyncio.sleep(0.15)
    assert bad.id not in room.clients  # personne n'a voté : le créateur (oui) l'emporte 1-0


async def test_one_vote_per_spectator_and_only_spectators_vote():
    room, _, owner, bad, _, specs = await setup(spectators=3)
    await room.start_kick(owner, bad.number)
    spec = specs[0][0]
    await room.vote(spec, True)
    with pytest.raises(NotAllowedError):
        await room.vote(spec, False)  # pas de double vote ni de changement
    with pytest.raises(NotAllowedError):
        await room.vote(owner, True)  # le créateur a déjà son vote
    with pytest.raises(NotAllowedError):
        await room.vote(bad, False)  # la cible ne vote pas


async def test_vote_without_running_vote_is_refused():
    room, _, _, _, _, specs = await setup(spectators=1)
    with pytest.raises(NotAllowedError):
        await room.vote(specs[0][0], True)


async def test_only_one_vote_at_a_time():
    room, _, owner, bad, *_ = await setup(spectators=2)
    await room.start_kick(owner, bad.number)
    with pytest.raises(NotAllowedError):
        await room.start_kick(owner, bad.number)


async def test_vote_is_cancelled_if_target_leaves():
    room, _, owner, bad, _, specs = await setup(spectators=1)
    await room.start_kick(owner, bad.number)
    await room.leave(bad.id)
    assert room._vote is None
    sink = specs[0][1]
    assert sink.of("kick_result")[-1]["outcome"] == "cancelled"
    assert BAD not in room._kicked  # partir n'est pas être exclu


async def test_vote_is_cancelled_if_target_recovers_during_the_vote():
    room, _, owner, bad, _, specs = await setup(spectators=1)
    await room.start_kick(owner, bad.number)
    score_for(room, bad.number, *("verified",) * 20)
    await room.vote(specs[0][0], True)
    assert bad.id in room.clients and BAD not in room._kicked


async def test_reconnecting_target_does_not_cancel_the_vote():
    room, _, owner, bad, _, specs = await setup(spectators=2)
    await room.start_kick(owner, bad.number)
    new, _ = room.join(Sink().send, BAD)  # même identité : remplace l'ancienne connexion
    await room.leave(bad.id)
    assert room._vote is not None and new.number == bad.number


async def test_vote_event_reports_counts_and_snapshot_carries_it():
    room, _, owner, bad, _, specs = await setup(spectators=2)
    await room.start_kick(owner, bad.number)
    ev = room._vote_event()
    assert ev["type"] == "kick_vote" and ev["yes"] == 1 and ev["no"] == 0 and ev["voters"] == 2
    assert ev["threshold"] == 30 and ev["score"] == room.individual_score(bad.number)
    assert room.snapshot("spectator")["kick_vote"]["target"] == bad.number
    await room.aclose()


async def test_kicked_target_never_leaks_votes_identities():
    room, _, owner, bad, _, specs = await setup(spectators=2)
    await room.start_kick(owner, bad.number)
    await room.vote(specs[0][0], False)
    for ev in (room._vote_event(), room.snapshot("spectator")):
        assert "'s0'" not in str(ev) and f"'{OWNER}'" not in str(ev)
    await room.aclose()


# ---------- prise de siège ----------
async def test_spectator_takes_the_freed_seat_first_come_first_served():
    room, _, owner, bad, _, specs = await setup(spectators=2)
    # 2 sièges occupés sur 3 : un siège libre existe déjà ; on le remplit puis on exclut
    filler, _ = join(room, "filler")
    assert filler.role == "C"
    await room.start_kick(owner, bad.number)
    for c, _ in specs:
        await room.vote(c, True)
    first, second = specs[0][0], specs[1][0]
    await room.take_seat(first)
    assert first.role == "B" and first.number is not None
    assert specs[0][1].of("role")[-1]["role"] == "B"
    with pytest.raises(NotAllowedError):
        await room.take_seat(second)  # plus de place
    assert second.role == "spectator"


async def test_participant_cannot_take_a_seat_and_no_seat_means_refusal():
    room, _, owner, *_ = await setup()
    with pytest.raises(NotAllowedError):
        await room.take_seat(owner)


async def test_taking_a_seat_keeps_the_same_number_for_the_same_identity():
    room, *_ = await setup()
    spec, _ = join(room, "viewer", spectate=True)
    await room.take_seat(spec)
    n = spec.number
    await room.leave(spec.id)
    again, _ = join(room, "viewer")
    assert again.number == n


async def test_kicked_cannot_come_back_even_as_spectator():
    room, _, owner, bad, *_ = await setup()
    await room.start_kick(owner, bad.number)
    with pytest.raises(KickedError):
        join(room, BAD, spectate=True)


# ---------- paramètre de seuil ----------
def test_threshold_bounds_are_enforced_in_room():
    for bad in (KICK_THRESHOLD_MIN - 1, KICK_THRESHOLD_MAX + 1):
        with pytest.raises(ValueError):
            Room("r", "T", "C", "social", NullChecker(), CheckLimits(2, 20, 5.0), kick_threshold=bad)


async def test_custom_threshold_is_used():
    room, _ = make_room(kick_threshold=40)
    owner, _s = join(room, OWNER)
    bad, _s2 = join(room, BAD)
    score_for(room, bad.number, "false", "false", "nuanced")
    assert room.individual_score(bad.number) == 30  # n'aurait PAS suffi avec le seuil par défaut (30, strict)
    assert await room.start_kick(owner, bad.number) == "kicked"


# ---------- API (WebSocket + création) ----------
@pytest.mark.parametrize("bad", [19, 41, "30", 30.0, True, None, -1])
def test_create_rejects_invalid_threshold(bad):
    with make_client() as c:
        assert create(c, kick_threshold=bad).status_code == 422


def test_create_accepts_threshold_and_exposes_it():
    with make_client() as c:
        r = create(c, kick_threshold=25)
        assert r.status_code == 201
        rid = r.json()["id"]
        assert c.get(f"/api/v1/rooms/{rid}").json()["room"]["kick_threshold"] == 25
        assert create(c, 2).status_code == 201  # défaut


def test_ws_kick_events_are_strictly_validated():
    with make_client() as c:
        rid = create(c, 1).json()["id"]
        with connect(c, rid, 1) as ws:
            recv_until(ws, "snapshot")
            for payload in ({"type": "kick", "target": "2"}, {"type": "kick", "target": 0}, {"type": "kick"},
                            {"type": "vote", "approve": "yes"}, {"type": "vote", "approve": 1},
                            {"type": "take_seat", "x": 1}, {"type": "kick", "target": 2, "extra": 1}):
                ws.send_json(payload)
                assert recv_until(ws, "error")["code"] == "invalid_event"


def test_ws_non_owner_cannot_kick_and_gets_forbidden():
    with make_client() as c:
        rid = create(c, 1).json()["id"]
        with connect(c, rid, 1) as owner, connect(c, rid, 2) as other:
            recv_until(owner, "snapshot")
            recv_until(other, "snapshot")
            other.send_json({"type": "kick", "target": 1})
            assert recv_until(other, "error")["code"] == "forbidden"


def test_ws_kicked_identity_is_rejected_at_join():
    with make_client() as c:
        rid = create(c, 1).json()["id"]
        room = c.app.state.rooms.get(rid)
        room._kicked.add(participant_id_of(2))
        with connect(c, rid, 2) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error" and msg["code"] == "kicked"


def participant_id_of(n):
    from app.core.identity import participant_id
    return participant_id(token(n))
