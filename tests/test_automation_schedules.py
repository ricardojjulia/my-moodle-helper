from datetime import UTC, datetime, timedelta

from app.backend import database as dbmod
from app.backend.routers import courses as courses_router


def _course_content() -> dict:
    return {
        "course_structure": {
            "course_summary": "Overview",
            "modules": [
                {"number": 1, "title": "Module 1", "objective": "Obj 1", "key_topics": ["Topic A"]},
            ],
        },
        "module_contents": [
            {
                "module_num": 1,
                "lecture_html": "<p>Lecture</p>",
                "forum_question": "Discuss this.",
                "sections": [{"heading": "H1", "text": "Body"}],
                "glossary": [{"term": "term", "definition": "definition"}],
                "glossary_terms": ["term"],
            }
        ],
        "quiz_questions": [],
        "syllabus": {},
        "homework_spec": {},
    }


def test_schedule_list_starts_empty_without_auto_seed(client):
    dbmod.upsert_course("THAUTO1", "Auto Course", "Prof", "Cat", "Prompt")
    dbmod.save_version("THAUTO1", "local-model", "2026-01-01", "2026-03-01", _course_content())

    response = client.get("/api/courses/schedules")

    assert response.status_code == 200
    assert response.json() == []


def test_import_version_does_not_create_default_schedule(client):
    dbmod.set_setting("llm_url", "")

    response = client.post(
        "/api/courses/THAUTO2/versions/import",
        json={
            "shortname": "THAUTO2",
            "fullname": "Auto Import",
            "professor": "Prof",
            "category": "Cat",
            "model_used": "imported",
            "content": _course_content(),
        },
    )

    assert response.status_code == 200
    assert dbmod.list_schedules() == []


def test_clear_schedules_removes_all_review_schedules(client):
    dbmod.set_setting("llm_url", "")
    dbmod.upsert_course("THAUTO3", "Auto Review", "Prof", "Cat", "Prompt")
    dbmod.save_schedule(
        shortname="THAUTO3",
        agent_id="theological-reviewer",
        agent_label="Theological Reviewer",
        agent_color="violet",
        agent_context="Review this course.",
        model_id="local-model",
        frequency="weekly",
        next_run_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    )

    response = client.delete("/api/courses/schedules")

    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
    assert dbmod.list_schedules() == []


def test_run_overdue_reviews_uses_manually_created_schedule(client, monkeypatch):
    dbmod.set_setting("llm_url", "")
    dbmod.upsert_course("THAUTO4", "Manual Review", "Prof", "Cat", "Prompt")
    version = dbmod.save_version("THAUTO4", "imported", "2026-01-01", "2026-03-01", _course_content())
    dbmod.save_schedule(
        shortname="THAUTO4",
        version_id=version["id"],
        agent_id="theological-reviewer",
        agent_label="Theological Reviewer",
        agent_color="violet",
        agent_context="Review this course.",
        model_id="local-model",
        frequency="weekly",
        next_run_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    )

    dbmod.set_setting("llm_url", "http://llm.local/v1")

    def _fake_call_llm(messages, llm_url, model_id, temperature, max_tokens, api_key=""):
        return '{"overall":"Passed","score":91,"summary":"Looks good","sections":[]}'

    monkeypatch.setattr(courses_router.cc, "call_llm", _fake_call_llm)

    run_response = client.post("/api/courses/schedules/run-overdue")

    assert run_response.status_code == 200
    assert run_response.json()["triggered"] == 1
    reviews = dbmod.list_reviews("THAUTO4")
    assert len(reviews) == 1
