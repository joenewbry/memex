from adapters.base import Prospect


class Ranker:
    """Compute final scores and rank prospects."""

    def __init__(self, weights: dict = None):
        self.weights = weights or {
            "trust_gap": 0.45,
            "reachability": 0.25,
            "relevance": 0.30,
        }

    def rank(self, prospects: list[Prospect]) -> list[Prospect]:
        for p in prospects:
            p.final_score = (
                p.trust_gap_score * self.weights["trust_gap"]
                + p.reachability_score * self.weights["reachability"]
                + p.relevance_score * self.weights["relevance"]
            )
        prospects.sort(key=lambda p: p.final_score, reverse=True)
        return prospects
