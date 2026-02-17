# Prospector Deployment & Stats Page Design

**Date**: 2026-02-17

## Part 1: Deploy to prospector.digitalsurfacelabs.com

- Deploy `/Users/joe/dev/memex/prospector/` to Prometheus at `/ssd/prospector/`
- Python venv with deps on Jetson
- systemd service (`prospector.service`) on port 8090
- Cloudflare tunnel: `prospector.digitalsurfacelabs.com → localhost:8090`
- DNS CNAME in Cloudflare for `prospector`
- Add card to directory page
- Bind `0.0.0.0` in server.py

## Part 2: Stats Page

### PVA Hero Cards (position/velocity/acceleration)
- Prospects Found, Outreach Generated, Replies, Pipeline Runs

### Acceleration Over Time Chart
- Chart.js line chart, ramp dark theme (#06060f, monospace fonts)

### Pipeline Breakdown
- Source adapter hit rates
- Average score by category
- Score distribution
- Outreach conversion rate

### New Endpoints
- `GET /stats` — HTML stats page
- `GET /api/stats` — JSON metrics

### Navigation
- Add "Stats" link to existing nav bar in index.html
