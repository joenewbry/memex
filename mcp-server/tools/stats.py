#!/usr/bin/env python3
"""
Stats Tool for Flow MCP Server

Provides statistics about OCR data and system status.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def now() -> datetime:
    """Get current timezone-aware datetime in local timezone."""
    return datetime.now().astimezone()


class StatsTool:
    """Tool for getting Flow system statistics."""
    
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
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive Flow system statistics."""
        try:
            logger.info("Getting Flow system statistics...")
            
            # Get OCR files
            ocr_files = list(self.ocr_data_dir.glob("*.json"))
            total_files = len(ocr_files)
            
            if total_files == 0:
                return {
                    "ocr_files": {
                        "count": 0,
                        "directory": str(self.ocr_data_dir)
                    },
                    "date_range": None,
                    "unique_screens": 0,
                    "total_text_length": 0,
                    "avg_text_length": 0,
                    "chroma_collection": {
                        "name": "screen_ocr_history",
                        "status": "no_data"
                    },
                    "last_updated": now().isoformat()
                }
            
            # Sample files for analysis (use more recent files)
            ocr_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            sample_size = min(500, total_files)  # Larger sample for better stats
            sample_files = ocr_files[:sample_size]
            
            total_text_length = 0
            unique_screens = set()
            timestamps = []
            valid_files = 0
            content_files = 0  # Files with meaningful content
            
            for file_path in sample_files:
                data = self._read_ocr_file(file_path)
                if not data:
                    continue
                
                valid_files += 1
                text_length = data.get('text_length', 0)
                total_text_length += text_length
                
                if text_length > 10:  # Consider 10+ chars as meaningful content
                    content_files += 1
                
                unique_screens.add(data.get('screen_name', 'unknown'))
                timestamps.append(data.get('timestamp', ''))
            
            # Calculate date range
            valid_timestamps = [ts for ts in timestamps if ts]
            date_range = None
            if valid_timestamps:
                try:
                    dates = []
                    for ts in valid_timestamps:
                        if 'T' in ts:
                            if ts.endswith('Z'):
                                ts = ts[:-1] + '+00:00'
                        dates.append(datetime.fromisoformat(ts))
                    
                    if dates:
                        earliest = min(dates)
                        latest = max(dates)
                        date_range = {
                            "earliest": earliest.isoformat(),
                            "latest": latest.isoformat(),
                            "span_days": (latest - earliest).days,
                            "span_hours": round((latest - earliest).total_seconds() / 3600, 1)
                        }
                except Exception as e:
                    logger.warning(f"Error parsing timestamps for date range: {e}")
            
            # Try to get ChromaDB status
            chroma_status = await self._get_chroma_status()
            
            # Calculate activity metrics
            activity_rate = 0
            if date_range and date_range["span_hours"] > 0:
                activity_rate = round(total_files / date_range["span_hours"], 2)
            
            content_percentage = round((content_files / valid_files) * 100) if valid_files > 0 else 0
            
            stats = {
                "ocr_files": {
                    "count": total_files,
                    "directory": str(self.ocr_data_dir),
                    "valid_files": valid_files,
                    "content_files": content_files,
                    "content_percentage": content_percentage
                },
                "date_range": date_range,
                "unique_screens": len(unique_screens),
                "screen_names": sorted(list(unique_screens)),
                "text_analysis": {
                    "total_text_length": total_text_length,
                    "avg_text_length": total_text_length // valid_files if valid_files > 0 else 0,
                    "total_words": sum(data.get('word_count', 0) for data in [self._read_ocr_file(f) for f in sample_files[:100]] if data),
                },
                "activity_metrics": {
                    "captures_per_hour": activity_rate,
                    "sample_size": valid_files,
                    "total_files_analyzed": sample_size
                },
                "chroma_collection": chroma_status,
                "system_info": {
                    "workspace_root": str(self.workspace_root),
                    "ocr_directory": str(self.ocr_data_dir),
                    "directory_exists": self.ocr_data_dir.exists()
                },
                "last_updated": now().isoformat()
            }
            
            logger.info(f"Statistics generated: {total_files} files, {len(unique_screens)} screens, {content_percentage}% with content")
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "error": str(e),
                "ocr_files": {"count": 0},
                "last_updated": now().isoformat()
            }
    
    def _resolve_chroma_url(self) -> tuple:
        """Derive ChromaDB URL and collection name from instance config."""
        host, port, collection = "localhost", 8000, "screen_ocr_history"
        try:
            import json as _json
            inst_path = Path.home() / ".memex" / "instance.json"
            if inst_path.exists():
                with open(inst_path) as f:
                    data = _json.load(f)
                mode = data.get("hosting_mode", "local")
                instance_name = data.get("instance_name", "")
                if instance_name:
                    collection = f"{instance_name}_ocr_history"
                if mode == "jetson":
                    host = data.get("jetson_host", host)
                    port = data.get("jetson_chroma_port", port)
                elif mode == "remote":
                    host = data.get("remote_host", host)
                    port = data.get("remote_chroma_port", port)
        except Exception:
            pass
        return f"http://{host}:{port}", collection

    async def _get_chroma_status(self) -> Dict[str, Any]:
        """Get ChromaDB collection status."""
        try:
            import httpx

            url, collection_name = self._resolve_chroma_url()

            # Try to connect to ChromaDB
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{url}/api/v1/heartbeat", timeout=2.0)
                if response.status_code != 200:
                    return {
                        "name": collection_name,
                        "status": "server_unavailable",
                        "error": f"ChromaDB server returned {response.status_code}"
                    }

                # Server is running, try to get collection info
                return {
                    "name": collection_name,
                    "status": "server_running",
                    "server_url": url,
                    "note": "Server is accessible - detailed collection stats require ChromaDB client"
                }

        except Exception as e:
            return {
                "name": collection_name,
                "status": "unavailable",
                "error": str(e)
            }
