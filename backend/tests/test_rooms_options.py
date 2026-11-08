"""Options de salon (participants, spectateurs), suppression par le créateur, statut des salons."""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.services.rooms import (
    MAX_SPECTATORS,
    CheckLimits,
    NotAllowedError,
    Room,
    RoomFullError,
    RoomNotEmptyError,
    RoomNotFoundError,
    SpectatorsNotAllowedError,
)
from tests.test_api_rooms import connect, make_client, recv_until, token
from tests.test_rooms_create import TITLE, NullChecker, Quiet, create, make_registry, recv_error


def room(**kw):
    return Room("r", "Titre", "Cat", "social", NullChecker(), CheckLimits(2, 20, 5.0), **kw)


# ====================== Room : sièges ======================
def test_seats_follow_max_participants_then_spectators():
    r = room(max_participants=4)
    roles = [r.join(Quiet().send, f"p{i}")[0].role for i in range(6)]
    assert roles == ["A", "B", "C", "D", "spectator", "spectator"]


@pytest.mark.parametrize("bad", [0, 1, 7, -2])
def test_participant_count_is_bounded(bad):
    with pytest.raises(ValueError):
        room(max_participants=bad)


def test_freed_seat_is_reused_by_the_next_newcomer():
    r = room(max_participants=3)
    clients = [r.join(Quiet().send, f"p{i}")[0] for i in range(3)]
    import asyncio

    asyncio.run(r.leave(clients[0].id))  # A part
    assert r.join(Quiet().send, "nouveau")[0].role == "A"


def test_presence_lists_occupied_seats_in_order():
    r = room(max_participants=3)
    r.join(Quiet().send, "p0")
    b = r.join(Quiet().send, "p1")[0]
    r.join(Quiet().send, "p2")
    r.join(Quiet().send, "p3")  # spectateur
    import asyncio

    asyncio.run(r.leave(b.id))
    assert r._presence() == {"type": "presence", "seats": ["A", "C"], "max_participants": 3, "spectators": 1}


def test_spectators_can_be_refused():
    r = room(spectators_allowed=False)
    r.join(Quiet().send, "a")
    r.join(Quiet().send, "b")
    with pytest.raises(SpectatorsNotAllowedError):
        r.join(Quiet().send, "c")


def test_refusing_spectators_does_not_block_a_reconnection_of_a_seated_participant():
    r = room(spectators_allowed=False)
    first, _ = r.join(Quiet().send, "a")
    r.join(Quiet().send, "b")
    again, replaced = r.join(Quiet().send, "a")
    assert replaced is first and again.role == "A"


def test_spectators_are_capped():
    r = room(max_clients=1000)
    r.join(Quiet().send, "a")
    r.join(Quiet().send, "b")
    for i in range(MAX_SPECTATORS):
        assert r.join(Quiet().send, f"s{i}")[0].role == "spectator"
    with pytest.raises(RoomFullError):
        r.join(Quiet().send, "un-de-trop")


async def test_every_seat_can_speak_and_spectators_cannot():
    r = room(max_participants=3)
    clients = [r.join(Quiet().send, f"p{i}")[0] for i in range(4)]
    message = await r.post_message(clients[2], "Je suis C, sans chiffre.")
    assert message["speaker"] == "C" and message["speaker_name"] == "Participant C"
    with pytest.raises(NotAllowedError):
        await r.post_message(clients[3], "Je suis spectateur.")


def test_summary_describes_the_room_settings():
    r = room(max_participants=4, spectators_allowed=False)
    r.join(Quiet().send, "a")
    s = r.summary()
    assert (s["max_participants"], s["spectators_allowed"], s["participants"], s["spectators"]) == (4, False, 1, 0)


def test_snapshot_flags_only_the_owner():
    r = room(owner_id="own")
    assert r.snapshot("A", "own")["room"]["is_owner"] is True
    assert r.snapshot("A", "other")["room"]["is_owner"] is False
    assert r.snapshot("A")["room"]["is_owner"] is False


# ====================== Registry : suppression, statut ======================
async def new_room(reg, owner="own", **kw):
    return await reg.create(title=TITLE, theme_category="social", visibility="public", owner_id=owner, **kw)


async def test_owner_deletes_an_empty_room():
    reg, _ = make_registry()
    r = await new_room(reg)
    await reg.delete(r.id, "own")
    assert reg.get(r.id) is None and reg.summaries() == reg.summaries()
    assert r.id not in [s["id"] for s in reg.summaries()]


