import hmac
import json
import os
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config, validate_config
from db import (TOPICS, briefing_row, close_db, get_db, init_db, latest_briefing_row,
                save_briefing, set_setting)
from logic import (fallback_coach_note, learner_summary, previous_week,
                   public_briefing, record_chat_start,
                   record_vote, sanitize_briefing, score_quiz)
from news import build_digest, free_tutor_reply

BUILD = {"state": "idle", "week": None, "message": "", "updated_at": None}
BUILD_LOCK = threading.Lock()
LOGIN_FAILURES = {}
LOGIN_LOCK = threading.Lock()
OPEN_TRIGGERED = set()


def create_app(test_config=None):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(Config)
    if test_config: app.config.update(test_config)
    validate_config(app.config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(SESSION_COOKIE_SECURE=app.config["BRIEFING_PUBLIC"])
    app.teardown_appcontext(close_db)
    with app.app_context(): init_db()

    @app.before_request
    def protect():
        if request.endpoint in ("login", "healthz") or request.path == "/favicon.ico": return
        if not session.get("authenticated"):
            if request.path.startswith("/api/"): return jsonify({"error":"authentication required"}), 401
            return redirect(url_for("login"))

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    @app.get("/healthz")
    def healthz(): return jsonify({"status":"ok"})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        ip = request.remote_addr or "unknown"; now = time.time()
        with LOGIN_LOCK:
            attempts = [t for t in LOGIN_FAILURES.get(ip, []) if now - t < 900]
            LOGIN_FAILURES[ip] = attempts
        locked = len(attempts) >= 5
        error = None
        if request.method == "POST":
            if locked: error = "Too many attempts. Try again in 15 minutes."
            else:
                submitted = request.form.get("password", "").encode()
                expected = app.config["BRIEFING_PASSWORD"].encode()
                if expected and hmac.compare_digest(submitted, expected):
                    with LOGIN_LOCK: LOGIN_FAILURES.pop(ip, None)
                    session.clear(); session["authenticated"] = True; session.permanent = True
                    return redirect(url_for("index"))
                with LOGIN_LOCK: LOGIN_FAILURES.setdefault(ip, []).append(now)
                error = "That password didn’t match."
        return render_template("login.html", error=error, locked=locked)

    @app.post("/logout")
    def logout(): session.clear(); return redirect(url_for("login"))

    @app.get("/")
    def index():
        ensure_current(app, force=False)
        return render_template("index.html")

    @app.get("/api/bootstrap")
    def bootstrap():
        row = latest_briefing_row(); edition = row["week_start"] if row else None
        attempt = get_db().execute("SELECT * FROM quiz_attempts WHERE week_start=?", (edition,)).fetchone() if edition else None
        archive = [dict(r) for r in get_db().execute("SELECT week_start,week_end,mode,created_at,json_extract(payload,'$.headline') headline FROM briefings ORDER BY week_start DESC")]
        payload = json.loads(row["payload"]) if row else None
        return jsonify({"week":edition, "edition":edition, "briefing": public_briefing(payload, bool(attempt)) if payload else None,
            "mode": row["mode"] if row else "free-live", "attempt": dict(attempt) if attempt else None,
            "learner": learner_summary(), "archive":archive, "status":BUILD})

    @app.get("/api/briefings/<week>")
    def get_briefing(week):
        row = briefing_row(week)
        if not row: abort(404)
        attempt = get_db().execute("SELECT * FROM quiz_attempts WHERE week_start=?", (week,)).fetchone()
        return jsonify({"week":week,"mode":row["mode"],"attempt":dict(attempt) if attempt else None,
                        "briefing":public_briefing(json.loads(row["payload"]), bool(attempt))})

    @app.get("/api/status")
    def status(): return jsonify(BUILD)

    @app.post("/api/generate")
    def generate():
        started = ensure_current(app, force=True)
        return jsonify({"started":started,"status":BUILD}), 202 if started else 409

    @app.post("/api/refresh")
    def refresh():
        started = ensure_current(app, force=True)
        return jsonify({"started":started,"status":BUILD}), 202 if started else 409

    @app.post("/api/feedback")
    def feedback():
        data = request.get_json(silent=True) or {}
        if data.get("topic") not in TOPICS or data.get("vote") not in (-1, 1): abort(400)
        record_vote(data.get("week",""), str(data.get("card_id",""))[:100], data["topic"], data["vote"])
        return jsonify({"ok":True,"learner":learner_summary()})

    @app.route("/api/chat/<week>/<card_id>", methods=["GET", "POST"])
    def chat(week, card_id):
        db = get_db()
        if request.method == "GET":
            rows = [dict(r) for r in db.execute("SELECT role,content,created_at FROM chats WHERE week_start=? AND card_id=? ORDER BY id", (week,card_id))]
            return jsonify({"history":rows})
        data = request.get_json(silent=True) or {}; topic = data.get("topic")
        if topic not in TOPICS or not str(data.get("message","")).strip(): abort(400)
        record_chat_start(week, card_id, topic)
        db.execute("INSERT INTO chats(week_start,card_id,role,content) VALUES (?,?,?,?)", (week,card_id,"user",str(data["message"])[:2000])); db.commit()
        history = [dict(r) for r in db.execute("SELECT role,content FROM chats WHERE week_start=? AND card_id=? ORDER BY id", (week,card_id))]
        level_row = db.execute("SELECT mastery FROM learner_topics WHERE topic=?", (topic,)).fetchone(); mastery=level_row["mastery"]
        level = "beginner" if mastery < .4 else "intermediate" if mastery < .7 else "advanced"
        reply = free_tutor_reply(data.get("item",{}), str(data["message"])[:2000])
        db.execute("INSERT INTO chats(week_start,card_id,role,content) VALUES (?,?,?,?)", (week,card_id,"assistant",reply)); db.commit()
        return jsonify({"reply":reply,"learner":learner_summary()})

    @app.post("/api/quiz/<week>")
    def quiz(week):
        row = briefing_row(week)
        if not row: abort(404)
        answers = (request.get_json(silent=True) or {}).get("answers", [])
        try: result = score_quiz(week, json.loads(row["payload"]), answers)
        except ValueError as exc: return jsonify({"error":str(exc)}), 409
        note = fallback_coach_note(result)
        set_setting("coach_notes", note)
        result["learner"] = learner_summary()
        return jsonify(result)

    if app.config["BRIEFING_SCHEDULE"] and not app.config.get("TESTING"):
        threading.Thread(target=scheduler_loop, args=(app,), daemon=True, name="briefing-scheduler").start()
    return app


def _row_age_seconds(row):
    if not row: return None
    created = datetime.fromisoformat(row["created_at"])
    if created.tzinfo is None: created = created.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds())


