"""Sync command - sync OCR files to ChromaDB (LAN or tunnel)."""

import json
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from cli.display.components import print_header, print_success, print_error, format_number
from cli.display.colors import COLORS
from cli.config import get_settings

console = Console()


def _prepare_document(file_path: Path) -> Optional[dict]:
    """Prepare a document from an OCR JSON file for syncing.

    Handles both old format (extracted_text) and new format (text).
    Returns dict with id, text, metadata, raw_json or None if unusable.
    """
    try:
        with open(file_path, "r") as fp:
            data = json.load(fp)
    except Exception:
        return None

    # Handle both field names
    text = data.get("text", "") or data.get("extracted_text", "") or data.get("summary", "")
    if not text or not text.strip():
        return None

    doc_id = file_path.stem
    timestamp_str = data.get("timestamp", "")

    # Parse timestamp
    try:
        if timestamp_str:
            dt = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
            timestamp = dt.timestamp()
        else:
            timestamp = file_path.stat().st_mtime
            dt = datetime.fromtimestamp(timestamp)
            timestamp_str = dt.isoformat()
    except Exception:
        timestamp = file_path.stat().st_mtime
        timestamp_str = datetime.fromtimestamp(timestamp).isoformat()

    metadata = {
        "timestamp": timestamp,
        "timestamp_iso": timestamp_str,
        "screen_name": data.get("screen_name", "unknown"),
        "word_count": data.get("word_count", len(text.split())),
        "text_length": len(text),
        "data_type": "ocr",
    }

    return {
        "id": doc_id,
        "text": text,
        "metadata": metadata,
        "raw_json": data,
    }


def _check_chroma_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Quick socket check to see if ChromaDB is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _get_tunnel_url(settings) -> Optional[str]:
    """Get the tunnel URL from instance.json config."""
    instance_path = settings.config_dir / "instance.json"
    if not instance_path.exists():
        return None
    try:
        with open(instance_path, "r") as f:
            data = json.load(f)
        return data.get("jetson_tunnel_url") or data.get("tunnel_url")
    except Exception:
        return None


def _get_instance_name(settings) -> str:
    """Get instance name from instance.json config."""
    instance_path = settings.config_dir / "instance.json"
    if not instance_path.exists():
        return "personal"
    try:
        with open(instance_path, "r") as f:
            data = json.load(f)
        return data.get("instance_name", "personal")
    except Exception:
        return "personal"


def _sync_tunnel(tunnel_url: str, instance: str, token: str, files: list[Path],
                 batch_size: int, dry_run: bool, force: bool) -> tuple[int, int]:
    """Sync files through the Cloudflare tunnel. Returns (synced, errors)."""
    import urllib.request
    import urllib.error

    base_url = tunnel_url.rstrip("/")

    # Step 1: Get server-side document IDs for diffing
    if not force:
        console.print("  Fetching server sync status...")
        try:
            req = urllib.request.Request(
                f"{base_url}/{instance}/sync/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                status_data = json.loads(resp.read().decode())
            server_ids = set(status_data.get("ids", []))
            console.print(f"  Server has [bold]{format_number(len(server_ids))}[/bold] documents")
        except urllib.error.HTTPError as e:
            print_error(f"Server sync/status failed: HTTP {e.code}")
            if e.code == 401:
                console.print("  [dim]Check your MEMEX_PROMETHEUS_TOKEN or credentials.json[/dim]")
            return 0, 0
        except Exception as e:
            print_error(f"Failed to reach server: {e}")
            return 0, 0

        # Filter to files not on server
        to_sync = [f for f in files if f.stem not in server_ids]
    else:
        to_sync = files
        console.print("  [dim]Force mode: re-syncing all files[/dim]")

    if not to_sync:
        print_success("Already in sync!")
        console.print()
        return 0, 0

    console.print(f"\n  Syncing [bold]{format_number(len(to_sync))}[/bold] documents via tunnel...")

    if dry_run:
        console.print()
        console.print("  [dim]Dry run - no changes made[/dim]")
        console.print(f"  [dim]Would sync {len(to_sync)} files to {base_url}/{instance}/sync[/dim]")
        console.print()
        return 0, 0

    synced = 0
    errors = 0
    max_retries = 3

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("  Uploading...", total=len(to_sync))

        batch = []
        for f in to_sync:
            doc = _prepare_document(f)
            if doc:
                batch.append(doc)

            if len(batch) >= batch_size:
                ok, err = _send_batch(base_url, instance, token, batch, max_retries)
                synced += ok
                errors += err
                progress.advance(task, advance=len(batch))
                batch = []
            else:
                if not doc:
                    progress.advance(task)

        # Send remaining batch
        if batch:
            ok, err = _send_batch(base_url, instance, token, batch, max_retries)
            synced += ok
            errors += err
            progress.advance(task, advance=len(batch))

    return synced, errors


def _send_batch(base_url: str, instance: str, token: str,
                batch: list[dict], max_retries: int) -> tuple[int, int]:
    """Send a batch of documents to the sync endpoint with retry. Returns (ok, errors)."""
    import urllib.request
    import urllib.error

    payload = json.dumps({"documents": batch}).encode("utf-8")

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                f"{base_url}/{instance}/sync",
                data=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())

            return result.get("indexed", 0), len(result.get("errors", []))
        except urllib.error.HTTPError as e:
            if e.code == 413:
                # Payload too large - split batch in half and retry
                if len(batch) > 1:
                    mid = len(batch) // 2
                    ok1, err1 = _send_batch(base_url, instance, token, batch[:mid], max_retries)
                    ok2, err2 = _send_batch(base_url, instance, token, batch[mid:], max_retries)
                    return ok1 + ok2, err1 + err2
                return 0, len(batch)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return 0, len(batch)
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return 0, len(batch)


