from __future__ import annotations

import json
import logging
from time import monotonic
from typing import Any

from flask import Flask, Response, g, jsonify, render_template, request, stream_with_context

from .cache import FightCache
from .config import Config

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

cache = FightCache(
    ttl_seconds=Config.CACHE_TTL_SECONDS,
    poll_seconds=Config.SERVER_POLL_SECONDS,
)


def _sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    @app.before_request
    def start_request_timer():
        g.request_started_at = monotonic()

    @app.after_request
    def log_request_performance(response):
        started_at = getattr(g, "request_started_at", None)
        if started_at is not None:
            logger.info(
                "event=http_response_ready endpoint=%s method=%s status=%s duration_ms=%.1f",
                request.endpoint or "unmatched",
                request.method,
                response.status_code,
                (monotonic() - started_at) * 1000,
            )
        return response

    # Start one server-side poller per web-service process. Render should run this
    # project with a single Gunicorn worker so the in-memory cache is shared by
    # all SSE clients.
    cache.start_polling(app.config["DEFAULT_SOURCE_URL"])

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            default_source_url=app.config["DEFAULT_SOURCE_URL"],
            server_poll_seconds=app.config["SERVER_POLL_SECONDS"],
            tatami_ids=app.config["TATAMI_IDS"],
        )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/fights")
    def api_fights():
        """Debug/compatibility endpoint returning the current cache snapshot."""
        source_url = request.args.get("source_url") or app.config["DEFAULT_SOURCE_URL"]
        selected_team = request.args.get("team") or ""
        force = request.args.get("force", "0") == "1"

        cache.set_source_url(source_url)
        cache.refresh_if_needed(source_url, force=force)
        return jsonify(cache.snapshot(selected_team))

    @app.post("/api/refresh")
    def api_refresh():
        """Manual refresh button endpoint.

        The server-side poller refreshes automatically at its configured interval. This
        endpoint forces an immediate refresh and also wakes all SSE clients once
        the cache changes.
        """
        payload = request.get_json(silent=True) or {}
        source_url = payload.get("source_url") or request.form.get("source_url") or app.config["DEFAULT_SOURCE_URL"]
        selected_team = payload.get("team") or request.form.get("team") or ""

        cache.set_source_url(source_url)
        cache.refresh_if_needed(source_url, force=True, reset_tatamis=True)
        return jsonify(cache.snapshot(selected_team))

    @app.get("/api/events")
    def api_events():
        """Server-Sent Events stream.

        Clients receive an initial snapshot immediately and then a new snapshot
        whenever the server-side poller refreshes the cache. Keep-alive comments
        are sent so Render/proxies do not close idle connections.
        """
        source_url = request.args.get("source_url") or app.config["DEFAULT_SOURCE_URL"]
        cache.set_source_url(source_url)
        cache.refresh_if_needed(source_url, force=False)

        @stream_with_context
        def stream():
            snapshot = cache.snapshot()
            version = snapshot.get("version", 0)
            yield _sse("snapshot", snapshot)

            while True:
                snapshot, version, changed = cache.wait_for_update(int(version), timeout=25.0)
                if changed:
                    yield _sse("snapshot", snapshot)
                else:
                    yield ": keep-alive\n\n"

        headers = {
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return Response(stream(), mimetype="text/event-stream", headers=headers)

    return app