def ensure_current(app, force=False):
    with app.app_context():
        latest = latest_briefing_row(); age = _row_age_seconds(latest)
    refresh_after = app.config["BRIEFING_REFRESH_MINUTES"] * 60
    with BUILD_LOCK:
        if BUILD["state"] == "running": return False
        if latest and age is not None and age < (300 if force else refresh_after): return False
        BUILD.update(state="running", week=latest["week_start"] if latest else None,
                     message="Checking trusted sources for new developments…", updated_at=datetime.now(timezone.utc).isoformat())
    threading.Thread(target=build_current, args=(app,), daemon=True, name="daily-briefing-builder").start()
    return True


def build_current(app):
    try:
        with app.app_context():
            previous_row = latest_briefing_row()
            previous = json.loads(previous_row["payload"]) if previous_row else None
            raw = build_digest(previous=previous, learner=learner_summary(), tz_name=app.config["BRIEFING_TZ"])
            payload = sanitize_briefing(raw)
            if len(payload["quiz"]) < 2 or not payload["items"]: raise ValueError("Generated briefing did not pass validation")
            edition = raw["edition_id"]
            save_briefing(edition, payload["daily_meta"]["period_end"], "free-live", payload)
            db = get_db()
            for concept in payload["concepts"]:
                db.execute("INSERT OR IGNORE INTO concepts(term,topic) VALUES (?,?)", (concept["term"], concept["topic"]))
            db.commit()
        with BUILD_LOCK: BUILD.update(state="complete", week=edition, message="Your financial radar is current.", updated_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        app.logger.exception("Daily build failed")
        with BUILD_LOCK: BUILD.update(state="failed", message=f"Refresh failed; your previous edition is still available. {str(exc)[:140]}", updated_at=datetime.now(timezone.utc).isoformat())


def scheduler_loop(app):
    while True:
        try:
            ensure_current(app, force=False)
        except Exception: app.logger.exception("Scheduler check failed")
        time.sleep(600)


app = create_app()
