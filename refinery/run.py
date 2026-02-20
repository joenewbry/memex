#!/usr/bin/env python3
"""
Flow Run Script - Multi-Screen Screenshot Capture and OCR Processing

This script captures screen_ocr_history from all available screens every minute,
processes them with OCR, and saves the data to ChromaDB.

Screen Naming Convention:
- Screen 0: "screen_0" (primary display)
- Screen 1: "screen_1" (secondary display)
- Screen N: "screen_N" (additional displays)

Screenshot files are saved as: {timestamp}_{screen_name}.png
OCR data files are saved as: {timestamp}_{screen_name}.json

All data is stored in ChromaDB collection "screen_ocr_history" for search and analysis.
"""

import asyncio
import logging
import json
import platform
import threading
import time
import requests
import glob
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from PIL import Image
from io import BytesIO

# Import screen detection, chroma client, and OCR
from lib.screen_detection import screen_detector
from lib.chroma_client import chroma_client
from lib.ocr import extract_text, detect_backend, get_backend_info

logger = logging.getLogger(__name__)

# Module-level CLIP embedding function singleton (lazy-loaded, avoids reloading per capture)
_clip_ef_singleton = None
_clip_ef_lock = threading.Lock()


def _get_clip_ef():
    """Get or create the singleton CLIP embedding function."""
    global _clip_ef_singleton
    if _clip_ef_singleton is not None:
        return _clip_ef_singleton
    with _clip_ef_lock:
        if _clip_ef_singleton is not None:
            return _clip_ef_singleton
        try:
            from chromadb.utils.embedding_functions import OpenCLIPEmbeddingFunction
            _clip_ef_singleton = OpenCLIPEmbeddingFunction(
                model_name="ViT-B-32",
                checkpoint="laion2b_s34b_b79k",
            )
            logger.info("CLIP embedding function loaded (ViT-B-32)")
        except ImportError:
            logger.debug("OpenCLIP not installed, multimodal features disabled")
        except Exception as e:
            logger.warning(f"Failed to load CLIP embedding function: {e}")
    return _clip_ef_singleton


def now() -> datetime:
    """Get current timezone-aware datetime in local timezone."""
    return datetime.now().astimezone()


