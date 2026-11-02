import json
import sqlite3
from flask import current_app, g

TOPICS = ("Markets & investing", "Real estate & mortgages", "Tech, AI & industry")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=20)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS briefings (
      week_start TEXT PRIMARY KEY, week_end TEXT NOT NULL, mode TEXT NOT NULL,
      payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS learner_topics (
      topic TEXT PRIMARY KEY, mastery REAL NOT NULL DEFAULT .35,
      interest REAL NOT NULL DEFAULT .5
    );
    CREATE TABLE IF NOT EXISTS concepts (
      term TEXT PRIMARY KEY, topic TEXT NOT NULL, strength INTEGER NOT NULL DEFAULT 0,
      introduced INTEGER NOT NULL DEFAULT 1, mastered INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS quiz_attempts (
      week_start TEXT PRIMARY KEY, answers TEXT NOT NULL, score INTEGER NOT NULL,
      total INTEGER NOT NULL, topic_results TEXT NOT NULL,
      submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS feedback (
      week_start TEXT NOT NULL, card_id TEXT NOT NULL, topic TEXT NOT NULL,
      vote INTEGER NOT NULL, PRIMARY KEY (week_start, card_id)
    );
    CREATE TABLE IF NOT EXISTS chats (
      id INTEGER PRIMARY KEY AUTOINCREMENT, week_start TEXT NOT NULL,
      card_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS chat_started (
      week_start TEXT NOT NULL, card_id TEXT NOT NULL, topic TEXT NOT NULL,
      PRIMARY KEY (week_start, card_id)
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    for topic in TOPICS:
        db.execute("INSERT OR IGNORE INTO learner_topics(topic) VALUES (?)", (topic,))
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('coach_notes','Welcome. Take the quiz after this week’s reading so I can tune the next briefing.')")
    db.commit()


def setting(key, default=""):
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    get_db().execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    get_db().commit()


def save_briefing(week_start, week_end, mode, payload):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO briefings(week_start,week_end,mode,payload) VALUES (?,?,?,?)",
               (week_start, week_end, mode, json.dumps(payload)))
    db.commit()


def briefing_row(week_start):
    return get_db().execute("SELECT * FROM briefings WHERE week_start=?", (week_start,)).fetchone()