async def test_owner_alone_in_the_room_can_delete_and_is_disconnected():
    reg, _ = make_registry()
    r = await new_room(reg)
    events = []

    async def send(event):
        events.append(event)

    closed = []

    async def close():
        closed.append(True)

    r.join(send, "own", close)
    await reg.delete(r.id, "own")
    assert events[-1]["code"] == "room_deleted" and closed == [True] and reg.get(r.id) is None


async def test_deletion_is_refused_while_someone_else_is_connected():
    reg, _ = make_registry()
    r = await new_room(reg)
    r.join(Quiet().send, "own")
    r.join(Quiet().send, "visiteur")
    with pytest.raises(RoomNotEmptyError):
        await reg.delete(r.id, "own")
    assert reg.get(r.id) is r


async def test_only_the_owner_can_delete_and_default_rooms_never():
    reg, _ = make_registry()
    r = await new_room(reg)
    with pytest.raises(NotAllowedError):
        await reg.delete(r.id, "intrus")
    with pytest.raises(NotAllowedError):
        await reg.delete("room-1", "own")
    assert reg.get(r.id) is r and reg.get("room-1") is not None


async def test_deleting_an_unknown_room():
    reg, _ = make_registry()
    with pytest.raises(RoomNotFoundError):
        await reg.delete("zzzzzzzz", "own")


async def test_existing_filters_and_deduplicates():
    reg, _ = make_registry()
    r = await new_room(reg)
    assert reg.existing([r.id, "room-1", "zzzzzzzz", r.id]) == [r.id, "room-1"]


# ====================== API ======================
def test_create_with_options_and_defaults():
    with make_client(daily_room_creation_limit=10, rate_limit_requests=50) as c:
        rid = create(c, max_participants=4, spectators_allowed=False).json()["id"]
        room_ = c.get(f"/api/v1/rooms/{rid}").json()["room"]
        assert room_["max_participants"] == 4 and room_["spectators_allowed"] is False
        default = c.get(f"/api/v1/rooms/{create(c).json()['id']}").json()["room"]
        assert default["max_participants"] == 2 and default["spectators_allowed"] is True
        seed = c.get("/api/v1/rooms").json()[0]
        assert seed["max_participants"] == 2 and seed["spectators_allowed"] is True


@pytest.mark.parametrize(
    "over",
    [
        {"max_participants": 1},
        {"max_participants": 7},
        {"max_participants": 0},
        {"max_participants": -1},
        {"max_participants": "3"},
        {"max_participants": 3.0},
        {"max_participants": True},
        {"max_participants": None},
        {"spectators_allowed": "oui"},
        {"spectators_allowed": 1},
        {"spectators_allowed": None},
    ],
)
def test_invalid_options_are_rejected(over):
    with make_client() as c:
        assert create(c, **over).status_code == 422


def test_three_participant_room_seats_c_and_then_spectators():
    with make_client() as c:
        rid = create(c, max_participants=3).json()["id"]
        with connect(c, rid, n=1) as a, connect(c, rid, n=2) as b, connect(c, rid, n=3) as cc, connect(c, rid, n=4) as spec:
            roles = [recv_until(w, "snapshot")["role"] for w in (a, b, cc, spec)]
            assert roles == ["A", "B", "C", "spectator"]
            cc.send_json({"type": "message", "text": "Selon l'INSEE, 12 % en 2024."})
            assert recv_until(cc, "message")["message"]["speaker"] == "C"


def test_room_without_spectators_refuses_the_extra_visitor_without_retry():
    with make_client() as c:
        rid = create(c, spectators_allowed=False).json()["id"]
        with connect(c, rid, n=1), connect(c, rid, n=2):
            with connect(c, rid, n=3) as third:
                assert recv_error(third)["code"] == "spectators_not_allowed"  # fermeture 1008 : le client ne réessaie pas


def test_full_room_reports_it_and_asks_to_retry_later():
    with make_client(ws_max_room_connections=2) as c:
        with connect(c, n=1), connect(c, n=2):
            with connect(c, n=3) as third:
                assert third.receive_json()["code"] == "room_full"
                with pytest.raises(WebSocketDisconnect) as exc:
                    third.receive_json()
                assert exc.value.code == 1013


def test_snapshot_tells_only_the_creator_that_they_own_the_room():
    with make_client() as c:
        rid = create(c, n=1).json()["id"]
        with connect(c, rid, n=1) as owner:
            assert recv_until(owner, "snapshot")["room"]["is_owner"] is True
        with connect(c, rid, n=2) as visitor:
            assert recv_until(visitor, "snapshot")["room"]["is_owner"] is False


# ---------- suppression ----------
def delete(c, rid, n=1, **over):
    body = {"participant_token": token(n)}
    body.update(over)
    return c.post(f"/api/v1/rooms/{rid}/delete", json=body)


