from __future__ import annotations

import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    DEFAULT_SOURCE_URL = os.environ.get(
        "DEFAULT_SOURCE_URL",
        "https://www.k2.main1.hu/index.php?p=competitionschedule&compid=504&tatamiid=0&slsession=a9315eb958",
    )
    DEFAULT_TATAMI_IDS = os.environ.get("DEFAULT_TATAMI_IDS", "1,2,3,4")
    DEFAULT_POLL_SECONDS = int(os.environ.get("DEFAULT_POLL_SECONDS", "60"))
    CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "55"))
    REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))
    USER_AGENT = os.environ.get(
        "USER_AGENT",
        "KumiteTeamViewer/1.1 Render (+https://render.com/)"
    )
