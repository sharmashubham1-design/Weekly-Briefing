import hmac
import json
import os
import threading
import time
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import agent
from config import Config, validate_config
from db import (TOPICS, briefing_row, close_db, get_db, init_db, save_briefing,
                set_setting)
from logic import (fallback_coach_note, learner_summary, previous_week,
                   prompt_learner_summary, public_briefing, record_chat_start,
                   record_vote, sanitize_briefing, score_quiz)
from sample import SAMPLE

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
        start, _ = previous_week(tz_name=app.config["BRIEFING_TZ"]); key = start.isoformat()
        if key not in OPEN_TRIGGERED:
            OPEN_TRIGGERED.add(key); ensure_week(app, force=False)
        return render_template("index.html")

    @app.get("/api/bootstrap")
    def bootstrap():
        start, _ = previous_week(tz_name=app.config["BRIEFING_TZ"]); week = start.isoformat()
        row = briefing_row(week)
        attempt = get_db().execute("SELECT * FROM quiz_attempts WHERE week_start=?", (week,)).fetchone()
        archive = [dict(r) for r in get_db().execute("SELECT week_start,week_end,mode,created_at,json_extract(payload,'$.headline') headline FROM briefings ORDER BY week_start DESC")]
        payload = json.loads(row["payload"]) if row else None
        return jsonify({"week":week, "briefing": public_briefing(payload, bool(attempt)) if payload else None,
            "mode": row["mode"] if row else ("live" if os.getenv("ANTHROPIC_API_KEY") else "demo"),
            "attempt": dict(attempt) if attempt else None, "learner": learner_summary(), "archive":archive, "status":BUILD})

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
        started = ensure_week(app, force=True)
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
        if os.getenv("ANTHROPIC_API_KEY"):
            reply = agent.tutor_reply(data.get("item",{}), history[:-1], str(data["message"])[:2000], level, bool(data.get("web_search",True)))
        else:
            reply = "**Demo tutor:** connect the card’s main claim to its underlying **mechanism**, then ask what evidence would disprove it.\n\nExample: a higher mortgage rate raises debt service, but local supply can still support prices.\n\n→ Explain the key concept more simply\n→ What evidence should I look for?"
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
        if os.getenv("ANTHROPIC_API_KEY"):
            try: note = agent.coach_note(result, learner_summary()).strip()[:700] or note
            except Exception: pass
        set_setting("coach_notes", note)
        result["learner"] = learner_summary()
        return jsonify(result)

    if app.config["BRIEFING_SCHEDULE"] and not app.config.get("TESTING"):
        threading.Thread(target=scheduler_loop, args=(app,), daemon=True, name="briefing-scheduler").start()
    return app


def ensure_week(app, force=False):
    start, end = previous_week(tz_name=app.config["BRIEFING_TZ"]); week = start.isoformat()
    with app.app_context(): exists = briefing_row(week) is not None
    with BUILD_LOCK:
        if BUILD["state"] == "running" or (exists and not force): return False
        if BUILD["state"] == "failed" and BUILD["week"] == week and not force: return False
        BUILD.update(state="running", week=week, message="Researching and shaping your course…", updated_at=datetime.utcnow().isoformat())
    threading.Thread(target=build_week, args=(app,start,end), daemon=True, name="briefing-builder").start()
    return True


def build_week(app, start, end):
    try:
        with app.app_context():
            if os.getenv("ANTHROPIC_API_KEY"):
                raw = agent.build_briefing(start.isoformat(), end.isoformat(), prompt_learner_summary()); mode="live"
            else: raw = SAMPLE; mode="demo"
            payload = sanitize_briefing(raw)
            if len(payload["quiz"]) < 2 or not payload["items"]: raise ValueError("Generated briefing did not pass validation")
            save_briefing(start.isoformat(), end.isoformat(), mode, payload)
            db = get_db()
            for concept in payload["concepts"]:
                db.execute("INSERT OR IGNORE INTO concepts(term,topic) VALUES (?,?)", (concept["term"], concept["topic"]))
            db.commit()
        with BUILD_LOCK: BUILD.update(state="complete", message="Your briefing is ready.", updated_at=datetime.utcnow().isoformat())
    except Exception as exc:
        app.logger.exception("Weekly build failed")
        with BUILD_LOCK: BUILD.update(state="failed", message=f"Build failed: {str(exc)[:180]}", updated_at=datetime.utcnow().isoformat())


def scheduler_loop(app):
    while True:
        try:
            now = datetime.now(ZoneInfo(app.config["BRIEFING_TZ"]))
            if now.weekday() == 0 and now.hour >= 7: ensure_week(app, force=False)
        except Exception: app.logger.exception("Scheduler check failed")
        time.sleep(900)


app = create_app()
