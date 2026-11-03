# Daily Briefing

A private financial-intelligence and learning dashboard designed to be useful in the morning, at midday, and in the evening. It collects recent items from a fixed set of free public RSS/Atom feeds, preserves links to the original sources, classifies the stories, highlights what changed, and creates a practical decision checklist.

No API key or paid AI service is used. The app does **not** recommend buys, sells, timing, allocations, or price targets.

## Daily workflow

- The default screen is a **five-minute briefing**: three ranked developments, a compact market strip, three Reddit discussion themes, one concept, and three next steps.
- Everything else is progressively disclosed under **Open the full research desk** so the product teaches before it expands.
- Opening the app automatically refreshes an edition that is older than 45 minutes.
- **Refresh sources** requests an update, with a five-minute safety cooldown.
- Morning, midday, and evening editions use a rolling seven-day context window.
- **What changed** distinguishes new source items from the prior edition.
- **Your action checklist** suggests verification and planning steps, not trades.
- **The manager's desk** adds delayed public cross-asset observations, macro/policy releases, SEC filing links, catalyst questions, a primary-source reference board, and an explicit list of blind spots.
- Every story links to its original source and includes a concept, tutor, feedback controls, and quiz question.
- Interest and mastery still adapt story ranking and the learning experience.

The source set currently includes Federal Reserve/FRED, SEC, BLS, BEA, EIA, CFPB, BBC Business, NPR Business, BBC Technology, and Ars Technica. Broad editorial feeds must pass a finance/industry relevance filter. One failed feed does not prevent the other sources from producing an edition.

The sentiment panel makes one low-frequency, public RSS request covering r/investing, r/wallstreetbets, r/stocks, and r/SecurityAnalysis. If Reddit blocks the hosting provider, it falls back to a public news RSS index constrained to those communities and lowers confidence. It stores only post titles, links, community names, and publication times. The pulse is a simple, disclosed lexical indicator; it is labelled as low/medium-confidence attention data and never treated as factual research or a forecast. A successful result is reused for six hours to respect public rate limits.

The free desk is intentionally honest about latency. FRED observations are daily rather than live; CFTC positioning is periodic; Form 13F holdings can be filed up to 45 days after quarter-end; and SEC automated feeds may rate-limit or reject a refresh. The app links directly to the official calendars and searches when a feed is unavailable.

## Run locally

Python 3.12 is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BRIEFING_PASSWORD='a-local-password'
export SECRET_KEY='local-development-secret'
export DATABASE_PATH='./data/monday-briefing.sqlite3'
flask --app app run --debug
```

## Configuration

| Variable | Required in production | Purpose |
|---|---:|---|
| `BRIEFING_PASSWORD` | Yes | Single-user login; 10+ characters when public |
| `SECRET_KEY` | Yes | Strong random Flask session signing key |
| `BRIEFING_PUBLIC` | Yes | Set to `1` on a public host |
| `BRIEFING_SCHEDULE` | Recommended | Set to `1` for in-process freshness checks while awake |
| `BRIEFING_REFRESH_MINUTES` | No | Refresh threshold; defaults to `45`, minimum `15` |
| `BRIEFING_TZ` | No | Defaults to `America/Los_Angeles` |
| `DATABASE_PATH` | No | Defaults to `/data/monday-briefing.sqlite3` |

On Render's free tier the service sleeps. Page-open refresh is therefore the reliable mechanism; the scheduler is an additional convenience while the service is awake.

## Tests

```bash
pytest -q
```

Tests use local sample feed XML, never the network. They cover authentication, security checks, week math, feed parsing and daily digest construction, validation, quiz scoring, learner updates, and one-attempt enforcement.

## Architecture

- `news.py`: fixed-source feed fetching, RSS/Atom parsing, ranking, classification, change detection, deterministic digest/quiz generation, and free tutor responses.
- `logic.py`: validation/sanitising, scoring, and learner-model updates.
- `db.py`: SQLite schema and data access.
- `app.py`: Flask routes, authentication, refresh coordination, and scheduler.
- `static/`: no-build vanilla JavaScript interface.

All factual story text comes from feed titles/descriptions and retains the original URL. Added interpretation is limited to clearly labelled educational context and decision questions.
