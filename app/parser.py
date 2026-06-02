from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import Competitor, Fight

_COMPETITOR_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<meta>.*?)\)\s*$", re.S)


def set_query_param(url: str, key: str, value: str | int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def fetch_html(source_url: str, tatami_id: int, timeout: int = Config.REQUEST_TIMEOUT_SECONDS) -> str:
    url = set_query_param(source_url, "tatamiid", tatami_id)
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": Config.USER_AGENT},
    )
    response.raise_for_status()
    return response.text


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
        marked.append(Fight(**{**fight.to_dict(), "is_current": current}))
    return marked


def get_all_fights(source_url: str, tatami_ids: Iterable[int]) -> list[Fight]:
    all_fights: list[Fight] = []
    for tatami_id in tatami_ids:
        html = fetch_html(source_url, tatami_id)
        all_fights.extend(parse_tatami_html(html, tatami_id))
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
