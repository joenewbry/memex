# Prospector Deployment & Stats Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy prospector to Jetson at prospector.digitalsurfacelabs.com and add a ramp-style stats/acceleration page.

**Architecture:** FastAPI app deployed to Jetson via rsync, served through Cloudflare tunnel. Stats page uses embedded HTML (like ramp.py) with Chart.js, computing PVA metrics from existing SQLite data. New `/stats` route and `/api/stats` JSON endpoint.

**Tech Stack:** Python/FastAPI, SQLite/aiosqlite, Chart.js, systemd, Cloudflare tunnel

---

### Task 1: Add stats DB queries to db.py

**Files:**
- Modify: `db.py` (add 3 new query functions at the end)

**Step 1: Add daily prospect counts query**

Add to bottom of `db.py`:

```python
async def get_daily_prospect_counts(days: int = 30) -> list[dict]:
    """Get number of prospects found per day."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT date(fetched_at, 'unixepoch') as date, COUNT(*) as count
            FROM prospects
            WHERE fetched_at > unixepoch('now', ?)
            GROUP BY date(fetched_at, 'unixepoch')
            ORDER BY date
        """, (f'-{days} days',))
        return [dict(r) for r in await cursor.fetchall()]


async def get_daily_run_counts(days: int = 30) -> list[dict]:
    """Get number of pipeline runs per day."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT date(started_at, 'unixepoch') as date, COUNT(*) as count
            FROM runs
            WHERE started_at > unixepoch('now', ?)
            GROUP BY date(started_at, 'unixepoch')
            ORDER BY date
        """, (f'-{days} days',))
        return [dict(r) for r in await cursor.fetchall()]


async def get_stats_summary() -> dict:
    """Get aggregate stats for the stats page."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # Totals
        cur = await conn.execute("SELECT COUNT(*) as total FROM prospects")
        total_prospects = (await cur.fetchone())["total"]

        cur = await conn.execute("SELECT COUNT(*) as total FROM prospects WHERE outreach_message IS NOT NULL AND outreach_message != ''")
        total_outreach = (await cur.fetchone())["total"]

        cur = await conn.execute("SELECT COUNT(*) as total FROM runs")
        total_runs = (await cur.fetchone())["total"]

        # By source
        cur = await conn.execute("""
            SELECT source, COUNT(*) as count, AVG(final_score) as avg_score
            FROM prospects GROUP BY source ORDER BY count DESC
        """)
        by_source = [dict(r) for r in await cur.fetchall()]

        # By category
        cur = await conn.execute("""
            SELECT category, COUNT(*) as count, AVG(final_score) as avg_score
            FROM prospects WHERE category IS NOT NULL AND category != ''
            GROUP BY category ORDER BY count DESC
        """)
        by_category = [dict(r) for r in await cur.fetchall()]

        # Score distribution (buckets: 0-0.2, 0.2-0.4, etc.)
        cur = await conn.execute("""
            SELECT
                CASE
                    WHEN final_score < 0.2 THEN '0.0-0.2'
                    WHEN final_score < 0.4 THEN '0.2-0.4'
                    WHEN final_score < 0.6 THEN '0.4-0.6'
                    WHEN final_score < 0.8 THEN '0.6-0.8'
                    ELSE '0.8-1.0'
                END as bucket,
                COUNT(*) as count
            FROM prospects GROUP BY bucket ORDER BY bucket
        """)
        score_dist = [dict(r) for r in await cur.fetchall()]

        return {
            "total_prospects": total_prospects,
            "total_outreach": total_outreach,
            "total_runs": total_runs,
            "by_source": by_source,
            "by_category": by_category,
            "score_distribution": score_dist,
        }
```

**Step 2: Verify queries work**

Run: `cd /Users/joe/dev/memex/prospector && python3 -c "import asyncio; import db; asyncio.run(db.init_db()); print(asyncio.run(db.get_stats_summary()))"`

Expected: Dict with totals and breakdowns printed.

**Step 3: Commit**

```bash
git add db.py && git commit -m "feat: add stats query functions to db.py"
```

