from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import Competitor, Fight

logger = logging.getLogger(__name__)

_COMPETITOR_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<meta>.*?)\)\s*$", re.S)


def sanitize_url_for_log(url: str) -> str:
    """Return a URL location without credentials, query parameters, or fragment."""
    try:
        parts = urlsplit(url)
        hostname = parts.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = f":{parts.port}" if parts.port is not None else ""
    except ValueError:
        return "<invalid-url>"
    return f"{parts.scheme}://{hostname}{port}{parts.path}"


def set_query_param(url: str, key: str, value: str | int) -> str:
    """Return URL with one query parameter inserted/replaced."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def tatami_url(source_url: str, tatami_id: int) -> str:
    """Convert the configured competition URL into a concrete tatami URL.

    Example:
    ...&tatamiid=0&... -> ...&tatamiid=1&...
    """
    return set_query_param(source_url, "tatamiid", tatami_id)


def fetch_html_static(source_url: str, tatami_id: int, timeout: int = Config.REQUEST_TIMEOUT_SECONDS) -> str:
    """Fetch the initial server HTML.

    The k2/main1 page normally returns an almost empty schedule table first and
    fills #csc_tatamicontent via JavaScript afterwards. This method is kept as a
    fallback and for diagnostics, but rendered fetching is preferred.
    """
    url = tatami_url(source_url, tatami_id)
    safe_url = sanitize_url_for_log(url)
    started_at = monotonic()
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": Config.USER_AGENT},
        )
    except Exception as exc:
        logger.error(
            "event=tatami_fetch_failed mode=static tatami=%s source=%s "
            "total_ms=%.1f error_type=%s",
            tatami_id,
            safe_url,
            (monotonic() - started_at) * 1000,
            type(exc).__name__,
        )
        raise
    logger.info(
        "event=tatami_fetch mode=static tatami=%s source=%s status=%s upstream_elapsed_ms=%.1f html_bytes=%s",
        tatami_id,
        safe_url,
        response.status_code,
        response.elapsed.total_seconds() * 1000,
        len(response.content),
    )
    response.raise_for_status()
    return response.text


def _html_has_fight_rows(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="csc_tatamicontent")
    if table is None:
        return False
    for row in table.select("tbody tr"):
        idx_text = _clean_text(_cell_by_name(row, "s_idxx"))
        if idx_text and idx_text != "-":
            return True
    return False


def fetch_all_tatami_html_rendered(source_url: str, tatami_ids: Iterable[int]) -> dict[int, str]:
    """Fetch all tatamis after JavaScript has populated the schedule table.

    This uses Playwright/Chromium. Render installs Chromium during build via
    `playwright install chromium` from render.yaml.
    """
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - only hit when dependency missing
        logger.warning("Playwright unavailable; falling back to static requests. error_type=%s", type(exc).__name__)
        return _fetch_static_html_concurrently(source_url, tatami_ids)

    async def fetch_all() -> dict[int, str]:
        html_by_tatami: dict[int, str] = {}
        semaphore = asyncio.Semaphore(Config.TATAMI_FETCH_CONCURRENCY)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

            async def fetch_one(tatami_id: int) -> tuple[int, str]:
                url = tatami_url(source_url, tatami_id)
                safe_url = sanitize_url_for_log(url)
                async with semaphore:
                    page = None
                    started_at = monotonic()
                    try:
                        page = await browser.new_page(user_agent=Config.USER_AGENT)
                        navigation_started_at = monotonic()
                        response = await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=Config.BROWSER_TIMEOUT_SECONDS * 1000,
                        )
                        navigation_ms = (monotonic() - navigation_started_at) * 1000
                        timing = await page.evaluate(
                            """() => {
                              const entry = performance.getEntriesByType('navigation')[0];
                              return entry ? {
                                upstream_ttfb_ms: entry.responseStart - entry.requestStart,
                                upstream_download_ms: entry.responseEnd - entry.responseStart
                              } : {};
                            }"""
                        )
                        row_wait_started_at = monotonic()
                        rows_ready = True
                        try:
                            await page.wait_for_function(
                                """
                                () => Array.from(document.querySelectorAll('#csc_maintable_tbody tr'))
                                  .some(row => {
                                    const cell = row.querySelector('[name="s_idxx"]');
                                    return cell && cell.textContent.trim() && cell.textContent.trim() !== '-';
                                  })
                                """,
                                timeout=Config.BROWSER_TIMEOUT_SECONDS * 1000,
                            )
                        except PlaywrightTimeoutError:
                            rows_ready = False
                            logger.warning(
                                "event=tatami_rows_timeout tatami=%s source=%s",
                                tatami_id,
                                safe_url,
                            )
                        row_wait_ms = (monotonic() - row_wait_started_at) * 1000
                        html = await page.content()
                        logger.info(
                            "event=tatami_fetch mode=rendered tatami=%s source=%s status=%s "
                            "navigation_ms=%.1f upstream_ttfb_ms=%s upstream_download_ms=%s "
                            "row_wait_ms=%.1f rows_ready=%s total_ms=%.1f html_bytes=%s has_rows=%s",
                            tatami_id,
                            safe_url,
                            response.status if response is not None else None,
                            navigation_ms,
                            round(timing.get("upstream_ttfb_ms", 0), 1) if timing else None,
                            round(timing.get("upstream_download_ms", 0), 1) if timing else None,
                            row_wait_ms,
                            rows_ready,
                            (monotonic() - started_at) * 1000,
                            len(html),
                            _html_has_fight_rows(html),
                        )
                        return tatami_id, html
                    except Exception as exc:
                        logger.error(
                            "event=tatami_fetch_failed mode=rendered tatami=%s source=%s "
                            "total_ms=%.1f error_type=%s",
                            tatami_id,
                            safe_url,
                            (monotonic() - started_at) * 1000,
                            type(exc).__name__,
                        )
                        return tatami_id, ""
                    finally:
                        if page is not None:
                            try:
                                await page.close()
                            except Exception as exc:
                                logger.error(
                                    "Failed to close browser page for tatami %s. error_type=%s",
                                    tatami_id,
                                    type(exc).__name__,
                                )

            try:
                results = await asyncio.gather(*(fetch_one(tatami_id) for tatami_id in tatami_ids))
                html_by_tatami.update(results)
            finally:
                await browser.close()
        return html_by_tatami

    return asyncio.run(fetch_all())


def _fetch_static_html_concurrently(source_url: str, tatami_ids: Iterable[int]) -> dict[int, str]:
    def fetch_one(tatami_id: int) -> tuple[int, str]:
        try:
            return tatami_id, fetch_html_static(source_url, tatami_id)
        except Exception as exc:
            logger.error("event=tatami_fetch_failed mode=static tatami=%s error_type=%s", tatami_id, type(exc).__name__)
            return tatami_id, ""

    with ThreadPoolExecutor(max_workers=Config.TATAMI_FETCH_CONCURRENCY) as executor:
        return dict(executor.map(fetch_one, tatami_ids))


def _clean_text(element) -> str:
    if element is None:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def parse_competitor(button) -> Competitor:
    raw = _clean_text(button)
    is_winner = bool(button and "btn-success" in (button.get("class") or []))
    name = raw
    team = ""
    nationality = ""
    match = _COMPETITOR_RE.match(raw)
    if match:
        name = match.group("name").strip()
        meta = match.group("meta").strip()
        if " - " in meta:
            team, nationality = meta.rsplit(" - ", 1)
            team = team.strip()
            nationality = nationality.strip()
        else:
            team = meta.strip()
    return Competitor(raw=raw, name=name, team=team, nationality=nationality, is_winner=is_winner)


def _cell_by_name(row, name: str):
    return row.find(attrs={"name": name})


def parse_tatami_html(html: str, tatami_id: int, tatami_name: Optional[str] = None) -> list[Fight]:
    started_at = monotonic()
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="csc_tatamicontent")
    if table is None:
        logger.warning(
            "event=tatami_parse tatami=%s duration_ms=%.1f fights=0 table_found=false",
            tatami_id,
            (monotonic() - started_at) * 1000,
        )
        return []

    fights: list[Fight] = []
    for row in table.select("tbody tr"):
        idx_text = _clean_text(_cell_by_name(row, "s_idxx"))
        if not idx_text or idx_text == "-":
            continue
        try:
            actual_no = int(idx_text)
        except ValueError:
            actual_no = None

        opponent_a_button = row.find("button", attrs={"name": "s_opponent1"})
        opponent_b_button = row.find("button", attrs={"name": "s_opponent2"})
        if not opponent_a_button or not opponent_b_button:
            continue

        opponent_a = parse_competitor(opponent_a_button)
        opponent_b = parse_competitor(opponent_b_button)
        is_completed = opponent_a.is_winner or opponent_b.is_winner
        fights.append(
            Fight(
                tatami_id=tatami_id,
                tatami_name=tatami_name or f"Tatami {tatami_id}",
                actual_fight_no=actual_no,
                category=_clean_text(_cell_by_name(row, "s_compcategorystr")),
                execution=_clean_text(_cell_by_name(row, "s_drawbasenote")),
                level=_clean_text(_cell_by_name(row, "s_level")),
                fight=_clean_text(_cell_by_name(row, "s_matchindex")),
                opponent_a=opponent_a,
                opponent_b=opponent_b,
                is_completed=is_completed,
            )
        )

    first_unfinished_seen = False
    marked: list[Fight] = []
    for fight in fights:
        current = False
        if not first_unfinished_seen and not fight.is_completed:
            current = True
            first_unfinished_seen = True
        marked.append(
            Fight(
                tatami_id=fight.tatami_id,
                tatami_name=fight.tatami_name,
                actual_fight_no=fight.actual_fight_no,
                category=fight.category,
                execution=fight.execution,
                level=fight.level,
                fight=fight.fight,
                opponent_a=fight.opponent_a,
                opponent_b=fight.opponent_b,
                is_completed=fight.is_completed,
                is_current=current,
            )
        )
    logger.info(
        "event=tatami_parse tatami=%s duration_ms=%.1f fights=%s table_found=true",
        tatami_id,
        (monotonic() - started_at) * 1000,
        len(marked),
    )
    return marked


def get_fights_by_tatami(
    source_url: str,
    tatami_ids: Iterable[int] = Config.TATAMI_IDS,
) -> dict[int, list[Fight]]:
    started_at = monotonic()
    tatami_ids = tuple(tatami_ids)
    safe_url = sanitize_url_for_log(source_url)
    logger.info("event=scrape_started source=%s tatamis=%s", safe_url, len(tatami_ids))
    html_by_tatami = fetch_all_tatami_html_rendered(source_url, tatami_ids)
    fights_by_tatami = {
        tatami_id: parse_tatami_html(html_by_tatami.get(tatami_id, ""), tatami_id)
        for tatami_id in tatami_ids
    }

    tatamis_needing_fallback = [tatami_id for tatami_id, fights in fights_by_tatami.items() if not fights]
    for tatami_id, html in _fetch_static_html_concurrently(source_url, tatamis_needing_fallback).items():
        logger.warning("No fights parsed from rendered HTML for tatami %s; tried static fallback", tatami_id)
        fights_by_tatami[tatami_id] = parse_tatami_html(html, tatami_id)

    logger.info(
        "event=scrape_completed source=%s duration_ms=%.1f tatamis=%s "
        "active_tatamis=%s total_fights=%s",
        safe_url,
        (monotonic() - started_at) * 1000,
        len(tatami_ids),
        sum(bool(fights) for fights in fights_by_tatami.values()),
        sum(len(fights) for fights in fights_by_tatami.values()),
    )
    return fights_by_tatami


def get_all_fights(source_url: str, tatami_ids: Iterable[int] = Config.TATAMI_IDS) -> list[Fight]:
    return [
        fight
        for fights in get_fights_by_tatami(source_url, tatami_ids).values()
        for fight in fights
    ]


def teams_from_fights(fights: Iterable[Fight]) -> list[str]:
    teams = set()
    for fight in fights:
        if fight.opponent_a.team:
            teams.add(fight.opponent_a.team)
        if fight.opponent_b.team:
            teams.add(fight.opponent_b.team)
    return sorted(teams, key=str.casefold)


def filter_by_team(fights: Iterable[Fight], team: str | None) -> list[Fight]:
    if not team:
        return list(fights)
    return [fight for fight in fights if fight.opponent_a.team == team or fight.opponent_b.team == team]
