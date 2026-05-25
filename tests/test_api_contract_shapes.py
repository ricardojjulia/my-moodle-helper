from app.backend import database as dbmod
from app.backend.routers import courses as courses_router
from app.backend.routers import moodle as moodle_router


def _seed_course_version(shortname: str = "CT101") -> dict:
    dbmod.upsert_course(shortname, f"{shortname} Title", "Prof", "Cat", "Prompt")
    content = {
        "course_structure": {
            "course_title": f"{shortname} Title",
            "course_summary": "Overview",
            "modules": [{"number": 1, "title": "Module 1", "objective": "Obj", "key_topics": []}],
        },
        "module_contents": [{"module_num": 1, "lecture_html": "<p>x</p>", "discussion_question": "q", "glossary": [], "sections": []}],
        "quiz_questions": [],
        "syllabus": {},
        "homework_spec": {},
    }
    return dbmod.save_version(shortname, "local-model", "2026-01-01", "2026-03-01", content)


def test_contract_settings_audit_logs_page_shape(client):
    dbmod.save_admin_audit("users", "create", "user", "u1", {"k": "v"}, "ok", "admin")

    response = client.get("/api/settings/audit-logs", params={"limit": 10, "offset": 0})
    assert response.status_code == 200
    payload = response.json()

    for key in ("items", "total", "limit", "offset"):
        assert key in payload
    assert isinstance(payload["items"], list)
    assert isinstance(payload["total"], int)
    assert isinstance(payload["limit"], int)
    assert isinstance(payload["offset"], int)

    row = payload["items"][0]
    for key in ("id", "area", "action", "actor", "target_type", "target_id", "detail", "status", "created_at"):
        assert key in row


def test_contract_admin_policy_shape(client):
    response = client.get("/api/settings/admin-policy")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"allowed_role_ids", "parsed_role_ids"}
    assert isinstance(payload["allowed_role_ids"], str)
    assert isinstance(payload["parsed_role_ids"], list)


def test_contract_write_capabilities_shape(client, monkeypatch):
    monkeypatch.setattr(moodle_router, "_site_functions", lambda: {"core_user_create_users"})

    response = client.get("/api/moodle/write-capabilities")
    assert response.status_code == 200
    payload = response.json()

    assert "ok" in payload
    assert "checks" in payload
    assert isinstance(payload["ok"], bool)
    assert isinstance(payload["checks"], list)
    assert payload["checks"], "checks should not be empty"

    check = payload["checks"][0]
    for key in ("key", "ok", "required", "missing"):
        assert key in check
    assert isinstance(check["required"], list)
    assert isinstance(check["missing"], list)


def test_contract_review_response_shape(client, monkeypatch):
    version = _seed_course_version("CT202")
    dbmod.set_setting("llm_url", "http://llm.local/v1")

    monkeypatch.setattr(
        courses_router.cc,
        "call_llm",
        lambda *a, **k: '{"overall":"Passed","score":91,"summary":"Looks good","sections":[{"title":"Checks","items":[{"label":"Quiz","status":"Passed","note":"ok"}]}]}',
    )

    response = client.post(
        "/api/courses/CT202/review",
        json={"agent_context": "ctx", "model_id": "model-a", "version_id": version["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    for key in ("shortname", "version_num", "overall", "score", "summary", "sections"):
        assert key in payload
    assert isinstance(payload["sections"], list)
    assert payload["overall"] in {"Passed", "Needs Revision", "Incomplete"}


def test_contract_finalize_review_shape(client, monkeypatch):
    version = _seed_course_version("CT203")
    dbmod.set_setting("llm_url", "http://llm.local/v1")

    monkeypatch.setattr(courses_router.cc, "generate_quiz_questions", lambda *a, **k: [{"question": "Q1", "options": ["A", "B", "C", "D"], "answer": "A"}])
    monkeypatch.setattr(courses_router.cc, "generate_syllabus", lambda *a, **k: {"description": "S"})

    response = client.post(
        f"/api/courses/CT203/versions/{version['id']}/finalize-review",
        json={"model_id": "model-a", "reviews": []},
    )

    assert response.status_code == 200
    payload = response.json()
    for key in ("id", "shortname", "version_num", "model_used", "start_date", "end_date", "content", "created_at"):
        assert key in payload
    assert isinstance(payload["content"], dict)
    assert "quiz_questions" in payload["content"]
    assert "syllabus" in payload["content"]