---

### Task 2: Add /api/stats and /stats endpoints to server.py

**Files:**
- Modify: `server.py`

**Step 1: Add PVA compute function and stats endpoints**

Add these imports at top of `server.py`:
```python
from fastapi.responses import HTMLResponse
```

Add before the `app.mount(...)` line (line 166):

```python
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
```

**Step 2: Add the STATS_HTML constant**

Add before the `compute_pva` function. This is the full embedded stats page HTML — see Task 3.

**Step 3: Change bind address for Jetson deployment**

Change line 170 from:
```python
    uvicorn.run(app, host="127.0.0.1", port=8090)
```
to:
```python
    uvicorn.run(app, host="0.0.0.0", port=8090)
```

**Step 4: Verify locally**

Run: `cd /Users/joe/dev/memex/prospector && python3 server.py &`
Then: `curl http://127.0.0.1:8090/api/stats | python3 -m json.tool`

Expected: JSON with summary, prospect_metrics, run_metrics

**Step 5: Commit**

```bash
git add server.py && git commit -m "feat: add /stats and /api/stats endpoints"
```

---

### Task 3: Create the stats page HTML (embedded in server.py)

**Files:**
- Modify: `server.py` (add STATS_HTML string constant)

The stats page matches ramp's dark theme exactly:
- Background: `#06060f`
- Font: `'SF Mono', 'Cascadia Code', 'Fira Code', monospace`
- Accent: `#7c8aff`
- Cards: `linear-gradient(135deg, #0e0e22 0%, #141430 100%)`, border `#2a2a4a`
- Chart.js v4.4.1

**Sections:**
1. Header: "Prospector // acceleration" with refresh timestamp
2. Status pills showing adapter health
3. PVA hero cards: Prospects Found, Outreach Generated, Pipeline Runs
4. Acceleration over time chart (Chart.js line)
5. Source breakdown cards (prospects per source, bar chart)
6. Category breakdown (horizontal bar)
7. Score distribution (histogram)
8. Daily acceleration table (last 5 days)

**Step 1: Write the full STATS_HTML constant**

Add as `STATS_HTML = r"""<!DOCTYPE html>..."""` before the `compute_pva` function in server.py.

Full HTML content to write is specified in the implementation (too large for plan — implement matching ramp.py patterns exactly from lines 455-1010).

**Step 2: Verify stats page renders**

Open: `http://127.0.0.1:8090/stats`

Expected: Dark dashboard with PVA cards, charts, tables.

**Step 3: Commit**

```bash
git add server.py && git commit -m "feat: add ramp-style stats dashboard HTML"
```

---

### Task 4: Add Stats tab to index.html navigation

**Files:**
- Modify: `static/index.html`

**Step 1: Add Stats button to tab bar**

At line 173, after the History tab button, add:
```html
        <a class="tab-btn" href="/stats" style="text-decoration:none">Stats</a>
```

**Step 2: Verify tab appears**

Open: `http://127.0.0.1:8090/`

Expected: "Stats" tab visible in nav bar, clicking navigates to /stats.

**Step 3: Commit**

```bash
git add static/index.html && git commit -m "feat: add Stats tab to nav bar"
```

---

### Task 5: Deploy prospector to Jetson

**Step 1: rsync code to Jetson**

```bash
ssh prometheus "mkdir -p /ssd/prospector"
rsync -avz --exclude='__pycache__' --exclude='.git' --exclude='data/*.db' \
    /Users/joe/dev/memex/prospector/ prometheus:/ssd/prospector/
```

**Step 2: Set up venv and install deps**

```bash
ssh prometheus "cd /ssd/prospector && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
```

**Step 3: Copy the SQLite database**

```bash
rsync -avz /Users/joe/dev/memex/prospector/data/ prometheus:/ssd/prospector/data/
```

**Step 4: Create systemd service**

