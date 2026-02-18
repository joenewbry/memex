"""Sync command - sync OCR files to ChromaDB."""

import json
from datetime import datetime
from pathlib import Path
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from cli.display.components import print_header, print_success, print_error, format_number
from cli.display.colors import COLORS
from cli.services.health import HealthService
from cli.config import get_settings

console = Console()


def sync(
    force: bool = typer.Option(False, "--force", "-f", help="Re-sync all files"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be synced"),
    batch_size: int = typer.Option(100, "--batch-size", "-b", help="Batch size for syncing"),
    skip_multimodal: bool = typer.Option(False, "--skip-multimodal", help="Skip CLIP multimodal sync"),
):
    """Sync OCR files to ChromaDB."""
    print_header("Sync")

    health = HealthService()
    settings = get_settings()

    # Check ChromaDB is running
    chroma_check = health.check_chroma_server()
    if not chroma_check.running:
        print_error("ChromaDB server not running")
        console.print("  [dim]Start it with: chroma run --host localhost --port 8000[/dim]")
        console.print()
        return

    # Get file counts
    console.print("  Scanning OCR files...", end=" ")
    ocr_files = list(settings.ocr_data_path.glob("*.json")) if settings.ocr_data_path.exists() else []
    console.print(f"[bold]{format_number(len(ocr_files))}[/bold] found")

    # Connect to ChromaDB
    try:
        import chromadb
        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )

        # Get or create collection
        try:
            collection = client.get_collection(name=settings.chroma_collection)
            existing_count = collection.count()
        except Exception:
            collection = client.create_collection(name=settings.chroma_collection)
            existing_count = 0

        console.print(f"  Checking ChromaDB...   [bold]{format_number(existing_count)}[/bold] indexed")

    except ImportError:
        print_error("ChromaDB package not installed")
        console.print("  [dim]Install with: pip install chromadb[/dim]")
        console.print()
        return
    except Exception as e:
        print_error(f"Failed to connect to ChromaDB: {e}")
        console.print()
        return

    # Get existing document IDs
    if force:
        to_sync = ocr_files
        console.print(f"  [dim]Force mode: re-syncing all files[/dim]")
    else:
        # Get IDs already in collection
        console.print("  Checking for missing documents...")
        existing_ids = set()

        if existing_count > 0:
            # Get all IDs in batches
            try:
                result = collection.get(include=[])
                existing_ids = set(result["ids"]) if result["ids"] else set()
            except Exception:
                pass

        # Find files not in collection
        to_sync = []
        for f in ocr_files:
            doc_id = f.stem  # Use filename without extension as ID
            if doc_id not in existing_ids:
                to_sync.append(f)

    if not to_sync:
        print_success("Already in sync!")
        console.print()
        return

    console.print()
    console.print(f"  Syncing [bold]{format_number(len(to_sync))}[/bold] documents...")

    if dry_run:
        console.print()
        console.print("  [dim]Dry run - no changes made[/dim]")
        console.print(f"  [dim]Would sync {len(to_sync)} files[/dim]")
        console.print()
        return

    # Sync in batches
    synced = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("  Syncing...", total=len(to_sync))

        batch_ids = []
        batch_documents = []
        batch_metadatas = []

        for f in to_sync:
            try:
                with open(f, "r") as fp:
                    data = json.load(fp)

                text = data.get("text", "")
                if not text:
                    progress.advance(task)
                    continue

                # Prepare document
                doc_id = f.stem
                timestamp_str = data.get("timestamp", "")

                # Parse timestamp
                try:
                    if timestamp_str:
                        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        timestamp = dt.timestamp()
                    else:
                        timestamp = f.stat().st_mtime
                        dt = datetime.fromtimestamp(timestamp)
                        timestamp_str = dt.isoformat()
                except Exception:
                    timestamp = f.stat().st_mtime
                    timestamp_str = datetime.fromtimestamp(timestamp).isoformat()

                metadata = {
                    "timestamp": timestamp,
                    "timestamp_iso": timestamp_str,
                    "screen_name": data.get("screen_name", "unknown"),
                    "word_count": data.get("word_count", len(text.split())),
                    "text_length": len(text),
                    "data_type": "ocr",
                }

                batch_ids.append(doc_id)
                batch_documents.append(text)
                batch_metadatas.append(metadata)

                # Add batch when full
                if len(batch_ids) >= batch_size:
                    try:
                        collection.add(
                            ids=batch_ids,
                            documents=batch_documents,
                            metadatas=batch_metadatas,
                        )
                        synced += len(batch_ids)
                    except Exception as e:
                        errors += len(batch_ids)

                    batch_ids = []
                    batch_documents = []
                    batch_metadatas = []

            except Exception as e:
                errors += 1

            progress.advance(task)

        # Add remaining batch
        if batch_ids:
            try:
                collection.add(
                    ids=batch_ids,
                    documents=batch_documents,
                    metadatas=batch_metadatas,
                )
                synced += len(batch_ids)
            except Exception:
                errors += len(batch_ids)

    console.print()
    if errors > 0:
        console.print(f"  [{COLORS['success']}]✓[/] Synced {format_number(synced)} documents")
        console.print(f"  [{COLORS['error']}]✗[/] {format_number(errors)} errors")
    else:
        print_success(f"Sync complete. {format_number(synced)} documents added.")

    console.print()

    # Phase 2: Multimodal CLIP sync
    if skip_multimodal:
        return

    _sync_multimodal(client, settings, ocr_files, force, dry_run, batch_size)


