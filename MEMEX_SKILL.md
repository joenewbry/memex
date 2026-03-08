# Memex Skill

## What Memex Is
A personal screen memory system. Captures screenshots, OCRs them, stores in ChromaDB for semantic search. Data lives on Prometheus (Jetson) at `/ssd/memex/data/`.

## When to Use Which Tool
- **Quick lookup** ("what was I looking at?"): `search-recent-relevant` — combines relevance + recency
- **Deep search across dates**: `vector-search-windowed` — semantic search within a time range
- **Exact text match**: `search-screenshots` — keyword search with optional date filters
- **Daily review**: `daily-summary` — structured breakdown by time-of-day periods
- **System health**: `get-stats` — capture counts, ChromaDB status
- **Activity patterns**: `activity-graph` — timeline of when capture was active
- **Raw samples**: `sample-time-range` / `time-range-summary` — evenly distributed OCR snapshots

## Common Patterns
- Check `get-stats` first to confirm the system is running and has data
- Use ISO date format: YYYY-MM-DD (dates) or YYYY-MM-DDTHH:MM:SS (timestamps)
- Results include relevance scores 0-1; >0.7 is a strong match
- `search-recent-relevant` auto-expands its search window if initial results are weak
- For "what did I do today/yesterday", use `daily-summary` with the date param
- Pre-computed daily summaries may exist at `~/.memex/summaries/today.md` and `~/.memex/summaries/yesterday.md`

## Control
- `start-flow` / `stop-flow` — start/stop screen capture + ChromaDB
