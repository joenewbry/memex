from dataclasses import dataclass, field, asdict
from typing import Optional
import time


@dataclass
class Prospect:
    source: str
    username: str
    display_name: str
    profile_url: str
    bio: str = ""
    category: str = ""
    signals: list = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)
    trust_gap_score: float = 0.0
    reachability_score: float = 0.0
    relevance_score: float = 0.0
    final_score: float = 0.0
    outreach_message: str = ""
    fetched_at: float = field(default_factory=time.time)

    def to_dict(self):
        return asdict(self)


class BaseAdapter:
    name: str = "base"
    description: str = ""
    icon: str = ""
    categories: list = []

    async def fetch(self, config: dict) -> list[Prospect]:
        raise NotImplementedError

    def get_config_schema(self) -> dict:
        return {}
