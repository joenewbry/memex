#!/usr/bin/env python3
"""
Vector Search Tool for Flow MCP Server
Provides vector search with intelligent windowing.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)


class VectorSearchTool:
    """Tool for vector search across time with windowing."""
    
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.ocr_data_dir = workspace_root / "refinery" / "data" / "ocr"
        self.chroma_client = None
        self.collection = None
        
        # Try to initialize ChromaDB client
        self._init_chroma()
    
    def _init_chroma(self):
        """Initialize ChromaDB client."""
        try:
            import chromadb

            # Try HTTP client first (server running)
            try:
                self.chroma_client = chromadb.HttpClient(host="localhost", port=8000)
                self.chroma_client.heartbeat()
                logger.info("Connected to ChromaDB server at localhost:8000")
            except Exception:
                # Fall back to persistent client
                chroma_path = self.workspace_root / "refinery" / "chroma"
                self.chroma_client = chromadb.PersistentClient(path=str(chroma_path))
            
            # Try to get the collection
            try:
                self.collection = self.chroma_client.get_collection("screen_ocr_history")
                logger.info("Connected to ChromaDB collection 'screen_ocr_history'")
            except Exception as e:
                logger.warning(f"ChromaDB collection not found: {e}")
                self.collection = None
                
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            self.chroma_client = None
            self.collection = None
    
    async def vector_search_windowed(
        self,
        query: str,
        start_time: str,
        end_time: str,
        max_results: int = 20,
        min_relevance: float = 0.5
    ) -> Dict[str, Any]:
        """
        Perform vector search across time with intelligent windowing.
        
        Args:
            query: Search query (semantic)
            start_time: Start of time range (ISO format)
            end_time: End of time range (ISO format)
            max_results: Maximum windows to return
            min_relevance: Minimum relevance score (0-1)
        """
        try:
            logger.info(f"Vector search with windowing: '{query}' from {start_time} to {end_time}")
            
            # Check if ChromaDB is available
            if not self.collection:
                return {
                    "error": "ChromaDB not available. Using fallback text search.",
                    "tool_name": "vector_search_windowed",
                    "data": [],
                    "fallback_used": True
                }
            
            # Parse time range
            if start_time.count('T') == 0:
                start_dt = datetime.fromisoformat(start_time + "T00:00:00")
            else:
                start_dt = datetime.fromisoformat(start_time)
            
            if end_time.count('T') == 0:
                end_dt = datetime.fromisoformat(end_time + "T23:59:59")
            else:
                end_dt = datetime.fromisoformat(end_time)
            
            if start_dt >= end_dt:
                raise ValueError("Start time must be before end time")
            
            # Calculate window size
            total_hours = (end_dt - start_dt).total_seconds() / 3600
            window_hours = max(1, total_hours / max_results)
            
            logger.info(f"Window size: {window_hours:.1f} hours for {total_hours:.0f} hour range")
            
            # Create windows
            windows = []
            current_time = start_dt
            while current_time < end_dt:
                window_end = min(current_time + timedelta(hours=window_hours), end_dt)
                windows.append({
                    "start": current_time,
                    "end": window_end,
                    "result": None
                })
                current_time = window_end
            
            # Perform vector search for each window
            results = []
            for i, window in enumerate(windows):
                try:
                    # Query ChromaDB with time filter
                    # Note: ChromaDB metadata filtering syntax
                    window_results = self.collection.query(
                        query_texts=[query],
                        n_results=1,  # Get top result per window
                        where={
                            "$and": [
                                {"timestamp": {"$gte": window["start"].timestamp()}},
                                {"timestamp": {"$lt": window["end"].timestamp()}}
                            ]
                        }
                    )
                    
                    # Process results
                    if window_results and window_results["documents"] and window_results["documents"][0]:
                        doc = window_results["documents"][0][0]
                        metadata = window_results["metadatas"][0][0] if window_results["metadatas"] else {}
                        distance = window_results["distances"][0][0] if window_results["distances"] else 1.0
                        
                        # Convert distance to similarity score (0-1, higher is better)
                        relevance = max(0, 1 - distance)
                        
                        if relevance >= min_relevance:
                            results.append({
                                "text": doc,
                                "timestamp": metadata.get("timestamp_iso", metadata.get("timestamp", "")),
                                "screen_name": metadata.get("screen_name", "unknown"),
                                "relevance_score": round(relevance, 3),
                                "window_start": window["start"].isoformat(),
                                "window_end": window["end"].isoformat(),
                                "window_index": i
                            })
                    
                except Exception as e:
                    logger.debug(f"Error querying window {i}: {e}")
                    continue
            
            # Sort by relevance
            results.sort(key=lambda x: x["relevance_score"], reverse=True)
            
            logger.info(f"Found {len(results)} results across {len(windows)} windows")
            
            return {
                "tool_name": "vector_search_windowed",
                "query": query,
                "time_range": {
                    "start_time": start_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                    "duration_hours": round(total_hours, 2)
                },
                "windowing": {
                    "window_size_hours": round(window_hours, 2),
                    "total_windows": len(windows),
                    "windows_with_results": len(results),
                    "empty_windows": len(windows) - len(results)
                },
                "search_params": {
                    "min_relevance": min_relevance,
                    "max_results": max_results
                },
                "summary": {
                    "results_returned": len(results),
                    "avg_relevance": round(sum(r["relevance_score"] for r in results) / len(results), 3) if results else 0,
                    "unique_screens": list(set(r["screen_name"] for r in results))
                },
                "results": results
            }
            
        except Exception as e:
            logger.error(f"Error in vector search with windowing: {e}")
            return {
                "error": str(e),
                "tool_name": "vector_search_windowed",
                "query": query,
                "results": []
            }

