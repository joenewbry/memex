import httpx
import os
from .base import BaseAdapter, Prospect


class XTwitterAdapter(BaseAdapter):
    name = "x_twitter"
    description = "Find job seekers and builders on X/Twitter. Requires Basic API key ($100/mo) for live search — uses mock data without one."
    icon = "twitter"
    categories = ["Job Seekers", "AI/Prompt Engineers", "Build in Public"]

    def get_config_schema(self):
        return {
            "queries": {
                "type": "list",
                "label": "Search queries",
                "default": [
                    "#OpenToWork developer",
                    "#buildinpublic",
                    "laid off software engineer looking",
                    "self-taught developer portfolio",
                    "prompt engineer seeking",
                ],
            },
            "max_results_per_query": {
                "type": "number",
                "label": "Max results per query",
                "default": 20,
            },
            "bearer_token": {
                "type": "password",
                "label": "X API Bearer Token (optional - uses mock data if empty)",
                "default": "",
            },
        }

    async def fetch(self, config: dict) -> list[Prospect]:
        bearer = config.get("bearer_token") or os.environ.get("X_BEARER_TOKEN", "")
        if not bearer:
            return self._mock_data(config)
        return await self._live_fetch(config, bearer)

    async def _live_fetch(self, config: dict, bearer: str) -> list[Prospect]:
        queries = config.get("queries", self.get_config_schema()["queries"]["default"])
        max_per = config.get("max_results_per_query", 20)
        prospects = []
        seen = set()

        async with httpx.AsyncClient(timeout=30) as client:
            for query in queries:
                try:
                    resp = await client.get(
                        "https://api.twitter.com/2/tweets/search/recent",
                        params={
                            "query": f"{query} -is:retweet lang:en",
                            "max_results": min(max_per, 100),
                            "tweet.fields": "author_id,created_at,public_metrics",
                            "expansions": "author_id",
                            "user.fields": "name,username,description,public_metrics,profile_image_url",
                        },
                        headers={"Authorization": f"Bearer {bearer}"},
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    users_map = {}
                    for user in data.get("includes", {}).get("users", []):
                        users_map[user["id"]] = user

                    for tweet in data.get("data", []):
                        author_id = tweet.get("author_id")
                        user = users_map.get(author_id, {})
                        username = user.get("username", "")
                        if username in seen:
                            continue
                        seen.add(username)

                        bio = user.get("description", "")
                        signals = self._extract_signals(bio, tweet.get("text", ""), query)

                        prospects.append(Prospect(
                            source="x_twitter",
                            username=username,
                            display_name=user.get("name", username),
                            profile_url=f"https://x.com/{username}",
                            bio=bio,
                            category=self._categorize(bio, signals, query),
                            signals=signals,
                            raw_data={
                                "tweet_text": tweet.get("text", ""),
                                "tweet_id": tweet.get("id"),
                                "followers": user.get("public_metrics", {}).get("followers_count", 0),
                                "following": user.get("public_metrics", {}).get("following_count", 0),
                                "tweet_likes": tweet.get("public_metrics", {}).get("like_count", 0),
                                "query_matched": query,
                                "created_at": tweet.get("created_at"),
                            },
                        ))
                except httpx.TimeoutException:
                    continue

        return prospects

    def _mock_data(self, config: dict) -> list[Prospect]:
        """Return realistic mock data when no API key is available."""
        mocks = [
            ("sarahcodes_", "Sarah Chen", "Self-taught dev | Day 87 of #100DaysOfCode | Building a habit tracker in React | Previously in marketing | Open to junior roles", "#OpenToWork developer",
             ["bio_mentions_open_to", "self_taught", "career_changer", "tech_react"]),
            ("rustacean_mike", "Mike Okonkwo", "Rust + WebAssembly | Ex-FAANG, laid off Jan 2026 | Building CLI tools in public | DMs open for collab", "laid off software engineer looking",
             ["bio_mentions_laid_off", "senior_level", "tech_rust", "build_in_public"]),
            ("promptcraft_ai", "Jess Rivera", "Prompt engineer & AI workflow designer | I make LLMs do things they shouldn't be able to | Freelance available", "prompt engineer seeking",
             ["freelance_available", "ai_prompt_engineer", "bio_mentions_available"]),
            ("fullstack_nomad", "Alex Petrov", "Digital nomad | Full-stack TS/React/Node | Building SaaS products from Lisbon | #buildinpublic | Portfolio: alexdev.io", "#buildinpublic",
             ["fullstack", "digital_nomad", "build_in_public", "has_website", "tech_typescript"]),
            ("boot2code", "Priya Sharma", "Flatiron grad '25 | Python + Django | Looking for my first role | Love pair programming | She/her", "#OpenToWork developer",
             ["bootcamp_grad", "junior_level", "bio_mentions_looking_for", "tech_python"]),
            ("ml_marcus", "Marcus Johnson", "ML Engineer | PyTorch + Transformers | Fine-tuning LLMs on weekends | Open to contract work | ex-research at university lab", "prompt engineer seeking",
             ["tech_machine_learning", "freelance_available", "senior_level"]),
            ("designdev_kate", "Kate Nakamura", "Design engineer → Full-stack dev | Career changer | Building in Svelte + Go | #100DaysOfCode Day 45", "#buildinpublic",
             ["career_changer", "self_taught", "tech_go", "build_in_public"]),
            ("indie_hacker_tom", "Tom Blackwood", "Indie hacker | 3 shipped products, 0 that make money yet | Currently building an AI writing tool | #buildinpublic", "#buildinpublic",
             ["build_in_public", "indie_hacker", "tech_ai", "has_shipped_products"]),
            ("dao_contrib_sam", "Sam Osei", "DAO contributor | Solidity + React | Built governance tools for 3 DAOs | Seeking full-time web3 role", "#OpenToWork developer",
             ["tech_solidity", "web3", "bio_mentions_seeking", "has_portfolio"]),
            ("junior_jana", "Jana Mueller", "CS student → self-taught web dev | Left academia for tech | Building React apps | Looking for internship/junior role in Berlin", "#OpenToWork developer",
             ["junior_level", "career_changer", "tech_react", "bio_mentions_looking_for"]),
            ("devops_diana", "Diana Reyes", "SRE/DevOps | AWS + Terraform + K8s | Just got laid off from Series B startup | 8 years exp | Open to remote", "laid off software engineer looking",
             ["senior_level", "bio_mentions_laid_off", "tech_devops", "wants_remote"]),
            ("ai_artisan", "Kai Thompson", "AI image generation + workflow automation | Building custom Stable Diffusion pipelines | Freelance open", "prompt engineer seeking",
             ["ai_prompt_engineer", "freelance_available", "tech_ai"]),
            ("react_queen", "Aisha Williams", "React/Next.js specialist | 5 years frontend | Contributor to Radix UI | Exploring new opportunities post-layoff", "laid off software engineer looking",
             ["senior_level", "bio_mentions_laid_off", "tech_react", "open_source_contributor"]),
            ("data_dave", "Dave Kowalski", "Data engineer | Spark + dbt + Snowflake | Ex-fintech | Building a personal data stack in public | Available Q1 2026", "#buildinpublic",
             ["senior_level", "build_in_public", "bio_mentions_available", "tech_data"]),
            ("code_newbie_li", "Li Wei", "Career changer: teacher → developer | Learning Python through building | #100DaysOfCode Day 23 | Documenting everything", "#OpenToWork developer",
             ["career_changer", "self_taught", "junior_level", "tech_python", "build_in_public"]),
        ]

        prospects = []
        for username, name, bio, query, signals in mocks:
            prospects.append(Prospect(
                source="x_twitter",
                username=username,
                display_name=name,
                profile_url=f"https://x.com/{username}",
                bio=bio,
                category=self._categorize(bio, signals, query),
                signals=signals,
                raw_data={
                    "tweet_text": f"[Mock] Based on query: {query}",
                    "followers": 0,
                    "query_matched": query,
                    "is_mock": True,
                },
            ))

        return prospects

    def _extract_signals(self, bio: str, tweet: str, query: str) -> list:
        signals = []
        combined = f"{bio} {tweet}".lower()
        for kw, signal in [
            ("open to", "bio_mentions_open_to"),
            ("looking for", "bio_mentions_looking_for"),
            ("seeking", "bio_mentions_seeking"),
            ("available", "bio_mentions_available"),
            ("laid off", "bio_mentions_laid_off"),
            ("freelance", "freelance_available"),
            ("self-taught", "self_taught"),
            ("bootcamp", "bootcamp_grad"),
            ("career change", "career_changer"),
            ("#buildinpublic", "build_in_public"),
            ("#100daysofcode", "100_days_of_code"),
            ("remote", "wants_remote"),
            ("senior", "senior_level"),
            ("junior", "junior_level"),
        ]:
            if kw in combined:
                signals.append(signal)
        for tech in ["python", "rust", "go ", "typescript", "react", "machine learning", "ai ", "llm", "solidity"]:
            if tech in combined:
                signals.append(f"tech_{tech.strip().replace(' ', '_')}")
        return signals

    def _categorize(self, bio: str, signals: list, query: str) -> str:
        bio_lower = bio.lower()
        if "build_in_public" in signals or "indie_hacker" in signals:
            return "Build in Public"
        if "ai_prompt_engineer" in signals or "prompt engineer" in query.lower():
            return "AI/Prompt Engineer"
        if "career_changer" in signals:
            return "Career Changer"
        if "bootcamp_grad" in signals:
            return "Bootcamp Graduate"
        if "self_taught" in signals:
            return "Self-Taught Developer"
        if "bio_mentions_laid_off" in signals:
            return "Recently Laid Off"
        if "freelance_available" in signals:
            return "Freelancer"
        return "Job Seeker"
