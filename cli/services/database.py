"""Database service for interacting with ChromaDB."""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from cli.config import get_settings


@dataclass
class SearchResult:
    """A search result from the database."""
    timestamp: datetime
    text: str
    screen_name: str
    word_count: int
    relevance: float = 0.0
    screenshot_path: str = ""


class DatabaseService:
    """Service for interacting with the OCR database."""

    def __init__(self):
        self.settings = get_settings()
        self._client = None
        self._collection = None

    def _get_client(self):
        """Get ChromaDB client (lazy initialization)."""
        if self._client is None:
            try:
                import chromadb
                self._client = chromadb.HttpClient(
                    host=self.settings.chroma_host,
                    port=self.settings.chroma_port,
                )
            except Exception:
                return None
        return self._client

    def _get_collection(self):
        """Get the OCR collection."""
        if self._collection is None:
            client = self._get_client()
            if client:
                try:
                    self._collection = client.get_collection(
                        name=self.settings.chroma_collection
                    )
                except Exception:
                    return None
        return self._collection

    def is_connected(self) -> bool:
        """Check if connected to ChromaDB."""
        client = self._get_client()
        if client is None:
            return False
        try:
            client.heartbeat()
            return True
        except Exception:
            return False

    def get_document_count(self) -> int:
        """Get total document count in ChromaDB."""
        collection = self._get_collection()
        if collection is None:
            return 0
        try:
            return collection.count()
        except Exception:
            return 0

    def search(
        self,
        query: str,
        limit: int = 10,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[SearchResult]:
        """Search for documents matching query."""
        collection = self._get_collection()

        # If ChromaDB not available, fall back to file search
        if collection is None:
            return self._file_search(query, limit, start_date, end_date)

        try:
            # Build where clause for date filtering
            where = None
            if start_date or end_date:
                conditions = []
                if start_date:
                    conditions.append({"timestamp": {"$gte": start_date.timestamp()}})
                if end_date:
                    conditions.append({"timestamp": {"$lte": end_date.timestamp()}})
                if len(conditions) == 1:
                    where = conditions[0]
                else:
                    where = {"$and": conditions}

            results = collection.query(
                query_texts=[query],
                n_results=limit,
                where=where,
                include=["documents", "metadatas", "distances"],
            )

            search_results = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}
                    distance = results["distances"][0][i] if results["distances"] else 0

                    # Parse timestamp
                    ts = meta.get("timestamp_iso", meta.get("timestamp", ""))
                    try:
                        if isinstance(ts, str):
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        else:
                            dt = datetime.fromtimestamp(ts)
                    except Exception:
                        dt = datetime.now()

                    search_results.append(SearchResult(
                        timestamp=dt,
                        text=doc or "",
                        screen_name=meta.get("screen_name", "unknown"),
                        word_count=meta.get("word_count", 0),
                        relevance=1.0 - distance if distance else 0.0,
                        screenshot_path=meta.get("screenshot_path", ""),
                    ))

            return search_results
        except Exception:
            return self._file_search(query, limit, start_date, end_date)

    def _file_search(
        self,
        query: str,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> List[SearchResult]:
        """Fallback file-based search."""
        results = []
        query_lower = query.lower()

        if not self.settings.ocr_data_path.exists():
            return results

        files = sorted(
            self.settings.ocr_data_path.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        for f in files:
            if len(results) >= limit:
                break

            # Date filtering by filename
            file_date = f.stem.split("_")[0] if "_" in f.stem else f.stem
            try:
                file_dt = datetime.strptime(file_date[:10], "%Y-%m-%d")
                if start_date and file_dt.date() < start_date.date():
                    continue
                if end_date and file_dt.date() > end_date.date():
                    continue
            except ValueError:
                pass

            try:
                with open(f, "r") as fp:
                    data = json.load(fp)
                    text = data.get("text", "")
                    if query_lower in text.lower():
                        # Parse timestamp from data or filename
                        ts_str = data.get("timestamp", f.stem)
                        try:
                            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        except Exception:
                            dt = datetime.fromtimestamp(f.stat().st_mtime)

                        results.append(SearchResult(
                            timestamp=dt,
                            text=text,
                            screen_name=data.get("screen_name", "unknown"),
                            word_count=data.get("word_count", len(text.split())),
                            relevance=0.5,  # File search doesn't have relevance scores
                        ))
            except Exception:
                continue

        return results

    def get_capture_count(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> int:
        """Count captures in a date range by file mtime (no JSON parsing, fast)."""
        if not self.settings.ocr_data_path.exists():
            return 0

        count = 0
        for f in self.settings.ocr_data_path.glob("*.json"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if start_date and mtime < start_date:
                    continue
                if end_date and mtime > end_date:
                    continue
                count += 1
            except Exception:
                continue
        return count

    def get_stats(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get statistics for the given date range."""
        if start_date is None:
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if end_date is None:
            end_date = datetime.now()

        stats = {
            "captures": 0,
            "words": 0,
            "screens": set(),
            "hours": {},
        }

        if not self.settings.ocr_data_path.exists():
            return stats

        for f in self.settings.ocr_data_path.glob("*.json"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < start_date or mtime > end_date:
                    continue

                with open(f, "r") as fp:
                    data = json.load(fp)

                stats["captures"] += 1
                stats["words"] += data.get("word_count", 0)
                stats["screens"].add(data.get("screen_name", "unknown"))

                hour = mtime.hour
                if hour not in stats["hours"]:
                    stats["hours"][hour] = 0
                stats["hours"][hour] += 1

            except Exception:
                continue

        stats["screens"] = list(stats["screens"])
        return stats
