from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class Competitor:
    raw: str
    name: str
    team: str
    nationality: str
    is_winner: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Fight:
    tatami_id: int
    tatami_name: str
    actual_fight_no: Optional[int]
    category: str
    execution: str
    level: str
    fight: str
    opponent_a: Competitor
    opponent_b: Competitor
    is_completed: bool
    is_current: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
