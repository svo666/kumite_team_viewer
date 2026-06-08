from pathlib import Path

from app.config import Config
from app.parser import parse_tatami_html, tatami_url, teams_from_fights


def test_tatami_url_replaces_zero_with_requested_id():
    url = "https://www.k2.main1.hu/index.php?p=competitionschedule&compid=504&tatamiid=0&slsession=abc"
    assert "tatamiid=8" in tatami_url(url, 8)
    assert "slsession=abc" in tatami_url(url, 8)


def test_default_tatamis_are_one_to_eight():
    assert Config.TATAMI_IDS == (1, 2, 3, 4, 5, 6, 7, 8)


def test_parser_extracts_fights_and_teams_from_sample():
    html_path = Path(__file__).resolve().parents[1] / "sample" / "csc_tatamicontent.html"
    if not html_path.exists():
        # The sample file is optional in the deployment ZIP.
        return
    fights = parse_tatami_html(html_path.read_text(encoding="utf-8"), tatami_id=1)
    assert fights
    teams = teams_from_fights(fights)
    assert "Castrum" in teams
