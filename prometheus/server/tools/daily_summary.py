#!/usr/bin/env python3
"""
Daily Summary Tool for Memex Prometheus Server
Adapted for multi-instance deployment with configurable paths.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now().astimezone()


PERIODS = [
    ("early_morning", 5, 8),
    ("morning", 8, 12),
    ("afternoon", 12, 17),
    ("evening", 17, 21),
    ("night", 21, 24),
    ("late_night", 0, 5),
]


class DailySummaryTool:
    """Tool for generating a structured summary of a single day's activity."""

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

    def _get_period(self, hour: int) -> str:
        for label, start, end in PERIODS:
            if start <= hour < end:
                return label
        return "late_night"

    def _sample_evenly(self, items: List[Dict], max_samples: int) -> List[Dict]:
        if len(items) <= max_samples:
            return items
        step = len(items) / max_samples
        return [items[int(i * step)] for i in range(max_samples)]

    async def daily_summary(self, date: str = None, include_text: bool = True) -> Dict[str, Any]:
        try:
            if date:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            else:
                target_date = now().date()
                date = target_date.isoformat()

            day_start = datetime.combine(target_date, datetime.min.time())
            day_end = datetime.combine(target_date, datetime.max.time())

            ocr_files = list(self.ocr_data_dir.glob("*.json"))
            captures: List[Dict[str, Any]] = []

            for file_path in ocr_files:
                file_ts = self._parse_filename_timestamp(file_path.name)
                if not file_ts or file_ts < day_start or file_ts > day_end:
                    continue
                data = self._read_ocr_file(file_path)
                if not data:
                    continue
                captures.append({
                    "timestamp": data.get("timestamp", file_ts.isoformat()),
                    "hour": file_ts.hour,
                    "screen_name": data.get("screen_name", "unknown"),
                    "text_length": data.get("text_length", 0),
                    "word_count": data.get("word_count", 0),
                    "text": data.get("text", ""),
                    "screenshot_path": data.get("screenshot_path", ""),
                })

            captures.sort(key=lambda c: c["timestamp"])

            total_captures = len(captures)
            total_words = sum(c["word_count"] for c in captures)
            unique_screens = sorted(set(c["screen_name"] for c in captures))
            active_hours = sorted(set(c["hour"] for c in captures))

            period_buckets: Dict[str, List[Dict]] = {}
            for cap in captures:
                period = self._get_period(cap["hour"])
                period_buckets.setdefault(period, []).append(cap)

            periods_output = []
            for label, start_h, end_h in PERIODS:
                bucket = period_buckets.get(label, [])
                if not bucket:
                    continue
                sampled = self._sample_evenly(bucket, 5)
                sample_data = []
                for s in sampled:
                    entry: Dict[str, Any] = {
                        "timestamp": s["timestamp"],
                        "screen_name": s["screen_name"],
                        "word_count": s["word_count"],
                    }
                    if include_text:
                        text = s["text"]
                        if len(text) > 500:
                            text = text[:500] + "..."
                        entry["text"] = text
                    screenshot_path = s.get("screenshot_path", "")
                    if screenshot_path:
                        entry["screenshot_path"] = screenshot_path
                        entry["has_screenshot"] = True
                    sample_data.append(entry)
                periods_output.append({
                    "period": label,
                    "hours": f"{start_h:02d}:00-{end_h:02d}:00",
                    "capture_count": len(bucket),
                    "unique_screens": sorted(set(b["screen_name"] for b in bucket)),
                    "word_count": sum(b["word_count"] for b in bucket),
                    "samples": sample_data,
                })

            return {
                "tool_name": "daily_summary", "date": date,
                "stats": {
                    "total_captures": total_captures, "total_words": total_words,
                    "unique_screens": unique_screens, "active_hours": active_hours,
                    "active_hour_count": len(active_hours),
                },
                "periods": periods_output,
            }
        except ValueError as e:
            return {"error": f"Invalid date format: {e}. Use YYYY-MM-DD.", "tool_name": "daily_summary"}
        except Exception as e:
            logger.error(f"Error generating daily summary: {e}")
            return {"error": str(e), "tool_name": "daily_summary"}