class FlowRunner:
    def __init__(self, capture_interval: int = 60, max_concurrent_ocr: int = 4):
        self.capture_interval = capture_interval  # seconds
        self.max_concurrent_ocr = max_concurrent_ocr
        self.ocr_data_dir = Path("data/ocr")
        self.screenshots_dir = Path("data/images")
        
        self.is_running = False
        self.processing_queue: List[Dict[str, Any]] = []
        self._semaphore = asyncio.Semaphore(max_concurrent_ocr)
        
        # Detect OCR backend (Apple Vision on macOS, Tesseract elsewhere)
        backend = detect_backend()
        backend_info = get_backend_info()
        logger.info(f"OCR backend: {backend_info['description']}")

        # Initialize threading for background OCR processing
        self.ocr_thread = None
        self.ocr_queue = []
        self.ocr_lock = threading.Lock()
    
    async def ensure_directories(self):
        """Ensure output directories exist."""
        self.ocr_data_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured directories exist: {self.ocr_data_dir}, {self.screenshots_dir}")
    
    def process_ocr_background(self, image: Image.Image, screen_name: str, timestamp: str, screenshot_path: str = None):
        """Process OCR in background thread."""
        ocr_success = False
        result = None

        try:
            logger.info(f"[{timestamp}] Processing OCR on thread {threading.current_thread().ident}")

            # Perform OCR (Apple Vision on macOS, Tesseract elsewhere)
            text = extract_text(image)
            text = text.strip()

            result = {
                "screen_name": screen_name,
                "timestamp": timestamp,
                "text": text,
                "text_length": len(text),
                "word_count": len([word for word in text.split() if word.strip()]),
                "source": "flow-runner",
            }

            if screenshot_path:
                result["screenshot_path"] = screenshot_path

            # Save OCR data to JSON file
            timestamp_str = timestamp.replace(':', '-').replace('.', '-')
            ocr_filename = f"{timestamp_str}_{screen_name}.json"
            ocr_filepath = self.ocr_data_dir / ocr_filename

            with open(ocr_filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            logger.info(f"[{timestamp}] OCR data saved as {ocr_filename}")
            logger.info(f"[{timestamp}] Screen: {screen_name}, Text: {len(text)} chars, Words: {result['word_count']}")

            ocr_success = True

        except Exception as error:
            logger.error(f"OCR error for {screen_name}: {error}")
            return  # Exit early if OCR fails

        # Try to store in ChromaDB only if OCR was successful
        # This is separate from OCR processing so ChromaDB failures don't affect OCR
        if ocr_success and result:
            try:
                self.store_in_chroma_sync(result)
            except Exception as chroma_error:
                logger.warning(f"[{timestamp}] ChromaDB storage failed for {screen_name}, but OCR data was saved: {chroma_error}")
    
    def store_in_chroma_sync(self, ocr_data: Dict[str, Any]):
        """Store OCR data in ChromaDB collection 'screen_ocr_history' (synchronous version for background threads)."""
        try:
            import chromadb
            from chromadb.errors import ChromaError
            import requests.exceptions

            # Initialize ChromaDB client
            client = chromadb.HttpClient(host="localhost", port=8000)

            # Get or create the screen_ocr_history collection
            collection = client.get_or_create_collection(
                name="screen_ocr_history",
                metadata={"description": "Screenshot OCR data"}
            )

            # Prepare content for embedding
            content = f"Screen: {ocr_data['screen_name']} Text: {ocr_data['text']}"

            # Prepare metadata
            # Convert timestamp to Unix timestamp for ChromaDB filtering
            timestamp_dt = datetime.fromisoformat(ocr_data["timestamp"])

            screenshot_path = ocr_data.get("screenshot_path", "")

            metadata = {
                "timestamp": timestamp_dt.timestamp(),  # Unix timestamp (float) for filtering
                "timestamp_iso": ocr_data["timestamp"],  # ISO string for display
                "screen_name": ocr_data["screen_name"],
                "text_length": ocr_data["text_length"],
                "word_count": ocr_data["word_count"],
                "source": ocr_data["source"],
                "extracted_text": ocr_data["text"],
                "data_type": "ocr",
                "task_category": "screenshot_ocr",
            }

            if screenshot_path:
                metadata["screenshot_path"] = screenshot_path
                metadata["has_screenshot"] = True

            # Store in ChromaDB
            doc_id = ocr_data["timestamp"] + "_" + ocr_data["screen_name"]

            collection.add(
                documents=[content],
                metadatas=[metadata],
                ids=[doc_id]
            )

            logger.debug(f"Stored OCR data in ChromaDB screen_ocr_history collection: {ocr_data['timestamp']}")

            # Also store in multimodal collection if screenshot exists and CLIP is available
            if screenshot_path:
                self._store_multimodal_sync(client, doc_id, screenshot_path, content, metadata)

        except requests.exceptions.ConnectionError as conn_error:
            # ChromaDB server is not running or not accessible
            raise Exception(f"ChromaDB server connection failed (is server running on localhost:8000?): {conn_error}")
        except ChromaError as chroma_error:
            # ChromaDB-specific errors
            raise Exception(f"ChromaDB operation failed: {chroma_error}")
        except Exception as error:
            # General errors
            raise Exception(f"Unexpected error storing in ChromaDB: {error}")

    def _store_multimodal_sync(self, client, doc_id: str, screenshot_path: str, document: str, metadata: Dict[str, Any]):
        """Store screenshot in multimodal CLIP collection. Failures are non-fatal."""
        try:
            import numpy as np

            clip_ef = _get_clip_ef()
            if clip_ef is None:
                return

            mm_collection = client.get_or_create_collection(
                name="screen_multimodal",
                metadata={"description": "Multimodal screen captures with CLIP embeddings"},
                embedding_function=clip_ef,
            )

            # Load image as numpy array for CLIP image embedding
            img = Image.open(screenshot_path).convert("RGB")
            img_array = np.array(img)

            # ChromaDB multimodal: use images for embedding, store OCR text in metadata
            mm_metadata = dict(metadata)
            mm_metadata["ocr_text"] = document

            mm_collection.add(
                ids=[doc_id],
                images=[img_array],
                metadatas=[mm_metadata],
            )
            logger.debug(f"Stored in multimodal collection: {doc_id}")

        except Exception as error:
            logger.warning(f"Multimodal storage failed (non-fatal): {error}")
    
    async def store_in_chroma(self, ocr_data: Dict[str, Any]):
        """Store OCR data in ChromaDB collection 'screen_ocr_history'."""
        try:
            # Prepare content for embedding
            content = f"Screen: {ocr_data['screen_name']} Text: {ocr_data['text']}"
            
            # Prepare metadata
            # Convert timestamp to Unix timestamp for ChromaDB filtering
            timestamp_dt = datetime.fromisoformat(ocr_data["timestamp"])
            
            metadata = {
                "timestamp": timestamp_dt.timestamp(),  # Unix timestamp (float) for filtering
                "timestamp_iso": ocr_data["timestamp"],  # ISO string for display
                "screen_name": ocr_data["screen_name"],
                "text_length": ocr_data["text_length"],
                "word_count": ocr_data["word_count"],
                "source": ocr_data["source"],
                "extracted_text": ocr_data["text"],
                "data_type": "ocr",
                "task_category": "screenshot_ocr"
            }
            
            # Store in ChromaDB collection 'screen_ocr_history'
            await chroma_client.add_document(
                collection_name="screen_ocr_history",
                doc_id=ocr_data["timestamp"] + "_" + ocr_data["screen_name"],
                content=content,
                metadata=metadata
            )
            
            logger.debug(f"Stored OCR data in ChromaDB screen_ocr_history collection: {ocr_data['timestamp']}")
            
        except Exception as error:
            logger.warning(f"ChromaDB storage failed, but OCR data was already saved: {error}")
            # Don't re-raise the exception - OCR data is safely stored in JSON files
    
    async def load_existing_ocr_data(self):
        """Load existing OCR data from refinery/data/ocr directory into ChromaDB.
        Optimized to only process files newer than the most recent sync timestamp."""
        try:
            logger.info("Checking for existing OCR data to load...")
            
            # Get all JSON files from the OCR data directory
            all_ocr_files = glob.glob(str(self.ocr_data_dir / "*.json"))
            
            if not all_ocr_files:
                logger.info("No existing OCR data found")
                return
            
            # Try to initialize ChromaDB client for bulk operations
            try:
                import chromadb
                from chromadb.errors import ChromaError
                import requests.exceptions
                
                client = chromadb.HttpClient(host="localhost", port=8000)
                
                # Test connection with heartbeat
                try:
                    client.heartbeat()
                except Exception as hb_error:
                    logger.warning(f"ChromaDB heartbeat failed: {hb_error}")
                    logger.info("OCR files are safely stored as JSON files and can be loaded when ChromaDB is available")
                    return
                
                # Get or create the screen_ocr_history collection
                collection = client.get_or_create_collection(
                    name="screen_ocr_history",
                    metadata={"description": "Screenshot OCR data"}
                )
                
            except requests.exceptions.ConnectionError as conn_error:
                logger.warning(f"ChromaDB server not available for bulk loading (is server running on localhost:8000?): {conn_error}")
                logger.info("OCR files are safely stored as JSON files and can be loaded when ChromaDB is available")
                return
            except Exception as chroma_error:
                logger.warning(f"ChromaDB initialization failed for bulk loading: {chroma_error}")
                logger.info("OCR files are safely stored as JSON files and can be loaded when ChromaDB is available")
                return
            
            # Get the most recent timestamp from ChromaDB to optimize sync
            last_sync_timestamp = None
            try:
                # Get collection count to determine if we should optimize
                collection_count = collection.count()
                
                if collection_count > 0:
                    # Get a sample of recent documents to find max timestamp
                    # We get up to 1000 documents (or all if less) and find the max timestamp
                    sample_size = min(1000, collection_count)
                    result = collection.get(limit=sample_size)
                    
                    if result and result.get('metadatas') and len(result['metadatas']) > 0:
                        # Find the maximum timestamp from existing documents
                        timestamps = [
                            meta.get('timestamp') for meta in result['metadatas']
                            if meta and 'timestamp' in meta and isinstance(meta.get('timestamp'), (int, float))
                        ]
                        if timestamps:
                            last_sync_timestamp = max(timestamps)
                            logger.info(f"Found {collection_count} documents in ChromaDB. Most recent timestamp: {datetime.fromtimestamp(last_sync_timestamp).isoformat()}")
                        else:
                            logger.info("ChromaDB collection exists but has no valid timestamp metadata")
                    else:
                        logger.info("ChromaDB collection is empty or new")
                else:
                    logger.info("ChromaDB collection is empty or new")
            except Exception as error:
                logger.debug(f"Could not determine last sync timestamp (will process all files): {error}")
                last_sync_timestamp = None
            
            # Filter files to only process those newer than last sync (or all if no sync exists)
            ocr_files = []
            if last_sync_timestamp is not None:
                # Parse file timestamps and filter
                for file_path in all_ocr_files:
                    try:
                        # Read timestamp from file
                        with open(file_path, 'r', encoding='utf-8') as f:
                            ocr_data = json.load(f)
                        
                        timestamp_str = ocr_data.get("timestamp")
                        if timestamp_str:
                            timestamp_dt = datetime.fromisoformat(timestamp_str)
                            file_timestamp = timestamp_dt.timestamp()
                            
                            # Only include files newer than last sync
                            if file_timestamp > last_sync_timestamp:
                                ocr_files.append((file_path, file_timestamp))
                    except Exception as error:
                        # If we can't parse the file, include it to be safe
                        logger.debug(f"Could not parse timestamp from {file_path}, will process it: {error}")
                        ocr_files.append((file_path, 0))
                
                # Sort by timestamp (oldest first)
                ocr_files.sort(key=lambda x: x[1])
                ocr_files = [f[0] for f in ocr_files]  # Extract just file paths
                
                skipped_count = len(all_ocr_files) - len(ocr_files)
                if skipped_count > 0:
                    logger.info(f"Optimization: Skipping {skipped_count} files already synced (only processing {len(ocr_files)} new files)")
            else:
                # No existing data, process all files
                ocr_files = all_ocr_files
                logger.info(f"Found {len(ocr_files)} OCR files to process (first sync)")
            
            if not ocr_files:
                logger.info("All OCR files are already synced to ChromaDB")
                return
            
            # Process files in smaller batches to avoid overwhelming ChromaDB
            # Reduced batch size to prevent segmentation faults
            batch_size = 10
            total_loaded = 0
            total_skipped = 0
            total_errors = 0
            max_retries = 3
            retry_delay = 2  # seconds
            
            # Build a set of existing IDs for faster duplicate checking (only if collection is small)
            # For large collections, we'll check per document
            existing_ids_cache = set()
            try:
                if last_sync_timestamp is not None:
                    # If we have a last sync timestamp, we can be more confident about duplicates
                    # But still check individual IDs to be safe
                    pass
            except Exception:
                pass
            
            for i in range(0, len(ocr_files), batch_size):
                batch_files = ocr_files[i:i + batch_size]
                
                documents = []
                metadatas = []
                ids = []
                
                # Process files in this batch
                for file_path in batch_files:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            ocr_data = json.load(f)
                        
                        # Create document ID
                        doc_id = ocr_data["timestamp"] + "_" + ocr_data["screen_name"]
                        
                        # Quick check against cache if available
                        if doc_id in existing_ids_cache:
                            total_skipped += 1
                            continue
                        
                        # Check if already exists (query ChromaDB for this specific ID)
                        # We still do this check even with timestamp filtering to handle edge cases
                        try:
                            existing = collection.get(ids=[doc_id])
                            if existing and existing.get('ids') and len(existing['ids']) > 0:
                                existing_ids_cache.add(doc_id)
                                total_skipped += 1
                                continue
                        except Exception:
                            # If check fails, proceed with adding (might be a new document)
                            pass
                        
                        # Prepare content for embedding
                        content = f"Screen: {ocr_data['screen_name']} Text: {ocr_data['text']}"
                        
                        # Prepare metadata
                        # Convert timestamp to Unix timestamp for ChromaDB filtering
                        timestamp_dt = datetime.fromisoformat(ocr_data["timestamp"])
                        
                        metadata = {
                            "timestamp": timestamp_dt.timestamp(),  # Unix timestamp (float) for filtering
                            "timestamp_iso": ocr_data["timestamp"],  # ISO string for display
                            "screen_name": ocr_data["screen_name"],
                            "text_length": ocr_data["text_length"],
                            "word_count": ocr_data["word_count"],
                            "source": ocr_data["source"],
                            "extracted_text": ocr_data["text"],
                            "data_type": "ocr",
                            "task_category": "screenshot_ocr"
                        }
                        
                        documents.append(content)
                        metadatas.append(metadata)
                        ids.append(doc_id)
                        
                    except Exception as error:
                        logger.error(f"Error processing file {file_path}: {error}")
                        total_errors += 1
                        continue
                
                # Bulk add documents to ChromaDB with retry logic
                if documents:
                    retry_count = 0
                    success = False
                    
                    while retry_count < max_retries and not success:
                        try:
                            # Check ChromaDB server health before adding
                            try:
                                client.heartbeat()
                            except Exception as hb_error:
                                logger.warning(f"ChromaDB heartbeat failed, waiting {retry_delay}s before retry: {hb_error}")
                                await asyncio.sleep(retry_delay)
                                retry_count += 1
                                continue
                            
                            collection.add(
                                documents=documents,
                                metadatas=metadatas,
                                ids=ids
                            )
                            total_loaded += len(documents)
                            success = True
                            
                            # Log progress every 100 files or at end
                            progress = i + len(batch_files)
                            if progress % 100 == 0 or progress >= len(ocr_files):
                                logger.info(f"Loaded batch of {len(documents)} documents (progress: {progress}/{len(ocr_files)}, total loaded: {total_loaded}, skipped: {total_skipped})")
                            
                        except Exception as error:
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.warning(f"Error adding batch to ChromaDB (attempt {retry_count}/{max_retries}): {error}")
                                logger.info(f"Waiting {retry_delay * retry_count}s before retry...")
                                await asyncio.sleep(retry_delay * retry_count)  # Exponential backoff
                            else:
                                logger.error(f"Failed to add batch after {max_retries} attempts: {error}")
                                total_errors += len(documents)
                    
                    # Small delay between batches to avoid overwhelming ChromaDB
                    if i + batch_size < len(ocr_files):
                        await asyncio.sleep(0.5)  # 500ms delay between batches
            
            logger.info(f"Bulk loading complete: {total_loaded} documents loaded, {total_skipped} skipped (already existed), {total_errors} errors")
            
        except Exception as error:
            logger.warning(f"Error in bulk loading existing OCR data: {error}")
            logger.info("OCR files are safely stored as JSON files and can be processed individually or loaded later when ChromaDB is available")
    
    async def capture_all_screens(self):
        """Capture screen_ocr_history from all available screens."""
        try:
            # Detect screens if not already done
            if not screen_detector.screens:
                await screen_detector.detect_screens()
            
            if not screen_detector.screens:
                logger.warning("No screens detected")
                return
            
            timestamp = now().isoformat()
            logger.info(f"[{timestamp}] Screenshot taken from {len(screen_detector.screens)} screen(s)")
            
            # Capture each screen separately
            screen_captures = await screen_detector.capture_all_screens_separately()
            
            # Process each capture
            for screen_info, image in screen_captures:
                try:
                    # Save screenshot as JPEG (resized)
                    screenshot_path = None
                    try:
                        # Convert RGBA to RGB (screenshots may have alpha channel)
                        rgb_image = image.convert("RGB")

                        # Resize to max 1280px wide, preserving aspect ratio
                        max_width = 1280
                        if rgb_image.width > max_width:
                            ratio = max_width / rgb_image.width
                            new_size = (max_width, int(rgb_image.height * ratio))
                            resized = rgb_image.resize(new_size, Image.LANCZOS)
                        else:
                            resized = rgb_image

                        timestamp_str = timestamp.replace(':', '-').replace('.', '-')
                        img_filename = f"{timestamp_str}_{screen_info.name}.jpg"
                        screenshot_path = str(self.screenshots_dir / img_filename)
                        resized.save(screenshot_path, "JPEG", quality=70)
                        logger.debug(f"Saved screenshot: {img_filename}")
                    except Exception as img_error:
                        logger.warning(f"Failed to save screenshot for {screen_info.name}: {img_error}")
                        screenshot_path = None

                    # Start background OCR processing
                    ocr_thread = threading.Thread(
                        target=self.process_ocr_background,
                        args=(image, screen_info.name, timestamp, screenshot_path)
                    )
                    ocr_thread.daemon = True
                    ocr_thread.start()

                except Exception as error:
                    logger.error(f"Error processing {screen_info.name}: {error}")
                    continue
            
        except Exception as error:
            logger.error(f"Error in capture_all_screens: {error}")
    
    async def start(self):
        """Start the Flow runner service."""
        try:
            logger.info("Starting Flow Runner service...")
            logger.info(f"Capture interval: {self.capture_interval} seconds")
            logger.info(f"OCR data directory: {self.ocr_data_dir}")
            logger.info(f"Max concurrent OCR: {self.max_concurrent_ocr}")
            
            await self.ensure_directories()
            
            # Configure ChromaDB host from instance.json if present
            _skip_chroma = False
            try:
                import json as _json
                _inst_path = Path.home() / ".memex" / "instance.json"
                if _inst_path.exists():
                    with open(_inst_path) as _f:
                        _inst = _json.load(_f)
                    if _inst.get("hosting_mode") == "jetson":
                        _host = _inst.get("jetson_host", "")
                        _port = _inst.get("jetson_chroma_port", 8000)
                        if _host:
                            chroma_client.host = _host
                            chroma_client.port = _port
                            logger.info(f"ChromaDB target from instance.json: {_host}:{_port}")
            except Exception as e:
                logger.warning(f"Could not load instance.json: {e}")

            # Initialize ChromaDB (non-fatal — capture works without it)
            try:
                await chroma_client.init()
                # Load existing OCR data into ChromaDB
                await self.load_existing_ocr_data()
            except Exception as e:
                logger.warning(f"ChromaDB unavailable, capture-only mode: {e}")
                _skip_chroma = True
            self._skip_chroma = _skip_chroma
            
            # Load existing OCR data into ChromaDB
            await self.load_existing_ocr_data()
            
            # Detect screens
            await screen_detector.detect_screens()
            if not screen_detector.screens:
                raise Exception("No screens detected. Please check your display setup.")
            
            logger.info(f"Detected {len(screen_detector.screens)} screen(s): {[s.name for s in screen_detector.screens]}")
            
            # Initial capture
            await self.capture_all_screens()
            
            # Start continuous capture
            self.is_running = True
            logger.info("Flow Runner service started successfully")
            
            # Main loop
            while self.is_running:
                await asyncio.sleep(self.capture_interval)
                if self.is_running:  # Check again in case we were stopped
                    await self.capture_all_screens()
            
        except Exception as error:
            logger.error(f"Error starting Flow Runner service: {error}")
            raise
    
    async def stop(self):
        """Stop the Flow runner service."""
        logger.info("Stopping Flow Runner service...")
        
        self.is_running = False
        
        logger.info("Flow Runner service stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the Flow runner service."""
        return {
            "running": self.is_running,
            "last_capture": now().isoformat(),
            "interval": self.capture_interval,
            "ocr_data_dir": str(self.ocr_data_dir),
            "available_screens": len(screen_detector.screens) if screen_detector.screens else 0
        }


# Global instance
flow_runner = FlowRunner()


async def main():
    """Main entry point for running the Flow runner."""
    import signal
    
    # Set up logging with file and console handlers
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Create formatters
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # File handler
    file_handler = logging.FileHandler(log_dir / "screen-capture.log")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Flag to track shutdown
    shutdown_event = asyncio.Event()
    
    # Handle shutdown signals
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal")
        # Set the shutdown event to break the main loop
        shutdown_event.set()
        # Also stop the flow runner
        flow_runner.is_running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start the flow runner in a background task
        runner_task = asyncio.create_task(flow_runner.start())
        
        # Wait for either shutdown signal or runner to complete
        done, pending = await asyncio.wait(
            [runner_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # If shutdown was triggered, stop the runner
        if shutdown_event.is_set():
            logger.info("Shutdown signal received, stopping Flow Runner...")
            await flow_runner.stop()
            
            # Cancel the runner task if it's still running
            if not runner_task.done():
                runner_task.cancel()
                try:
                    await runner_task
                except asyncio.CancelledError:
                    pass
            
            # Cancel any pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("Flow Runner service stopped")
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        await flow_runner.stop()
    except Exception as error:
        logger.error(f"Fatal error: {error}")
        await flow_runner.stop()
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
