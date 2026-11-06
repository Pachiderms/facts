from datetime import datetime, timezone

import pytest

from app.core.resilience import CircuitBreaker, MonthlyQuota


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


# ---------- CircuitBreaker ----------
def test_breaker_stays_closed_below_threshold():
    b = CircuitBreaker(3, 60, clock=Clock())
    b.record_failure()
    b.record_failure()
    assert b.allow() and not b.is_open


def test_breaker_opens_at_threshold_and_blocks():
    clock = Clock()
    b = CircuitBreaker(3, 60, clock=clock)
    for _ in range(3):
        b.record_failure()
    assert b.is_open and not b.allow()
    clock.t = 59
    assert not b.allow()


def test_success_resets_failure_count():
    b = CircuitBreaker(3, 60, clock=Clock())
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.allow()  # 2 échecs consécutifs seulement : jamais 3 d'affilée


def test_half_open_allows_a_single_probe():
    clock = Clock()
    b = CircuitBreaker(1, 60, clock=clock)
    b.record_failure()
    clock.t = 61
    assert b.allow()  # l'essai
    assert not b.allow()  # pas de second essai en parallèle


def test_probe_success_closes_breaker():
    clock = Clock()
    b = CircuitBreaker(1, 60, clock=clock)
    b.record_failure()
    clock.t = 61
    assert b.allow()
    b.record_success()
    assert not b.is_open and b.allow() and b.allow()


def test_probe_failure_reopens_for_a_full_cooldown():
    clock = Clock()
    b = CircuitBreaker(3, 60, clock=clock)
    for _ in range(3):
        b.record_failure()
    clock.t = 61
    assert b.allow()
    b.record_failure()  # un seul échec suffit à rouvrir pendant l'essai
    assert not b.allow()
    clock.t = 100
    assert not b.allow()  # nouveau délai compté depuis la réouverture (t=61)
    clock.t = 122
    assert b.allow()


def test_breaker_rejects_invalid_threshold():
    with pytest.raises(ValueError):
        CircuitBreaker(0)


# ---------- MonthlyQuota ----------
def dt(year, month, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


class DateClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def test_quota_consumes_until_limit():
    q = MonthlyQuota(2, clock=DateClock(dt(2026, 11)))
    assert q.try_consume() and q.try_consume()
    assert not q.try_consume()
    assert q.remaining == 0


def test_quota_resets_on_new_month():
    clock = DateClock(dt(2026, 11, 30))
    q = MonthlyQuota(1, clock=clock)
    assert q.try_consume() and not q.try_consume()
    clock.now = dt(2026, 12, 1)
    assert q.try_consume()


def test_quota_does_not_reset_within_same_month():
    clock = DateClock(dt(2026, 11, 1))
    q = MonthlyQuota(1, clock=clock)
    assert q.try_consume()
    clock.now = dt(2026, 11, 28)
    assert not q.try_consume()


def test_quota_resets_across_years():
    clock = DateClock(dt(2026, 12, 15))
    q = MonthlyQuota(1, clock=clock)
    assert q.try_consume()
    clock.now = dt(2027, 12, 15)  # même numéro de mois, autre année
    assert q.try_consume()


def test_quota_zero_blocks_everything():
    q = MonthlyQuota(0, clock=DateClock(dt(2026, 11)))
    assert not q.try_consume() and q.remaining == 0


def test_quota_multi_credit_consumption_is_atomic():
    q = MonthlyQuota(3, clock=DateClock(dt(2026, 11)))
    assert not q.try_consume(4)
    assert q.remaining == 3  # refus total : rien de consommé


def test_quota_rejects_negative_limit():
    with pytest.raises(ValueError):
        MonthlyQuota(-1)
