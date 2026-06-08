# Kumite Team Viewer - Render SSE version

Flask application for showing karate fights from the K2 competition schedule site.

This version is designed for Render and uses:

- Playwright/Chromium to render the JavaScript-filled source table.
- Server-side polling once per minute.
- Server-Sent Events (SSE) to push refreshed data to browsers.
- A single shared in-memory cache so 10 connected browsers do not cause 10 separate scrape cycles.
- Automatic Tatami 1-8 fetching. The UI no longer asks for Tatami IDs.
- Pinned dependency/runtime set: Python 3.14, `lxml==6.1.1`, and `playwright==1.60.0`.

## How it works

1. Configure `DEFAULT_SOURCE_URL` with a competition URL such as:

   ```text
   https://www.k2.main1.hu/index.php?p=competitionschedule&compid=504&tatamiid=0&slsession=a9315eb958
   ```

2. The backend generates and renders these URLs automatically:

   ```text
   ...&tatamiid=1&...
   ...&tatamiid=2&...
   ...
   ...&tatamiid=8&...
   ```

3. A background polling thread refreshes all 8 tatamis every `SERVER_POLL_SECONDS`, default `60`.
4. Browsers connect to `/api/events` using Server-Sent Events.
5. After every server refresh, all connected browsers receive the updated table.
6. Team filtering happens in the browser using the latest server snapshot, so changing the team filter does not scrape the source site again.

## Deploy on Render

Render does not support direct ZIP upload for web services. Put the project in a GitHub, GitLab, or Bitbucket repository and connect that repository to Render.

The included `render.yaml` defines the web service:

```yaml
services:
  - type: web
    name: kumite-team-viewer
    runtime: python
    plan: free
    buildCommand: python -m pip install --upgrade pip && python -m pip install -r requirements.txt && PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium
    startCommand: gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 20 --timeout 300 --keep-alive 75 --access-logfile - --error-logfile -
```

Use **one Gunicorn worker**. This is important because the cache and server-side polling thread are in memory. Multiple workers would each create their own poller and cache.

## Environment variables

| Variable | Default | Meaning |
|---|---:|---|
| `DEFAULT_SOURCE_URL` | sample K2 URL | Base competition URL. `tatamiid` is replaced with 1-8 automatically. |
| `SERVER_POLL_SECONDS` | `60` | How often the server refreshes the source site. |
| `CACHE_TTL_SECONDS` | `55` | Prevents duplicate manual/event refreshes inside one minute. |
| `BROWSER_TIMEOUT_SECONDS` | `20` | Max seconds Playwright waits for the JavaScript-filled table. |
| `REQUEST_TIMEOUT_SECONDS` | `20` | Timeout for the static fallback request. |
| `USER_AGENT` | app default | User-Agent used by requests/Playwright. |

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium
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

Every source fetch is logged. Render logs will show lines such as:

```text
Fetching rendered tatami data: tatami=1 url=https://www.k2.main1.hu/index.php?p=competitionschedule&compid=504&tatamiid=1&slsession=...
Fetched rendered tatami data: tatami=1 url=... size=123456 has_rows=True
```

## Notes

The source K2 site fills the table with JavaScript after the initial page load. Plain `requests.get()` often returns the empty shell table, so this project uses Playwright to wait for rows to appear before parsing.

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

## Render Playwright build command

This version uses `python -m playwright install chromium` instead of the bare `playwright install chromium` command. This avoids Render build failures where the `playwright` console script is not on `PATH` even though the Python package was installed.

If you created a normal Render Web Service instead of a Blueprint, check the service **Settings → Build Command** and set it to:

```bash
python -m pip install --upgrade pip && python -m pip install -r requirements.txt && PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium
```

If you deployed via a Render Blueprint, push the updated `render.yaml` and sync/redeploy.

## Render Playwright browser install note

This version sets `PLAYWRIGHT_BROWSERS_PATH=0` so the Chromium browser downloaded by Playwright is stored with the Python environment instead of Render's external cache directory. This avoids the runtime error:

```text
BrowserType.launch: Executable doesn't exist at /opt/render/.cache/ms-playwright/...
```

Use this Render build command:

```bash
python -m pip install --upgrade pip && python -m pip install -r requirements.txt && PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium
```

Also set these environment variables in Render if your dashboard settings override `render.yaml`:

```text
PLAYWRIGHT_BROWSERS_PATH=0
PYTHON_VERSION=3.14
PYTHONUNBUFFERED=1
```

The app also has a one-time runtime fallback: if Chromium is still missing, it will try `python -m playwright install chromium` once and then retry launching the browser. The runtime fallback inherits `PLAYWRIGHT_BROWSERS_PATH=0`, so it installs to the same location used by the build command.

## v13 runtime pin update

This package keeps the browser-install correction but uses the required runtime/dependency versions:

```text
Python 3.14
lxml==6.1.1
playwright==1.60.0
```
