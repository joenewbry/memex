#!/usr/bin/env python3
"""
Reindex OCR files into ChromaDB for a specific Memex instance.

Usage:
    python reindex.py --instance personal
    python reindex.py --instance walmart --force
    python reindex.py --instance alaska --batch-size 200 --dry-run

Adapted from memex/cli/commands/sync.py for multi-instance deployment.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path


def reindex(instance: str, chroma_host: str = "localhost", chroma_port: int = 8000,
            data_base_dir: str = "/ssd/memex/data", force: bool = False,
            dry_run: bool = False, batch_size: int = 100):
    """Sync OCR files to ChromaDB for a specific instance."""

    collection_name = f"{instance}_ocr_history"
    ocr_dir = Path(data_base_dir) / instance / "ocr"

    print(f"Reindex: instance={instance}")
    print(f"  Collection: {collection_name}")
    print(f"  OCR dir:    {ocr_dir}")
    print(f"  ChromaDB:   {chroma_host}:{chroma_port}")
    print()

    if not ocr_dir.exists():
        print(f"ERROR: OCR directory does not exist: {ocr_dir}")
        sys.exit(1)

    # Connect to ChromaDB
    import chromadb
    try:
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        client.heartbeat()
    except Exception as e:
        print(f"ERROR: Cannot connect to ChromaDB at {chroma_host}:{chroma_port}: {e}")
        sys.exit(1)

    try:
        collection = client.get_collection(name=collection_name)
        existing_count = collection.count()
    except Exception:
        collection = client.get_or_create_collection(name=collection_name)
        existing_count = 0

    # Get OCR files
    ocr_files = list(ocr_dir.glob("*.json"))
    total_files = len(ocr_files)
    print(f"  OCR files:  {total_files}")
    print(f"  Indexed:    {existing_count}")

    # Get existing IDs
    if force:
        to_sync = ocr_files
        print(f"  Force mode: re-syncing all files")
    else:
        existing_ids = set()
        if existing_count > 0:
            try:
                result = collection.get(include=[])
                existing_ids = set(result["ids"]) if result["ids"] else set()
            except Exception:
                pass

        to_sync = [f for f in ocr_files if f.stem not in existing_ids]

    if not to_sync:
        print("\n  Already in sync!")
        return

    print(f"\n  To sync:    {len(to_sync)} documents")

    if dry_run:
        print(f"\n  Dry run - no changes made.")
        return

    # Sync in batches
    synced = 0
    errors = 0
    start_time = time.time()

    batch_ids = []
    batch_documents = []
    batch_metadatas = []

    for i, f in enumerate(to_sync):
        try:
            with open(f, "r") as fp:
                data = json.load(fp)

            text = data.get("text", "") or data.get("extracted_text", "") or data.get("summary", "")
            if not text:
                continue

            doc_id = f.stem
            timestamp_str = data.get("timestamp", "")

            try:
                if timestamp_str:
                    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    timestamp = dt.timestamp()
                else:
                    timestamp = f.stat().st_mtime
                    timestamp_str = datetime.fromtimestamp(timestamp).isoformat()
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

            if len(batch_ids) >= batch_size:
                try:
                    collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
                    synced += len(batch_ids)
                except Exception as e:
                    errors += len(batch_ids)
                    print(f"  Batch error: {e}")

                batch_ids = []
                batch_documents = []
                batch_metadatas = []

                # Progress
                elapsed = time.time() - start_time
                rate = synced / elapsed if elapsed > 0 else 0
                print(f"  Progress: {synced + errors}/{len(to_sync)} ({rate:.0f} docs/sec)", end="\r")

        except Exception as e:
            errors += 1

    # Add remaining batch
    if batch_ids:
        try:
            collection.add(ids=batch_ids, documents=batch_documents, metadatas=batch_metadatas)
            synced += len(batch_ids)
        except Exception as e:
            errors += len(batch_ids)
            print(f"  Final batch error: {e}")

    elapsed = time.time() - start_time
    print(f"\n\n  Done in {elapsed:.1f}s")
    print(f"  Synced:  {synced}")
    if errors:
        print(f"  Errors:  {errors}")
    print(f"  Total:   {collection.count()}")


def main():
    parser = argparse.ArgumentParser(description="Reindex OCR files into ChromaDB")
    parser.add_argument("--instance", required=True, choices=["joe", "personal", "walmart", "alaska"],
                        help="Instance to reindex")
    parser.add_argument("--chroma-host", default="localhost", help="ChromaDB host")
    parser.add_argument("--chroma-port", type=int, default=8000, help="ChromaDB port")
    parser.add_argument("--data-dir", default="/ssd/memex/data", help="Base data directory")
    parser.add_argument("--force", action="store_true", help="Re-sync all files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be synced")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for syncing")
    args = parser.parse_args()

    reindex(
        instance=args.instance,
        chroma_host=args.chroma_host,
        chroma_port=args.chroma_port,
        data_base_dir=args.data_dir,
        force=args.force,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
