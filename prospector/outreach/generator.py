import httpx
import logging

logger = logging.getLogger(__name__)

MEMEX_GITHUB = "https://github.com/joenewbry/memex"


class OutreachGenerator:
    """Generates personalized outreach by doing a deep lookup on each person."""

    async def generate(self, prospect: dict) -> tuple[str, dict]:
        """Returns (message, deep_profile) after researching the person."""
        deep = await self._deep_lookup(prospect)
        message = self._compose(prospect, deep)
        return message, deep

    async def _deep_lookup(self, p: dict) -> dict:
        """Fetch additional info about the person from their public profiles."""
        deep = {"lookups_done": [], "details": {}}

        async with httpx.AsyncClient(timeout=15) as client:
            # GitHub deep lookup
            if p["source"] == "github" or (p.get("raw_data") or {}).get("github_url"):
                username = p["username"] if p["source"] == "github" else None
                github_url = (p.get("raw_data") or {}).get("github_url", "")
                if not username and github_url:
                    username = github_url.rstrip("/").split("/")[-1]
                if username:
                    deep = await self._lookup_github(client, username, deep)

            # HN deep lookup
            if p["source"] == "hackernews":
                deep = await self._lookup_hn(client, p["username"], deep)

        # Determine seniority
        deep["is_senior"] = self._assess_seniority(p, deep)
        return deep

    async def _lookup_github(self, client: httpx.AsyncClient, username: str, deep: dict) -> dict:
        try:
            # Profile
            resp = await client.get(
                f"https://api.github.com/users/{username}",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code == 200:
                profile = resp.json()
                deep["details"]["github"] = {
                    "name": profile.get("name"),
                    "bio": profile.get("bio"),
                    "company": profile.get("company"),
                    "location": profile.get("location"),
                    "public_repos": profile.get("public_repos"),
                    "followers": profile.get("followers"),
                    "blog": profile.get("blog"),
                    "twitter_username": profile.get("twitter_username"),
                    "created_at": profile.get("created_at"),
                }
                deep["lookups_done"].append("github_profile")

            # Top repos
            resp = await client.get(
                f"https://api.github.com/users/{username}/repos",
                params={"sort": "stars", "per_page": 5},
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code == 200:
                repos = resp.json()
                deep["details"]["top_repos"] = [
                    {
                        "name": r.get("name"),
                        "description": r.get("description"),
                        "stars": r.get("stargazers_count"),
                        "language": r.get("language"),
                        "fork": r.get("fork"),
                    }
                    for r in repos if not r.get("fork")
                ][:5]
                deep["lookups_done"].append("github_repos")

            # Recent activity
            resp = await client.get(
                f"https://api.github.com/users/{username}/events/public",
                params={"per_page": 10},
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code == 200:
                events = resp.json()
                event_types = [e.get("type") for e in events[:10]]
                recent_repos = list({e.get("repo", {}).get("name", "") for e in events[:10]})
                deep["details"]["recent_activity"] = {
                    "event_types": event_types,
                    "active_repos": recent_repos[:5],
                }
                deep["lookups_done"].append("github_activity")
        except Exception as e:
            logger.warning(f"GitHub lookup failed for {username}: {e}")
        return deep

    async def _lookup_hn(self, client: httpx.AsyncClient, username: str, deep: dict) -> dict:
        try:
            resp = await client.get(f"https://hacker-news.firebaseio.com/v0/user/{username}.json")
            if resp.status_code == 200:
                user = resp.json()
                if user:
                    deep["details"]["hn"] = {
                        "karma": user.get("karma"),
                        "about": user.get("about", ""),
                        "created": user.get("created"),
                        "submitted_count": len(user.get("submitted", [])),
                    }
                    deep["lookups_done"].append("hn_profile")
        except Exception as e:
            logger.warning(f"HN lookup failed for {username}: {e}")
        return deep

    def _assess_seniority(self, p: dict, deep: dict) -> bool:
        signals = p.get("signals", [])
        if "senior_level" in signals:
            return True
        gh = deep.get("details", {}).get("github", {})
        if gh:
            if (gh.get("followers") or 0) > 100:
                return True
            if (gh.get("public_repos") or 0) > 30:
                return True
        hn = deep.get("details", {}).get("hn", {})
        if hn:
            if (hn.get("karma") or 0) > 5000:
                return True
        bio = (p.get("bio") or "").lower()
        for kw in ["senior", "staff", "principal", "lead", "architect", "director", "vp ", "cto", "founder", "ex-faang", "10+ years", "8+ years"]:
            if kw in bio:
                return True
        return False

    def _compose(self, p: dict, deep: dict) -> str:
        # Bootcamp partnership outreach is completely different
        if p.get("source") == "bootcamps":
            return self._compose_bootcamp(p)

        first_name = (p.get("display_name") or p.get("username", "")).split()[0]
        source_story = self._source_story(p)
        specific_hook = self._find_specific_hook(p, deep)
        is_senior = deep.get("is_senior", False)

        if is_senior:
            msg = self._compose_senior(first_name, source_story, specific_hook, p, deep)
        else:
            msg = self._compose_standard(first_name, source_story, specific_hook, p, deep)

        return msg.strip()

    def _source_story(self, p: dict) -> str:
        source = p.get("source", "")
        raw = p.get("raw_data", {})
        query = raw.get("query_matched", "")
        thread = raw.get("thread_title", "")

        if source == "github":
            if query:
                return f"found your GitHub profile searching for \"{query}\""
            return "came across your GitHub profile"
        elif source == "hackernews":
            if thread:
                return f"saw your post in the HN \"{thread}\" thread"
            return "found your post in a Hacker News hiring thread"
        elif source == "x_twitter":
            if query:
                return f"found you via a search for \"{query}\" on X"
            return "came across your post on X"
        return "found your profile"

    def _find_specific_hook(self, p: dict, deep: dict) -> str:
        """Find the most interesting specific thing to mention."""
        details = deep.get("details", {})

        # Best repos
        top_repos = details.get("top_repos", [])
        starred = [r for r in top_repos if (r.get("stars") or 0) > 0]
        if starred:
            best = max(starred, key=lambda r: r["stars"])
            desc = f" ({best['description']})" if best.get("description") else ""
            return f"your {best['language'] or 'project'} repo \"{best['name']}\"{desc} caught my eye"

        # Active repos
        activity = details.get("recent_activity", {})
        active_repos = activity.get("active_repos", [])
        if active_repos:
            repo = active_repos[0].split("/")[-1] if "/" in active_repos[0] else active_repos[0]
            return f"I can see you've been actively working on {repo}"

        # HN karma
        hn = details.get("hn", {})
        if hn.get("karma") and hn["karma"] > 1000:
            return f"with {hn['karma']:,} karma on HN you clearly have deep community credibility"

        # Bio details
        bio = p.get("bio", "")
        if bio and len(bio) > 20:
            # Pick something specific from the bio
            for marker in ["building", "working on", "created", "shipped", "launched"]:
                if marker in bio.lower():
                    idx = bio.lower().index(marker)
                    snippet = bio[idx:idx+80].split(".")[0].split(",")[0]
                    return f"saw that you're {snippet.lower()}" if not snippet[0].isupper() else f"saw that you're {snippet[0].lower()}{snippet[1:]}"

        # GitHub profile
        gh = details.get("github", {})
        if gh.get("location"):
            return f"saw you're based in {gh['location']}"

        return ""

    def _compose_senior(self, name: str, source: str, hook: str, p: dict, deep: dict) -> str:
        """Senior people: ask for advice, reference their experience."""
        hook_line = f" — {hook}" if hook else ""
        category = p.get("category", "")

        question = self._pick_question_senior(category, p)

        return f"""Hey {name},

I {source}{hook_line}.

I'm building Memex ({MEMEX_GITHUB}) — continuous screen history that acts as a verifiable trust layer for knowledge workers. Think proof-of-work for everything that happens between git commits.

Given your background, I'd genuinely value your perspective: {question}

— Joe"""

    def _compose_standard(self, name: str, source: str, hook: str, p: dict, deep: dict) -> str:
        """Standard outreach: mention specifics, explain relevance, single question."""
        hook_line = f" — {hook}" if hook else ""
        category = p.get("category", "")

        relevance = self._category_relevance(category)
        question = self._pick_question_standard(category, p)

        return f"""Hey {name},

I {source}{hook_line}.

I'm building Memex ({MEMEX_GITHUB}) — continuous screen history as a verifiable trust layer. {relevance}

{question}

— Joe"""

    def _category_relevance(self, category: str) -> str:
        mapping = {
            "Self-Taught Developer": "For self-taught devs, it's the credential that doesn't exist yet — proof of what you actually build, every day.",
            "Career Changer": "For career changers, it bridges the credibility gap — showing your learning velocity and real problem-solving instead of a missing CS degree.",
            "Build in Public": "For builders in public, it's the difference between curated updates and a continuous, verifiable record of what you actually ship.",
            "AI/Prompt Engineer": "For AI-native roles where there's no standard credential yet, it captures your actual workflow with LLMs as proof of expertise.",
            "Bootcamp Graduate": "For bootcamp grads competing against CS degrees, it levels the field by showing how you actually think through problems.",
            "Recently Laid Off": "It lets you carry a verifiable record of your engineering work between jobs — better than resume bullets or reference calls.",
            "Freelancer": "For freelancers, it replaces the slow trust-building of reviews and portfolios with immediate proof of how you work.",
            "OSS Contributor": "For maintainers, it captures the 90% of work that isn't in the commit log — triaging, debugging, code review, research.",
            "Junior Developer": "For early-career devs, it's a way to stand out by showing your actual problem-solving process, not just finished projects.",
            "Job Seeker": "It gives job seekers a verifiable record of what they actually do — stronger than any resume claim.",
        }
        return mapping.get(category, "It creates a verifiable record of your actual work — stronger than any resume or portfolio.")

    def _pick_question_senior(self, category: str, p: dict) -> str:
        mapping = {
            "Senior Developer": "what would have convinced you to adopt something like this at a previous team?",
            "Recently Laid Off": "when you think about proving your impact at your last role, what evidence do you wish you had?",
            "Build in Public": "do you think verifiable screen history would make build-in-public more credible, or would it kill the curated narrative that works?",
            "AI/Prompt Engineer": "how do you think AI-native roles should credential themselves when the field is moving this fast?",
            "Freelancer": "what's the single biggest trust barrier you face with new clients, and would process transparency help or hurt?",
            "OSS Contributor": "if sponsors could see your full maintenance effort (not just commits), would that change the funding conversation?",
        }
        return mapping.get(category, "what's the biggest trust gap you see in how technical work gets evaluated today?")

    def _pick_question_standard(self, category: str, p: dict) -> str:
        mapping = {
            "Self-Taught Developer": "Would a verifiable record of your daily coding help your job search, or do employers not care about process?",
            "Career Changer": "When you're applying, what's the hardest part of proving you can actually build things?",
            "Build in Public": "Would you share continuous screen history with your audience, or is the curated version more valuable?",
            "AI/Prompt Engineer": "How do you currently prove your AI expertise to potential clients or employers?",
            "Bootcamp Graduate": "What's been the biggest barrier in your job search — skills, credibility, or something else?",
            "Recently Laid Off": "In your current search, what would help you stand out faster?",
            "Freelancer": "What do you currently show new clients to build trust before they've worked with you?",
            "OSS Contributor": "If you could show sponsors the full picture of your maintenance work, would it change things?",
            "Junior Developer": "What's the hardest part of proving what you can do with limited professional experience?",
            "Job Seeker": "What would make the biggest difference in your job search right now?",
            "100DaysOfCode": "Would a verifiable record of your daily progress be useful beyond just the tweets?",
        }
        return mapping.get(category, "Would a verifiable record of your actual work process be useful to you?")

    def _compose_bootcamp(self, p: dict) -> str:
        raw = p.get("raw_data", {})
        name = p.get("display_name", "")
        contact_role = raw.get("contact_role", "the team")
        programs = ", ".join(raw.get("programs", []))
        pitch = raw.get("pitch_angle", "")
        size = raw.get("size", "")
        locations = raw.get("locations", "")

        return f"""Hi,

I'm reaching out to the {contact_role} at {name}. I'm building Memex ({MEMEX_GITHUB}) — open source continuous screen history — and I'd like to offer it completely free to all {name} students.

Here's why I think it's a fit for {name} specifically: {pitch}.

The idea is simple — students run Memex during their {programs} coursework, and it creates a verifiable, timestamped record of their entire learning journey. After graduation, instead of just a certificate and a portfolio, they have proof of how they actually work: debugging sessions, design decisions, the messy real process that employers want to see.

For {name} ({size}, {locations}), this could be a differentiator for your graduates in a competitive market.

Would you be open to a 15-minute call to see if this makes sense as a student tool?

— Joe
joenewbry@gmail.com
{MEMEX_GITHUB}""".strip()
