#!/usr/bin/env python3
"""
Search Tool for Memex Prometheus Server

Provides search functionality for OCR data from screenshots.
Adapted for multi-instance deployment with configurable paths and ChromaDB settings.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SearchTool:
    """Tool for searching OCR data from screenshots."""

    def __init__(self, ocr_data_dir: Path, chroma_host: str = "localhost",
                 chroma_port: int = 8000, chroma_collection: str = "screen_ocr_history"):
        self.ocr_data_dir = ocr_data_dir
        self.chroma_host = chroma_host
        self.chroma_port = chroma_port
        self.chroma_collection_name = chroma_collection
        self.chroma_client = None
        self.collection = None

        self.ocr_data_dir.mkdir(parents=True, exist_ok=True)
        self._init_chroma()

    def _init_chroma(self):
        """Initialize ChromaDB client."""
        try:
            import chromadb
            self.chroma_client = chromadb.HttpClient(host=self.chroma_host, port=self.chroma_port)
            self.chroma_client.heartbeat()
            self.collection = self.chroma_client.get_collection(self.chroma_collection_name)
            logger.info(f"Connected to ChromaDB collection '{self.chroma_collection_name}' at {self.chroma_host}:{self.chroma_port}")
        except Exception as e:
            logger.warning(f"ChromaDB not available: {e}")
            self.chroma_client = None
            self.collection = None

    def _parse_filename_timestamp(self, filename: str) -> Optional[datetime]:
        """Parse timestamp from OCR filename."""
        try:
            if not filename.endswith('.json'):
                return None
            timestamp_part = filename.split('_')[0]
            parts = timestamp_part.split('T')
            if len(parts) != 2:
                return None
            date_part = parts[0]
            time_part = parts[1]
            time_components = time_part.split('-')
            if len(time_components) < 3:
                return None
            hour, minute = time_components[0], time_components[1]
            if len(time_components) >= 4:
                second = time_components[2]
                microsecond = time_components[3][:6].ljust(6, '0')
            else:
                second_part = time_components[2]
                if '.' in second_part:
                    second, microsecond = second_part.split('.', 1)
                    microsecond = microsecond[:6].ljust(6, '0')
                else:
                    second = second_part
                    microsecond = '000000'
            iso_string = f"{date_part}T{hour}:{minute}:{second}.{microsecond}"
            return datetime.fromisoformat(iso_string)
        except Exception as e:
            logger.debug(f"Error parsing timestamp from filename {filename}: {e}")
            return None

    def _read_ocr_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Read and parse OCR file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if 'timestamp' not in data:
                file_timestamp = self._parse_filename_timestamp(file_path.name)
                if file_timestamp:
                    data['timestamp'] = file_timestamp.isoformat()
                else:
                    data['timestamp'] = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
            data.setdefault('screen_name', 'unknown')
            data.setdefault('text_length', len(data.get('text', '')))
            data.setdefault('word_count', len(data.get('text', '').split()) if data.get('text') else 0)
            data.setdefault('text', '')
            return data
        except Exception as e:
            logger.warning(f"Error reading OCR file {file_path}: {e}")
            return None

    async def search_screenshots(
        self, query: str, start_date: Optional[str] = None,
        end_date: Optional[str] = None, limit: int = 10,
        data_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search OCR data from screenshots."""
        try:
            logger.info(f"Searching: query='{query}', start_date={start_date}, end_date={end_date}, limit={limit}")
            if self.collection:
                return await self._search_chromadb(query, start_date, end_date, limit, data_type)
            else:
                return await self._search_files(query, start_date, end_date, limit, data_type)
        except Exception as e:
            logger.error(f"Error searching OCR data: {e}")
            return {"error": str(e), "query": query, "results": [], "total_found": 0}

    async def _search_chromadb(
        self, query: str, start_date: Optional[str] = None,
        end_date: Optional[str] = None, limit: int = 10,
        data_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search using ChromaDB vector search."""
        try:
            where_filters = []
            if start_date:
                start_dt = datetime.fromisoformat(start_date + "T00:00:00")
                where_filters.append({"timestamp": {"$gte": start_dt.timestamp()}})
            if end_date:
                end_dt = datetime.fromisoformat(end_date + "T23:59:59")
                where_filters.append({"timestamp": {"$lte": end_dt.timestamp()}})
            if data_type and data_type == "ocr":
                where_filters.append({"data_type": "ocr"})

            where_clause = None
            if len(where_filters) > 1:
                where_clause = {"$and": where_filters}
            elif len(where_filters) == 1:
                where_clause = where_filters[0]

            query_results = self.collection.query(
                query_texts=[query], n_results=limit, where=where_clause
            )

            results = []
            if query_results and query_results["documents"] and query_results["documents"][0]:
                for i in range(len(query_results["documents"][0])):
                    doc = query_results["documents"][0][i]
                    metadata = query_results["metadatas"][0][i] if query_results["metadatas"] else {}
                    distance = query_results["distances"][0][i] if query_results["distances"] else 1.0
                    relevance = max(0, 1 - distance)
                    text_preview = metadata.get("extracted_text", doc)[:200]
                    screenshot_path = metadata.get("screenshot_path", "")
                    results.append({
                        "timestamp": metadata.get("timestamp_iso", metadata.get("timestamp", "")),
                        "screen_name": metadata.get("screen_name", "N/A"),
                        "data_type": metadata.get("data_type", "unknown"),
                        "text_length": metadata.get("text_length", 0),
                        "word_count": metadata.get("word_count", 0),
                        "text_preview": text_preview,
                        "relevance": round(relevance, 3),
                        "source": metadata.get("source", "unknown"),
                        "screenshot_path": screenshot_path,
                        "has_screenshot": bool(screenshot_path),
                    })

            return {
                "query": query, "results": results, "total_found": len(results),
                "search_method": "vector_search_chromadb",
                "data_type_filter": data_type or "all",
                "date_range": {"start_date": start_date, "end_date": end_date},
            }
        except Exception as e:
            logger.error(f"Error in ChromaDB search: {e}")
            return await self._search_files(query, start_date, end_date, limit, data_type)

    async def _search_files(
        self, query: str, start_date: Optional[str] = None,
        end_date: Optional[str] = None, limit: int = 10,
        data_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fallback file-based search."""
        try:
            start_dt = datetime.fromisoformat(start_date + "T00:00:00") if start_date else None
            end_dt = datetime.fromisoformat(end_date + "T23:59:59") if end_date else None

            ocr_files = list(self.ocr_data_dir.glob("*.json"))
            ocr_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            results = []
            processed = 0

            for file_path in ocr_files:
                if len(results) >= limit:
                    break
                try:
                    file_timestamp = self._parse_filename_timestamp(file_path.name)
                    if file_timestamp:
                        if start_dt and file_timestamp < start_dt:
                            continue
                        if end_dt and file_timestamp > end_dt:
                            continue
                    data = self._read_ocr_file(file_path)
                    if not data:
                        continue
                    text = data.get('text', '')
                    processed += 1
                    text_lower = text.lower()
                    query_lower = query.lower()
                    if query_lower in text_lower:
                        relevance = text_lower.count(query_lower)
                        idx = text_lower.find(query_lower)
                        context_size = (200 - len(query)) // 2
                        start = max(0, idx - context_size)
                        end = min(len(text), idx + len(query) + context_size)
                        preview = ("..." if start > 0 else "") + text_lower[start:end] + ("..." if end < len(text) else "")
                        screenshot_path = data.get("screenshot_path", "")
                        results.append({
                            "timestamp": data.get("timestamp"),
                            "screen_name": data.get("screen_name", "N/A"),
                            "data_type": "ocr",
                            "text_length": len(text),
                            "word_count": len(text.split()),
                            "text_preview": preview,
                            "relevance": relevance,
                            "source": "file_based_search",
                            "screenshot_path": screenshot_path,
                            "has_screenshot": bool(screenshot_path),
                        })
                except Exception:
                    continue

            results.sort(key=lambda x: x["relevance"], reverse=True)
            return {
                "query": query, "results": results, "total_found": len(results),
                "processed_files": processed, "search_method": "file_based_text_search",
                "data_type_filter": "ocr",
                "date_range": {"start_date": start_date, "end_date": end_date},
            }
        except Exception as e:
            logger.error(f"Error searching OCR data: {e}")
            return {"error": str(e), "query": query, "results": [], "total_found": 0}
