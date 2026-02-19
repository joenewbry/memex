#!/usr/bin/env python3
"""
Sampling Tool for Memex Prometheus Server
Adapted for multi-instance deployment with configurable paths.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now().astimezone()


class SamplingTool:
    """Tool for flexible time range sampling with smart windowing."""

    def __init__(self, ocr_data_dir: Path, **kwargs):
        self.ocr_data_dir = ocr_data_dir
        self.ocr_data_dir.mkdir(parents=True, exist_ok=True)

    def _parse_filename_timestamp(self, filename: str) -> Optional[datetime]:
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
        except Exception:
            return None

    def _read_ocr_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
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
        time_str = time_str.lower().strip()
        current_time = now()
        if 'yesterday' in time_str:
            base_date = current_time - timedelta(days=1)
            if '9am' in time_str or '9:00' in time_str:
                return base_date.replace(hour=9, minute=0, second=0, microsecond=0)
            elif '5pm' in time_str or '17:00' in time_str:
                return base_date.replace(hour=17, minute=0, second=0, microsecond=0)
            return base_date.replace(hour=0, minute=0, second=0, microsecond=0)
        if 'today' in time_str:
            if '9am' in time_str or '9:00' in time_str:
                return current_time.replace(hour=9, minute=0, second=0, microsecond=0)
            elif '5pm' in time_str or '17:00' in time_str:
                return current_time.replace(hour=17, minute=0, second=0, microsecond=0)
            return current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        if 'last week' in time_str:
            return current_time - timedelta(days=7)
        return None

    async def sample_time_range(self, start_time: str, end_time: str,
                                max_samples: int = 24, min_window_minutes: int = 15,
                                include_text: bool = True) -> Dict[str, Any]:
        try:
            start_dt = self._parse_relative_time(start_time)
            if not start_dt:
                start_dt = datetime.fromisoformat(start_time + "T00:00:00" if 'T' not in start_time else start_time)
            end_dt = self._parse_relative_time(end_time)
            if not end_dt:
                end_dt = datetime.fromisoformat(end_time + "T23:59:59" if 'T' not in end_time else end_time)

            if start_dt >= end_dt:
                raise ValueError("Start time must be before end time")

            total_minutes = (end_dt - start_dt).total_seconds() / 60
            window_minutes = max(min_window_minutes, total_minutes / max_samples)

            ocr_files = list(self.ocr_data_dir.glob("*.json"))

            windows = []
            current_time = start_dt
            while current_time < end_dt:
                window_end = min(current_time + timedelta(minutes=window_minutes), end_dt)
                windows.append({"start": current_time, "end": window_end, "data": None})
                current_time = window_end

            for file_path in ocr_files:
                file_timestamp = self._parse_filename_timestamp(file_path.name)
                if not file_timestamp or file_timestamp < start_dt or file_timestamp > end_dt:
                    continue
                for window in windows:
                    if window["start"] <= file_timestamp < window["end"] and window["data"] is None:
                        data = self._read_ocr_file(file_path)
                        if data:
                            screenshot_path = data.get("screenshot_path", "")
                            window["data"] = {
                                "timestamp": data.get("timestamp", file_timestamp.isoformat()),
                                "screen_name": data.get("screen_name", "unknown"),
                                "text_length": data.get("text_length", 0),
                                "word_count": data.get("word_count", 0),
                                "text": data.get("text", "") if include_text else None,
                                "has_content": data.get("text_length", 0) > 10,
                                "window_start": window["start"].isoformat(),
                                "window_end": window["end"].isoformat(),
                                "screenshot_path": screenshot_path,
                                "has_screenshot": bool(screenshot_path),
                            }
                        break

            results = [w["data"] for w in windows if w["data"] is not None]

            return {
                "tool_name": "sample_time_range",
                "time_range": {
                    "start_time": start_dt.isoformat(), "end_time": end_dt.isoformat(),
                    "duration_hours": round(total_minutes / 60, 2),
                },
                "windowing": {
                    "window_size_minutes": round(window_minutes, 2),
                    "total_windows": len(windows), "filled_windows": len(results),
                },
                "summary": {
                    "samples_returned": len(results),
                    "unique_screens": list(set(r["screen_name"] for r in results)),
                },
                "data": results,
            }
        except Exception as e:
            logger.error(f"Error sampling time range: {e}")
            return {"error": str(e), "tool_name": "sample_time_range", "data": []}
