from datetime import datetime, timezone
import json
import pytest
from db import get_db, save_briefing
from logic import previous_week, sanitize_briefing, score_quiz
from sample import SAMPLE


def test_previous_week_monday_edge():
    start,end=previous_week(datetime(2026,11,2,15,tzinfo=timezone.utc),"America/Los_Angeles")
    assert (start.isoformat(),end.isoformat()) == ("2026-10-26","2026-11-01")


def test_previous_week_sunday_edge():
    start,end=previous_week(datetime(2026,11,2,6,30,tzinfo=timezone.utc),"America/Los_Angeles")
    assert (start.isoformat(),end.isoformat()) == ("2026-10-19","2026-10-25")


def test_sanitizes_sources_topics_and_bad_quiz():
    raw={"headline":"ok","items":[{"title":"x","topic":"unknown","sources":[{"url":"javascript:bad"},{"url":"https://good.test","title":"Good"}]}],
         "quiz":[{"q":"bad","options":["a"],"answer_index":3},{"q":"good","topic":"nope","options":["a","b"],"answer_index":1,"explanation":"yes"}]}
    out=sanitize_briefing(raw)
    assert out["items"][0]["topic"] == "Markets & investing"
    assert out["items"][0]["sources"] == [{"title":"Good","url":"https://good.test"}]
    assert len(out["quiz"]) == 1 and out["quiz"][0]["answer_index"] == 1


def test_quiz_scoring_updates_mastery_and_concepts(app):
    payload=sanitize_briefing(SAMPLE)
    with app.app_context():
        before=get_db().execute("SELECT mastery FROM learner_topics WHERE topic='Markets & investing'").fetchone()[0]
        result=score_quiz("2026-10-26",payload,[0,1,0,1,1,0])
        after=get_db().execute("SELECT mastery FROM learner_topics WHERE topic='Markets & investing'").fetchone()[0]
        assert result["score"] == 6 and after > before
        assert get_db().execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 6


def test_one_attempt_per_week(app):
    payload=sanitize_briefing(SAMPLE)
    with app.app_context():
        score_quiz("2026-10-26",payload,[0,1,0,1,1,0])
        with pytest.raises(ValueError,match="already submitted"):
            score_quiz("2026-10-26",payload,[0,1,0,1,1,0])


def test_quiz_answers_withheld_until_submit(app, authed):
    payload=sanitize_briefing(SAMPLE)
    with app.app_context(): save_briefing("2026-10-26","2026-11-01","demo",payload)
    # The current test date may differ, so verify the archive endpoint directly.
    data=authed.get("/api/briefings/2026-10-26").get_json()["briefing"]
    assert "answer_index" not in data["quiz"][0]
    response=authed.post("/api/quiz/2026-10-26",json={"answers":[0,1,0,1,1,0]})
    assert response.status_code == 200
    data=authed.get("/api/briefings/2026-10-26").get_json()["briefing"]
    assert data["quiz"][0]["answer_index"] == 0

