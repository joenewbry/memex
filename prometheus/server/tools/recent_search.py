#!/usr/bin/env python3
"""
Recent Search Tool for Memex Prometheus Server
Adapted for multi-instance deployment with configurable ChromaDB settings.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now().astimezone()


class RecentSearchTool:
    """Tool for finding most recent and relevant information."""

    def __init__(self, ocr_data_dir: Path, chroma_host: str = "localhost",
                 chroma_port: int = 8000, chroma_collection: str = "screen_ocr_history"):
        self.ocr_data_dir = ocr_data_dir
        self.chroma_host = chroma_host
        self.chroma_port = chroma_port
        self.chroma_collection_name = chroma_collection
        self.chroma_client = None
        self.collection = None
        self._init_chroma()

    def _init_chroma(self):
        try:
            import chromadb
            self.chroma_client = chromadb.HttpClient(host=self.chroma_host, port=self.chroma_port)
            self.chroma_client.heartbeat()
            self.collection = self.chroma_client.get_collection(self.chroma_collection_name)
            logger.info(f"Connected to ChromaDB collection '{self.chroma_collection_name}'")
        except Exception as e:
            logger.warning(f"ChromaDB not available: {e}")
            self.chroma_client = None
            self.collection = None

    def _calculate_recency_score(self, timestamp: str, max_age_days: int = 90) -> float:
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            age_days = (now() - dt).total_seconds() / 86400
            if age_days < 0:
                return 1.0
            elif age_days > max_age_days:
                return 0.0
            return 1.0 - (age_days / max_age_days)
        except Exception:
            return 0.5

    async def search_recent_relevant(self, query: str, max_results: int = 10,
                                     initial_days: int = 7, max_days: int = 90,
                                     recency_weight: float = 0.5, min_score: float = 0.6) -> Dict[str, Any]:
        try:
            if not self.collection:
                return {"error": "ChromaDB not available", "tool_name": "search_recent_relevant", "results": []}

            current_time = now()
            all_results = []
            search_windows = []
            current_days = initial_days
            relevance_weight = 1.0 - recency_weight

            while current_days <= max_days and len(all_results) < max_results:
                start_time = current_time - timedelta(days=current_days)
                search_windows.append(current_days)

                try:
                    results = self.collection.query(
                        query_texts=[query], n_results=max_results * 2,
                        where={"timestamp": {"$gte": start_time.timestamp()}},
                    )
                    if results and results["documents"] and results["documents"][0]:
                        for i in range(len(results["documents"][0])):
                            doc = results["documents"][0][i]
                            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                            distance = results["distances"][0][i] if results["distances"] else 1.0
                            relevance = max(0, 1 - distance)
                            timestamp = metadata.get("timestamp_iso", metadata.get("timestamp", ""))
                            recency = self._calculate_recency_score(timestamp, max_days)
                            combined_score = (relevance * relevance_weight) + (recency * recency_weight)
                            if combined_score >= min_score:
                                screenshot_path = metadata.get("screenshot_path", "")
                                all_results.append({
                                    "text": doc,
                                    "timestamp": timestamp,
                                    "screen_name": metadata.get("screen_name", "unknown"),
                                    "relevance_score": round(relevance, 3),
                                    "recency_score": round(recency, 3),
                                    "combined_score": round(combined_score, 3),
                                    "screenshot_path": screenshot_path,
                                    "has_screenshot": bool(screenshot_path),
                                })
                    if len(all_results) >= max_results:
                        break
                    if current_days == initial_days:
                        current_days = min(initial_days * 4, max_days)
                    else:
                        current_days = min(current_days * 2, max_days)
                except Exception as e:
                    logger.error(f"Error querying {current_days} day window: {e}")
                    break

            # Deduplicate by timestamp
            seen = set()
            unique_results = []
            for r in all_results:
                if r["timestamp"] not in seen:
                    seen.add(r["timestamp"])
                    unique_results.append(r)

            unique_results.sort(key=lambda x: x["combined_score"], reverse=True)
            final_results = unique_results[:max_results]

            return {
                "tool_name": "search_recent_relevant",
                "query": query,
                "search_strategy": {
                    "initial_days": initial_days, "max_days": max_days,
                    "windows_searched": search_windows,
                },
                "scoring": {"recency_weight": recency_weight, "relevance_weight": round(relevance_weight, 2), "min_score": min_score},
                "summary": {
                    "results_returned": len(final_results),
                    "avg_combined_score": round(sum(r["combined_score"] for r in final_results) / len(final_results), 3) if final_results else 0,
                },
                "results": final_results,
            }
        except Exception as e:
            logger.error(f"Error in recent+relevant search: {e}")
            return {"error": str(e), "tool_name": "search_recent_relevant", "query": query, "results": []}
