"""Contextual tips system for Memex CLI chat."""

from __future__ import annotations

import random
from typing import Optional, Set

TIPS = [
    "Use /search to search without AI -- it's instant.",
    "Try asking: \"What was I working on yesterday?\"",
    "Use /stats to see today's capture count and word total.",
    "Try asking: \"Summarize my activity this week.\"",
    "Run `memex watch` in another terminal to see captures live.",
    "Use /clear to reset the conversation and start fresh.",
    "Try asking: \"Find any URLs I visited today.\"",
    "Run `memex doctor` for a full system health check.",
    "Use /status for a quick inline health check.",
    "Try asking: \"What emails did I read this morning?\"",
    "Run `memex config` to view or tweak your settings.",
    "You can pipe output: `memex ask \"summarize today\" --raw | pbcopy`",
    "Use `memex ask` for a one-shot question without entering chat.",
    "Try asking: \"Generate a standup update from my activity.\"",
    "Run `memex sync` if your database feels out of date.",
    "Ask: \"What did I learn this week?\" for a learning summary.",
    "Use `memex standup --save` to build a daily work journal.",
    "Ask: \"What projects did I work on today?\" for portfolio evidence.",
    "Ask: \"Summarize my debugging sessions this week\" for pattern review.",
    "Run `memex stats` to see your coding streak.",
]


class TipEngine:
    """Manages contextual tip display with probabilistic showing."""

    def __init__(self, probability: float = 0.25):
        self.probability = probability
        self.shown: Set[int] = set()
        self.response_count = 0

    def maybe_show_tip(self) -> Optional[str]:
        """Maybe return a tip after a response. Skips the first response."""
        self.response_count += 1

        if self.response_count <= 1:
            return None

        if random.random() > self.probability:
            return None

        return self._pick_tip()

    def force_tip(self) -> Optional[str]:
        """Return a tip immediately (for /tips command)."""
        return self._pick_tip()

    def _pick_tip(self) -> Optional[str]:
        """Pick a random unshown tip."""
        available = [i for i in range(len(TIPS)) if i not in self.shown]

        if not available:
            self.shown.clear()
            available = list(range(len(TIPS)))

        idx = random.choice(available)
        self.shown.add(idx)
        return TIPS[idx]


_engine: Optional[TipEngine] = None


def get_tip_engine() -> TipEngine:
    """Get or create the singleton TipEngine."""
    global _engine
    if _engine is None:
        _engine = TipEngine()
    return _engine
