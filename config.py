import os
from pathlib import Path


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    BRIEFING_PASSWORD = os.getenv("BRIEFING_PASSWORD", "")
    BRIEFING_PUBLIC = os.getenv("BRIEFING_PUBLIC", "0") == "1"
    BRIEFING_TZ = os.getenv("BRIEFING_TZ", "America/Los_Angeles")
    BRIEFING_MODEL = os.getenv("BRIEFING_MODEL", "claude-sonnet-5-5")
    BRIEFING_SCHEDULE = os.getenv("BRIEFING_SCHEDULE", "0") == "1"
    BRIEFING_REFRESH_MINUTES = max(15, int(os.getenv("BRIEFING_REFRESH_MINUTES", "45")))
    DATABASE = os.getenv("DATABASE_PATH", "/data/monday-briefing.sqlite3")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30


def validate_config(config):
    if config.get("BRIEFING_PUBLIC") and len(config.get("BRIEFING_PASSWORD", "")) < 10:
        raise RuntimeError("BRIEFING_PASSWORD must be at least 10 characters when BRIEFING_PUBLIC=1")
    if config.get("BRIEFING_PUBLIC") and config.get("SECRET_KEY") in ("", "dev-only-change-me"):
        raise RuntimeError("Set a strong SECRET_KEY when BRIEFING_PUBLIC=1")
    Path(config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
