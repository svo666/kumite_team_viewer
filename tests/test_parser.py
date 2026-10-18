from app.config import Config
from app.parser import (
    _fight_from_record,
    fetch_all_tatami_fights,
    sanitize_url_for_log,
    teams_from_fights,
)


def test_log_url_omits_credentials_query_and_fragment():
    url = "https://user:pass@example.test/schedule?token=secret&tatamiid=3#section"

    assert sanitize_url_for_log(url) == "https://example.test/schedule"


def test_default_tatamis_are_one_to_eight():
    assert Config.TATAMI_IDS == (1, 2, 3, 4, 5, 6, 7, 8)


def test_ajax_record_maps_to_fight_fields_and_winner():
    record = {
        "scheduleidx": 12,
        "compgroupid": 42,
        "levelid": 2,
        "matchindex": 5,
        "athaid": 101,
        "athaname": "A Competitor",
        "athaassocdesc": "A Team",
        "athacountrydesc": "HUN",
        "athbid": 202,
        "athbname": "B Competitor",
        "athbassocdesc": "B Team",
        "athbcountrydesc": "AUT",
        "winner": 202,
    }

    fight = _fight_from_record(
        record,
        {42: {"compcategorystr": "Kumite - Senior", "drawbasenote": "Elimination"}},
        tatami_id=3,
    )

    assert fight is not None
    assert fight.tatami_name == "Tatami 3"
    assert fight.actual_fight_no == 12
    assert fight.category == "Kumite - Senior"
    assert fight.execution == "Elimination"
    assert fight.level == "2"
    assert fight.fight == "5"
    assert fight.opponent_a.name == "A Competitor"
    assert fight.opponent_a.team == "A Team"
    assert fight.opponent_a.nationality == "HUN"
    assert not fight.opponent_a.is_winner
    assert fight.opponent_b.is_winner
    assert fight.is_completed
    assert teams_from_fights([fight]) == ["A Team", "B Team"]


def test_ajax_record_without_schedule_index_is_not_a_fight():
    assert _fight_from_record(
        {"scheduleidx": None, "compgroupid": 42},
        {42: {"compcategorystr": "", "drawbasenote": ""}},
        tatami_id=1,
    ) is None


def test_ajax_fetch_uses_page_session_and_returns_empty_tatami(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = (
            '<input id="comp_param_compid" value="512">'
            '<input id="comp_param_sessionid" value="fresh-session">'
        )

        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.post_calls = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, timeout):
            assert "slsession=stale-session" in url
            return FakeResponse({})

        def post(self, url, data, headers, timeout):
            self.post_calls.append(data.copy())
            if data["p"] == "compgrouplist":
                return FakeResponse(
                    {"compgrouplist": {"42": {"compcategorystr": "Kumite", "drawbasenote": "Round robin"}}}
                )
            if data["tatamiid"] == "1":
                return FakeResponse(
                    {
                        "drawlist": [
                            {
                                "scheduleidx": 1,
                                "compgroupid": 42,
                                "athaid": 101,
                                "athaname": "A",
                                "athaassocdesc": "Team A",
                                "athacountrydesc": "HUN",
                                "athbid": 202,
                                "athbname": "B",
                                "athbassocdesc": "Team B",
                                "athbcountrydesc": "AUT",
                                "winner": None,
                            }
                        ]
                    }
                )
            return FakeResponse({"drawlist": []})

    fake_session = FakeSession()
    monkeypatch.setattr("app.parser.requests.Session", lambda: fake_session)
    result = fetch_all_tatami_fights(
        "https://example.test/index.php?p=competitionschedule&compid=512&slsession=stale-session",
        (1, 6),
    )

    assert len(result[1]) == 1
    assert result[1][0].opponent_a.raw == "A (Team A - HUN)"
    assert result[1][0].is_current
    assert result[6] == []
    assert [call["p"] for call in fake_session.post_calls] == [
        "compgrouplist",
        "compdrawlistsch",
        "compdrawlistsch",
    ]
    assert all(call["slsession"] == "fresh-session" for call in fake_session.post_calls)
