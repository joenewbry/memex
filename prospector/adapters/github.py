import httpx
from datetime import datetime, timedelta
from .base import BaseAdapter, Prospect


class GitHubAdapter(BaseAdapter):
    name = "github"
    description = "Find developers on GitHub with trust gaps: sparse commits, no portfolio, career changers. Filters to recently active users only."
    icon = "github"
    categories = ["Developer Communities", "Open Source", "Job Seekers"]

    def get_config_schema(self):
        return {
            "queries": {
                "type": "list",
                "label": "Search queries",
                "default": [
                    "open to work",
                    "looking for work developer",
                    "bootcamp graduate",
                    "career change software",
                    "self-taught developer",
                ],
            },
            "max_results_per_query": {
                "type": "number",
                "label": "Max results per query",
                "default": 20,
            },
            "recency_months": {
                "type": "number",
                "label": "Only users created/updated in last N months",
                "default": 6,
            },
        }

    async def fetch(self, config: dict) -> list[Prospect]:
        queries = config.get("queries", self.get_config_schema()["queries"]["default"])
        max_per = config.get("max_results_per_query", 20)
        recency = config.get("recency_months", 6)
        prospects = []
        seen = set()

        cutoff = (datetime.now() - timedelta(days=recency * 30)).strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=30) as client:
            for query in queries:
                try:
                    # Search users by bio, sorted by most recently joined, filtered by recency
                    resp = await client.get(
                        "https://api.github.com/search/users",
                        params={
                            "q": f"{query} in:bio created:>{cutoff}",
                            "sort": "joined",
                            "order": "desc",
                            "per_page": min(max_per, 30),
                        },
                        headers={"Accept": "application/vnd.github.v3+json"},
                    )
                    if resp.status_code == 403:
                        break  # Rate limited
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    for user in data.get("items", []):
                        login = user["login"]
                        if login in seen:
                            continue
                        seen.add(login)

                        user_resp = await client.get(
                            f"https://api.github.com/users/{login}",
                            headers={"Accept": "application/vnd.github.v3+json"},
                        )
                        if user_resp.status_code == 403:
                            break  # Rate limited
                        if user_resp.status_code != 200:
                            continue
                        profile = user_resp.json()

                        # Skip users who haven't been active recently
                        updated = profile.get("updated_at", "")
                        if updated and updated[:10] < cutoff:
                            continue

                        signals = []
                        bio = profile.get("bio") or ""

                        if profile.get("public_repos", 0) > 0 and profile.get("public_repos", 0) < 10:
                            signals.append("few_public_repos")
                        if not profile.get("company"):
                            signals.append("no_company")
                        if profile.get("hireable"):
                            signals.append("hireable_flag")
                        if profile.get("followers", 0) < 50:
                            signals.append("low_followers")

                        bio_lower = bio.lower()
                        for kw in ["looking for", "open to", "seeking", "available", "hire me", "freelance"]:
                            if kw in bio_lower:
                                signals.append(f"bio_mentions_{kw.replace(' ', '_')}")
                        for kw in ["self-taught", "bootcamp", "career change", "100daysofcode", "#buildinpublic"]:
                            if kw in bio_lower:
                                signals.append(kw.replace("-", "_").replace("#", ""))

                        prospects.append(Prospect(
                            source="github",
                            username=login,
                            display_name=profile.get("name") or login,
                            profile_url=profile["html_url"],
                            bio=bio,
                            category=self._categorize(bio, signals, query),
                            signals=signals,
                            raw_data={
                                "public_repos": profile.get("public_repos", 0),
                                "followers": profile.get("followers", 0),
                                "following": profile.get("following", 0),
                                "company": profile.get("company"),
                                "location": profile.get("location"),
                                "hireable": profile.get("hireable"),
                                "created_at": profile.get("created_at"),
                                "updated_at": profile.get("updated_at"),
                                "query_matched": query,
                            },
                        ))

                except httpx.TimeoutException:
                    continue

        return prospects

    def _categorize(self, bio: str, signals: list, query: str) -> str:
        bio_lower = bio.lower()
        if "bootcamp" in bio_lower or "bootcamp" in query.lower():
            return "Bootcamp Graduate"
        if "self_taught" in signals or "self-taught" in query.lower():
            return "Self-Taught Developer"
        if "career_change" in signals or "career change" in query.lower():
            return "Career Changer"
        if "100daysofcode" in bio_lower:
            return "100DaysOfCode"
        if "buildinpublic" in signals:
            return "Build in Public"
        if "hireable_flag" in signals:
            return "Job Seeker"
        return "Developer"
