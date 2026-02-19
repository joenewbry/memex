#!/usr/bin/env python3
"""
Memex Prometheus Server

Multi-instance MCP server hosting personal, walmart, and alaska Memex instances.
Path-based routing: /{instance}/mcp for MCP Streamable HTTP transport.

Middleware chain: CORS -> Size limit -> Audit log -> Auth -> Rate limit
For tools/call: AI validation before dispatch.
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.responses import StreamingResponse
import uvicorn

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent))

from instance_manager import InstanceManager
from auth import AuthManager
from rate_limiter import RateLimiter
from ai_validator import AIValidator
from chat_handler import ChatHandler

# Load configuration
config_dir = Path("/ssd/memex/config")
if config_dir.exists():
    load_dotenv(config_dir / "prometheus.env")

# Configure logging
log_dir = Path(os.environ.get("LOG_DIR", "/ssd/memex/logs"))
log_dir.mkdir(parents=True, exist_ok=True)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler = logging.FileHandler(log_dir / "prometheus-server.log")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

audit_handler = logging.FileHandler(log_dir / "audit.log")
audit_handler.setLevel(logging.INFO)
audit_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

logger = logging.getLogger("prometheus")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

audit_logger = logging.getLogger("prometheus.audit")
audit_logger.setLevel(logging.INFO)
audit_logger.addHandler(audit_handler)

# Usage tracking — JSONL append compatible with cli/services/usage.py schema
usage_log_path = log_dir / "usage.jsonl"


def _log_usage_event(instance: str, tool_name: str, arguments: dict, result: Any, duration_ms: int):
    """Append a JSONL usage event for metering."""
    try:
        query_len = len(json.dumps(arguments)) if arguments else 0
        result_count = 0
        if isinstance(result, dict):
            result_count = result.get("total_results", result.get("count", 0))
        elif isinstance(result, list):
            result_count = len(result)
        event = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": "tool_call",
            "instance": instance,
            "tool": tool_name,
            "query_len": query_len,
            "results": result_count,
            "duration_ms": duration_ms,
        }
        with open(usage_log_path, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


# Constants
PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "memex-prometheus"
SERVER_VERSION = "1.0.0"
MAX_REQUEST_SIZE = 1 * 1024 * 1024  # 1MB

# Configuration from environment
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8082"))
DATA_BASE_DIR = os.environ.get("DATA_BASE_DIR", "/ssd/memex/data")
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "2.0"))
API_KEYS_PATH = os.environ.get("API_KEYS_PATH", "/ssd/memex/config/api_keys.env")
SECURITY_POLICY_PATH = os.environ.get("SECURITY_POLICY_PATH", "/ssd/memex/config/security-policy.md")
INSTANCES = os.environ.get("INSTANCES", "personal,walmart,alaska").split(",")
PAGES_DIR = os.environ.get("PAGES_DIR", "/ssd/memex/pages")

# Initialize components
app = FastAPI(title="Memex Prometheus Server", version=SERVER_VERSION)

# Will be initialized on startup
instance_manager = None
auth_manager = None
rate_limiter = None
ai_validator = None
chat_handler = None
sessions = {}


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["MCP-Session-Id"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize all components on startup."""
    global instance_manager, auth_manager, rate_limiter, ai_validator, chat_handler

    logger.info("Starting Memex Prometheus Server...")
    logger.info(f"Instances: {INSTANCES}")
    logger.info(f"Data dir: {DATA_BASE_DIR}")
    logger.info(f"ChromaDB: {CHROMA_HOST}:{CHROMA_PORT}")

    instance_manager = InstanceManager(
        data_base_dir=DATA_BASE_DIR,
        chroma_host=CHROMA_HOST,
        chroma_port=CHROMA_PORT,
        instances=INSTANCES,
    )

    auth_manager = AuthManager(api_keys_path=API_KEYS_PATH)

    rate_limiter = RateLimiter(
        ip_per_minute=60,
        ip_per_hour=500,
        instance_per_minute=120,
    )

    ai_validator = AIValidator(
        ollama_host=OLLAMA_HOST,
        ollama_model=OLLAMA_MODEL,
        policy_path=SECURITY_POLICY_PATH,
        timeout=OLLAMA_TIMEOUT,
    )

    chat_handler = ChatHandler(
        instance_manager=instance_manager,
        pages_dir=PAGES_DIR,
    )

    logger.info("Memex Prometheus Server initialized successfully")


