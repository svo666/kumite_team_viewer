from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Condition, Event, Lock, Thread
from time import monotonic
from typing import Any

from .config import Config
from .parser import filter_by_team, get_fights_by_tatami, sanitize_url_for_log, teams_from_fights

logger = logging.getLogger(__name__)


class FightCache:
    """In-memory fight cache with server-side polling and SSE notifications.

    The application runs as one Render web service instance. A single background
    thread refreshes the configured competition source at a fixed interval. Browser
    clients subscribe to /api/events and receive cache snapshots whenever the
    server refreshes data.
    """

    def __init__(self, ttl_seconds: int = 45, poll_seconds: int = 45) -> None:
        self.ttl_seconds = ttl_seconds
        self.poll_seconds = poll_seconds

        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._source_url = ""
        self._active_source_url = ""
        self._tatami_ids: tuple[int, ...] = Config.TATAMI_IDS
        self._disabled_tatami_ids: set[int] = set()
        self._fights: list[Any] = []
        self._teams: list[str] = []
        self._last_updated: datetime | None = None
        self._last_error: str | None = None
        self._last_refresh_monotonic = 0.0
        self._refreshing = False
        self._version = 0

        self._stop_event = Event()
        self._poller_thread: Thread | None = None

    def start_polling(self, default_source_url: str) -> None:
        """Start the singleton server-side polling loop."""
        with self._lock:
            if not self._active_source_url:
                self._active_source_url = default_source_url
            if self._poller_thread and self._poller_thread.is_alive():
                return

            self._stop_event.clear()
            self._poller_thread = Thread(
                target=self._poll_loop,
                name="kumite-poller",
                daemon=True,
            )
            self._poller_thread.start()
            logger.info(
                "Started server-side poller. interval_seconds=%s source=%s",
                self.poll_seconds,
                sanitize_url_for_log(self._active_source_url),
            )

    def stop_polling(self) -> None:
        self._stop_event.set()

    def set_source_url(self, source_url: str) -> None:
        source_url = source_url.strip()
        if not source_url:
            return
        with self._lock:
            if self._active_source_url != source_url:
                logger.info("Active source URL changed: %s", sanitize_url_for_log(source_url))
                self._active_source_url = source_url
                self._disabled_tatami_ids.clear()
                self._tatami_ids = Config.TATAMI_IDS
                # Make the next refresh immediate.
                self._last_refresh_monotonic = 0.0

    def _poll_loop(self) -> None:
        # Do not wait a full poll interval for the first refresh after startup.
        while not self._stop_event.is_set():
            with self._lock:
                source_url = self._active_source_url

            if source_url:
                self.refresh_if_needed(source_url, force=False)

            self._stop_event.wait(self.poll_seconds)

    def _is_stale_locked(self, source_url: str) -> bool:
        if self._source_url != source_url:
            return True
        if not self._last_updated:
            return True
        return monotonic() - self._last_refresh_monotonic >= self.ttl_seconds

    def refresh_if_needed(
        self,
        source_url: str,
        force: bool = False,
        reset_tatamis: bool = False,
    ) -> bool:
        """Refresh the cache if needed.

        Returns True if this call performed a refresh. If another refresh is
        already running, this method returns False immediately unless a manual
        refresh requests a tatami reset, in which case it waits and then runs.
        """
        source_url = source_url.strip()
        if not source_url:
            source_url = Config.DEFAULT_SOURCE_URL

        with self._condition:
            if self._active_source_url != source_url:
                self._active_source_url = source_url
                self._disabled_tatami_ids.clear()
                self._tatami_ids = Config.TATAMI_IDS
                self._last_refresh_monotonic = 0.0
            while self._refreshing and reset_tatamis:
                self._condition.wait()
            if self._refreshing:
                logger.info(
                    "Refresh already running; skipping duplicate refresh request for %s",
                    sanitize_url_for_log(source_url),
                )
                return False
            if reset_tatamis:
                self._disabled_tatami_ids.clear()
                self._tatami_ids = Config.TATAMI_IDS
            if not force and not self._is_stale_locked(source_url):
                return False
            tatami_ids = tuple(
                tatami_id
                for tatami_id in Config.TATAMI_IDS
                if tatami_id not in self._disabled_tatami_ids
            )
            self._refreshing = True

        refresh_started_at = monotonic()
        safe_url = sanitize_url_for_log(source_url)
        logger.info("event=cache_refresh_started source=%s tatamis=%s", safe_url, len(tatami_ids))
        try:
            fights_by_tatami = get_fights_by_tatami(source_url, tatami_ids) if tatami_ids else {}
            fights = [fight for tatami_fights in fights_by_tatami.values() for fight in tatami_fights]
            teams = teams_from_fights(fights)
            with self._condition:
                self._source_url = source_url
                if self._active_source_url == source_url:
                    unavailable_tatamis = {
                        tatami_id
                        for tatami_id, tatami_fights in fights_by_tatami.items()
                        if not tatami_fights
                    }
                    if unavailable_tatamis:
                        logger.info("Disabling tatamis with no parseable fights: %s", sorted(unavailable_tatamis))
                        self._disabled_tatami_ids.update(unavailable_tatamis)
                self._tatami_ids = tuple(
                    tatami_id
                    for tatami_id in Config.TATAMI_IDS
                    if tatami_id not in self._disabled_tatami_ids
                )
                self._fights = fights
                self._teams = teams
                self._last_updated = datetime.now(timezone.utc)
                self._last_refresh_monotonic = monotonic()
                self._last_error = None
                self._version += 1
                active_tatamis = len(self._tatami_ids)
                disabled_tatamis = len(self._disabled_tatami_ids)
                self._condition.notify_all()
            logger.info(
                "event=cache_refresh_completed source=%s duration_ms=%.1f fights=%s teams=%s "
                "active_tatamis=%s disabled_tatamis=%s version=%s",
                safe_url,
                (monotonic() - refresh_started_at) * 1000,
                len(fights),
                len(teams),
                active_tatamis,
                disabled_tatamis,
                self.version,
            )
            return True
        except Exception as exc:
            logger.error(
                "event=cache_refresh_failed source=%s duration_ms=%.1f error_type=%s",
                safe_url,
                (monotonic() - refresh_started_at) * 1000,
                type(exc).__name__,
            )
            with self._condition:
                self._source_url = source_url
                self._last_error = str(exc)
                self._last_refresh_monotonic = monotonic()
                self._version += 1
                self._condition.notify_all()
            return True
        finally:
            with self._condition:
                self._refreshing = False
                self._condition.notify_all()

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self, team: str | None = None) -> dict:
        with self._lock:
            fights = filter_by_team(self._fights, team)
            return {
                "source_url": self._source_url or self._active_source_url,
                "tatami_ids": list(self._tatami_ids),
                "teams": self._teams,
                "selected_team": team or "",
                "last_updated": self._last_updated.isoformat() if self._last_updated else None,
                "last_error": self._last_error,
                "refreshing": self._refreshing,
                "version": self._version,
                "server_poll_seconds": self.poll_seconds,
                "fights": [fight.to_dict() for fight in fights],
            }

    def wait_for_update(self, last_seen_version: int, timeout: float = 25.0) -> tuple[dict, int, bool]:
        """Wait until cache version changes, then return a full snapshot.

        Returns (snapshot, version, changed). When timeout expires, changed is
        False and the returned snapshot is still useful for keep-alive/status.
        """
        with self._condition:
            changed = self._condition.wait_for(
                lambda: self._version != last_seen_version,
                timeout=timeout,
            )
            version = self._version
            fights = list(self._fights)
            snapshot = {
                "source_url": self._source_url or self._active_source_url,
                "tatami_ids": list(self._tatami_ids),
                "teams": list(self._teams),
                "selected_team": "",
                "last_updated": self._last_updated.isoformat() if self._last_updated else None,
                "last_error": self._last_error,
                "refreshing": self._refreshing,
                "version": self._version,
                "server_poll_seconds": self.poll_seconds,
                "fights": [fight.to_dict() for fight in fights],
            }
        return snapshot, version, changed
