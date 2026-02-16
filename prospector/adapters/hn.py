import httpx
import re
from .base import BaseAdapter, Prospect

HN_ALGOLIA = "https://hn.algolia.com/api/v1"


class HackerNewsAdapter(BaseAdapter):
    name = "hackernews"
    description = "Find job seekers and hiring startups from HN Who's Hiring monthly threads"
    icon = "hackernews"
    categories = ["Startup Hiring", "Job Seekers", "Developer Communities"]

    def get_config_schema(self):
        return {
            "thread_type": {
                "type": "select",
                "label": "Thread type",
                "options": ["Who wants to be hired?", "Who is hiring?", "Freelancer? Seeking freelancer?"],
                "default": "Who wants to be hired?",
            },
            "months_back": {
                "type": "number",
                "label": "Months to search back",
                "default": 2,
            },
            "max_results": {
                "type": "number",
                "label": "Max results per thread",
                "default": 50,
            },
        }

    async def fetch(self, config: dict) -> list[Prospect]:
        thread_type = config.get("thread_type", "Who wants to be hired?")
        months_back = config.get("months_back", 2)
        max_results = config.get("max_results", 50)
        prospects = []

        async with httpx.AsyncClient(timeout=30) as client:
            # Use the whoishiring bot's posts — these are the official monthly threads
            thread_keyword = thread_type.split("?")[0].strip()
            resp = await client.get(
                f"{HN_ALGOLIA}/search_by_date",
                params={
                    "tags": "ask_hn,author_whoishiring",
                    "hitsPerPage": 20,
                },
            )
            if resp.status_code != 200:
                return prospects

            all_threads = resp.json().get("hits", [])

            # Filter to matching thread type
            matching = [t for t in all_threads if thread_keyword.lower() in (t.get("title") or "").lower()]
            threads = matching[:months_back]

            if not threads:
                return prospects

            for thread in threads:
                story_id = thread.get("objectID")
                thread_title = thread.get("title", "")
                if not story_id:
                    continue

                # Get comments from this thread
                comment_resp = await client.get(
                    f"{HN_ALGOLIA}/search",
                    params={
                        "tags": f"comment,story_{story_id}",
                        "hitsPerPage": max_results,
                    },
                )
                if comment_resp.status_code != 200:
                    continue

                comments = comment_resp.json().get("hits", [])

                for comment in comments:
                    text = comment.get("comment_text") or ""
                    author = comment.get("author") or "unknown"

                    if len(text) < 50:
                        continue

                    signals = []
                    text_lower = text.lower()

                    if "remote" in text_lower:
                        signals.append("wants_remote")
                    if "freelance" in text_lower or "contract" in text_lower:
                        signals.append("freelance_available")
                    if "full-stack" in text_lower or "fullstack" in text_lower:
                        signals.append("fullstack")
                    if "senior" in text_lower or "staff" in text_lower or "principal" in text_lower:
                        signals.append("senior_level")
                    if "junior" in text_lower or "entry" in text_lower or "new grad" in text_lower:
                        signals.append("junior_level")
                    for tech in ["python", "rust", "go ", "golang", "typescript", "react", "machine learning", "ai ", "llm", "kubernetes", "aws"]:
                        if tech in text_lower:
                            signals.append(f"tech_{tech.strip().replace(' ', '_')}")

                    urls = re.findall(r'https?://[^\s<>"\']+', text)
                    github_url = next((u for u in urls if "github.com" in u), None)
                    linkedin_url = next((u for u in urls if "linkedin.com" in u), None)
                    website_url = next((u for u in urls if "github.com" not in u and "linkedin.com" not in u), None)

                    if github_url:
                        signals.append("has_github")
                    if linkedin_url:
                        signals.append("has_linkedin")
                    if website_url:
                        signals.append("has_website")

                    clean_bio = re.sub(r'<[^>]+>', ' ', text)
                    clean_bio = re.sub(r'\s+', ' ', clean_bio).strip()
                    if len(clean_bio) > 500:
                        clean_bio = clean_bio[:500] + "..."

                    prospects.append(Prospect(
                        source="hackernews",
                        username=author,
                        display_name=author,
                        profile_url=f"https://news.ycombinator.com/user?id={author}",
                        bio=clean_bio,
                        category=self._categorize(text_lower, signals, thread_type),
                        signals=signals,
                        raw_data={
                            "thread_title": thread_title,
                            "comment_id": comment.get("objectID"),
                            "github_url": github_url,
                            "linkedin_url": linkedin_url,
                            "website_url": website_url,
                            "thread_type": thread_type,
                            "created_at": comment.get("created_at"),
                        },
                    ))

        return prospects

    def _categorize(self, text: str, signals: list, thread_type: str) -> str:
        if "Who is hiring" in thread_type:
            return "Startup Hiring"
        if "freelance_available" in signals:
            return "Freelancer"
        if "junior_level" in signals:
            return "Junior Developer"
        if "senior_level" in signals:
            return "Senior Developer"
        return "Job Seeker"
