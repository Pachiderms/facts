"""Identité de compte dans les salons (sans base) : alias, propriété, sanctions. Fonctionnel + sécurité."""

import uuid

from app.core.identity import account_identity, is_valid_token, participant_id
from app.services.moderation import MAX_STRIKES, ModerationLedger
from app.services.rooms import CheckLimits, Room
from tests.test_moderation import Sink
from tests.test_rooms_create import Clock, NullChecker

ANON, ANON2, ACCOUNT, ACCOUNT2 = "a" * 16, "b" * 16, "u:" + "1" * 16, "u:" + "2" * 16


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def room(owner=ANON, **kw):
    return Room("r", "T", "C", "social", NullChecker(), CheckLimits(2, 20, 5.0), owner_id=owner, max_participants=2, clock=Clock(), **kw)


def join(r, pid, aliases=(), spectate=False):
    return r.join(Sink().send, pid, spectate=spectate, aliases=aliases)[0]


# ---------- format de l'identité ----------
def test_account_identity_cannot_collide_with_an_anonymous_hash():
    uid = uuid.uuid4()
    ident = account_identity(uid)
    assert ident.startswith("u:") and len(ident) == 18 and ident == account_identity(uid)
    assert ":" not in participant_id("x" * 30)
    assert not is_valid_token(ident + "x" * 10)  # un jeton client ne peut pas contenir « : »


# ---------- registre des sanctions ----------
def test_link_moves_strikes_and_bans_to_the_account():
    clock = FakeClock()
    ledger = ModerationLedger(clock=clock)
    ledger.add_strike(ANON)
    ledger.link(ACCOUNT, [ANON])
    assert ledger.strikes(ACCOUNT) == 1 and ledger.strikes(ANON) == 1  # l'alias lit le compte
    for _ in range(MAX_STRIKES):
        ledger.add_strike(ANON)
    assert ledger.ban_remaining(ACCOUNT) > 0 and ledger.ban_remaining(ANON) > 0


def test_ban_follows_the_account_to_a_new_device():
    ledger = ModerationLedger(clock=FakeClock())
    for _ in range(MAX_STRIKES):
        ledger.add_strike(ANON)
    ledger.link(ACCOUNT, [ANON])
    ledger.link(ACCOUNT, [ANON2])  # même compte, nouvel appareil
    assert ledger.ban_remaining(ANON2) > 0


def test_ban_before_login_is_not_shed_by_logging_in():
    ledger = ModerationLedger(clock=FakeClock())
    for _ in range(MAX_STRIKES):
        ledger.add_strike(ANON)
    ledger.link(ACCOUNT, [ANON])
    assert ledger.ban_remaining(ACCOUNT) > 0


def test_ban_expires_for_account_and_aliases():
    clock = FakeClock()
    ledger = ModerationLedger(ban_seconds=100, clock=clock)
    for _ in range(MAX_STRIKES):
        ledger.add_strike(ACCOUNT)
    ledger.link(ACCOUNT, [ANON])
    clock.now = 101
    assert ledger.ban_remaining(ACCOUNT) == 0 and ledger.ban_remaining(ANON) == 0


def test_first_account_keeps_the_alias():
    ledger = ModerationLedger(clock=FakeClock())
    ledger.link(ACCOUNT, [ANON])
    ledger.link(ACCOUNT2, [ANON])  # même navigateur, autre compte : l'alias reste au premier
    assert ledger.resolve(ANON) == ACCOUNT
    ledger.add_strike(ANON)
    assert ledger.strikes(ACCOUNT) == 1 and ledger.strikes(ACCOUNT2) == 0


def test_link_is_idempotent_and_ignores_self():
    ledger = ModerationLedger(clock=FakeClock())
    ledger.add_strike(ANON)
    ledger.link(ACCOUNT, [ANON, ACCOUNT])
    ledger.link(ACCOUNT, [ANON])
    assert ledger.strikes(ACCOUNT) == 1


def test_worst_of_both_wins_when_merging():
    ledger = ModerationLedger(clock=FakeClock())
    ledger.add_strike(ANON)
    ledger.add_strike(ANON)
    ledger.add_strike(ACCOUNT)
    ledger.link(ACCOUNT, [ANON])
    assert ledger.strikes(ACCOUNT) == 2


def test_alias_table_is_bounded():
    ledger = ModerationLedger(max_entries=5, clock=FakeClock())
    ledger.link(ACCOUNT, [f"{i:016x}" for i in range(50)])
    assert len(ledger._alias) <= 5


def test_unrelated_people_are_not_merged():
    ledger = ModerationLedger(clock=FakeClock())
    for _ in range(MAX_STRIKES):
        ledger.add_strike(ANON)
    ledger.link(ACCOUNT2, [ANON2])
    assert ledger.ban_remaining(ACCOUNT2) == 0


# ---------- salon : identité canonique ----------
def test_owner_created_anonymously_stays_owner_after_login():
    r = room(owner=ANON)
    assert r.is_owner(ANON) and not r.is_owner(ACCOUNT)
    client = join(r, ACCOUNT, (ANON,))
    assert r.is_owner(client.participant_id) and r.is_owner(ACCOUNT)


def test_owner_created_with_account_is_owner_from_any_device():
    r = room(owner=ACCOUNT)
    r.canonical(ACCOUNT, (ANON,))
    join(r, ACCOUNT, (ANON2,))
    assert r.is_owner(ACCOUNT) and r.is_owner(ANON2)


def test_stranger_is_never_owner_and_cannot_claim_by_alias_alone():
    r = room(owner=ACCOUNT)
    r.canonical(ACCOUNT, (ANON,))
    join(r, ACCOUNT2, (ANON2,))
    assert not r.is_owner(ACCOUNT2) and not r.is_owner(ANON2)


def test_seat_and_number_survive_login():
    r = room()
    first = join(r, ANON2)
    second, replaced = r.join(Sink().send, ACCOUNT2, aliases=(ANON2,))
    assert replaced is first and second.role == first.role and second.number == first.number
    assert len(r.clients) == 1  # une seule place, pas de doublon anonyme + compte


def test_kicked_stays_kicked_after_login_and_on_other_device():
    from app.services.rooms import KickedError
    import pytest
    r = room()
    c = join(r, ANON2)
    r._kicked.add(c.participant_id)
    with pytest.raises(KickedError):
        r.join(Sink().send, ACCOUNT2, aliases=(ANON2,))
    with pytest.raises(KickedError):
        r.join(Sink().send, ACCOUNT2, aliases=("c" * 16,))  # autre appareil, même compte


def test_canonical_table_is_bounded():
    r = room()
    for i in range(2000):
        r.canonical(f"{i:016x}")
    assert len(r._canon) <= 1000 + 2
