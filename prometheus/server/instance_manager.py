#!/usr/bin/env python3
"""
Instance Manager for Memex Prometheus Server

Manages multiple FlowMCPServer instances, one per Memex source laptop.
Each instance has its own data directory, ChromaDB collection, and tool set.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.search import SearchTool
from tools.stats import StatsTool
from tools.activity import ActivityTool
from tools.system import SystemTool
from tools.sampling import SamplingTool
from tools.vector_search import VectorSearchTool
from tools.recent_search import RecentSearchTool
from tools.daily_summary import DailySummaryTool

logger = logging.getLogger(__name__)


@dataclass
class InstanceConfig:
    """Configuration for a single Memex instance."""
    name: str
    data_dir: Path
    chroma_collection: str
    chroma_host: str = "localhost"
    chroma_port: int = 8000


class MemexInstance:
    """A single Memex instance with its own tools and data."""

    def __init__(self, config: InstanceConfig):
        self.config = config
        self.name = config.name
        self.ocr_data_dir = config.data_dir / "ocr"
        self._chroma_collection = None

    def get_chroma_collection(self):
        """Get the ChromaDB collection for this instance (lazy-initialized)."""
        if self._chroma_collection is None:
            import chromadb
            client = chromadb.HttpClient(
                host=self.config.chroma_host,
                port=self.config.chroma_port,
            )
            self._chroma_collection = client.get_or_create_collection(
                name=self.config.chroma_collection,
            )
        return self._chroma_collection

        tool_kwargs = {
            "ocr_data_dir": self.ocr_data_dir,
            "chroma_host": config.chroma_host,
            "chroma_port": config.chroma_port,
            "chroma_collection": config.chroma_collection,
        }

        self.search_tool = SearchTool(**tool_kwargs)
        self.stats_tool = StatsTool(**tool_kwargs)
        self.activity_tool = ActivityTool(ocr_data_dir=self.ocr_data_dir)
        self.system_tool = SystemTool(instance_name=config.name, **tool_kwargs)
        self.sampling_tool = SamplingTool(ocr_data_dir=self.ocr_data_dir)
        self.vector_search_tool = VectorSearchTool(**tool_kwargs)
        self.recent_search_tool = RecentSearchTool(**tool_kwargs)
        self.daily_summary_tool = DailySummaryTool(ocr_data_dir=self.ocr_data_dir)

        self.tools = {
            "search-screenshots": self.search_tool,
            "what-can-i-do": self.system_tool,
            "get-stats": self.stats_tool,
            "activity-graph": self.activity_tool,
            "time-range-summary": self.activity_tool,
            "sample-time-range": self.sampling_tool,
            "vector-search-windowed": self.vector_search_tool,
            "search-recent-relevant": self.recent_search_tool,
            "daily-summary": self.daily_summary_tool,
        }

        logger.info(f"Instance '{config.name}' initialized with {len(self.tools)} tools, data_dir={self.ocr_data_dir}")

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return MCP tool definitions for this instance."""
        return [
            {
                "name": "search-screenshots",
                "description": f"[{self.name.upper()}] Search OCR data from screenshots with optional filtering by date range.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for the OCR text content"},
                        "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD format, optional)"},
                        "end_date": {"type": "string", "description": "End date (YYYY-MM-DD format, optional)"},
                        "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10},
                        "data_type": {"type": "string", "enum": ["ocr"], "description": "Filter by data type"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "what-can-i-do",
                "description": f"[{self.name.upper()}] Get information about available capabilities",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "get-stats",
                "description": f"[{self.name.upper()}] Get statistics about OCR data and ChromaDB collection",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "activity-graph",
                "description": f"[{self.name.upper()}] Generate activity timeline graph data",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "Number of days (default: 7)", "default": 7},
                        "grouping": {"type": "string", "enum": ["hourly", "daily"], "default": "hourly"},
                        "include_empty": {"type": "boolean", "default": True},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "time-range-summary",
                "description": f"[{self.name.upper()}] Get sampled summary over a time range",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_time": {"type": "string", "description": "Start time (ISO format or YYYY-MM-DD)"},
                        "end_time": {"type": "string", "description": "End time (ISO format or YYYY-MM-DD)"},
                        "max_results": {"type": "integer", "default": 24},
                        "include_text": {"type": "boolean", "default": True},
                    },
                    "required": ["start_time", "end_time"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "sample-time-range",
                "description": f"[{self.name.upper()}] Flexible time range sampling with windowing",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_time": {"type": "string", "description": "Start time (ISO or relative like 'yesterday 9am')"},
                        "end_time": {"type": "string", "description": "End time (ISO or relative like 'yesterday 5pm')"},
                        "max_samples": {"type": "integer", "default": 24},
                        "min_window_minutes": {"type": "integer", "default": 15},
                        "include_text": {"type": "boolean", "default": True},
                    },
                    "required": ["start_time", "end_time"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "vector-search-windowed",
                "description": f"[{self.name.upper()}] Semantic vector search across time with windowing",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (semantic)"},
                        "start_time": {"type": "string", "description": "Start of time range (ISO format)"},
                        "end_time": {"type": "string", "description": "End of time range (ISO format)"},
                        "max_results": {"type": "integer", "default": 20},
                        "min_relevance": {"type": "number", "default": 0.5},
                    },
                    "required": ["query", "start_time", "end_time"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "search-recent-relevant",
                "description": f"[{self.name.upper()}] Find most recent and relevant information with combined scoring",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (semantic)"},
                        "max_results": {"type": "integer", "default": 10},
                        "initial_days": {"type": "integer", "default": 7},
                        "max_days": {"type": "integer", "default": 90},
                        "recency_weight": {"type": "number", "default": 0.5},
                        "min_score": {"type": "number", "default": 0.6},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "daily-summary",
                "description": f"[{self.name.upper()}] Get structured daily summary grouped by time periods",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Date in YYYY-MM-DD format (default: today)"},
                        "include_text": {"type": "boolean", "default": True},
                    },
                    "additionalProperties": False,
                },
            },
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool by name with given arguments."""
        if name not in self.tools:
            raise ValueError(f"Unknown tool: {name}")

        tool = self.tools[name]

        if name == "search-screenshots":
            return await tool.search_screenshots(
                query=arguments["query"],
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                limit=arguments.get("limit", 10),
                data_type=arguments.get("data_type"),
            )
        elif name == "what-can-i-do":
            return await tool.what_can_i_do()
        elif name == "get-stats":
            return await tool.get_stats()
        elif name == "activity-graph":
            return await tool.activity_graph(
                days=arguments.get("days", 7),
                grouping=arguments.get("grouping", "hourly"),
                include_empty=arguments.get("include_empty", True),
            )
        elif name == "time-range-summary":
            return await tool.time_range_summary(
                start_time=arguments["start_time"],
                end_time=arguments["end_time"],
                max_results=arguments.get("max_results", 24),
                include_text=arguments.get("include_text", True),
            )
        elif name == "sample-time-range":
            return await tool.sample_time_range(
                start_time=arguments["start_time"],
                end_time=arguments["end_time"],
                max_samples=arguments.get("max_samples", 24),
                min_window_minutes=arguments.get("min_window_minutes", 15),
                include_text=arguments.get("include_text", True),
            )
        elif name == "vector-search-windowed":
            return await tool.vector_search_windowed(
                query=arguments["query"],
                start_time=arguments["start_time"],
                end_time=arguments["end_time"],
                max_results=arguments.get("max_results", 20),
                min_relevance=arguments.get("min_relevance", 0.5),
            )
        elif name == "search-recent-relevant":
            return await tool.search_recent_relevant(
                query=arguments["query"],
                max_results=arguments.get("max_results", 10),
                initial_days=arguments.get("initial_days", 7),
                max_days=arguments.get("max_days", 90),
                recency_weight=arguments.get("recency_weight", 0.5),
                min_score=arguments.get("min_score", 0.6),
            )
        elif name == "daily-summary":
            return await tool.daily_summary(
                date=arguments.get("date"),
                include_text=arguments.get("include_text", True),
            )
        else:
            raise ValueError(f"Tool {name} not implemented")


class InstanceManager:
    """Manages all Memex instances."""

    def __init__(self, data_base_dir: str, chroma_host: str = "localhost",
                 chroma_port: int = 8000, instances: Optional[List[str]] = None):
        self.data_base_dir = Path(data_base_dir)
        self.chroma_host = chroma_host
        self.chroma_port = chroma_port
        self.instances: Dict[str, MemexInstance] = {}

        instance_names = instances or ["personal", "walmart", "alaska"]
        for name in instance_names:
            config = InstanceConfig(
                name=name,
                data_dir=self.data_base_dir / name,
                chroma_collection=f"{name}_ocr_history",
                chroma_host=chroma_host,
                chroma_port=chroma_port,
            )
            self.instances[name] = MemexInstance(config)

        logger.info(f"InstanceManager initialized with {len(self.instances)} instances: {list(self.instances.keys())}")

    def get_instance(self, name: str) -> Optional[MemexInstance]:
        return self.instances.get(name)

    def list_instances(self) -> List[str]:
        return list(self.instances.keys())
