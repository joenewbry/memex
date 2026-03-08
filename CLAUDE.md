# CLAUDE.md — Memex

## Release Workflow

After any change to the **Prometheus dashboard** (`prometheus/server/dashboard.html`) or the **Memex service** (`prometheus/server/prometheus_server.py`, `cli/`, `refinery/`, `mcp-server/`):

1. Commit the changes
2. Tag with a version: `git tag -a v1.x.x -m "description"`
3. Push with tags: `git push && git push --tags`

Use semantic versioning:
- **patch** (v1.0.1) — bug fixes, copy changes, style tweaks
- **minor** (v1.1.0) — new features, new dashboard sections, new CLI commands
- **major** (v2.0.0) — breaking changes to API, config format, or architecture

## Deploying to Prometheus (Jetson)

After pushing, sync changes to the Jetson:
```bash
sshpass -p 'rising' rsync -avz -e "sshpass -p 'rising' ssh" \
  prometheus/server/ prometheus@prometheus.local:/ssd/memex/server/
```

Then restart the service:
```bash
sshpass -p 'rising' ssh prometheus@prometheus.local \
  'echo "rising" | sudo -S systemctl restart memex-server'
```

## Important: Prometheus vs Local

Memex services run on Prometheus (Jetson), not locally. When adding cron jobs, data pipelines, or services, always consider whether they should run on Prometheus. Active OCR data on local machines lives at `~/.memex/refinery/data/ocr/` — the dev repo copy (`refinery/data/ocr/`) may be stale.

## Key Paths

- Dashboard: `prometheus/server/dashboard.html`
- Server: `prometheus/server/prometheus_server.py`
- CLI: `cli/`
- Capture: `refinery/`
- MCP Server: `mcp-server/`
- Skill file: `MEMEX_SKILL.md` (knowledge layer for agents)
- Daily export: `bin/memex-daily-export`
- Summaries: `~/.memex/summaries/` (local), `~/.memex/summaries/{instance}/` (Prometheus)
- Jetson data: `/ssd/memex/data/{instance}/ocr/`
- Jetson config: `/ssd/memex/config/`
