#!/usr/bin/env python3
"""
Sampling Tool for Flow MCP Server
Provides flexible time range sampling with intelligent windowing.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

logger = logging.getLogger(__name__)


def now() -> datetime:
    """Get current timezone-aware datetime in local timezone."""
    return datetime.now().astimezone()


class SamplingTool:
    """Tool for flexible time range sampling with smart windowing."""
    
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
    
    def _parse_relative_time(self, time_str: str) -> Optional[datetime]:
        """Parse relative time strings like 'yesterday 9am', 'last week', etc."""
        time_str = time_str.lower().strip()
        current_time = now()
        
        # Handle "yesterday"
        if 'yesterday' in time_str:
            base_date = current_time - timedelta(days=1)
            if '9am' in time_str or '9:00' in time_str:
                return base_date.replace(hour=9, minute=0, second=0, microsecond=0)
            elif '5pm' in time_str or '17:00' in time_str:
                return base_date.replace(hour=17, minute=0, second=0, microsecond=0)
            else:
                return base_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Handle "today"
        if 'today' in time_str:
            if '9am' in time_str or '9:00' in time_str:
                return current_time.replace(hour=9, minute=0, second=0, microsecond=0)
            elif '5pm' in time_str or '17:00' in time_str:
                return current_time.replace(hour=17, minute=0, second=0, microsecond=0)
            else:
                return current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Handle "last week"
        if 'last week' in time_str:
            return current_time - timedelta(days=7)
        
        # If no relative time found, return None
        return None
    
    async def sample_time_range(
        self,
        start_time: str,
        end_time: str,
        max_samples: int = 24,
        min_window_minutes: int = 15,
        include_text: bool = True
    ) -> Dict[str, Any]:
        """
        Sample OCR data over a time range with intelligent windowing.
        
        Args:
            start_time: Start time (ISO format or relative like "yesterday 9am")
            end_time: End time (ISO format or relative like "yesterday 5pm")
            max_samples: Maximum number of samples to return
            min_window_minutes: Minimum window size in minutes
            include_text: Include OCR text in results
        """
        try:
            logger.info(f"Sampling time range: {start_time} to {end_time}, max_samples={max_samples}")
            
            # Parse start time
            start_dt = self._parse_relative_time(start_time)
            if not start_dt:
                if start_time.count('T') == 0:
                    start_dt = datetime.fromisoformat(start_time + "T00:00:00")
                else:
                    start_dt = datetime.fromisoformat(start_time)
            
            # Parse end time
            end_dt = self._parse_relative_time(end_time)
            if not end_dt:
                if end_time.count('T') == 0:
                    end_dt = datetime.fromisoformat(end_time + "T23:59:59")
                else:
                    end_dt = datetime.fromisoformat(end_time)
            
            if start_dt >= end_dt:
                raise ValueError("Start time must be before end time")
            
            # Calculate time range and window size
            total_minutes = (end_dt - start_dt).total_seconds() / 60
            window_minutes = max(min_window_minutes, total_minutes / max_samples)
            
            logger.info(f"Window size: {window_minutes:.1f} minutes for {total_minutes:.0f} minute range")
            
            # Get all OCR files
            ocr_files = list(self.ocr_data_dir.glob("*.json"))
            
            # Create windows
            windows = []
            current_time = start_dt
            while current_time < end_dt:
                window_end = min(current_time + timedelta(minutes=window_minutes), end_dt)
                windows.append({
                    "start": current_time,
                    "end": window_end,
                    "data": None
                })
                current_time = window_end
            
            # Fill windows with first data point in each window
            for file_path in ocr_files:
                file_timestamp = self._parse_filename_timestamp(file_path.name)
                if not file_timestamp:
                    continue
                
                if file_timestamp < start_dt or file_timestamp > end_dt:
                    continue
                
                # Find which window this belongs to
                for window in windows:
                    if window["start"] <= file_timestamp < window["end"]:
                        if window["data"] is None:  # Take first item in window
                            data = self._read_ocr_file(file_path)
                            if data:
                                entry = {
                                    "timestamp": data.get("timestamp", file_timestamp.isoformat()),
                                    "screen_name": data.get("screen_name", "unknown"),
                                    "text_length": data.get("text_length", 0),
                                    "word_count": data.get("word_count", 0),
                                    "text": data.get("text", "") if include_text else None,
                                    "has_content": data.get("text_length", 0) > 10,
                                    "window_start": window["start"].isoformat(),
                                    "window_end": window["end"].isoformat(),
                                }

                                if data.get("screenshot_path"):
                                    entry["screenshot_path"] = data["screenshot_path"]
                                    entry["has_screenshot"] = True
                                else:
                                    entry["has_screenshot"] = False

                                window["data"] = entry
                        break
            
            # Extract results
            results = [w["data"] for w in windows if w["data"] is not None]
            
            logger.info(f"Sampled {len(results)} data points from {len(windows)} windows")
            
            return {
                "tool_name": "sample_time_range",
                "time_range": {
                    "start_time": start_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                    "duration_hours": round(total_minutes / 60, 2)
                },
                "windowing": {
                    "window_size_minutes": round(window_minutes, 2),
                    "total_windows": len(windows),
                    "filled_windows": len(results),
                    "empty_windows": len(windows) - len(results),
                    "strategy": "first_item_per_window"
                },
                "summary": {
                    "samples_returned": len(results),
                    "total_text_length": sum(r["text_length"] for r in results),
                    "total_word_count": sum(r["word_count"] for r in results),
                    "unique_screens": list(set(r["screen_name"] for r in results)),
                    "content_items": len([r for r in results if r["has_content"]])
                },
                "data": results
            }
            
        except Exception as e:
            logger.error(f"Error sampling time range: {e}")
            return {
                "error": str(e),
                "tool_name": "sample_time_range",
                "data": []
            }

