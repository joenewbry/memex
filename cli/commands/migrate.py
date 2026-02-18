"""Migrate command - re-embed existing OCR data into the multimodal CLIP collection."""

import json
from datetime import datetime
from pathlib import Path
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

from cli.display.components import print_header, print_success, print_error, format_number
from cli.display.colors import COLORS
from cli.services.health import HealthService
from cli.config import get_settings

console = Console()


def migrate(
    batch_size: int = typer.Option(50, "--batch-size", "-b", help="Batch size for migration"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be migrated"),
):
    """Migrate existing OCR data into the multimodal CLIP collection.

    Re-embeds all existing OCR entries using the CLIP text encoder so they
    share the same vector space as new screenshot-bearing entries.
    Historical entries won't have images but can still be found via
    cross-modal text queries.
    """
    print_header("Migrate to Multimodal")

    health = HealthService()
    settings = get_settings()

    # Pre-flight checks
    chroma_check = health.check_chroma_server()
    if not chroma_check.running:
        print_error("ChromaDB server not running")
        console.print("  [dim]Start it with: memex start[/dim]")
        console.print()
        return

    try:
        from chromadb.utils.embedding_functions import OpenCLIPEmbeddingFunction
    except ImportError:
        print_error("open-clip-torch not installed")
        console.print("  [dim]Install with: pip install open-clip-torch[/dim]")
        console.print()
        return

    # Scan OCR files
    console.print("  Scanning OCR files...", end=" ")
    ocr_files = sorted(
        settings.ocr_data_path.glob("*.json"),
        key=lambda f: f.name,
    ) if settings.ocr_data_path.exists() else []
    console.print(f"[bold]{format_number(len(ocr_files))}[/bold] found")

    if not ocr_files:
        console.print("  No OCR files to migrate.")
        console.print()
        return

    # Connect to ChromaDB and set up CLIP collection
    try:
        import chromadb

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )

        clip_ef = OpenCLIPEmbeddingFunction(
            model_name="ViT-B-32",
            checkpoint="laion2b_s34b_b79k",
        )

        try:
            mm_collection = client.get_collection(
                name=settings.chroma_multimodal_collection,
                embedding_function=clip_ef,
            )
            existing_count = mm_collection.count()
        except Exception:
            mm_collection = client.create_collection(
                name=settings.chroma_multimodal_collection,
                embedding_function=clip_ef,
            )
            existing_count = 0

        console.print(f"  Multimodal collection: [bold]{format_number(existing_count)}[/bold] existing entries")

    except Exception as e:
        print_error(f"Failed to connect: {e}")
        console.print()
        return

    # Check what already exists
    console.print("  Checking for already-migrated entries...")
    try:
        result = mm_collection.get(include=[])
        existing_ids = set(result["ids"]) if result["ids"] else set()
    except Exception:
        existing_ids = set()

    to_migrate = [f for f in ocr_files if f.stem not in existing_ids]

    if not to_migrate:
        print_success("All entries already migrated!")
        console.print()
        return

    console.print(f"  [bold]{format_number(len(to_migrate))}[/bold] entries to migrate "
                   f"({format_number(len(existing_ids))} already done)")
    console.print()

    if dry_run:
        console.print("  [dim]Dry run — no changes made.[/dim]")
        console.print()
        return

    # Check for images directory
    images_dir = settings.screenshots_data_path

    import numpy as np
    from PIL import Image

    migrated = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("  Migrating...", total=len(to_migrate))

        batch_ids = []
        batch_documents = []
        batch_metadatas = []
        batch_images = []

        for f in to_migrate:
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
                    "has_screenshot": False,
                }

                # Check for matching image
                screenshot_path = data.get("screenshot_path", "")
                img_array = None

                if screenshot_path and Path(screenshot_path).exists():
                    try:
                        img = Image.open(screenshot_path).convert("RGB")
                        img_array = np.array(img)
                        metadata["screenshot_path"] = screenshot_path
                        metadata["has_screenshot"] = True
                    except Exception:
                        pass
                elif images_dir and images_dir.exists():
                    img_path = images_dir / (f.stem + ".jpg")
                    if img_path.exists():
                        try:
                            img = Image.open(img_path).convert("RGB")
                            img_array = np.array(img)
                            metadata["screenshot_path"] = str(img_path)
                            metadata["has_screenshot"] = True
                        except Exception:
                            pass

                batch_ids.append(doc_id)
                batch_documents.append(text)
                batch_metadatas.append(metadata)
                batch_images.append(img_array)

                if len(batch_ids) >= batch_size:
                    count = _flush_batch(mm_collection, batch_ids, batch_documents, batch_metadatas, batch_images)
                    migrated += count
                    errors += len(batch_ids) - count
                    batch_ids, batch_documents, batch_metadatas, batch_images = [], [], [], []

            except Exception:
                errors += 1

            progress.advance(task)

        # Flush remaining
        if batch_ids:
            count = _flush_batch(mm_collection, batch_ids, batch_documents, batch_metadatas, batch_images)
            migrated += count
            errors += len(batch_ids) - count

    console.print()
    if errors > 0:
        console.print(f"  [{COLORS['success']}]✓[/] Migrated {format_number(migrated)} entries")
        console.print(f"  [{COLORS['error']}]✗[/] {format_number(errors)} errors")
    else:
        print_success(f"Migration complete. {format_number(migrated)} entries added to multimodal collection.")
    console.print()


def _flush_batch(collection, ids, documents, metadatas, images):
    """Add a batch to the multimodal collection, splitting image/text entries."""
    try:
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
            collection.add(
                ids=img_ids,
                images=img_arrays,
                documents=img_docs,
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
