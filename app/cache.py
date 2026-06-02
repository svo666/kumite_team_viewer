from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any

from .parser import filter_by_team, get_all_fights, teams_from_fights


class FightCache:
    """Small in-memory cache designed for one Render web service instance.

    Browsers may poll every minute, but this class prevents every user from
    scraping the source site separately. Only the first request after TTL expiry
    performs a refresh; other users receive the latest cached snapshot.
    """

    def __init__(self, ttl_seconds: int = 55) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._source_url = ""
        self._tatami_ids: tuple[int, ...] = ()
        self._fights: list[Any] = []
        self._teams: list[str] = []
        self._last_updated: datetime | None = None
        self._last_error: str | None = None
        self._last_refresh_monotonic = 0.0
        self._refreshing = False

    def _is_stale_locked(self, source_url: str, tatami_ids: list[int]) -> bool:
        ids = tuple(tatami_ids)
        if self._source_url != source_url or self._tatami_ids != ids:
            return True
        if not self._last_updated:
            return True
        return monotonic() - self._last_refresh_monotonic >= self.ttl_seconds

    def refresh_if_needed(self, source_url: str, tatami_ids: list[int], force: bool = False) -> None:
        with self._lock:
            if self._refreshing:
                return
            if not force and not self._is_stale_locked(source_url, tatami_ids):
                return
            self._refreshing = True

        try:
            fights = get_all_fights(source_url, tatami_ids)
            teams = teams_from_fights(fights)
            with self._lock:
                self._source_url = source_url
                self._tatami_ids = tuple(tatami_ids)
                self._fights = fights
                self._teams = teams
                self._last_updated = datetime.now(timezone.utc)
                self._last_refresh_monotonic = monotonic()
                self._last_error = None
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._last_refresh_monotonic = monotonic()
        finally:
            with self._lock:
                self._refreshing = False

    def snapshot(self, team: str | None = None) -> dict:
        with self._lock:
            fights = filter_by_team(self._fights, team)
            return {
                "source_url": self._source_url,
                "tatami_ids": list(self._tatami_ids),
                "teams": self._teams,
                "selected_team": team or "",
                "last_updated": self._last_updated.isoformat() if self._last_updated else None,
                "last_error": self._last_error,
                "fights": [fight.to_dict() for fight in fights],
            }