def sync(
    force: bool = typer.Option(False, "--force", "-f", help="Re-sync all files"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be synced"),
    batch_size: int = typer.Option(100, "--batch-size", "-b", help="Batch size for syncing"),
    skip_multimodal: bool = typer.Option(False, "--skip-multimodal", help="Skip CLIP multimodal sync"),
    mode: str = typer.Option("auto", "--mode", "-m", help="Sync mode: auto, lan, tunnel"),
):
    """Sync OCR files to ChromaDB."""
    print_header("Sync")

    settings = get_settings()

    # Scan OCR files
    console.print("  Scanning OCR files...", end=" ")
    ocr_files = list(settings.ocr_data_path.glob("*.json")) if settings.ocr_data_path.exists() else []
    console.print(f"[bold]{format_number(len(ocr_files))}[/bold] found")

    if not ocr_files:
        print_error("No OCR files found")
        console.print(f"  [dim]Expected at: {settings.ocr_data_path}[/dim]")
        console.print()
        return

    # Determine sync mode
    tunnel_url = _get_tunnel_url(settings)
    instance_name = _get_instance_name(settings)
    chroma_reachable = False

    if mode in ("auto", "lan"):
        console.print(f"  Checking ChromaDB at {settings.chroma_host}:{settings.chroma_port}...", end=" ")
        chroma_reachable = _check_chroma_reachable(settings.chroma_host, settings.chroma_port)
        if chroma_reachable:
            console.print("[bold green]reachable[/bold green]")
        else:
            console.print("[dim]unreachable[/dim]")

    # Route to the right sync path
    use_tunnel = False
    if mode == "tunnel":
        use_tunnel = True
    elif mode == "lan":
        use_tunnel = False
        if not chroma_reachable:
            print_error(f"ChromaDB not reachable at {settings.chroma_host}:{settings.chroma_port}")
            console.print("  [dim]Try --mode tunnel or --mode auto[/dim]")
            console.print()
            return
    elif mode == "auto":
        if chroma_reachable:
            console.print(f"  [{COLORS['accent']}]Using LAN sync (direct ChromaDB)[/]")
        elif tunnel_url:
            use_tunnel = True
            console.print(f"  [{COLORS['accent']}]Using tunnel sync ({tunnel_url})[/]")
        else:
            print_error("No sync target available")
            console.print("  [dim]ChromaDB unreachable and no tunnel_url in instance.json[/dim]")
            console.print()
            return

    if use_tunnel:
        if not tunnel_url:
            print_error("No tunnel URL configured")
            console.print("  [dim]Set jetson_tunnel_url in ~/.memex/instance.json[/dim]")
            console.print()
            return

        # Get auth token
        from cli.config.credentials import get_prometheus_token
        token = get_prometheus_token()
        if not token:
            print_error("No Prometheus API token found")
            console.print("  [dim]Set MEMEX_PROMETHEUS_TOKEN env var or add 'prometheus' to credentials.json[/dim]")
            console.print()
            return

        console.print(f"  Instance: [bold]{instance_name}[/bold]")
        console.print(f"  Tunnel:   [bold]{tunnel_url}[/bold]")
        console.print()

        synced, errors = _sync_tunnel(tunnel_url, instance_name, token, ocr_files,
                                      batch_size, dry_run, force)

        console.print()
        if errors > 0:
            console.print(f"  [{COLORS['success']}]\u2713[/] Synced {format_number(synced)} documents")
            console.print(f"  [{COLORS['error']}]\u2717[/] {format_number(errors)} errors")
        elif synced > 0:
            print_success(f"Sync complete. {format_number(synced)} documents added.")
        console.print()
        return

    # --- LAN mode: direct ChromaDB sync (original behavior) ---
    from cli.services.health import HealthService
    health = HealthService()

    chroma_check = health.check_chroma_server()
    if not chroma_check.running:
        print_error("ChromaDB server not running")
        console.print("  [dim]Start it with: chroma run --host localhost --port 8000[/dim]")
        console.print()
        return

    # Connect to ChromaDB
    try:
        import chromadb
        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )

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
        console.print("  Checking for missing documents...")
        existing_ids = set()

        if existing_count > 0:
            try:
                result = collection.get(include=[])
                existing_ids = set(result["ids"]) if result["ids"] else set()
            except Exception:
                pass

        to_sync = [f for f in ocr_files if f.stem not in existing_ids]

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
            doc = _prepare_document(f)
            if doc:
                batch_ids.append(doc["id"])
                batch_documents.append(doc["text"])
                batch_metadatas.append(doc["metadata"])

                if len(batch_ids) >= batch_size:
                    try:
                        collection.add(
                            ids=batch_ids,
                            documents=batch_documents,
                            metadatas=batch_metadatas,
                        )
                        synced += len(batch_ids)
                    except Exception:
                        errors += len(batch_ids)

                    batch_ids = []
                    batch_documents = []
                    batch_metadatas = []

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
        console.print(f"  [{COLORS['success']}]\u2713[/] Synced {format_number(synced)} documents")
        console.print(f"  [{COLORS['error']}]\u2717[/] {format_number(errors)} errors")
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
                doc = _prepare_document(f)
                if not doc:
                    progress.advance(task)
                    continue

                doc_id = doc["id"]
                text = doc["text"]
                metadata = doc["metadata"]

                # Check for matching screenshot
                screenshot_path = doc["raw_json"].get("screenshot_path", "")
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

                if len(batch_ids) >= batch_size:
                    mm_synced += _flush_multimodal_batch(
                        mm_collection, batch_ids, batch_documents, batch_metadatas, batch_images, has_images_in_batch
                    )
                    batch_ids, batch_documents, batch_metadatas, batch_images = [], [], [], []
                    has_images_in_batch = False

            except Exception:
                mm_errors += 1

            progress.advance(task)

        if batch_ids:
            mm_synced += _flush_multimodal_batch(
                mm_collection, batch_ids, batch_documents, batch_metadatas, batch_images, has_images_in_batch
            )

    console.print()
    if mm_errors > 0:
        console.print(f"  [{COLORS['success']}]\u2713[/] Multimodal: {format_number(mm_synced)} synced")
        console.print(f"  [{COLORS['error']}]\u2717[/] {format_number(mm_errors)} errors")
    else:
        print_success(f"Multimodal sync complete. {format_number(mm_synced)} entries added.")
    console.print()


def _flush_multimodal_batch(collection, ids, documents, metadatas, images, has_images):
    """Add a batch to the multimodal collection. Returns count of items added."""
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
