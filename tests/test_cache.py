from importlib import import_module

from app.cache import FightCache
from app.config import Config


def test_empty_tatamis_are_skipped_until_manual_refresh(monkeypatch):
    calls = []

    def fetch_fights(source_url, tatami_ids):
        calls.append(tuple(tatami_ids))
        return {tatami_id: [] for tatami_id in tatami_ids}

    cache_module = import_module("app.cache")
    monkeypatch.setattr(cache_module, "get_fights_by_tatami", fetch_fights)
    cache = FightCache(ttl_seconds=0, poll_seconds=45)

    cache.refresh_if_needed("https://example.test", force=True)

    assert calls == [Config.TATAMI_IDS]
    assert cache.snapshot()["tatami_ids"] == []

    cache.refresh_if_needed("https://example.test")
    assert calls == [Config.TATAMI_IDS]

    cache.refresh_if_needed("https://example.test", force=True, reset_tatamis=True)
    assert calls == [Config.TATAMI_IDS, Config.TATAMI_IDS]