def test_owner_deletes_an_empty_room_over_http():
    with make_client() as c:
        rid = create(c, n=1).json()["id"]
        assert delete(c, rid, 1).status_code == 204
        assert c.get(f"/api/v1/rooms/{rid}").status_code == 404
        assert rid not in [r["id"] for r in c.get("/api/v1/rooms").json()]


def test_private_room_deletion_works_too():
    with make_client() as c:
        rid = create(c, n=1, visibility="private").json()["id"]
        assert delete(c, rid, 1).status_code == 204 and c.get(f"/api/v1/rooms/{rid}").status_code == 404


def test_a_stranger_cannot_delete_someone_elses_room():
    with make_client() as c:
        rid = create(c, n=1).json()["id"]
        r = delete(c, rid, 2)
        assert r.status_code == 403
        assert c.get(f"/api/v1/rooms/{rid}").status_code == 200  # intacte


def test_default_rooms_cannot_be_deleted():
    with make_client() as c:
        assert delete(c, "room-1", 1).status_code == 403
        assert len(c.get("/api/v1/rooms").json()) == 3


def test_deleting_unknown_or_malformed_ids_is_404():
    with make_client() as c:
        for rid in ("zzzzzzzz", "ROOM-1", "a" * 65, "a%20b"):
            assert delete(c, rid, 1).status_code == 404


@pytest.mark.parametrize("body", [{}, {"participant_token": "court"}, {"participant_token": 42}, {"participant_token": "a" * 30, "x": 1}])
def test_malformed_deletion_requests(body):
    with make_client() as c:
        rid = create(c).json()["id"]
        assert c.post(f"/api/v1/rooms/{rid}/delete", json=body).status_code == 422
        assert c.get(f"/api/v1/rooms/{rid}").status_code == 200


def test_deletion_refused_while_another_person_is_in_the_room():
    with make_client() as c:
        rid = create(c, n=1).json()["id"]
        with connect(c, rid, n=2):
            r = delete(c, rid, 1)
            assert r.status_code == 409 and "connectées" in r.json()["detail"]
        assert c.get(f"/api/v1/rooms/{rid}").status_code == 200


def test_owner_inside_the_room_can_delete_it_and_gets_disconnected():
    with make_client() as c:
        rid = create(c, n=1).json()["id"]
        with connect(c, rid, n=1) as ws:
            recv_until(ws, "snapshot")
            assert delete(c, rid, 1).status_code == 204
            assert recv_until(ws, "error")["code"] == "room_deleted"
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4000  # pas de reconnexion automatique
        assert c.get(f"/api/v1/rooms/{rid}").status_code == 404


def test_deleting_does_not_refund_the_daily_creation_quota():
    with make_client(daily_room_creation_limit=2, rate_limit_requests=50) as c:
        for _ in range(2):
            rid = create(c).json()["id"]
            assert delete(c, rid, 1).status_code == 204
        assert create(c).status_code == 429  # créer/supprimer en boucle ne contourne pas la limite


def test_deletion_is_rate_limited():
    with make_client(rate_limit_requests=2) as c:
        rid = create(c).json()["id"]
        delete(c, rid, 2)
        assert delete(c, rid, 2).status_code == 429


# ---------- statut des salons (historique) ----------
def test_status_returns_only_existing_rooms_including_private_ones():
    with make_client(daily_room_creation_limit=10, rate_limit_requests=50) as c:
        private = create(c, visibility="private").json()["id"]
        gone = create(c).json()["id"]
        delete(c, gone, 1)
        r = c.get("/api/v1/rooms/status", params={"ids": f"room-1,{private},{gone},zzzzzzzz"})
        assert r.status_code == 200 and r.json() == {"existing": ["room-1", private]}
        assert TITLE not in r.text  # aucune information sur le contenu


@pytest.mark.parametrize("ids", ["", ",", "ROOM-1", "a b", "../x", "room-1,<script>", ",".join(f"room-{i}" for i in range(21)), "x" * 2000])
def test_status_rejects_invalid_lists(ids):
    with make_client() as c:
        assert c.get("/api/v1/rooms/status", params={"ids": ids}).status_code == 422


def test_status_requires_the_ids_parameter_and_is_not_shadowed_by_the_id_route():
    with make_client() as c:
        assert c.get("/api/v1/rooms/status").status_code == 422  # et non 404 « salon introuvable »


def test_status_uses_the_light_read_quota():
    with make_client(read_rate_limit_requests=1) as c:
        assert c.get("/api/v1/rooms/status", params={"ids": "room-1"}).status_code == 200
        assert c.get("/api/v1/rooms/status", params={"ids": "room-1"}).status_code == 429
