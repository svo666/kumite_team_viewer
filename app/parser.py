from __future__ import annotations

import logging
import re
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import Competitor, Fight

logger = logging.getLogger(__name__)

_COMPETITOR_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<meta>.*?)\)\s*$", re.S)


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
    logger.info("Fetching static tatami HTML: tatami=%s url=%s", tatami_id, url)
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": Config.USER_AGENT},
    )
    response.raise_for_status()
    logger.info(
        "Fetched static tatami HTML: tatami=%s url=%s status=%s size=%s",
        tatami_id,
        url,
        response.status_code,
        len(response.text),
    )
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
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - only hit when dependency missing
        logger.exception("Playwright is not available; falling back to static requests: %s", exc)
        return {tatami_id: fetch_html_static(source_url, tatami_id) for tatami_id in tatami_ids}

    html_by_tatami: dict[int, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = browser.new_page(user_agent=Config.USER_AGENT)
            for tatami_id in tatami_ids:
                url = tatami_url(source_url, tatami_id)
                logger.info("Fetching rendered tatami data: tatami=%s url=%s", tatami_id, url)
                page.goto(url, wait_until="domcontentloaded", timeout=Config.BROWSER_TIMEOUT_SECONDS * 1000)
                try:
                    page.wait_for_function(
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
                    logger.warning(
                        "Timed out waiting for rendered rows: tatami=%s url=%s. Capturing current HTML anyway.",
                        tatami_id,
                        url,
                    )
                html = page.content()
                logger.info(
                    "Fetched rendered tatami data: tatami=%s url=%s size=%s has_rows=%s",
                    tatami_id,
                    url,
                    len(html),
                    _html_has_fight_rows(html),
                )
                html_by_tatami[tatami_id] = html
        finally:
            browser.close()
    return html_by_tatami


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
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="csc_tatamicontent")
    if table is None:
        logger.warning("No csc_tatamicontent table found for tatami %s", tatami_id)
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

    logger.info("Parsed tatami %s: fights=%s", tatami_id, len(fights))

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
    return marked


def get_all_fights(source_url: str, tatami_ids: Iterable[int] = Config.TATAMI_IDS) -> list[Fight]:
    tatami_ids = tuple(tatami_ids)
    all_fights: list[Fight] = []

    logger.info("Starting rendered refresh for source URL: %s", source_url)
    html_by_tatami = fetch_all_tatami_html_rendered(source_url, tatami_ids)

    for tatami_id in tatami_ids:
        html = html_by_tatami.get(tatami_id, "")
        fights = parse_tatami_html(html, tatami_id)

        # Extra safety: if rendered fetch produced no rows, try static once. This
        # helps local tests and gives clearer Render logs.
        if not fights:
            logger.warning("No fights parsed from rendered HTML for tatami %s; trying static fallback", tatami_id)
            try:
                static_html = fetch_html_static(source_url, tatami_id)
                fights = parse_tatami_html(static_html, tatami_id)
            except Exception as exc:
                logger.exception("Static fallback failed for tatami %s: %s", tatami_id, exc)

        all_fights.extend(fights)

    logger.info("Completed refresh for source URL: %s total_fights=%s", source_url, len(all_fights))
    return all_fights


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
