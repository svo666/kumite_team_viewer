from __future__ import annotations

import logging
from dataclasses import replace
from time import monotonic
from typing import Iterable, Optional
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import Competitor, Fight

logger = logging.getLogger(__name__)


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


def _response_json(response: requests.Response, operation: str) -> dict:
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError(f"Competition site returned invalid JSON for {operation}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Competition site returned an invalid response for {operation}")
    if data in ({"error": "error"}, {"error": "nopermission"}):
        raise ValueError(f"Competition site rejected {operation}")
    return data


def _fetch_competition_context(
    session: requests.Session,
    source_url: str,
) -> tuple[str, str, str, dict]:
    safe_url = sanitize_url_for_log(source_url)
    started_at = monotonic()
    response = session.get(source_url, timeout=Config.REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    compid = soup.find(id="comp_param_compid")
    session_id = soup.find(id="comp_param_sessionid")
    if not compid or not compid.get("value") or not session_id or not session_id.get("value"):
        raise ValueError("Competition page did not provide competition and session identifiers")

    ajax_url = urljoin(source_url, "z_ajaxcollector.php")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    groups_response = session.post(
        ajax_url,
        data={
            "p": "compgrouplist",
            "compid": compid["value"],
            "notsorted": "1",
            "gencatdesc": "1",
            "slsession": session_id["value"],
        },
        headers=headers,
        timeout=Config.REQUEST_TIMEOUT_SECONDS,
    )
    groups_data = _response_json(groups_response, "competition groups")
    groups = groups_data.get("compgrouplist")
    if not isinstance(groups, dict):
        raise ValueError("Competition site response did not include competition groups")

    logger.info(
        "event=competition_context_fetched source=%s status=%s duration_ms=%.1f groups=%s",
        safe_url,
        response.status_code,
        (monotonic() - started_at) * 1000,
        len(groups),
    )
    return ajax_url, compid["value"], session_id["value"], groups


def _competitor_from_record(record: dict, side: str) -> Competitor:
    athlete_id = record.get(f"ath{side}id")
    name = record.get(f"ath{side}name") or ""
    team = record.get(f"ath{side}assocdesc") or ""
    nationality = record.get(f"ath{side}countrydesc") or ""
    raw = f"{name} ({team} - {nationality})" if athlete_id is not None else ""
    winner = record.get("winner")
    return Competitor(
        raw=raw,
        name=name,
        team=team,
        nationality=nationality,
        is_winner=winner is not None and winner == athlete_id,
    )


def _fight_from_record(record: dict, groups: dict, tatami_id: int) -> Optional[Fight]:
    schedule_index = record.get("scheduleidx")
    if schedule_index is None or str(schedule_index).strip() in ("", "-"):
        return None

    group = groups.get(str(record.get("compgroupid"))) or groups.get(record.get("compgroupid"))
    if not isinstance(group, dict):
        raise ValueError(f"Competition group metadata missing for tatami {tatami_id}")
    try:
        actual_fight_no = int(schedule_index)
    except (TypeError, ValueError):
        actual_fight_no = None

    opponent_a = _competitor_from_record(record, "a")
    opponent_b = _competitor_from_record(record, "b")
    return Fight(
        tatami_id=tatami_id,
        tatami_name=f"Tatami {tatami_id}",
        actual_fight_no=actual_fight_no,
        category=str(group.get("compcategorystr") or ""),
        execution=str(group.get("drawbasenote") or ""),
        level=str(record.get("levelid") if record.get("levelid") is not None else ""),
        fight=str(record.get("matchindex") if record.get("matchindex") is not None else ""),
        opponent_a=opponent_a,
        opponent_b=opponent_b,
        is_completed=opponent_a.is_winner or opponent_b.is_winner,
    )


def fetch_all_tatami_fights(source_url: str, tatami_ids: Iterable[int]) -> dict[int, list[Fight]]:
    """Fetch schedule records directly from the competition site's AJAX endpoint."""
    safe_url = sanitize_url_for_log(source_url)
    with requests.Session() as session:
        session.headers.update({"User-Agent": Config.USER_AGENT})
        ajax_url, compid, session_id, groups = _fetch_competition_context(session, source_url)
        fights_by_tatami: dict[int, list[Fight]] = {}

        for tatami_id in tatami_ids:
            started_at = monotonic()
            response = session.post(
                ajax_url,
                data={
                    "p": "compdrawlistsch",
                    "compid": compid,
                    "tatamiid": str(tatami_id),
                    "slsession": session_id,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=Config.REQUEST_TIMEOUT_SECONDS,
            )
            data = _response_json(response, f"tatami {tatami_id} schedule")
            drawlist = data.get("drawlist")
            if not isinstance(drawlist, (dict, list)):
                raise ValueError(f"Competition site response did not include tatami {tatami_id} schedule")

            fights = []
            records = drawlist.values() if isinstance(drawlist, dict) else drawlist
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError(f"Invalid schedule record for tatami {tatami_id}")
                fight = _fight_from_record(record, groups, tatami_id)
                if fight is not None:
                    fights.append(fight)
            first_unfinished = next(
                (index for index, fight in enumerate(fights) if not fight.is_completed),
                None,
            )
            if first_unfinished is not None:
                fights[first_unfinished] = replace(fights[first_unfinished], is_current=True)
            fights_by_tatami[tatami_id] = fights
            logger.info(
                "event=tatami_fetch mode=ajax tatami=%s source=%s status=%s duration_ms=%.1f "
                "records=%s fights=%s",
                tatami_id,
                safe_url,
                response.status_code,
                (monotonic() - started_at) * 1000,
                len(drawlist),
                len(fights),
            )

    return fights_by_tatami


def get_fights_by_tatami(
    source_url: str,
    tatami_ids: Iterable[int] = Config.TATAMI_IDS,
) -> dict[int, list[Fight]]:
    started_at = monotonic()
    tatami_ids = tuple(tatami_ids)
    safe_url = sanitize_url_for_log(source_url)
    logger.info("event=scrape_started source=%s tatamis=%s", safe_url, len(tatami_ids))
    fights_by_tatami = fetch_all_tatami_fights(source_url, tatami_ids)

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