```bash
ssh prometheus "sudo tee /etc/systemd/system/prospector.service > /dev/null << 'EOF'
[Unit]
Description=Prospector — Screen Trust Beachhead Finder
After=network.target

[Service]
Type=simple
User=prometheus
WorkingDirectory=/ssd/prospector
ExecStart=/ssd/prospector/.venv/bin/python server.py
Restart=always
RestartSec=5
Environment=PATH=/ssd/prospector/.venv/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF"
```

**Step 5: Enable and start service**

```bash
ssh prometheus "sudo systemctl daemon-reload && sudo systemctl enable prospector && sudo systemctl start prospector"
```

**Step 6: Verify service is running**

```bash
ssh prometheus "systemctl status prospector && curl -s http://localhost:8090/api/stats | python3 -m json.tool | head"
```

Expected: Active (running), JSON stats output.

---

### Task 6: Add Cloudflare tunnel route

**Step 1: Add ingress rule to tunnel config**

```bash
ssh prometheus "sudo python3 -c \"
import yaml
with open('/etc/cloudflared/config.yml') as f:
    cfg = yaml.safe_load(f)
# Insert before catch-all
new_rule = {'hostname': 'prospector.digitalsurfacelabs.com', 'service': 'http://localhost:8090'}
cfg['ingress'].insert(-1, new_rule)
with open('/etc/cloudflared/config.yml', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print('Added prospector route')
\""
```

If yaml not available, use sed:
```bash
ssh prometheus "sudo sed -i '/- service: http_status:404/i\\  - hostname: prospector.digitalsurfacelabs.com\\n    service: http://localhost:8090' /etc/cloudflared/config.yml"
```

**Step 2: Add DNS CNAME via Cloudflare API or dashboard**

```bash
ssh prometheus "cloudflared tunnel route dns buddy-tunnel prospector.digitalsurfacelabs.com"
```

**Step 3: Restart cloudflared**

```bash
ssh prometheus "sudo systemctl restart cloudflared"
```

**Step 4: Verify public access**

```bash
curl -s https://prospector.digitalsurfacelabs.com/api/stats | head
```

Expected: JSON stats data returned.

---

### Task 7: Update directory page

**Files:**
- Modify: `/Users/joe/dev/alice-robotics-dashboard/directory.html`

**Step 1: Add prospector card**

After the ramp card (line 166), add:

```html
  <a class="card" href="https://prospector.digitalsurfacelabs.com" target="_blank" data-check="https://prospector.digitalsurfacelabs.com">
    <div class="status checking" title="Checking..."></div>
    <div class="card-header">
      <div class="card-icon" style="background:rgba(249,115,22,0.15)">&#128269;</div>
      <div>
        <div class="card-title">Prospector</div>
        <div class="card-url">prospector.digitalsurfacelabs.com</div>
      </div>
    </div>
    <div class="card-desc">Sales prospecting pipeline — finds developers across GitHub, Twitter, HN, and bootcamps. Scores trust gaps, generates personalized outreach via Claude AI.</div>
    <div class="card-meta">
      <span class="tag">Port 8090</span>
      <span class="tag">Python / FastAPI</span>
      <span class="tag">systemd</span>
    </div>
  </a>
```

**Step 2: Deploy updated directory page**

```bash
rsync -avz /Users/joe/dev/alice-robotics-dashboard/directory.html prometheus:/ssd/alice-dashboard/directory.html
```

(Verify the actual path on Jetson where directory.html is served from.)

**Step 3: Verify card appears**

Open: `https://directory.digitalsurfacelabs.com`

Expected: Prospector card visible with status check.

**Step 4: Commit**

```bash
cd /Users/joe/dev/alice-robotics-dashboard && git add directory.html && git commit -m "feat: add Prospector to service directory"
```

---

### Task 8: End-to-end verification

**Step 1: Verify all endpoints**

```bash
curl -s https://prospector.digitalsurfacelabs.com/ | head -5
curl -s https://prospector.digitalsurfacelabs.com/stats | head -5
curl -s https://prospector.digitalsurfacelabs.com/api/stats | python3 -m json.tool | head -20
```

**Step 2: Verify directory shows green status**

Open: `https://directory.digitalsurfacelabs.com`

Expected: All services including Prospector show green dots.