def _get_client_ip(request: Request) -> str:
    """Get client IP, respecting X-Forwarded-For from Cloudflare."""
    forwarded = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- Health endpoint (no auth) ---

@app.get("/health")
async def health_check():
    """Health check endpoint - no authentication required."""
    instances_status = {}
    if instance_manager:
        for name in instance_manager.list_instances():
            inst = instance_manager.get_instance(name)
            ocr_count = len(list(inst.ocr_data_dir.glob("*.json"))) if inst.ocr_data_dir.exists() else 0
            instances_status[name] = {"ocr_files": ocr_count, "data_dir": str(inst.ocr_data_dir)}

    return {
        "status": "healthy",
        "service": SERVER_NAME,
        "version": SERVER_VERSION,
        "instances": instances_status,
        "timestamp": datetime.now().isoformat(),
    }


def _parse_metrics() -> Dict[str, Any]:
    """Parse audit.log and usage.jsonl to build metrics for the dashboard."""
    metrics = {"source_ips": {}, "mcp_calls": {}, "mcp_calls_by_tool": {}, "daily_trends": {}}

    # Parse audit.log for source IPs
    audit_path = log_dir / "audit.log"
    if audit_path.exists():
        try:
            lines = audit_path.read_text().strip().split("\n")
            for line in lines[-5000:]:  # last 5000 lines
                if "REQUEST " not in line and "TOOL_OK " not in line:
                    continue
                parts = {}
                for token in line.split():
                    if "=" in token:
                        k, v = token.split("=", 1)
                        parts[k] = v
                ip = parts.get("ip")
                instance = parts.get("instance")
                if not ip or ip == "unknown":
                    continue
                # Extract timestamp from log line (format: YYYY-MM-DD HH:MM:SS,mmm)
                ts = line[:23] if len(line) > 23 else ""
                if ip not in metrics["source_ips"]:
                    metrics["source_ips"][ip] = {
                        "request_count": 0, "last_seen": ts, "instances": set()
                    }
                metrics["source_ips"][ip]["request_count"] += 1
                metrics["source_ips"][ip]["last_seen"] = ts
                if instance:
                    metrics["source_ips"][ip]["instances"].add(instance)
        except Exception as e:
            logger.warning(f"Error parsing audit.log: {e}")

    # Convert sets to lists for JSON serialization
    for ip_data in metrics["source_ips"].values():
        ip_data["instances"] = sorted(ip_data["instances"])

    # Parse usage.jsonl for MCP call counts
    if usage_log_path.exists():
        try:
            lines = usage_log_path.read_text().strip().split("\n")
            for line in lines[-5000:]:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                instance = event.get("instance", "unknown")
                tool = event.get("tool", "unknown")
                ts = event.get("ts", "")
                duration = event.get("duration_ms", 0)

                if instance not in metrics["mcp_calls"]:
                    metrics["mcp_calls"][instance] = {
                        "total_calls": 0, "last_call": "", "total_duration_ms": 0
                    }
                metrics["mcp_calls"][instance]["total_calls"] += 1
                metrics["mcp_calls"][instance]["last_call"] = ts
                metrics["mcp_calls"][instance]["total_duration_ms"] += duration

                tool_key = f"{instance}/{tool}"
                if tool_key not in metrics["mcp_calls_by_tool"]:
                    metrics["mcp_calls_by_tool"][tool_key] = 0
                metrics["mcp_calls_by_tool"][tool_key] += 1

                # Daily trends per instance
                date = ts[:10] if ts else ""
                if date:
                    if instance not in metrics["daily_trends"]:
                        metrics["daily_trends"][instance] = {}
                    metrics["daily_trends"][instance][date] = metrics["daily_trends"][instance].get(date, 0) + 1
        except Exception as e:
            logger.warning(f"Error parsing usage.jsonl: {e}")

    return metrics


