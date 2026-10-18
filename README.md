# Kumite Team Viewer - Render SSE version

Flask application for showing karate fights from the K2 competition schedule site.

This version is designed for Render and uses:

- The source site's AJAX endpoint to fetch schedule data directly, without running a browser.
- Server-side polling every 45 seconds.
- Server-Sent Events (SSE) to push refreshed data to browsers.
- A single shared in-memory cache so 10 connected browsers do not cause 10 separate scrape cycles.
- Automatic initial Tatami 1-8 fetching. The UI no longer asks for Tatami IDs.

## How it works

1. Configure `DEFAULT_SOURCE_URL` with a competition URL such as:

   ```text
   https://www.xzy.com
   ```

2. The backend loads the competition page to obtain its current session identifier, then requests schedule JSON for tatamis 1-8.
3. A background polling thread refreshes enabled tatamis every `SERVER_POLL_SECONDS`, default `45`.
4. Empty tatamis are disabled for automatic refreshes. **Refresh now** re-enables all tatamis and retries them.
5. Browsers connect to `/api/events` using Server-Sent Events.
6. After every server refresh, all connected browsers receive the updated table.
7. Team filtering happens in the browser using the latest server snapshot, so changing the team filter does not scrape the source site again.

## Deploy on Render

Render does not support direct ZIP upload for web services. Put the project in a GitHub, GitLab, or Bitbucket repository and connect that repository to Render.

The included `render.yaml` defines the web service:

```yaml
services:
  - type: web
    name: kumite-team-viewer
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 20 --timeout 300 --keep-alive 75 --access-logfile - --error-logfile -
```

Use **one Gunicorn worker**. This is important because the cache and server-side polling thread are in memory. Multiple workers would each create their own poller and cache.

## Environment variables

| Variable | Default | Meaning |
|---|---:|---|
| `DEFAULT_SOURCE_URL` | sample K2 URL | Competition schedule URL. |
| `SERVER_POLL_SECONDS` | `45` | How often the server refreshes enabled tatamis. |
| `CACHE_TTL_SECONDS` | `45` | Prevents duplicate event-triggered refreshes within the cache TTL. |
| `REQUEST_TIMEOUT_SECONDS` | `15` | Timeout for each source page or AJAX request. |
| `USER_AGENT` | app default | User-Agent used by source requests. |

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open:

```text
http://127.0.0.1:5000
```

## Useful endpoints

- `/` - main UI
- `/api/events?source_url=...` - SSE stream used by the browser
- `/api/refresh` - POST endpoint used by the manual refresh button
- `/api/fights` - debug/compatibility JSON endpoint
- `/healthz` - health check

## Logs

Performance logs are emitted as key-value records in the hosting logs:

```text
event=competition_context_fetched status=200 duration_ms=... groups=...
event=tatami_fetch mode=ajax tatami=1 status=200 duration_ms=... records=... fights=...
event=scrape_completed duration_ms=... total_fights=...
event=cache_refresh_completed duration_ms=... fights=... disabled_tatamis=...
event=http_response_ready endpoint=api_refresh status=200 duration_ms=...
```

AJAX logs record the per-request duration, returned schedule record count, and parsed fight count. For long-term comparisons, track p50/p95 durations, status codes, timeout/failure counts, and fight counts across refreshes. The HTTP response event measures time until Flask creates the response; for `/api/events` this is stream setup time, not the lifetime of the SSE connection.

Source locations in logs omit credentials, query parameters, and fragments so session tokens are not written to logs. The Render Gunicorn access-log format also omits request query strings, and the local Werkzeug access log is suppressed in favor of the safe application request-duration event. Do not add raw URLs or exception messages from HTTP/browser libraries to log records; they may contain sensitive query strings.

## Notes

The source K2 site fills its schedule table with JavaScript, but the page obtains the underlying schedule from `z_ajaxcollector.php`. The app requests that JSON endpoint directly and uses the page's current competition session identifier.

## v5 UI changes

- The former `Actual #` table column is now labelled `Fight #`.
- The old `Fight`/match-index display column has been removed from the UI.
- The schedule table uses a fixed-height scroll area with sticky two-row headers.
- Tatami groups are separated with stronger vertical borders.

## v6 UI changes

- Removed the visible top title/header bar.
- Moved **Refresh now** next to the team dropdown.
- Moved connection/update status and the color legend to the bottom of the page.
- Tatami group headers now show the current actual fight number, for example `Tatami 2 - actual fight # 12`.

## v7 UI changes

- Removed the Category column from the main table.
- Removed the hint text and color legend from the footer.
