# Monday Briefing

A private, adaptive weekly learning app. Each Monday it researches the previous Monday–Sunday window and produces a sourced briefing, per-card tutor, six-question quiz, learner model, and archive.

The app teaches decision-relevant context. It does **not** recommend financial actions, trades, timing, allocations, or price targets.

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

Without `ANTHROPIC_API_KEY`, the app starts in clearly labelled demo mode and uses timeless sample teaching content—not synthetic news. Set the key to enable live research.

## Configuration

| Variable | Required in production | Purpose |
|---|---:|---|
| `ANTHROPIC_API_KEY` | Yes for Live mode | Anthropic API credential |
| `BRIEFING_PASSWORD` | Yes | Single-user login; 10+ characters when public |
| `SECRET_KEY` | Yes | Strong random Flask session signing key |
| `BRIEFING_PUBLIC` | Yes | Set to `1` on a public host |
| `BRIEFING_SCHEDULE` | Recommended | Set to `1` for Monday scheduling |
| `BRIEFING_TZ` | No | Defaults to `America/Los_Angeles` |
| `BRIEFING_MODEL` | No | Defaults to `claude-sonnet-5-5` |
| `DATABASE_PATH` | No | Defaults to `/data/monday-briefing.sqlite3` |

When `BRIEFING_PUBLIC=1`, startup refuses weak passwords and a missing/default `SECRET_KEY`. Gunicorn must use exactly one worker because build status and the scheduler are in process; threads provide concurrent polling and page requests.

## Tests

```bash
pytest -q
```

The test suite does not need an API key. It covers login gating and lockout, production startup checks, week math, scoring and learner updates, malformed model-output sanitising, and the one-attempt rule.

## Architecture

- `agent.py`: the only Anthropic integration; streaming requests, server-side web search, and `pause_turn` continuation.
- `logic.py`: date math, validation/sanitising, scoring, and learner-model updates.
- `db.py`: SQLite schema and data access.
- `app.py`: Flask routes, authentication, build coordination, and scheduler.
- `static/`: no-build vanilla JavaScript interface.

Live weekly builds search for every factual claim, limit stored URLs to retrieved HTTP(S) sources, and validate the model’s JSON before saving. Quiz answers and explanations are removed from browser responses until submission.