@app.get("/api/metrics")
async def api_metrics():
    """Aggregated metrics for the dashboard — no auth required."""
    instances_data = {}
    if instance_manager:
        for name in instance_manager.list_instances():
            inst = instance_manager.get_instance(name)
            data_size = 0
            file_count = 0
            latest_mtime = 0
            if inst.ocr_data_dir.exists():
                for entry in os.scandir(inst.ocr_data_dir):
                    if entry.name.endswith('.json') and entry.is_file(follow_symlinks=False):
                        try:
                            stat = entry.stat()
                            data_size += stat.st_size
                            file_count += 1
                            if stat.st_mtime > latest_mtime:
                                latest_mtime = stat.st_mtime
                        except OSError:
                            pass
            latest_ts = datetime.fromtimestamp(latest_mtime).isoformat() if latest_mtime > 0 else None
            instances_data[name] = {
                "ocr_files": file_count,
                "latest_file": latest_ts,
                "data_size_bytes": data_size,
            }

    metrics = _parse_metrics()

    return {
        "server": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "timestamp": datetime.now().isoformat(),
        },
        "instances": instances_data,
        "source_ips": metrics["source_ips"],
        "mcp_calls": metrics["mcp_calls"],
        "mcp_calls_by_tool": metrics["mcp_calls_by_tool"],
        "daily_trends": metrics["daily_trends"],
    }


@app.get("/dashboard")
async def dashboard():
    """Self-contained HTML dashboard for node monitoring."""
    html = (Path(__file__).parent / "dashboard.html").read_text()
    return HTMLResponse(content=html)


@app.get("/")
async def root():
    """Serve the dashboard at root."""
    html = (Path(__file__).parent / "dashboard.html").read_text()
    return HTMLResponse(content=html)


@app.get("/api/instance/{name}/detail")
async def instance_detail(name: str):
    """Detailed per-instance metrics for the detail page."""
    if not instance_manager:
        raise HTTPException(status_code=503, detail="Server not initialized")

    inst = instance_manager.get_instance(name)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Unknown instance: {name}")

    # Scan files for data stats
    data_size = 0
    file_count = 0
    latest_mtime = 0
    oldest_mtime = float('inf')
    if inst.ocr_data_dir.exists():
        for entry in os.scandir(inst.ocr_data_dir):
            if entry.name.endswith('.json') and entry.is_file(follow_symlinks=False):
                try:
                    stat = entry.stat()
                    data_size += stat.st_size
                    file_count += 1
                    if stat.st_mtime > latest_mtime:
                        latest_mtime = stat.st_mtime
                    if stat.st_mtime < oldest_mtime:
                        oldest_mtime = stat.st_mtime
                except OSError:
                    pass

    # Parse usage.jsonl for this instance
    daily_calls: Dict[str, int] = {}
    tool_calls: Dict[str, int] = {}
    latencies = []
    if usage_log_path.exists():
        try:
            for line in usage_log_path.read_text().strip().split("\n"):
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if event.get("instance") != name:
                    continue
                date = event.get("ts", "")[:10]
                tool = event.get("tool", "unknown")
                duration = event.get("duration_ms", 0)
                if date:
                    daily_calls[date] = daily_calls.get(date, 0) + 1
                tool_calls[tool] = tool_calls.get(tool, 0) + 1
                if duration:
                    latencies.append(duration)
        except Exception:
            pass

    sorted_daily = sorted(daily_calls.items())[-30:]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
    sorted_latencies = sorted(latencies)
    p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)] if len(sorted_latencies) > 1 else 0

    return {
        "instance": name,
        "data": {
            "size_bytes": data_size,
            "file_count": file_count,
            "oldest": datetime.fromtimestamp(oldest_mtime).isoformat() if oldest_mtime < float('inf') else None,
            "newest": datetime.fromtimestamp(latest_mtime).isoformat() if latest_mtime > 0 else None,
        },
        "usage": {
            "total_calls": sum(daily_calls.values()),
            "daily": [{"date": d, "calls": c} for d, c in sorted_daily],
            "by_tool": dict(sorted(tool_calls.items(), key=lambda x: -x[1])),
        },
        "latency": {
            "avg_ms": avg_latency,
            "p95_ms": p95_latency,
            "total_samples": len(latencies),
        },
    }


