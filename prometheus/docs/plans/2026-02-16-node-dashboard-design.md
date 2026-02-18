# Node Dashboard Design

**Date:** 2026-02-16
**Approach:** A — Single-page HTML served by Memex itself

## What We're Building

A `/dashboard` page at `memex.digitalsurfacelabs.com/dashboard` showing:
- Per-instance status cards (personal, walmart, alaska + future laptops)
- Last data received timestamp per instance
- Screenshot counts per instance
- MCP call counts per instance (from usage.jsonl)
- Source IP table with last-seen, request count, instances accessed
- Auto-refresh every 30s

Future: IP geolocation map view, IP whitelisting/blacklisting for security.

## Changes

### 1. `/api/metrics` endpoint (no auth — like `/health`)
Returns JSON with:
- `instances`: per-instance OCR count, latest file timestamp, screens
- `source_ips`: parsed from audit.log — IP, last-seen, request count, instances
- `mcp_calls`: parsed from usage.jsonl — per-instance totals, per-tool breakdown
- `server`: uptime, version

### 2. `/dashboard` route (no auth)
Self-contained HTML page (inline CSS/JS). Polls `/api/metrics` every 30s.
Cards + table layout. Dark theme matching terminal aesthetic.

### 3. Deploy
`rsync` to Jetson, restart `memex-server`. No new ports or tunnel config needed.
