#!/usr/bin/env python3
"""
Vector Search Tool for Memex Prometheus Server
Adapted for multi-instance deployment with configurable ChromaDB settings.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VectorSearchTool:
    """Tool for vector search across time with windowing."""

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

    async def vector_search_windowed(self, query: str, start_time: str, end_time: str,
                                     max_results: int = 20, min_relevance: float = 0.5) -> Dict[str, Any]:
        try:
            if not self.collection:
                return {
                    "error": "ChromaDB not available",
                    "tool_name": "vector_search_windowed", "results": [],
                }

            start_dt = datetime.fromisoformat(start_time + "T00:00:00" if 'T' not in start_time else start_time)
            end_dt = datetime.fromisoformat(end_time + "T23:59:59" if 'T' not in end_time else end_time)

            if start_dt >= end_dt:
                raise ValueError("Start time must be before end time")

            total_hours = (end_dt - start_dt).total_seconds() / 3600
            window_hours = max(1, total_hours / max_results)

            windows = []
            current_time = start_dt
            while current_time < end_dt:
                window_end = min(current_time + timedelta(hours=window_hours), end_dt)
                windows.append({"start": current_time, "end": window_end})
                current_time = window_end

            results = []
            for i, window in enumerate(windows):
                try:
                    window_results = self.collection.query(
                        query_texts=[query], n_results=1,
                        where={
                            "$and": [
                                {"timestamp": {"$gte": window["start"].timestamp()}},
                                {"timestamp": {"$lt": window["end"].timestamp()}},
                            ]
                        },
                    )
                    if window_results and window_results["documents"] and window_results["documents"][0]:
                        doc = window_results["documents"][0][0]
                        metadata = window_results["metadatas"][0][0] if window_results["metadatas"] else {}
                        distance = window_results["distances"][0][0] if window_results["distances"] else 1.0
                        relevance = max(0, 1 - distance)
                        if relevance >= min_relevance:
                            screenshot_path = metadata.get("screenshot_path", "")
                            results.append({
                                "text": doc,
                                "timestamp": metadata.get("timestamp_iso", metadata.get("timestamp", "")),
                                "screen_name": metadata.get("screen_name", "unknown"),
                                "relevance_score": round(relevance, 3),
                                "window_start": window["start"].isoformat(),
                                "window_end": window["end"].isoformat(),
                                "window_index": i,
                                "screenshot_path": screenshot_path,
                                "has_screenshot": bool(screenshot_path),
                            })
                except Exception as e:
                    logger.debug(f"Error querying window {i}: {e}")
                    continue

            results.sort(key=lambda x: x["relevance_score"], reverse=True)

            return {
                "tool_name": "vector_search_windowed",
                "query": query,
                "time_range": {
                    "start_time": start_dt.isoformat(), "end_time": end_dt.isoformat(),
                    "duration_hours": round(total_hours, 2),
                },
                "windowing": {
                    "window_size_hours": round(window_hours, 2),
                    "total_windows": len(windows),
                    "windows_with_results": len(results),
                },
                "results": results,
            }
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
            return {"error": str(e), "tool_name": "vector_search_windowed", "query": query, "results": []}
