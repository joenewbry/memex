#!/usr/bin/env python3
"""Prospector — Screen History Trust Beachhead Finder"""

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from adapters import ADAPTERS
from extractors import PatternExtractor
from scoring import Ranker
from outreach import OutreachGenerator
import db

app = FastAPI(title="Prospector")

extractor = PatternExtractor()
ranker = Ranker()
outreach_gen = OutreachGenerator()


@app.on_event("startup")
async def startup():
    await db.init_db()


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/adapters")
async def list_adapters():
    result = {}
    for key, cls in ADAPTERS.items():
        adapter = cls()
        result[key] = {
            "name": adapter.name,
            "description": adapter.description,
            "icon": adapter.icon,
            "categories": adapter.categories,
            "config_schema": adapter.get_config_schema(),
        }
    return result


@app.get("/api/scoring/weights")
async def get_weights():
    return ranker.weights


@app.get("/api/runs")
async def list_runs():
    return await db.get_all_runs()


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    prospects = await db.get_run_prospects(run_id)
    return {"id": run_id, "prospects": prospects}


@app.get("/api/prospects")
async def all_prospects():
    """Get all prospects across all runs, deduped."""
    return await db.get_all_prospects()


@app.post("/api/prospects/{prospect_id}/outreach")
async def generate_outreach(prospect_id: int):
    prospect = await db.get_prospect_by_id(prospect_id)
    if not prospect:
        return {"error": "Prospect not found"}
    message, deep_profile = await outreach_gen.generate(prospect)
    await db.update_prospect_outreach(prospect_id, message, deep_profile)
    return {"message": message, "deep_profile": deep_profile}


@app.websocket("/ws/run")
async def run_pipeline(ws: WebSocket):
    await ws.accept()
    try:
        config = await ws.receive_json()
        enabled_adapters = config.get("adapters", list(ADAPTERS.keys()))
        adapter_configs = config.get("adapter_configs", {})
        weight_overrides = config.get("weights", {})

        if weight_overrides:
            ranker.weights.update(weight_overrides)

        run_id = f"run_{int(time.time())}"
        await db.save_run(run_id, "running", time.time(), adapters_used=enabled_adapters)

        await ws.send_json({"type": "run_started", "run_id": run_id})

        all_prospects = []
        log_entries = []

        for adapter_key in enabled_adapters:
            if adapter_key not in ADAPTERS:
                continue
            adapter = ADAPTERS[adapter_key]()
            await ws.send_json({
                "type": "adapter_started",
                "adapter": adapter_key,
                "message": f"Fetching from {adapter.name}...",
            })

            try:
                adapter_config = adapter_configs.get(adapter_key, {})
                prospects = await adapter.fetch(adapter_config)
                all_prospects.extend(prospects)
                msg = f"{adapter.name}: found {len(prospects)} prospects"
                log_entries.append(msg)
                await ws.send_json({
                    "type": "adapter_done",
                    "adapter": adapter_key,
                    "count": len(prospects),
                    "message": msg,
                })
            except Exception as e:
                msg = f"{adapter.name}: error — {str(e)}"
                log_entries.append(msg)
                await ws.send_json({
                    "type": "adapter_error",
                    "adapter": adapter_key,
                    "message": msg,
                })

        await ws.send_json({"type": "stage", "stage": "extracting", "message": "Extracting signals..."})
        all_prospects = extractor.extract(all_prospects)

        await ws.send_json({"type": "stage", "stage": "ranking", "message": "Scoring and ranking..."})
        all_prospects = ranker.rank(all_prospects)

        # Save to DB
        await ws.send_json({"type": "stage", "stage": "saving", "message": "Saving to database..."})
        await db.save_prospects(run_id, all_prospects)
        await db.save_run(run_id, "done", time.time(), time.time(),
                          adapters_used=enabled_adapters, log=log_entries)

        # Fetch back with DB IDs
        saved = await db.get_run_prospects(run_id)

        await ws.send_json({
            "type": "run_done",
            "run_id": run_id,
            "total": len(saved),
            "prospects": saved,
            "message": f"Done — {len(saved)} prospects ranked and saved",
        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8090)
