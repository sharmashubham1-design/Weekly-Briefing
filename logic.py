import copy
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from db import TOPICS, get_db, setting, set_setting


def previous_week(now=None, tz_name="America/Los_Angeles"):
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz) if now else datetime.now(tz)
    this_monday = local.date() - timedelta(days=local.weekday())
    start = this_monday - timedelta(days=7)
    return start, start + timedelta(days=6)


def http_sources(value):
    result = []
    for src in value if isinstance(value, list) else []:
        if isinstance(src, str):
            url, title = src, "Source"
        elif isinstance(src, dict):
            url, title = src.get("url", ""), src.get("title", "Source")
        else:
            continue
        if urlparse(url).scheme in ("http", "https"):
            result.append({"title": str(title)[:160], "url": url})
    return result[:8]


def clean_text(value, limit=2000):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "")).strip()[:limit]


def sanitize_briefing(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {"headline": clean_text(raw.get("headline"), 240), "tldr": [], "movers": [],
           "items": [], "trends": [], "concepts": [], "decision_lens": [], "quiz": []}
    out["tldr"] = [clean_text(x, 300) for x in raw.get("tldr", []) if clean_text(x, 300)][:4]
    for i, x in enumerate(raw.get("movers", []) if isinstance(raw.get("movers"), list) else []):
        if not isinstance(x, dict) or not clean_text(x.get("name")): continue
        out["movers"].append({"id": f"mover-{i}", "topic": "Markets & investing",
            "name": clean_text(x.get("name"), 100), "kind": clean_text(x.get("kind"), 80),
            "what_happened": clean_text(x.get("what_happened")), "takeaway": clean_text(x.get("takeaway")),
            "sources": http_sources(x.get("sources"))})
    for i, x in enumerate(raw.get("items", []) if isinstance(raw.get("items"), list) else []):
        if not isinstance(x, dict) or not clean_text(x.get("title")): continue
        topic = x.get("topic") if x.get("topic") in TOPICS else "Markets & investing"
        out["items"].append({"id": f"story-{i}", "topic": topic, "title": clean_text(x.get("title"), 180),
            "summary": clean_text(x.get("summary")), "why_it_matters": clean_text(x.get("why_it_matters")),
            "concept": clean_text(x.get("concept"), 500), "sources": http_sources(x.get("sources"))})
    for i, x in enumerate(raw.get("trends", []) if isinstance(raw.get("trends"), list) else []):
        if isinstance(x, dict) and clean_text(x.get("trend")):
            out["trends"].append({"id": f"trend-{i}", "topic": "Markets & investing", "trend": clean_text(x.get("trend"), 180),
                "evidence": clean_text(x.get("evidence")), "confidence": clean_text(x.get("confidence"), 80), "caveat": clean_text(x.get("caveat"))})
    for i, x in enumerate(raw.get("concepts", []) if isinstance(raw.get("concepts"), list) else []):
        if isinstance(x, dict) and clean_text(x.get("term")):
            out["concepts"].append({"id": f"concept-{i}", "topic": x.get("topic") if x.get("topic") in TOPICS else "Markets & investing",
                "term": clean_text(x.get("term"), 100), "definition": clean_text(x.get("definition")), "example": clean_text(x.get("example"))})
    for i, x in enumerate(raw.get("decision_lens", []) if isinstance(raw.get("decision_lens"), list) else []):
        if isinstance(x, dict) and clean_text(x.get("knowledge_point")):
            qs = x.get("questions_to_ask", [])
            if isinstance(qs, str): qs = [qs]
            out["decision_lens"].append({"id": f"lens-{i}", "topic": "Markets & investing",
                "knowledge_point": clean_text(x.get("knowledge_point")), "questions_to_ask": [clean_text(q, 300) for q in qs if clean_text(q, 300)][:5]})
    for i, x in enumerate(raw.get("quiz", []) if isinstance(raw.get("quiz"), list) else []):
        if not isinstance(x, dict): continue
        opts, ans = x.get("options"), x.get("answer_index")
        if not isinstance(opts, list) or len(opts) < 2 or len(opts) > 6 or not isinstance(ans, int) or not 0 <= ans < len(opts): continue
        out["quiz"].append({"id": f"q-{i}", "topic": x.get("topic") if x.get("topic") in TOPICS else "Markets & investing",
            "concept": clean_text(x.get("concept"), 100), "q": clean_text(x.get("q"), 500),
            "options": [clean_text(o, 300) for o in opts], "answer_index": ans, "explanation": clean_text(x.get("explanation"), 800)})
    return out


def public_briefing(payload, attempted=False):
    data = copy.deepcopy(payload)
    if not attempted:
        for q in data.get("quiz", []):
            q.pop("answer_index", None); q.pop("explanation", None)
    return data


def learner_summary():
    db = get_db()
    topics = [dict(r) for r in db.execute("SELECT * FROM learner_topics ORDER BY topic")]
    concepts = [dict(r) for r in db.execute("SELECT * FROM concepts ORDER BY strength DESC, term")]
    attempts = [dict(r) for r in db.execute("SELECT week_start,score,total,topic_results,submitted_at FROM quiz_attempts ORDER BY week_start")]
    for attempt in attempts:
        attempt["topic_results"] = json.loads(attempt["topic_results"])
    return {"topics": topics, "concepts": concepts, "quiz_trend": attempts, "coach_notes": setting("coach_notes")}


def prompt_learner_summary():
    data = learner_summary()
    total_interest = sum(t["interest"] for t in data["topics"]) or 1
    for t in data["topics"]:
        t["level"] = "beginner" if t["mastery"] < .4 else "intermediate" if t["mastery"] < .7 else "advanced"
        t["story_target"] = max(1, round(8 * t["interest"] / total_interest))
    data["weak_concepts"] = [c["term"] for c in data["concepts"] if c["strength"] > 0]
    data["mastered_concepts"] = [c["term"] for c in data["concepts"] if c["mastered"]]
    data["introduced_concepts"] = [c["term"] for c in data["concepts"]]
    return data


def record_vote(week, card_id, topic, vote):
    db = get_db(); vote = 1 if vote > 0 else -1
    old = db.execute("SELECT vote FROM feedback WHERE week_start=? AND card_id=?", (week, card_id)).fetchone()
    previous = old["vote"] if old else 0
    db.execute("INSERT INTO feedback VALUES (?,?,?,?) ON CONFLICT(week_start,card_id) DO UPDATE SET vote=excluded.vote", (week, card_id, topic, vote))
    delta = .12 * (vote - previous)
    db.execute("UPDATE learner_topics SET interest=MIN(1,MAX(0,interest+?)) WHERE topic=?", (delta, topic))
    db.commit()


def record_chat_start(week, card_id, topic):
    db = get_db()
    cur = db.execute("INSERT OR IGNORE INTO chat_started VALUES (?,?,?)", (week, card_id, topic))
    if cur.rowcount:
        db.execute("UPDATE learner_topics SET interest=MIN(1,interest+.05) WHERE topic=?", (topic,))
    db.commit()


def score_quiz(week, payload, answers):
    db = get_db()
    if db.execute("SELECT 1 FROM quiz_attempts WHERE week_start=?", (week,)).fetchone():
        raise ValueError("Quiz already submitted for this week")
    quiz = payload.get("quiz", []); details = []; topic_stats = {}
    for i, q in enumerate(quiz):
        chosen = answers[i] if i < len(answers) and isinstance(answers[i], int) else -1
        correct = chosen == q["answer_index"]
        details.append({"chosen": chosen, "correct": correct, "answer_index": q["answer_index"], "explanation": q["explanation"]})
        stat = topic_stats.setdefault(q["topic"], {"correct": 0, "total": 0}); stat["total"] += 1; stat["correct"] += int(correct)
        term = q.get("concept") or "General"
        db.execute("INSERT OR IGNORE INTO concepts(term,topic) VALUES (?,?)", (term, q["topic"]))
        db.execute("UPDATE concepts SET strength=MAX(0,strength+?), mastered=CASE WHEN MAX(0,strength+?)=0 AND strength>0 THEN 1 ELSE mastered END WHERE term=?",
                   (-1 if correct else 2, -1 if correct else 2, term))
    for topic, stat in topic_stats.items():
        accuracy = stat["correct"] / stat["total"]
        db.execute("UPDATE learner_topics SET mastery=.7*mastery+.3*? WHERE topic=?", (accuracy, topic))
    score = sum(d["correct"] for d in details)
    db.execute("INSERT INTO quiz_attempts(week_start,answers,score,total,topic_results) VALUES (?,?,?,?,?)",
               (week, json.dumps(answers), score, len(quiz), json.dumps(topic_stats)))
    db.commit()
    return {"score": score, "total": len(quiz), "details": details, "topic_results": topic_stats}


def fallback_coach_note(result):
    weak = [t for t, s in result["topic_results"].items() if s["correct"] < s["total"]]
    if not weak: return "Strong recall across all three topics. Next week, focus on connecting the concepts rather than memorising isolated facts."
    return f"You’re building the foundations. Slow down on {', '.join(weak)} and use each story’s example to explain the key concept in your own words next week."
