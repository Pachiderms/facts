import pytest

from app.services.trust import compute_trust_score, trust_delta


def test_no_checkable_messages_means_no_score():
    assert compute_trust_score({}) is None
    assert compute_trust_score({"no_claim": 5, "unchecked": 3}) is None  # ces statuts ne comptent pas


def test_single_message_cannot_swing_to_extremes():
    assert 30 <= compute_trust_score({"false": 1}) <= 40
    assert 60 <= compute_trust_score({"verified": 1}) <= 70


def test_known_values():
    assert compute_trust_score({"verified": 2}) == 75
    assert compute_trust_score({"verified": 1, "false": 1}) == 50
    assert compute_trust_score({"nuanced": 10}) == 50


def test_ordering_verified_beats_nuanced_beats_unsourced_beats_false():
    scores = [compute_trust_score({s: 4}) for s in ("verified", "nuanced", "unsourced", "false")]
    assert scores == sorted(scores, reverse=True) and len(set(scores)) == 4


def test_more_verified_messages_raise_the_score_monotonically():
    scores = [compute_trust_score({"verified": n}) for n in range(1, 30)]
    assert scores == sorted(scores)
    assert all(0 <= s <= 100 for s in scores)


@pytest.mark.parametrize("counts", [{"verified": 10_000}, {"false": 10_000}, {"verified": 1, "false": 5_000}])
def test_always_bounded(counts):
    assert 0 <= compute_trust_score(counts) <= 100


def test_score_is_symmetric_between_sides():
    """Le score ne dépend que des statuts : aucune notion de camp n'entre dans la formule."""
    assert compute_trust_score({"verified": 3, "false": 1}) == compute_trust_score({"false": 1, "verified": 3})


def test_delta():
    assert trust_delta(None, 67) == 17  # point de départ implicite : 50
    assert trust_delta(67, 75) == 8
    assert trust_delta(75, 60) == -15
    assert trust_delta(60, None) == 0
