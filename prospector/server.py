#!/usr/bin/env python3
"""Prospector — Screen History Trust Beachhead Finder"""

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

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


STATS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prospector — Acceleration Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
    background: #06060f;
    color: #e0e0e0;
    padding: 20px 24px;
    min-height: 100vh;
}

/* Header */
.header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 24px;
    border-bottom: 1px solid #1a1a3a;
    padding-bottom: 12px;
}
h1 { color: #7c8aff; font-size: 1.6em; letter-spacing: -0.5px; }
h1 span { color: #ff6b6b; font-weight: 400; }
.subtitle { color: #555; font-size: 0.8em; }
.refresh-info { color: #444; font-size: 0.72em; }
.back-link {
    color: #5c6bc0;
    text-decoration: none;
    font-size: 0.78em;
    border: 1px solid #2a2a4a;
    padding: 3px 10px;
    border-radius: 4px;
}
.back-link:hover { background: #1a1a3a; color: #7c8aff; }

/* Section */
h2 {
    color: #5c6bc0;
    font-size: 1.05em;
    margin: 28px 0 14px;
    border-bottom: 1px solid #1a1a3a;
    padding-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
}

/* Acceleration hero cards */
.accel-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 16px;
    margin-bottom: 8px;
}
.accel-card {
    background: linear-gradient(135deg, #0e0e22 0%, #141430 100%);
    border: 1px solid #2a2a4a;
    border-radius: 10px;
    padding: 20px;
    position: relative;
    overflow: hidden;
}
.accel-card .provider {
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #888;
    margin-bottom: 12px;
}
.accel-card .provider .dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 6px;
}
.accel-card .metrics-row {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
}
.metric-box {
    flex: 1;
    min-width: 80px;
    text-align: center;
    padding: 10px 6px;
    background: rgba(0,0,0,0.3);
    border-radius: 6px;
}
.metric-box .label {
    font-size: 0.65em;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #666;
    margin-bottom: 4px;
}
.metric-box .value {
    font-size: 1.5em;
    font-weight: 700;
}
.metric-box .unit {
    font-size: 0.6em;
    color: #555;
}
.positive { color: #4ade80; }
.negative { color: #f87171; }
.neutral { color: #7c8aff; }

/* Acceleration emphasis */
.metric-box.accel-emphasis {
    background: rgba(124, 138, 255, 0.08);
    border: 1px solid rgba(124, 138, 255, 0.2);
}
.metric-box.accel-emphasis .value {
    font-size: 1.8em;
}

/* Chart */
.chart-section {
    background: #0e0e22;
    border: 1px solid #1a1a3a;
    border-radius: 10px;
    padding: 20px;
    margin: 16px 0;
}
.chart-container { position: relative; height: 260px; }

/* Status pills */
.status-bar {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-top: 12px;
}
.status-pill {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: #12122a;
    border: 1px solid #2a2a4a;
    border-radius: 20px;
    font-size: 0.75em;
}
.status-pill .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
}
.dot-green { background: #4ade80; }
.dot-blue { background: #7c8aff; }
.dot-yellow { background: #fbbf24; }

/* Breakdown cards */
.breakdown-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
    margin-top: 12px;
}
.breakdown-card {
    background: linear-gradient(135deg, #0e0e22 0%, #141430 100%);
    border: 1px solid #2a2a4a;
    border-radius: 10px;
    padding: 14px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.breakdown-card .name {
    font-size: 0.85em;
    color: #ccc;
    text-transform: capitalize;
}
.breakdown-card .count {
    font-size: 1.3em;
    font-weight: 700;
    color: #7c8aff;
}
.breakdown-card .avg-score {
    font-size: 0.7em;
    color: #666;
    margin-top: 2px;
}
.bar-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 6px;
    font-size: 0.82em;
}
.bar-label {
    min-width: 120px;
    color: #aaa;
    text-transform: capitalize;
    text-align: right;
}
.bar-track {
    flex: 1;
    height: 18px;
    background: rgba(0,0,0,0.3);
    border-radius: 4px;
    overflow: hidden;
    position: relative;
}
.bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
}
.bar-value {
    min-width: 50px;
    color: #888;
    font-variant-numeric: tabular-nums;
}

/* Acceleration table */
.accel-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82em;
    margin-top: 12px;
}
.accel-table th {
    text-align: left;
    padding: 8px 10px;
    background: #12122a;
    color: #5c6bc0;
    border-bottom: 2px solid #2a2a5a;
    font-weight: 600;
}
.accel-table td {
    padding: 6px 10px;
    border-bottom: 1px solid #1a1a2a;
}
.accel-table tr:hover { background: #121230; }
.accel-table .num { text-align: right; font-variant-numeric: tabular-nums; }
</style>
</head>
<body>

<div class="header">
    <div>
        <h1>Prospector <span>// acceleration</span></h1>
        <div class="subtitle">Pipeline velocity and growth metrics</div>
    </div>
    <div style="text-align:right">
        <a href="/" class="back-link">&larr; Dashboard</a>
        <div class="refresh-info" id="refresh-info" style="margin-top:6px">Loading...</div>
    </div>
</div>

<div id="app"><div style="color:#555">Loading data...</div></div>

<script>
let charts = {};

function fmtNum(n) {
    if (typeof n !== 'number' || isNaN(n)) return '\u2014';
    if (Math.abs(n) >= 1e6) return (n/1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return (n/1e3).toFixed(1) + 'K';
    return n.toLocaleString(undefined, {maximumFractionDigits: 2});
}

function signClass(n) {
    if (n > 0) return 'positive';
    if (n < 0) return 'negative';
    return 'neutral';
}

function signPrefix(n) {
    return n > 0 ? '+' : '';
}

function renderStatusPills(summary) {
    return `<div class="status-bar">
        <div class="status-pill"><span class="dot dot-green"></span>${fmtNum(summary.total_prospects)} prospects</div>
        <div class="status-pill"><span class="dot dot-blue"></span>${fmtNum(summary.total_outreach)} outreach generated</div>
        <div class="status-pill"><span class="dot dot-yellow"></span>${fmtNum(summary.total_runs)} pipeline runs</div>
    </div>`;
}

function renderPvaCard(label, color, metrics, unit) {
    return `<div class="accel-card">
        <div class="provider"><span class="dot" style="background:${color}"></span>${label}</div>
        <div class="metrics-row">
            <div class="metric-box">
                <div class="label">Position</div>
                <div class="value neutral">${fmtNum(metrics.position)}</div>
                <div class="unit">${unit}</div>
            </div>
            <div class="metric-box">
                <div class="label">Velocity</div>
                <div class="value ${signClass(metrics.velocity)}">${signPrefix(metrics.velocity)}${fmtNum(metrics.velocity)}</div>
                <div class="unit">7-day avg/day</div>
            </div>
            <div class="metric-box accel-emphasis">
                <div class="label">Acceleration</div>
                <div class="value ${signClass(metrics.acceleration)}">${signPrefix(metrics.acceleration)}${fmtNum(metrics.acceleration)}</div>
                <div class="unit">&Delta; velocity</div>
            </div>
        </div>
    </div>`;
}

function renderPositionOnlyCard(label, color, value, unit) {
    return `<div class="accel-card">
        <div class="provider"><span class="dot" style="background:${color}"></span>${label}</div>
        <div class="metrics-row">
            <div class="metric-box">
                <div class="label">Position</div>
                <div class="value neutral">${fmtNum(value)}</div>
                <div class="unit">${unit}</div>
            </div>
            <div class="metric-box" style="opacity:0.3">
                <div class="label">Velocity</div>
                <div class="value neutral">\u2014</div>
                <div class="unit">no daily data</div>
            </div>
            <div class="metric-box" style="opacity:0.3">
                <div class="label">Acceleration</div>
                <div class="value neutral">\u2014</div>
                <div class="unit">no daily data</div>
            </div>
        </div>
    </div>`;
}

function renderAccelChart(prospectMetrics, runMetrics) {
    const pDaily = prospectMetrics.daily || [];
    const rDaily = runMetrics.daily || [];

    if (!pDaily.length && !rDaily.length) {
        return '<div class="chart-section"><div style="color:#555;text-align:center;padding:40px">No daily data yet</div></div>';
    }

    return `<div class="chart-section">
        <div style="font-size:0.85em;color:#5c6bc0;font-weight:600;margin-bottom:12px">ACCELERATION OVER TIME</div>
        <div class="chart-container"><canvas id="accelChart"></canvas></div>
    </div>`;
}

function updateAccelChart(prospectMetrics, runMetrics) {
    const canvas = document.getElementById('accelChart');
    if (!canvas) return;

    const pDaily = prospectMetrics.daily || [];
    const rDaily = runMetrics.daily || [];

    const allDatesSet = new Set();
    pDaily.forEach(d => allDatesSet.add(d.date));
    rDaily.forEach(d => allDatesSet.add(d.date));
    const allDates = [...allDatesSet].sort();
    if (!allDates.length) return;

    const pMap = {};
    pDaily.forEach(d => pMap[d.date] = d.acceleration);
    const rMap = {};
    rDaily.forEach(d => rMap[d.date] = d.acceleration);

    const datasets = [
        {
            label: 'Prospects Accel',
            data: allDates.map(d => pMap[d] || 0),
            borderColor: '#4ade80',
            backgroundColor: '#4ade8022',
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#4ade80',
            fill: true,
            tension: 0.3,
        },
        {
            label: 'Runs Accel',
            data: allDates.map(d => rMap[d] || 0),
            borderColor: '#7c8aff',
            backgroundColor: '#7c8aff22',
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#7c8aff',
            fill: true,
            tension: 0.3,
        },
    ];

    if (charts.accel) {
        charts.accel.data.labels = allDates;
        charts.accel.data.datasets = datasets;
        charts.accel.update('none');
        return;
    }

    charts.accel = new Chart(canvas, {
        type: 'line',
        data: { labels: allDates, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: { color: '#888', font: { family: "'SF Mono', monospace", size: 11 } } },
                tooltip: {
                    backgroundColor: '#1a1a3a',
                    titleColor: '#e0e0e0',
                    bodyColor: '#bbb',
                    borderColor: '#2a2a4a',
                    borderWidth: 1,
                },
            },
            scales: {
                x: {
                    ticks: { color: '#555', font: { size: 10 } },
                    grid: { color: 'rgba(42,42,74,0.3)' },
                },
                y: {
                    title: { display: true, text: 'Acceleration (\u0394 velocity)', color: '#5c6bc0', font: { size: 11 } },
                    ticks: { color: '#666', font: { size: 10 } },
                    grid: { color: 'rgba(42,42,74,0.3)' },
                },
            },
        },
    });
}

function renderSourceBreakdown(bySource) {
    if (!bySource || !bySource.length) return '<div style="color:#555;font-size:0.85em">No source data</div>';

    const maxCount = Math.max(...bySource.map(s => s.count));
    const sourceColors = {
        github: '#4ade80',
        twitter: '#60a5fa',
        hackernews: '#fbbf24',
        bootcamp: '#a78bfa',
    };

    return bySource.map(s => {
        const pct = maxCount > 0 ? (s.count / maxCount * 100) : 0;
        const color = sourceColors[s.source] || '#7c8aff';
        const avgScore = typeof s.avg_score === 'number' ? s.avg_score.toFixed(3) : '\u2014';
        return `<div class="bar-row">
            <div class="bar-label">${s.source}</div>
            <div class="bar-track">
                <div class="bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            <div class="bar-value">${fmtNum(s.count)} <span style="color:#555;font-size:0.85em">avg ${avgScore}</span></div>
        </div>`;
    }).join('');
}

function renderCategoryBreakdown(byCategory) {
    if (!byCategory || !byCategory.length) return '<div style="color:#555;font-size:0.85em">No category data</div>';

    const maxCount = Math.max(...byCategory.map(c => c.count));

    return byCategory.map(c => {
        const pct = maxCount > 0 ? (c.count / maxCount * 100) : 0;
        const avgScore = typeof c.avg_score === 'number' ? c.avg_score.toFixed(3) : '\u2014';
        return `<div class="bar-row">
            <div class="bar-label">${c.category}</div>
            <div class="bar-track">
                <div class="bar-fill" style="width:${pct}%;background:#5c6bc0"></div>
            </div>
            <div class="bar-value">${fmtNum(c.count)} <span style="color:#555;font-size:0.85em">avg ${avgScore}</span></div>
        </div>`;
    }).join('');
}

function renderScoreDistChart(scoreDist) {
    if (!scoreDist || !scoreDist.length) {
        return '<div style="color:#555;font-size:0.85em">No score data</div>';
    }

    return `<div class="chart-section">
        <div class="chart-container" style="height:200px"><canvas id="scoreChart"></canvas></div>
    </div>`;
}

function updateScoreChart(scoreDist) {
    const canvas = document.getElementById('scoreChart');
    if (!canvas || !scoreDist || !scoreDist.length) return;

    const labels = scoreDist.map(b => b.bucket);
    const values = scoreDist.map(b => b.count);
    const colors = ['#f87171', '#fbbf24', '#7c8aff', '#60a5fa', '#4ade80'];

    if (charts.score) {
        charts.score.data.labels = labels;
        charts.score.data.datasets[0].data = values;
        charts.score.update('none');
        return;
    }

    charts.score = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Prospects',
                data: values,
                backgroundColor: colors.slice(0, labels.length),
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1a1a3a',
                    titleColor: '#e0e0e0',
                    bodyColor: '#bbb',
                    borderColor: '#2a2a4a',
                    borderWidth: 1,
                },
            },
            scales: {
                x: {
                    ticks: { color: '#888', font: { family: "'SF Mono', monospace", size: 11 } },
                    grid: { display: false },
                },
                y: {
                    ticks: { color: '#666', font: { size: 10 } },
                    grid: { color: 'rgba(42,42,74,0.3)' },
                },
            },
        },
    });
}

function renderDailyTable(prospectMetrics, runMetrics) {
    const pDaily = prospectMetrics.daily || [];
    const rDaily = runMetrics.daily || [];
    const last5 = pDaily.slice(-5);

    if (!last5.length) return '<div style="color:#555;font-size:0.85em">No daily data yet</div>';

    const rMap = {};
    rDaily.forEach(d => rMap[d.date] = d);

    let rows = '';
    for (const d of last5) {
        const rd = rMap[d.date] || {};
        rows += `<tr>
            <td>${d.date}</td>
            <td class="num">${fmtNum(d.value)}</td>
            <td class="num">${fmtNum(d.cumulative)}</td>
            <td class="num ${signClass(d.velocity)}">${signPrefix(d.velocity)}${fmtNum(d.velocity)}</td>
            <td class="num ${signClass(d.acceleration)}">${signPrefix(d.acceleration)}${fmtNum(d.acceleration)}</td>
            <td class="num">${rd.value != null ? fmtNum(rd.value) : '\u2014'}</td>
        </tr>`;
    }

    return `<table class="accel-table">
        <thead><tr>
            <th>Date</th>
            <th class="num">Prospects</th>
            <th class="num">Cumulative</th>
            <th class="num">Velocity</th>
            <th class="num">Acceleration</th>
            <th class="num">Runs</th>
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

function render(data) {
    const el = document.getElementById('app');
    document.getElementById('refresh-info').textContent =
        'Last: ' + new Date().toLocaleTimeString() + ' \u2014 refreshes every 30s';

    const summary = data.summary;
    const pm = data.prospect_metrics;
    const rm = data.run_metrics;

    el.innerHTML = `
        ${renderStatusPills(summary)}

        <h2>PVA Overview</h2>
        <div class="accel-grid">
            ${renderPvaCard('Prospects Found', '#4ade80', pm, 'total found')}
            ${renderPvaCard('Pipeline Runs', '#7c8aff', rm, 'total runs')}
            ${renderPositionOnlyCard('Outreach Generated', '#fbbf24', summary.total_outreach, 'messages generated')}
        </div>

        ${renderAccelChart(pm, rm)}

        <h2>Source Breakdown</h2>
        <div style="margin-top:12px">
            ${renderSourceBreakdown(summary.by_source)}
        </div>

        <h2>Category Breakdown</h2>
        <div style="margin-top:12px">
            ${renderCategoryBreakdown(summary.by_category)}
        </div>

        <h2>Score Distribution</h2>
        ${renderScoreDistChart(summary.score_distribution)}

        <h2>Daily Acceleration (Last 5 Days)</h2>
        ${renderDailyTable(pm, rm)}
    `;

    requestAnimationFrame(() => {
        updateAccelChart(pm, rm);
        updateScoreChart(summary.score_distribution);
    });
}

async function refresh() {
    try {
        const resp = await fetch('/api/stats');
        const data = await resp.json();
        render(data);
    } catch (e) {
        document.getElementById('refresh-info').textContent = 'Error: ' + e.message;
    }
}

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""


def compute_pva(daily_counts: list[dict]) -> dict:
    """Compute position, velocity, acceleration from daily {date, count} list."""
    if not daily_counts:
        return {"position": 0, "velocity": 0, "acceleration": 0, "daily": []}

    result = []
    cumulative = 0
    for i, d in enumerate(daily_counts):
        cumulative += d["count"]
        velocity = sum(x["count"] for x in daily_counts[max(0,i-6):i+1]) / min(i+1, 7)
        prev_velocity = 0
        if i >= 1:
            prev_velocity = sum(x["count"] for x in daily_counts[max(0,i-7):i]) / min(i, 7)
        acceleration = velocity - prev_velocity
        result.append({
            "date": d["date"],
            "value": d["count"],
            "cumulative": cumulative,
            "velocity": round(velocity, 2),
            "acceleration": round(acceleration, 2),
        })

    return {
        "position": cumulative,
        "velocity": result[-1]["velocity"] if result else 0,
        "acceleration": result[-1]["acceleration"] if result else 0,
        "daily": result,
    }


@app.get("/api/stats")
async def get_stats():
    summary = await db.get_stats_summary()
    daily_prospects = await db.get_daily_prospect_counts()
    daily_runs = await db.get_daily_run_counts()

    return {
        "summary": summary,
        "prospect_metrics": compute_pva(daily_prospects),
        "run_metrics": compute_pva(daily_runs),
    }


@app.get("/stats", response_class=HTMLResponse)
async def stats_page():
    return STATS_HTML


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8102)
