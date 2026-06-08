from __future__ import annotations

import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    DEFAULT_SOURCE_URL = os.environ.get(
        "DEFAULT_SOURCE_URL",
        "https://www.k2.main1.hu/index.php?p=competitionschedule&compid=504&tatamiid=0&slsession=a9315eb958",
    )
    # The competition page uses tatamiid=0 as the selector/all URL, but the
    # schedule table must be fetched separately for tatamiid 1..8.
    TATAMI_IDS = tuple(range(1, 9))

    # Server-side polling interval. Browsers receive updates via Server-Sent Events.
    SERVER_POLL_SECONDS = int(os.environ.get("SERVER_POLL_SECONDS", "60"))
    CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "55"))

    REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))
    BROWSER_TIMEOUT_SECONDS = int(os.environ.get("BROWSER_TIMEOUT_SECONDS", "20"))

    USER_AGENT = os.environ.get(
        "USER_AGENT",
        "KumiteTeamViewer/1.3 Render SSE (+https://render.com/)"
    )
