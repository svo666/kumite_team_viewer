# Kumite Team Viewer for Render

Flask web app for Render Free. It reads the `csc_tatamicontent` table from the configured K2 competition schedule URL, combines multiple `tatamiid` tables, and displays a team-filterable live dashboard.

## Render-friendly design

The browser polls `/api/fights` every 60 seconds, but the server uses an in-memory cache with a 55-second TTL. This means 10 users polling at the same time still cause at most one scrape cycle per minute per running Render instance.

Manual **Refresh now** uses `force=1` and bypasses the cache.

## Files important for Render

- `render.yaml` — blueprint deployment configuration.
- `Procfile` — alternative start command if you deploy manually.
- `requirements.txt` — includes `gunicorn`.
- `wsgi.py` — exposes `app` for Gunicorn.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open `http://127.0.0.1:5000`.

## Deploy to Render Free

1. Create a GitHub repository and upload this project folder.
2. In Render, choose **New +** → **Blueprint** and select the repository.
3. Render will read `render.yaml` automatically.
4. Update environment variables in Render if needed:

```text
DEFAULT_SOURCE_URL=https://www.k2.main1.hu/index.php?p=competitionschedule&compid=504&tatamiid=0&slsession=YOUR_SESSION
DEFAULT_TATAMI_IDS=1,2,3,4
DEFAULT_POLL_SECONDS=60
CACHE_TTL_SECONDS=55
REQUEST_TIMEOUT_SECONDS=20
```

5. Deploy.

## Notes

- Render Free can spin down after inactivity. The first user during a tournament may wait while it wakes up.
- Once users are active and browser polling runs every minute, the service should remain awake.
- The K2 URL may require a valid `slsession`; paste a fresh source URL in the UI or update `DEFAULT_SOURCE_URL` when needed.
- `--workers 1 --threads 8` is intentional. One worker keeps the in-memory cache simple and shared between all requests handled by the app process.
