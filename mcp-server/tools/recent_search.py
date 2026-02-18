#!/usr/bin/env python3
"""
Recent Search Tool for Flow MCP Server
Finds most recent and relevant information combining vector search with recency scoring.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)


def now() -> datetime:
    """Get current timezone-aware datetime in local timezone."""
    return datetime.now().astimezone()


class RecentSearchTool:
    """Tool for finding most recent and relevant information."""
    
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
    
    def _calculate_recency_score(self, timestamp: str, max_age_days: int = 90) -> float:
        """
        Calculate recency score (0-1) based on how recent the data is.
        More recent = higher score.
        """
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            current_time = now()
            age_days = (current_time - dt).total_seconds() / 86400  # Convert to days
            
            if age_days < 0:
                return 1.0  # Future date (shouldn't happen)
            elif age_days > max_age_days:
                return 0.0  # Too old
            else:
                # Linear decay from 1.0 (today) to 0.0 (max_age_days ago)
                return 1.0 - (age_days / max_age_days)
                
        except Exception as e:
            logger.debug(f"Error calculating recency score: {e}")
            return 0.5  # Default mid-range score
    
    def _calculate_combined_score(
        self,
        relevance: float,
        recency: float,
        recency_weight: float = 0.5
    ) -> float:
        """
        Combine relevance and recency scores.
        
        Args:
            relevance: Vector similarity score (0-1)
            recency: Recency score (0-1)
            recency_weight: Weight for recency (0-1), relevance gets (1 - recency_weight)
        
        Returns:
            Combined score (0-1)
        """
        relevance_weight = 1.0 - recency_weight
        return (relevance * relevance_weight) + (recency * recency_weight)
    
    async def search_recent_relevant(
        self,
        query: str,
        max_results: int = 10,
        initial_days: int = 7,
        max_days: int = 90,
        recency_weight: float = 0.5,
        min_score: float = 0.6
    ) -> Dict[str, Any]:
        """
        Find most recent and relevant information.
        
        Performs expanding window search:
        1. Start with recent window (e.g., last 7 days)
        2. If not enough good matches, expand window
        3. Combine relevance and recency for scoring
        
        Args:
            query: Search query (semantic)
            max_results: Maximum results to return
            initial_days: Initial search window in days
            max_days: Maximum search window if expanding
            recency_weight: Weight for recency (0-1), 0.5 = equal weight
            min_score: Minimum combined score to include result
        """
        try:
            logger.info(f"Recent+relevant search: '{query}', initial_days={initial_days}")
            
            # Check if ChromaDB is available
            if not self.collection:
                return {
                    "error": "ChromaDB not available",
                    "tool_name": "search_recent_relevant",
                    "results": []
                }
            
            current_time = now()
            all_results = []
            search_windows = []
            current_days = initial_days
            
            # Expanding window search
            while current_days <= max_days and len(all_results) < max_results:
                start_time = current_time - timedelta(days=current_days)
                
                logger.info(f"Searching last {current_days} days...")
                search_windows.append(current_days)
                
                try:
                    # Query ChromaDB
                    results = self.collection.query(
                        query_texts=[query],
                        n_results=max_results * 2,  # Get more to filter by combined score
                        where={
                            "timestamp": {"$gte": start_time.timestamp()}
                        }
                    )
                    
                    # Process results
                    if results and results["documents"] and results["documents"][0]:
                        for i in range(len(results["documents"][0])):
                            doc = results["documents"][0][i]
                            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                            distance = results["distances"][0][i] if results["distances"] else 1.0
                            
                            # Convert distance to relevance score
                            relevance = max(0, 1 - distance)
                            
                            # Calculate recency score
                            timestamp = metadata.get("timestamp_iso", metadata.get("timestamp", ""))
                            recency = self._calculate_recency_score(timestamp, max_days)
                            
                            # Calculate combined score
                            combined_score = self._calculate_combined_score(
                                relevance, recency, recency_weight
                            )
                            
                            # Only include if meets minimum score
                            if combined_score >= min_score:
                                result_entry = {
                                    "text": doc,
                                    "timestamp": timestamp,
                                    "screen_name": metadata.get("screen_name", "unknown"),
                                    "relevance_score": round(relevance, 3),
                                    "recency_score": round(recency, 3),
                                    "combined_score": round(combined_score, 3),
                                }

                                if metadata.get("screenshot_path"):
                                    result_entry["screenshot_path"] = metadata["screenshot_path"]
                                    result_entry["has_screenshot"] = True
                                else:
                                    result_entry["has_screenshot"] = False

                                all_results.append(result_entry)
                    
                    # Check if we have enough results
                    if len(all_results) >= max_results:
                        break
                    
                    # Expand window (double each time)
                    if current_days == initial_days:
                        current_days = min(initial_days * 4, max_days)
                    else:
                        current_days = min(current_days * 2, max_days)
                        
                except Exception as e:
                    logger.error(f"Error querying {current_days} day window: {e}")
                    break
            
            # Remove duplicates (by timestamp) and sort by combined score
            seen_timestamps = set()
            unique_results = []
            for result in all_results:
                if result["timestamp"] not in seen_timestamps:
                    seen_timestamps.add(result["timestamp"])
                    unique_results.append(result)
            
            # Sort by combined score (highest first)
            unique_results.sort(key=lambda x: x["combined_score"], reverse=True)
            
            # Limit to max_results
            final_results = unique_results[:max_results]
            
            logger.info(f"Found {len(final_results)} results (searched {search_windows[-1] if search_windows else 0} days)")
            
            return {
                "tool_name": "search_recent_relevant",
                "query": query,
                "search_strategy": {
                    "initial_days": initial_days,
                    "max_days": max_days,
                    "windows_searched": search_windows,
                    "final_window_days": search_windows[-1] if search_windows else 0,
                    "expanding_used": len(search_windows) > 1
                },
                "scoring": {
                    "recency_weight": recency_weight,
                    "relevance_weight": round(1.0 - recency_weight, 2),
                    "min_score": min_score
                },
                "summary": {
                    "results_returned": len(final_results),
                    "avg_combined_score": round(sum(r["combined_score"] for r in final_results) / len(final_results), 3) if final_results else 0,
                    "avg_relevance": round(sum(r["relevance_score"] for r in final_results) / len(final_results), 3) if final_results else 0,
                    "avg_recency": round(sum(r["recency_score"] for r in final_results) / len(final_results), 3) if final_results else 0,
                    "unique_screens": list(set(r["screen_name"] for r in final_results))
                },
                "results": final_results
            }
            
        except Exception as e:
            logger.error(f"Error in recent+relevant search: {e}")
            return {
                "error": str(e),
                "tool_name": "search_recent_relevant",
                "query": query,
                "results": []
            }