@app.get("/api/info")
async def api_info():
    """Server information (JSON)."""
    return {
        "name": "Memex Prometheus Server",
        "version": SERVER_VERSION,
        "status": "running",
        "protocolVersion": PROTOCOL_VERSION,
        "instances": instance_manager.list_instances() if instance_manager else [],
    }


# --- Pages endpoint (static, no auth) ---

@app.get("/pages/{slug}")
async def serve_page(slug: str):
    """Serve a generated page by slug."""
    # Sanitize slug to prevent path traversal
    safe_slug = Path(slug).name
    if safe_slug != slug or ".." in slug:
        raise HTTPException(status_code=400, detail="Invalid slug")
    page_path = Path(PAGES_DIR) / f"{safe_slug}.html"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return HTMLResponse(content=page_path.read_text())


@app.get("/api/pages")
async def list_pages():
    """List all generated pages."""
    pages_path = Path(PAGES_DIR)
    if not pages_path.exists():
        return {"pages": []}
    pages = []
    for f in sorted(pages_path.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        pages.append({
            "slug": f.stem,
            "url": f"/pages/{f.stem}",
            "size_bytes": f.stat().st_size,
            "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return {"pages": pages}


# --- Screenshots endpoint ---

@app.get("/screenshots/{instance}/{filename}")
async def serve_screenshot(instance: str, filename: str):
    """Serve a screenshot image for a given instance."""
    # Sanitize to prevent path traversal
    safe_filename = Path(filename).name
    if safe_filename != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Check images directory under instance data dir
    img_path = Path(DATA_BASE_DIR) / instance / "images" / safe_filename
    if img_path.exists() and img_path.is_file():
        media = "image/jpeg" if safe_filename.endswith(".jpg") else "image/png"
        return FileResponse(img_path, media_type=media, headers={"Cache-Control": "public, max-age=86400"})

    raise HTTPException(status_code=404, detail="Screenshot not found")


# --- Sync endpoints (for tunnel-based CLI sync) ---

class SyncDocument(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any]
    raw_json: Dict[str, Any]


class SyncRequest(BaseModel):
    documents: list[SyncDocument]


@app.post("/{instance}/sync")
async def sync_documents(instance: str, request: Request):
    """Accept batched OCR documents from CLI sync, write to disk and upsert to ChromaDB."""
    if not instance_manager or not auth_manager:
        raise HTTPException(status_code=503, detail="Server not initialized")

    inst = instance_manager.get_instance(instance)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Unknown instance: {instance}")

    # Auth required
    is_auth, auth_error = auth_manager.authenticate(request, instance)
    if not is_auth:
        client_ip = _get_client_ip(request)
        audit_logger.info(f"AUTH_FAIL instance={instance} ip={client_ip} endpoint=sync error={auth_error}")
        raise HTTPException(status_code=401, detail=auth_error)

    try:
        body = await request.json()
        sync_req = SyncRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request body: {e}")

    client_ip = _get_client_ip(request)
    audit_logger.info(f"SYNC instance={instance} ip={client_ip} documents={len(sync_req.documents)}")

    # Ensure OCR data directory exists
    inst.ocr_data_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    indexed = 0
    errors = []

    # Write raw JSON files to disk
    for doc in sync_req.documents:
        try:
            file_path = inst.ocr_data_dir / f"{doc.id}.json"
            with open(file_path, "w") as f:
                json.dump(doc.raw_json, f, indent=2)
            written += 1
        except Exception as e:
            errors.append(f"write {doc.id}: {e}")

    # Batch upsert to ChromaDB
    if sync_req.documents:
        try:
            collection = inst.get_chroma_collection()
            batch_ids = []
            batch_documents = []
            batch_metadatas = []

            for doc in sync_req.documents:
                if not doc.text.strip():
                    continue
                batch_ids.append(doc.id)
                batch_documents.append(doc.text)
                # ChromaDB metadata must be flat (str/int/float/bool)
                meta = {}
                for k, v in doc.metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        meta[k] = v
                batch_metadatas.append(meta)

            if batch_ids:
                collection.upsert(
                    ids=batch_ids,
                    documents=batch_documents,
                    metadatas=batch_metadatas,
                )
                indexed = len(batch_ids)
        except Exception as e:
            errors.append(f"chromadb upsert: {e}")

    logger.info(f"SYNC_COMPLETE instance={instance} written={written} indexed={indexed} errors={len(errors)}")

    return {
        "status": "ok",
        "written": written,
        "indexed": indexed,
        "errors": errors[:10],  # Cap error detail
    }


@app.get("/{instance}/sync/status")
async def sync_status(instance: str, request: Request):
    """Return count and list of document IDs already on the server (for diffing)."""
    if not instance_manager or not auth_manager:
        raise HTTPException(status_code=503, detail="Server not initialized")

    inst = instance_manager.get_instance(instance)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Unknown instance: {instance}")

    # Auth required
    is_auth, auth_error = auth_manager.authenticate(request, instance)
    if not is_auth:
        raise HTTPException(status_code=401, detail=auth_error)

    # Get IDs from disk (source of truth)
    disk_ids = set()
    if inst.ocr_data_dir.exists():
        for entry in os.scandir(inst.ocr_data_dir):
            if entry.name.endswith(".json") and entry.is_file(follow_symlinks=False):
                disk_ids.add(entry.name[:-5])  # strip .json

    return {
        "instance": instance,
        "count": len(disk_ids),
        "ids": sorted(disk_ids),
    }


# --- Chat endpoints ---

@app.post("/chat")
async def cross_instance_chat(request: Request):
    """Cross-instance chat — no auth, tracked via audit log."""
    if not chat_handler:
        raise HTTPException(status_code=503, detail="Chat not initialized")

    client_ip = _get_client_ip(request)
    audit_logger.info(f"CHAT ip={client_ip} instance=cross type=message")

    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id")
    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    first_instance = instance_manager.list_instances()[0]
    session = chat_handler.get_or_create_session(session_id, first_instance)

    async def event_stream():
        yield f"event: session\ndata: {json.dumps({'session_id': session.id})}\n\n"
        async for event in chat_handler.chat(session, message, cross_instance=True):
            yield event

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/{instance}/chat")
async def instance_chat(instance: str, request: Request):
    """Chat with a specific instance's Memex data."""
    if not chat_handler or not instance_manager:
        raise HTTPException(status_code=503, detail="Server not initialized")

    inst = instance_manager.get_instance(instance)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Unknown instance: {instance}")

    client_ip = _get_client_ip(request)
    audit_logger.info(f"CHAT ip={client_ip} instance={instance} type=message")

    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id")
    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    session = chat_handler.get_or_create_session(session_id, instance)

    async def event_stream():
        yield f"event: session\ndata: {json.dumps({'session_id': session.id})}\n\n"
        async for event in chat_handler.chat(session, message, cross_instance=False):
            yield event

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/{instance}/chat/{session_id}")
async def delete_chat_session(instance: str, session_id: str, request: Request):
    """Delete a chat session — no auth."""
    if not chat_handler:
        raise HTTPException(status_code=503, detail="Chat not initialized")

    if chat_handler.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Session not found")


# --- MCP endpoint with path-based routing ---

@app.post("/{instance}/mcp")
async def mcp_endpoint(instance: str, request: Request):
    """
    MCP Streamable HTTP transport endpoint for a specific instance.
    Handles: initialize, tools/list, tools/call, notifications, ping.
    """
    # Validate instance exists
    if not instance_manager:
        return JSONResponse(status_code=503, content={"error": "Server not initialized"})

    inst = instance_manager.get_instance(instance)
    if not inst:
        return JSONResponse(
            status_code=404,
            content={
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": f"Unknown instance: {instance}. Available: {instance_manager.list_instances()}"},
            },
        )

    # Size limit check
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_SIZE:
        return JSONResponse(status_code=413, content={"error": "Request too large", "max_bytes": MAX_REQUEST_SIZE})

    # Authentication
    is_auth, auth_error = auth_manager.authenticate(request, instance)
    if not is_auth:
        audit_logger.info(f"AUTH_FAIL instance={instance} ip={_get_client_ip(request)} error={auth_error}")
        return JSONResponse(
            status_code=401,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": auth_error}},
        )

    # Rate limiting
    client_ip = _get_client_ip(request)
    allowed, retry_after, limit_type = rate_limiter.check(client_ip, instance)
    if not allowed:
        audit_logger.info(f"RATE_LIMIT instance={instance} ip={client_ip} type={limit_type}")
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded", "limit_type": limit_type},
            headers={"Retry-After": str(retry_after)},
        )

    # Parse JSON-RPC body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
        )

    method = body.get("method")
    request_id = body.get("id")
    params = body.get("params", {})

    # Audit log
    audit_logger.info(f"REQUEST instance={instance} ip={client_ip} method={method} id={request_id}")

    # --- Notifications (no id field) ---
    if request_id is None:
        return Response(status_code=202)

    # --- Requests ---

    if method == "initialize":
        session_id = str(uuid.uuid4())
        sessions[session_id] = {"initialized": True, "instance": instance}
        logger.info(f"MCP initialize: session={session_id} instance={instance}")

        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": f"{SERVER_NAME}-{instance}", "version": SERVER_VERSION},
                },
            },
            headers={"MCP-Session-Id": session_id},
        )

    elif method == "tools/list":
        tools = inst.get_tool_definitions()
        return JSONResponse(
            content={"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}},
        )

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            return JSONResponse(
                content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Missing tool name"}},
            )

        # AI Validation
        ai_allowed, ai_reason = await ai_validator.validate(tool_name, arguments, instance)
        if not ai_allowed:
            audit_logger.info(f"AI_DENY instance={instance} ip={client_ip} tool={tool_name} reason={ai_reason}")
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({
                            "error": "Request denied by security policy",
                            "reason": ai_reason,
                            "tool": tool_name,
                        })}],
                        "isError": True,
                    },
                },
            )

        # Call tool
        try:
            logger.info(f"tools/call: instance={instance} tool={tool_name} args={arguments}")
            t0 = time.monotonic()
            result = await inst.call_tool(tool_name, arguments)
            duration_ms = int((time.monotonic() - t0) * 1000)

            audit_logger.info(f"TOOL_OK instance={instance} ip={client_ip} tool={tool_name} duration_ms={duration_ms}")
            _log_usage_event(instance, tool_name, arguments, result, duration_ms)

            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                        "isError": False,
                    },
                },
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000) if 't0' in locals() else 0
            logger.error(f"Error calling tool {tool_name}: {e}")
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                        "isError": True,
                    },
                },
            )

    elif method == "ping":
        return JSONResponse(
            content={"jsonrpc": "2.0", "id": request_id, "result": {}},
        )

    else:
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            },
        )


# --- Legacy REST endpoints ---

@app.get("/{instance}/tools/list")
async def list_tools(instance: str, request: Request):
    """List tools for an instance (legacy REST)."""
    if not instance_manager:
        raise HTTPException(status_code=503, detail="Server not initialized")

    inst = instance_manager.get_instance(instance)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Unknown instance: {instance}")

    is_auth, auth_error = auth_manager.authenticate(request, instance)
    if not is_auth:
        raise HTTPException(status_code=401, detail=auth_error)

    return {"tools": inst.get_tool_definitions()}


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Memex Prometheus Server")
    parser.add_argument("--host", default=SERVER_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help="Port to serve on")
    args = parser.parse_args()

    logger.info(f"Starting Memex Prometheus Server on {args.host}:{args.port}")

    uvicorn.run(
        "prometheus_server:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
