from app.backend import database as dbmod
from app.backend.routers import courses as courses_router


def _seed_course_version(shortname: str = "TH101", model_used: str = "local-model") -> dict:
    dbmod.upsert_course(shortname, f"{shortname} Title", "Prof", "Cat", "Prompt")
    content = {
        "course_structure": {
            "course_title": f"{shortname} Title",
            "course_summary": "Overview",
            "modules": [
                {"number": 1, "title": "Module 1", "objective": "Obj 1", "key_topics": ["Topic A"]},
            ],
        },
        "module_contents": [
            {
                "module_num": 1,
                "lecture_html": "<p>Old lecture</p>",
                "discussion_question": "Old question",
                "forum_question": "Old forum question",
                "sections": [{"heading": "H1", "text": "Old body"}],
                "glossary": [{"term": "old", "definition": "old def"}],
                "glossary_terms": ["old"],
            }
        ],
        "quiz_questions": [],
        "syllabus": {},
        "homework_spec": {"1": "assign"},
    }
    return dbmod.save_version(shortname, model_used, "2026-01-01", "2026-03-01", content)


def test_review_requires_agent_context(client):
    _seed_course_version("TH201")
    dbmod.set_setting("llm_url", "http://llm.local/v1")

    response = client.post("/api/courses/TH201/review", json={"agent_context": ""})

    assert response.status_code == 400
    assert "agent_context is required" in response.json().get("detail", "")


def test_review_success_persists_result(client, monkeypatch):
    v = _seed_course_version("TH202")
    dbmod.set_setting("llm_url", "http://llm.local/v1")

    def _fake_call_llm(messages, llm_url, model_id, temperature, max_tokens, api_key=""):
        return (
            '{"overall":"Needs Revision","score":72,'
            '"summary":"Needs updates","sections":[{"title":"Checks","items":[{"label":"Quiz","status":"Needs Revision","note":"Add questions"}]}]}'
        )

    monkeypatch.setattr(courses_router.cc, "call_llm", _fake_call_llm)

    response = client.post(
        "/api/courses/TH202/review",
        json={
            "agent_context": "review prompt",
            "model_id": "model-a",
            "version_id": v["id"],
            "agent_id": "student",
            "agent_label": "Student Critic",
            "agent_color": "teal",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["shortname"] == "TH202"
    assert body["overall"] == "Needs Revision"
    assert body["score"] == 72

    reviews = dbmod.list_reviews("TH202")
    assert len(reviews) == 1
    assert reviews[0]["agent_id"] == "student"
    assert reviews[0]["agent_label"] == "Student Critic"
    assert reviews[0]["agent_color"] == "teal"


def test_regenerate_from_review_requires_reviews(client):
    _seed_course_version("TH203")
    response = client.post("/api/courses/TH203/regenerate-from-review", json={"reviews": []})

    assert response.status_code == 400
    assert "reviews list is required" in response.json().get("detail", "")


def test_regenerate_from_review_rejects_when_all_passed(client):
    _seed_course_version("TH204")

    response = client.post(
        "/api/courses/TH204/regenerate-from-review",
        json={
            "model_id": "model-a",
            "reviews": [
                {
                    "agent_label": "Reviewer",
                    "sections": [{"title": "Checks", "items": [{"label": "Quiz", "status": "Passed", "note": "OK"}]}],
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "No revision items found" in response.json().get("detail", "")


def test_regenerate_from_review_success_creates_new_version(client, monkeypatch):
    base = _seed_course_version("TH205")
    dbmod.set_setting("llm_url", "http://llm.local/v1")
    dbmod.set_setting("last_model", "model-fallback")

    def _fake_generate_module_content(*args, **kwargs):
        return {
            "sections": [{"heading": "Updated H1", "text": "Updated body"}],
            "glossary": [{"term": "new", "definition": "new def"}],
            "discussion_question": "Updated discussion",
        }

    monkeypatch.setattr(courses_router.cc, "generate_module_content", _fake_generate_module_content)
    monkeypatch.setattr(courses_router.cc, "sections_to_html", lambda sections: "<p>Updated lecture</p>")
    monkeypatch.setattr(courses_router.cc, "generate_quiz_questions", lambda *a, **k: [{"question": "Q1", "options": ["A", "B", "C", "D"], "answer": "A"}])
    monkeypatch.setattr(courses_router.cc, "generate_syllabus", lambda *a, **k: {"description": "Updated syllabus"})

    response = client.post(
        "/api/courses/TH205/regenerate-from-review",
        json={
            "model_id": "model-a",
            "reviews": [
                {
                    "agent_label": "Reviewer",
                    "sections": [
                        {
                            "title": "Checks",
                            "items": [
                                {"label": "Quiz question count", "status": "Needs Revision", "note": "Add more questions"}
                            ],
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] != base["id"]
    assert body["version_num"] == base["version_num"] + 1
    assert body["content"]["module_contents"][0]["lecture_html"] == "<p>Updated lecture</p>"
    assert body["content"]["syllabus"]["description"] == "Updated syllabus"
    assert len(body["content"]["quiz_questions"]) == 1


def test_finalize_review_updates_existing_version(client, monkeypatch):
    version = _seed_course_version("TH206")
    dbmod.set_setting("llm_url", "http://llm.local/v1")

    called = {"quiz": 0, "syllabus": 0}

    def _fake_quiz(*args, **kwargs):
        called["quiz"] += 1
        return [{"question": "Q-final", "options": ["A", "B", "C", "D"], "answer": "A"}]

    def _fake_syllabus(*args, **kwargs):
        called["syllabus"] += 1
        return {"description": "Finalized syllabus"}

    monkeypatch.setattr(courses_router.cc, "generate_quiz_questions", _fake_quiz)
    monkeypatch.setattr(courses_router.cc, "generate_syllabus", _fake_syllabus)

    response = client.post(
        f"/api/courses/TH206/versions/{version['id']}/finalize-review",
        json={
            "model_id": "model-a",
            "reviews": [
                {
                    "sections": [
                        {
                            "title": "Checks",
                            "items": [{"label": "Quiz", "status": "Needs Revision", "note": "Refresh quiz"}],
                        }
                    ]
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == version["id"]
    assert called["quiz"] == 1
    assert called["syllabus"] == 1
    assert body["content"]["syllabus"]["description"] == "Finalized syllabus"
    assert len(body["content"]["quiz_questions"]) == 1


def test_regenerate_module_rejects_imported_versions(client):
    version = _seed_course_version("TH207", model_used="mbz-import")

    response = client.post(
        f"/api/courses/TH207/versions/{version['id']}/modules/1/regenerate",
        json={"instructions": "Improve this", "model_id": "model-a"},
    )

    assert response.status_code == 400
    assert "Cannot regenerate content for imported courses" in response.json().get("detail", "")
