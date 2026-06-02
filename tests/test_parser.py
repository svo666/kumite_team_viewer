from pathlib import Path

from app.parser import parse_tatami_html, teams_from_fights


def test_parse_uploaded_sample_if_available():
    sample = Path('/mnt/data/csc_tatamicontent.html')
    if not sample.exists():
        return
    fights = parse_tatami_html(sample.read_text(encoding='utf-8'), 1)
    assert fights
    assert fights[0].actual_fight_no == 1
    assert fights[0].opponent_a.name == 'Pék Marcell'
    assert fights[0].opponent_a.team == 'Griff SE'
    assert fights[0].opponent_b.is_winner is True
    assert 'Castrum' in teams_from_fights(fights)
