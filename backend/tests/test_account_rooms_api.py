"""Salons + comptes de bout en bout (vraie base) : propriété, bannissement, historique synchronisé."""

import os

import pytest
from sqlalchemy import select

from app.core.identity import participant_id
from app.services.moderation import MAX_STRIKES
from tests.test_accounts_api import (  # noqa: F401  (fixture fresh_db réutilisée)
    ANON, KEYS, OTHER_ANON, auth, fresh_db, login, make_client, query,
)
from tests.test_api_rooms import recv_until

URL = os.environ.get("FACTS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="FACTS_TEST_DATABASE_URL non défini")

TITLE = "La semaine de quatre jours est-elle une bonne idée ?"


def session_for(c, sub="1", email="a@example.com", participant=None):
    r = login(c, sub=sub, email=email, participant=participant)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def create(c, token=ANON, session=None, **over):
    body = {"title": TITLE, "theme_category": "social", "visibility": "private", "participant_token": token, **over}
    return c.post("/api/v1/rooms", json=body, headers=auth(session) if session else {})


def snapshot(c, room, token, session=None, code=None):
    with c.websocket_connect(f"/api/v1/rooms/{room}/ws") as ws:
        hello = {"type": "hello", "token": token}
        if session is not None:
            hello["session"] = session
        if code is not None:
            hello["code"] = code
        ws.send_json(hello)
        event = ws.receive_json()
        return event


def ban(c, room_id, pid):
    ledger = c.app.state.rooms.get(room_id).moderator.ledger
    for _ in range(MAX_STRIKES):
        ledger.add_strike(pid)


# ---------- propriété ----------
def test_room_created_anonymously_is_still_owned_after_login(fresh_db):
    with make_client() as c:
        made = create(c, ANON).json()
        sess = session_for(c, participant=ANON)
        snap = snapshot(c, made["id"], ANON, sess)
        assert snap["type"] == "snapshot" and snap["room"]["is_owner"] is True and snap["room"]["access_code"] == made["access_code"]


def test_room_created_with_account_is_owned_from_another_device(fresh_db):
    with make_client() as c:
        sess = session_for(c)
        made = create(c, ANON, sess).json()
        snap = snapshot(c, made["id"], OTHER_ANON, sess)  # autre navigateur, même compte, sans code
        assert snap["type"] == "snapshot" and snap["room"]["is_owner"] is True


def test_creator_keeps_ownership_on_the_same_browser_after_logging_out(fresh_db):
    with make_client() as c:
        made = create(c, ANON, session_for(c)).json()
        assert snapshot(c, made["id"], ANON)["room"]["is_owner"] is True  # déconnecté, même navigateur


def test_anonymous_room_can_be_deleted_by_its_creator_once_logged_in(fresh_db):
    with make_client() as c:
        made = create(c, ANON).json()
        sess = session_for(c)  # jamais rejoint connecté : seul l'alias anonyme prouve la propriété
        r = c.post(f"/api/v1/rooms/{made['id']}/delete", json={"participant_token": ANON}, headers=auth(sess))
        assert r.status_code == 204


def test_other_account_is_not_owner_and_needs_the_code(fresh_db):
    with make_client() as c:
        made = create(c, ANON, session_for(c, "1", "a@example.com")).json()
        other = session_for(c, "2", "b@example.com")
        assert snapshot(c, made["id"], OTHER_ANON, other)["code"] == "invalid_code"
        snap = snapshot(c, made["id"], OTHER_ANON, other, made["access_code"])
        assert snap["room"]["is_owner"] is False


def test_invalid_session_falls_back_to_anonymous_identity(fresh_db):
    with make_client() as c:
        made = create(c, ANON).json()
        snap = snapshot(c, made["id"], ANON, "x" * 43)  # session inconnue : identité anonyme conservée
        assert snap["room"]["is_owner"] is True
        assert snapshot(c, made["id"], OTHER_ANON, "x" * 43)["code"] == "invalid_code"


def test_bogus_session_values_are_rejected_by_the_hello_schema(fresh_db):
    with make_client() as c:
        made = create(c, ANON).json()
        for bad in (123, "x" * 65, ["a"]):
            with c.websocket_connect(f"/api/v1/rooms/{made['id']}/ws") as ws:
                ws.send_json({"type": "hello", "token": ANON, "session": bad})
                assert ws.receive_json()["type"] == "error"


def test_delete_by_account_owner_from_another_device(fresh_db):
    with make_client() as c:
        sess = session_for(c)
        made = create(c, ANON, sess).json()
        denied = c.post(f"/api/v1/rooms/{made['id']}/delete", json={"participant_token": OTHER_ANON})
        assert denied.status_code == 403
        ok = c.post(f"/api/v1/rooms/{made['id']}/delete", json={"participant_token": OTHER_ANON}, headers=auth(sess))
        assert ok.status_code == 204


def test_other_account_cannot_delete(fresh_db):
    with make_client() as c:
        made = create(c, ANON, session_for(c, "1", "a@example.com")).json()
        other = session_for(c, "2", "b@example.com")
        r = c.post(f"/api/v1/rooms/{made['id']}/delete", json={"participant_token": OTHER_ANON}, headers=auth(other))
        assert r.status_code == 403


# ---------- bannissement ----------
def test_ban_follows_the_account_to_another_device(fresh_db):
    with make_client() as c:
        made = create(c, ANON, visibility="public").json()
        sess = session_for(c, participant=ANON)
        ban(c, made["id"], participant_id(ANON))
        assert snapshot(c, made["id"], ANON, sess)["code"] == "banned"  # le bannissement anonyme est rattaché au compte
        assert snapshot(c, made["id"], OTHER_ANON, sess)["code"] == "banned"  # nouvel appareil : toujours exclu


def test_ban_applies_to_the_account_even_if_logged_out_on_same_browser(fresh_db):
    with make_client() as c:
        made = create(c, ANON, visibility="public").json()
        sess = session_for(c)
        snapshot(c, made["id"], ANON, sess)  # rattache ce navigateur au compte
        ban(c, made["id"], participant_id(ANON))
        assert snapshot(c, made["id"], ANON)["code"] == "banned"  # déconnecté : l'exclusion suit le navigateur


def test_ban_does_not_leak_to_other_people(fresh_db):
    with make_client() as c:
        made = create(c, ANON, visibility="public").json()
        ban(c, made["id"], participant_id(ANON))
        other = session_for(c, "2", "b@example.com")
        assert snapshot(c, made["id"], OTHER_ANON, other)["type"] == "snapshot"


# ---------- historique synchronisé ----------
ENTRY = {"id": "room-1", "title": "Un salon", "visibility": "public", "owner": False, "pinned": True, "lastVisit": 1_700_000_000_000}


def test_history_requires_a_session(fresh_db):
    with make_client() as c:
        assert c.get("/api/v1/me/history").status_code == 401
        assert c.post("/api/v1/me/history", json={"entries": []}).status_code == 401
        assert c.get("/api/v1/me/history", headers=auth("x" * 43)).status_code == 401


def test_history_roundtrip_and_replace(fresh_db):
    with make_client() as c:
        h = auth(session_for(c))
        assert c.get("/api/v1/me/history", headers=h).json() == {"entries": []}
        r = c.post("/api/v1/me/history", json={"entries": [ENTRY, {**ENTRY, "id": "room-2", "pinned": False, "lastVisit": 5}]}, headers=h)
        assert [e["id"] for e in r.json()["entries"]] == ["room-1", "room-2"]  # épinglé d'abord
        c.post("/api/v1/me/history", json={"entries": [{**ENTRY, "id": "room-3"}]}, headers=h)
        assert [e["id"] for e in c.get("/api/v1/me/history", headers=h).json()["entries"]] == ["room-3"]
        assert c.post("/api/v1/me/history", json={"entries": []}, headers=h).json() == {"entries": []}


def test_history_is_private_to_each_account(fresh_db):
    with make_client() as c:
        a, b = auth(session_for(c, "1", "a@example.com")), auth(session_for(c, "2", "b@example.com"))
        c.post("/api/v1/me/history", json={"entries": [ENTRY]}, headers=a)
        assert c.get("/api/v1/me/history", headers=b).json() == {"entries": []}
        c.post("/api/v1/me/history", json={"entries": [{**ENTRY, "title": "B"}]}, headers=b)
        assert c.get("/api/v1/me/history", headers=a).json()["entries"][0]["title"] == "Un salon"


def test_history_validation(fresh_db):
    with make_client() as c:
        h = auth(session_for(c))
        post = lambda entries, **kw: c.post("/api/v1/me/history", json={"entries": entries, **kw}, headers=h).status_code  # noqa: E731
        assert post([{**ENTRY, "id": f"r-{i}"} for i in range(21)]) == 422  # > 20
        assert post([{**ENTRY, "id": "../etc"}]) == 422
        assert post([{**ENTRY, "id": "A" * 5}]) == 422  # majuscules interdites
        assert post([{**ENTRY, "visibility": "secret"}]) == 422
        assert post([{**ENTRY, "owner": "yes"}]) == 422
        assert post([{**ENTRY, "lastVisit": -1}]) == 422
        assert post([{**ENTRY, "lastVisit": 1.5}]) == 422
        assert post([{**ENTRY, "title": "   "}]) == 422
        assert post([{**ENTRY, "code": "ABCDEF"}]) == 422  # jamais de code d'accès côté serveur
        assert post([ENTRY], extra=1) == 422
        assert post([ENTRY]) == 200


def test_history_titles_are_sanitized_and_duplicates_collapse(fresh_db):
    with make_client() as c:
        h = auth(session_for(c))
        r = c.post("/api/v1/me/history", headers=h, json={"entries": [
            {**ENTRY, "title": "<script>alert(1)</script>  Salon​"},
            {**ENTRY, "lastVisit": 1, "title": "ancien"},
        ]})
        entries = r.json()["entries"]
        assert len(entries) == 1 and "<" not in entries[0]["title"] and "​" not in entries[0]["title"]
        assert entries[0]["lastVisit"] == ENTRY["lastVisit"]


def test_history_is_deleted_with_the_account_and_exported(fresh_db):
    with make_client() as c:
        h = auth(session_for(c))
        c.post("/api/v1/me/history", json={"entries": [ENTRY]}, headers=h)
        exported = c.get("/api/v1/auth/export", headers=h).json()
        assert exported["rooms_history"][0]["id"] == "room-1" and "code" not in exported["rooms_history"][0]
        assert c.post("/api/v1/auth/delete", json={"confirm": True}, headers=h).status_code == 200
        assert query("SELECT count(*) FROM user_rooms")[0][0] == 0


def test_history_responses_are_not_cacheable(fresh_db):
    with make_client() as c:
        h = auth(session_for(c))
        assert c.get("/api/v1/me/history", headers=h).headers["cache-control"] == "no-store"