def _sync_multimodal(client, settings, ocr_files, force, dry_run, batch_size):
    """Sync OCR files (with optional images) to the multimodal CLIP collection."""
    try:
        from chromadb.utils.embedding_functions import OpenCLIPEmbeddingFunction
    except ImportError:
        console.print("  [dim]Skipping multimodal sync (open-clip-torch not installed)[/dim]")
        console.print()
        return

    console.print(f"  [{COLORS['accent']}]Multimodal sync[/]")

    try:
        clip_ef = OpenCLIPEmbeddingFunction(
            model_name="ViT-B-32",
            checkpoint="laion2b_s34b_b79k",
        )

        try:
            mm_collection = client.get_collection(
                name=settings.chroma_multimodal_collection,
                embedding_function=clip_ef,
            )
            mm_existing_count = mm_collection.count()
        except Exception:
            mm_collection = client.create_collection(
                name=settings.chroma_multimodal_collection,
                embedding_function=clip_ef,
            )
            mm_existing_count = 0

        console.print(f"  Multimodal collection: [bold]{format_number(mm_existing_count)}[/bold] indexed")

    except Exception as e:
        console.print(f"  [{COLORS['error']}]Failed to init CLIP collection:[/] {e}")
        console.print()
        return

    # Determine what needs syncing
    if force:
        mm_to_sync = ocr_files
    else:
        try:
            result = mm_collection.get(include=[])
            mm_existing_ids = set(result["ids"]) if result["ids"] else set()
        except Exception:
            mm_existing_ids = set()

        mm_to_sync = [f for f in ocr_files if f.stem not in mm_existing_ids]

    if not mm_to_sync:
        console.print("  [dim]Multimodal collection already in sync[/dim]")
        console.print()
        return

    console.print(f"  Syncing [bold]{format_number(len(mm_to_sync))}[/bold] to multimodal...")

    if dry_run:
        console.print(f"  [dim]Dry run - would sync {len(mm_to_sync)} entries[/dim]")
        console.print()
        return

    import numpy as np
    from PIL import Image
    from datetime import datetime

    images_dir = settings.screenshots_data_path
    mm_synced = 0
    mm_errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("  Multimodal sync...", total=len(mm_to_sync))

        batch_ids = []
        batch_documents = []
        batch_metadatas = []
        batch_images = []
        has_images_in_batch = False

        for f in mm_to_sync:
            try:
                with open(f, "r") as fp:
                    data = json.load(fp)

                text = data.get("text", "")
                if not text:
                    progress.advance(task)
                    continue

                doc_id = f.stem
                timestamp_str = data.get("timestamp", "")

                try:
                    if timestamp_str:
                        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        timestamp = dt.timestamp()
                    else:
                        timestamp = f.stat().st_mtime
                        dt = datetime.fromtimestamp(timestamp)
                        timestamp_str = dt.isoformat()
                except Exception:
                    timestamp = f.stat().st_mtime
                    timestamp_str = datetime.fromtimestamp(timestamp).isoformat()

                metadata = {
                    "timestamp": timestamp,
                    "timestamp_iso": timestamp_str,
                    "screen_name": data.get("screen_name", "unknown"),
                    "word_count": data.get("word_count", len(text.split())),
                    "text_length": len(text),
                    "data_type": "ocr",
                }

                # Check for matching screenshot
                screenshot_path = data.get("screenshot_path", "")
                img_filename = f.stem + ".jpg"
                img_path = images_dir / img_filename if images_dir.exists() else None

                if screenshot_path and Path(screenshot_path).exists():
                    img_path = Path(screenshot_path)

                if img_path and img_path.exists():
                    try:
                        img = Image.open(img_path).convert("RGB")
                        img_array = np.array(img)
                        batch_images.append(img_array)
                        metadata["screenshot_path"] = str(img_path)
                        metadata["has_screenshot"] = True
                        has_images_in_batch = True
                    except Exception:
                        batch_images.append(None)
                        metadata["has_screenshot"] = False
                else:
                    batch_images.append(None)
                    metadata["has_screenshot"] = False

                batch_ids.append(doc_id)
                batch_documents.append(text)
                batch_metadatas.append(metadata)

                # Flush batch — multimodal batches must be all-image or all-text
                if len(batch_ids) >= batch_size:
                    mm_synced += _flush_multimodal_batch(
                        mm_collection, batch_ids, batch_documents, batch_metadatas, batch_images, has_images_in_batch
                    )
                    batch_ids, batch_documents, batch_metadatas, batch_images = [], [], [], []
                    has_images_in_batch = False

            except Exception:
                mm_errors += 1

            progress.advance(task)

        # Flush remaining
        if batch_ids:
            mm_synced += _flush_multimodal_batch(
                mm_collection, batch_ids, batch_documents, batch_metadatas, batch_images, has_images_in_batch
            )

    console.print()
    if mm_errors > 0:
        console.print(f"  [{COLORS['success']}]✓[/] Multimodal: {format_number(mm_synced)} synced")
        console.print(f"  [{COLORS['error']}]✗[/] {format_number(mm_errors)} errors")
    else:
        print_success(f"Multimodal sync complete. {format_number(mm_synced)} entries added.")
    console.print()


def _flush_multimodal_batch(collection, ids, documents, metadatas, images, has_images):
    """Add a batch to the multimodal collection. Returns count of items added."""
    try:
        # Split into image-bearing and text-only entries
        img_ids, img_docs, img_metas, img_arrays = [], [], [], []
        txt_ids, txt_docs, txt_metas = [], [], []

        for i in range(len(ids)):
            if images[i] is not None:
                img_ids.append(ids[i])
                img_docs.append(documents[i])
                img_metas.append(metadatas[i])
                img_arrays.append(images[i])
            else:
                txt_ids.append(ids[i])
                txt_docs.append(documents[i])
                txt_metas.append(metadatas[i])

        added = 0

        if img_ids:
            # ChromaDB multimodal: images for embedding, OCR text in metadata
            for i, meta in enumerate(img_metas):
                meta["ocr_text"] = img_docs[i]
            collection.add(
                ids=img_ids,
                images=img_arrays,
                metadatas=img_metas,
            )
            added += len(img_ids)

        if txt_ids:
            collection.add(
                ids=txt_ids,
                documents=txt_docs,
                metadatas=txt_metas,
            )
            added += len(txt_ids)

        return added
    except Exception:
        return 0
