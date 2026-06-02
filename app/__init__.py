from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from .cache import FightCache
from .config import Config

cache = FightCache(ttl_seconds=Config.CACHE_TTL_SECONDS)


def parse_tatami_ids(value: str | None) -> list[int]:
    raw = value or Config.DEFAULT_TATAMI_IDS
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids or [1]


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            default_source_url=app.config["DEFAULT_SOURCE_URL"],
            default_tatami_ids=app.config["DEFAULT_TATAMI_IDS"],
            default_poll_seconds=app.config["DEFAULT_POLL_SECONDS"],
        )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/fights")
    def api_fights():
        source_url = request.args.get("source_url") or app.config["DEFAULT_SOURCE_URL"]
        tatami_ids = parse_tatami_ids(request.args.get("tatami_ids"))
        selected_team = request.args.get("team") or ""
        force = request.args.get("force", "0") == "1"

        cache.refresh_if_needed(source_url, tatami_ids, force=force)
        return jsonify(cache.snapshot(selected_team))

    return app
