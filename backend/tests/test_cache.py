from app.core.cache import TTLCache


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_get_set():
    c = TTLCache(60, 10, clock=Clock())
    c.set("a", 1)
    assert c.get("a") == 1 and c.get("zzz") is None


def test_entry_expires():
    clock = Clock()
    c = TTLCache(60, 10, clock=clock)
    c.set("a", 1)
    clock.t = 59
    assert c.get("a") == 1
    clock.t = 60
    assert c.get("a") is None
    assert len(c) == 0  # l'entrée expirée est supprimée, pas seulement masquée


def test_size_is_bounded_and_oldest_evicted():
    c = TTLCache(60, 3, clock=Clock())
    for i in range(10):
        c.set(f"k{i}", i)
    assert len(c) == 3
    assert c.get("k0") is None and c.get("k9") == 9


def test_overwrite_refreshes_ttl_and_position():
    clock = Clock()
    c = TTLCache(60, 2, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.t = 50
    c.set("a", 10)  # a devient la plus récente, TTL repart
    c.set("c", 3)  # évince b (la plus ancienne), pas a
    assert c.get("b") is None and c.get("a") == 10
    clock.t = 100
    assert c.get("a") == 10
