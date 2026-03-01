#!/usr/bin/env python3
"""
Activity Tool for Flow MCP Server

Provides activity timeline and time range summary functionality.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def now() -> datetime:
    """Get current timezone-aware datetime in local timezone."""
    return datetime.now().astimezone()


class ActivityTool:
    """Tool for generating activity timelines and summaries."""
    
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.ocr_data_dir = workspace_root / "refinery" / "data" / "ocr"
        
        # Ensure OCR data directory exists
        self.ocr_data_dir.mkdir(parents=True, exist_ok=True)
    
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
            naive_dt = datetime.fromisoformat(iso_string)
            return naive_dt.astimezone()
            
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
    
    async def activity_graph(
        self,
        days: int = 7,
        grouping: str = "hourly",
        include_empty: bool = True
    ) -> Dict[str, Any]:
        """Generate activity timeline graph data."""
        try:
            logger.info(f"Generating activity graph: {days} days, {grouping} grouping")
            
            # Calculate time range
            end_time = now()
            start_time = end_time - timedelta(days=days)
            
            # Get OCR files
            ocr_files = list(self.ocr_data_dir.glob("*.json"))
            activity_data = []
            processed_files = 0
            
            for file_path in ocr_files:
                try:
                    # Quick timestamp check from filename first
                    file_timestamp = self._parse_filename_timestamp(file_path.name)
                    if not file_timestamp:
                        file_timestamp = datetime.fromtimestamp(file_path.stat().st_mtime).astimezone()
                    
                    # Skip files outside time range
                    if file_timestamp < start_time or file_timestamp > end_time:
                        continue
                    
                    # Read file data
                    data = self._read_ocr_file(file_path)
                    if not data:
                        continue
                    
                    processed_files += 1
                    activity_data.append({
                        "timestamp": data.get("timestamp", file_timestamp.isoformat()),
                        "screen_name": data.get("screen_name", "unknown"),
                        "text_length": data.get("text_length", 0),
                        "word_count": data.get("word_count", 0),
                        "has_content": (data.get("text_length", 0) > 10)  # 10+ chars as content
                    })
                    
                except Exception as e:
                    logger.debug(f"Error processing file {file_path}: {e}")
                    continue
            
            logger.info(f"Processed {processed_files} files, found {len(activity_data)} activities")
            
            # Group data by time period
            grouped_data = {}
            
            for activity in activity_data:
                try:
                    timestamp_str = activity["timestamp"]
                    if 'T' in timestamp_str:
                        if timestamp_str.endswith('Z'):
                            timestamp_str = timestamp_str[:-1] + '+00:00'
                        timestamp = datetime.fromisoformat(timestamp_str)
                    else:
                        timestamp = datetime.fromisoformat(timestamp_str)
                    
                    # Create grouping key
                    if grouping == "daily":
                        key = timestamp.strftime("%Y-%m-%d")
                    else:  # hourly
                        key = timestamp.strftime("%Y-%m-%d %H:00")
                    
                    if key not in grouped_data:
                        grouped_data[key] = {
                            "timestamp": key,
                            "capture_count": 0,
                            "total_text_length": 0,
                            "total_word_count": 0,
                            "screens": set(),
                            "has_content_count": 0
                        }
                    
                    grouped_data[key]["capture_count"] += 1
                    grouped_data[key]["total_text_length"] += activity["text_length"]
                    grouped_data[key]["total_word_count"] += activity["word_count"]
                    grouped_data[key]["screens"].add(activity["screen_name"])
                    
                    if activity["has_content"]:
                        grouped_data[key]["has_content_count"] += 1
                        
                except Exception as e:
                    logger.debug(f"Error grouping activity data: {e}")
                    continue
            
            # Convert to timeline data
            timeline_data = []
            for key, data in grouped_data.items():
                timeline_data.append({
                    "timestamp": key,
                    "capture_count": data["capture_count"],
                    "avg_text_length": data["total_text_length"] // data["capture_count"] if data["capture_count"] > 0 else 0,
                    "avg_word_count": data["total_word_count"] // data["capture_count"] if data["capture_count"] > 0 else 0,
                    "unique_screens": len(data["screens"]),
                    "content_percentage": round((data["has_content_count"] / data["capture_count"]) * 100) if data["capture_count"] > 0 else 0,
                    "screen_names": sorted(list(data["screens"]))
                })
            
            # Fill in empty periods if requested
            if include_empty:
                timeline_data = self._fill_empty_periods(timeline_data, start_time, end_time, grouping)
            
            # Sort by timestamp
            timeline_data.sort(key=lambda x: x["timestamp"])
            
            logger.info(f"Generated timeline with {len(timeline_data)} periods")
            
            return {
                "graph_type": "activity_timeline",
                "time_range": {
                    "start_date": start_time.isoformat(),
                    "end_date": end_time.isoformat(),
                    "days": days
                },
                "grouping": grouping,
                "data_summary": {
                    "total_captures": len(activity_data),
                    "total_periods": len(timeline_data),
                    "active_periods": len([d for d in timeline_data if d["capture_count"] > 0]),
                    "unique_screens": list(set().union(*[d["screen_names"] for d in timeline_data if d["screen_names"]])),
                    "processed_files": processed_files
                },
                "timeline_data": timeline_data,
                "visualization_suggestions": {
                    "chart_types": ["line", "bar", "heatmap"],
                    "recommended_chart": "bar",
                    "x_axis": "timestamp",
                    "y_axis_options": ["capture_count", "avg_text_length", "content_percentage"],
                    "recommended_y_axis": "capture_count",
                    "color_coding": "content_percentage",
                    "tips": [
                        "Use bar chart to show activity levels over time",
                        "Color by content_percentage to highlight productive periods",
                        "Group by daily for longer time ranges, hourly for detailed analysis"
                    ]
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating activity graph: {e}")
            return {
                "error": str(e),
                "graph_type": "activity_timeline",
                "timeline_data": [],
                "time_range": {"days": days, "grouping": grouping}
            }
    
    def _fill_empty_periods(self, timeline_data: List[Dict], start_time: datetime, end_time: datetime, grouping: str) -> List[Dict]:
        """Fill in empty time periods with zero data."""
        try:
            existing_timestamps = {item["timestamp"] for item in timeline_data}
            
            current_time = start_time
            increment = timedelta(days=1) if grouping == "daily" else timedelta(hours=1)
            
            while current_time <= end_time:
                if grouping == "daily":
                    key = current_time.strftime("%Y-%m-%d")
                else:  # hourly
                    key = current_time.strftime("%Y-%m-%d %H:00")
                
                if key not in existing_timestamps:
                    timeline_data.append({
                        "timestamp": key,
                        "capture_count": 0,
                        "avg_text_length": 0,
                        "avg_word_count": 0,
                        "unique_screens": 0,
                        "content_percentage": 0,
                        "screen_names": []
                    })
                
                current_time += increment
            
            return timeline_data
            
        except Exception as e:
            logger.error(f"Error filling empty periods: {e}")
            return timeline_data
    
    async def time_range_summary(
        self,
        start_time: str,
        end_time: str,
        max_results: int = 24,
        include_text: bool = True
    ) -> Dict[str, Any]:
        """Get sampled summary of OCR data over time range."""
        try:
            logger.info(f"Generating time range summary: {start_time} to {end_time}, max_results={max_results}")
            
            # Parse time ranges (ensure timezone-aware)
            if start_time.count('T') == 0:
                start_dt = datetime.fromisoformat(start_time + "T00:00:00").astimezone()
            else:
                start_dt = datetime.fromisoformat(start_time)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.astimezone()

            if end_time.count('T') == 0:
                end_dt = datetime.fromisoformat(end_time + "T23:59:59").astimezone()
            else:
                end_dt = datetime.fromisoformat(end_time)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.astimezone()
            
            if start_dt >= end_dt:
                raise ValueError("Start time must be before end time")
            
            # Get OCR files in time range
            ocr_files = list(self.ocr_data_dir.glob("*.json"))
            filtered_data = []
            
            for file_path in ocr_files:
                try:
                    file_timestamp = self._parse_filename_timestamp(file_path.name)
                    if not file_timestamp:
                        file_timestamp = datetime.fromtimestamp(file_path.stat().st_mtime).astimezone()
                    
                    if start_dt <= file_timestamp <= end_dt:
                        data = self._read_ocr_file(file_path)
                        if data:
                            filtered_data.append({
                                "filename": file_path.name,
                                "timestamp": data.get("timestamp", file_timestamp.isoformat()),
                                "screen_name": data.get("screen_name", "unknown"),
                                "text_length": data.get("text_length", 0),
                                "word_count": data.get("word_count", 0),
                                "text": data.get("text", "") if include_text else None,
                                "has_content": data.get("text_length", 0) > 10
                            })
                            
                except Exception as e:
                    logger.debug(f"Error processing file {file_path}: {e}")
                    continue
            
            # Sort by timestamp
            filtered_data.sort(key=lambda x: datetime.fromisoformat(x["timestamp"]))
            
            # Sample the data if needed
            sampled_data = filtered_data
            sampling_info = {"sampled": False, "total_items": len(filtered_data)}
            
            if len(filtered_data) > max_results:
                sampling_info["sampled"] = True
                sampling_info["step_size"] = len(filtered_data) / max_results
                sampling_info["sampling_method"] = "evenly_distributed"
                
                sampled_data = []
                step = len(filtered_data) / max_results
                
                for i in range(max_results):
                    index = int(i * step)
                    if index < len(filtered_data):
                        sampled_data.append(filtered_data[index])
            
            logger.info(f"Time range summary: {len(filtered_data)} total items, {len(sampled_data)} returned")
            
            return {
                "summary_type": "time_range_sampling",
                "time_range": {
                    "start_time": start_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                    "duration_hours": round((end_dt - start_dt).total_seconds() / 3600, 2)
                },
                "sampling_info": sampling_info,
                "results_summary": {
                    "total_items_in_range": len(filtered_data),
                    "returned_items": len(sampled_data),
                    "total_text_length": sum(item["text_length"] for item in sampled_data),
                    "total_word_count": sum(item["word_count"] for item in sampled_data),
                    "unique_screens": list(set(item["screen_name"] for item in sampled_data)),
                    "content_items": len([item for item in sampled_data if item["has_content"]]),
                    "time_span": {
                        "earliest": sampled_data[0]["timestamp"] if sampled_data else None,
                        "latest": sampled_data[-1]["timestamp"] if sampled_data else None
                    }
                },
                "data": sampled_data
            }
            
        except Exception as e:
            logger.error(f"Error generating time range summary: {e}")
            return {
                "error": str(e),
                "summary_type": "time_range_sampling",
                "time_range": {"start_time": start_time, "end_time": end_time},
                "data": []
            }
