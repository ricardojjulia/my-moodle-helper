import json
from fastapi import HTTPException

from app.backend import database as dbmod
from app.backend.routers import moodle as moodle_router


def _latest_audit() -> dict:
    with dbmod.db() as conn:
        row = conn.execute(
            "SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None, "Expected at least one audit log row"
    result = dict(row)
    result["detail"] = json.loads(result.pop("detail_json", "{}"))
    return result


def test_create_user_validation_failure_is_audited(client, monkeypatch):
    def _unexpected_call(*args, **kwargs):
        raise AssertionError("_moodle_call should not run for local password validation errors")

    monkeypatch.setattr(moodle_router, "_moodle_call", _unexpected_call)

    payload = {
        "username": "new-user",
        "firstname": "New",
        "lastname": "User",
        "email": "new.user@example.com",
        "password": "short",
        "auth": "manual",
    }
    response = client.post("/api/moodle/users", json=payload)

    assert response.status_code == 400
    assert "Password must be at least 12 characters" in response.json().get("detail", "")

    audit = _latest_audit()
    assert audit["area"] == "users"
    assert audit["action"] == "create"
    assert audit["target_type"] == "user"
    assert audit["target_id"] == "new-user"
    assert audit["status"] == "error"
    assert audit["actor"] == "local-admin"
    assert audit["detail"]["username"] == "new-user"
    assert audit["detail"]["email"] == "new.user@example.com"
    assert audit["detail"]["status_code"] == 400
    assert "Password must be at least 12 characters" in audit["detail"]["error"]


def test_create_user_success_is_audited(client, monkeypatch):
    def _fake_moodle_call(function: str, params: dict | None = None, settings=None):
        assert function == "core_user_create_users"
        assert params is not None
        assert params["users[0][username]"] == "good-user"
        return [{"id": 321}]

    monkeypatch.setattr(moodle_router, "_moodle_call", _fake_moodle_call)

    payload = {
        "username": "good-user",
        "firstname": "Good",
        "lastname": "User",
        "email": "good.user@example.com",
        "password": "StrongPass#2026",
        "auth": "manual",
    }
    response = client.post("/api/moodle/users", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["id"] == 321

    audit = _latest_audit()
    assert audit["area"] == "users"
    assert audit["action"] == "create"
    assert audit["target_type"] == "user"
    assert audit["target_id"] == "321"
    assert audit["status"] == "ok"
    assert audit["detail"]["id"] == 321
    assert audit["detail"]["username"] == "good-user"


def test_enroll_role_policy_failure_is_audited(client, monkeypatch):
    def _unexpected_call(*args, **kwargs):
        raise AssertionError("_moodle_call should not run for local role policy blocks")

    monkeypatch.setattr(moodle_router, "_moodle_call", _unexpected_call)

    response = client.post(
        "/api/moodle/courses/42/enrollments",
        json={"user_id": 10, "role_id": 99},
    )

    assert response.status_code == 400
    assert "Role 99 is not allowed by policy" in response.json().get("detail", "")

    audit = _latest_audit()
    assert audit["area"] == "enrollment"
    assert audit["action"] == "enroll"
    assert audit["target_type"] == "course_user"
    assert audit["target_id"] == "42:10"
    assert audit["status"] == "error"
    assert audit["detail"]["course_id"] == 42
    assert audit["detail"]["user_id"] == 10
    assert audit["detail"]["role_id"] == 99
    assert audit["detail"]["status_code"] == 400


def test_enroll_success_is_audited(client, monkeypatch):
    calls = []

    def _fake_moodle_call(function: str, params: dict | None = None, settings=None):
        calls.append((function, params))
        return {}

    monkeypatch.setattr(moodle_router, "_moodle_call", _fake_moodle_call)

    response = client.post(
        "/api/moodle/courses/42/enrollments",
        json={"user_id": 10, "role_id": 5},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls and calls[0][0] == "enrol_manual_enrol_users"

    audit = _latest_audit()
    assert audit["area"] == "enrollment"
    assert audit["action"] == "enroll"
    assert audit["target_type"] == "course_user"
    assert audit["target_id"] == "42:10"
    assert audit["status"] == "ok"
    assert audit["detail"]["course_id"] == 42
    assert audit["detail"]["user_id"] == 10
    assert audit["detail"]["role_id"] == 5


def test_suspend_user_success_is_audited(client, monkeypatch):
    calls = []

    def _fake_moodle_call(function: str, params: dict | None = None, settings=None):
        calls.append((function, params))
        return {}

    monkeypatch.setattr(moodle_router, "_moodle_call", _fake_moodle_call)

    response = client.post("/api/moodle/users/77/suspend", json={"suspended": True})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls and calls[0][0] == "core_user_update_users"

    audit = _latest_audit()
    assert audit["area"] == "users"
    assert audit["action"] == "suspend"
    assert audit["target_type"] == "user"
    assert audit["target_id"] == "77"
    assert audit["status"] == "ok"
    assert audit["detail"]["user_id"] == 77
    assert audit["detail"]["suspended"] is True


def test_unsuspend_user_success_is_audited(client, monkeypatch):
    calls = []

    def _fake_moodle_call(function: str, params: dict | None = None, settings=None):
        calls.append((function, params))
        return {}

    monkeypatch.setattr(moodle_router, "_moodle_call", _fake_moodle_call)

    response = client.post("/api/moodle/users/77/suspend", json={"suspended": False})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls and calls[0][0] == "core_user_update_users"

    audit = _latest_audit()
    assert audit["area"] == "users"
    assert audit["action"] == "unsuspend"
    assert audit["target_type"] == "user"
    assert audit["target_id"] == "77"
    assert audit["status"] == "ok"
    assert audit["detail"]["user_id"] == 77
    assert audit["detail"]["suspended"] is False


def test_delete_user_success_is_audited(client, monkeypatch):
    calls = []

    def _fake_moodle_call(function: str, params: dict | None = None, settings=None):
        calls.append((function, params))
        return {}

    monkeypatch.setattr(moodle_router, "_moodle_call", _fake_moodle_call)

    response = client.delete("/api/moodle/users/88")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls and calls[0][0] == "core_user_delete_users"

    audit = _latest_audit()
    assert audit["area"] == "users"
    assert audit["action"] == "delete"
    assert audit["target_type"] == "user"
    assert audit["target_id"] == "88"
    assert audit["status"] == "ok"
    assert audit["detail"]["user_id"] == 88


def test_assign_role_policy_failure_is_audited(client, monkeypatch):
    def _unexpected_call(*args, **kwargs):
        raise AssertionError("_moodle_call should not run for local role policy blocks")

    monkeypatch.setattr(moodle_router, "_moodle_call", _unexpected_call)

    response = client.post(
        "/api/moodle/courses/42/roles/assign",
        json={"user_id": 10, "role_id": 99},
    )

    assert response.status_code == 400
    assert "Role 99 is not allowed by policy" in response.json().get("detail", "")

    audit = _latest_audit()
    assert audit["area"] == "enrollment"
    assert audit["action"] == "assign_role"
    assert audit["target_type"] == "course_user_role"
    assert audit["target_id"] == "42:10:99"
    assert audit["status"] == "error"
    assert audit["detail"]["course_id"] == 42
    assert audit["detail"]["user_id"] == 10
    assert audit["detail"]["role_id"] == 99
    assert audit["detail"]["status_code"] == 400


def test_assign_role_success_is_audited(client, monkeypatch):
    calls = []

    def _fake_moodle_call(function: str, params: dict | None = None, settings=None):
        calls.append((function, params))
        if function == "core_course_get_courses_by_field":
            return {"courses": [{"contextid": 999}]}
        return {}

    monkeypatch.setattr(moodle_router, "_moodle_call", _fake_moodle_call)

    response = client.post(
        "/api/moodle/courses/42/roles/assign",
        json={"user_id": 10, "role_id": 5},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert [name for name, _ in calls] == [
        "core_course_get_courses_by_field",
        "core_role_assign_roles",
    ]

    audit = _latest_audit()
    assert audit["area"] == "enrollment"
    assert audit["action"] == "assign_role"
    assert audit["target_type"] == "course_user_role"
    assert audit["target_id"] == "42:10:5"
    assert audit["status"] == "ok"
    assert audit["detail"]["course_id"] == 42
    assert audit["detail"]["user_id"] == 10
    assert audit["detail"]["role_id"] == 5


def test_unassign_role_policy_failure_is_audited(client, monkeypatch):
    def _unexpected_call(*args, **kwargs):
        raise AssertionError("_moodle_call should not run for local role policy blocks")

    monkeypatch.setattr(moodle_router, "_moodle_call", _unexpected_call)

    response = client.post(
        "/api/moodle/courses/42/roles/unassign",
        json={"user_id": 10, "role_id": 99},
    )

    assert response.status_code == 400
    assert "Role 99 is not allowed by policy" in response.json().get("detail", "")

    audit = _latest_audit()
    assert audit["area"] == "enrollment"
    assert audit["action"] == "unassign_role"
    assert audit["target_type"] == "course_user_role"
    assert audit["target_id"] == "42:10:99"
    assert audit["status"] == "error"
    assert audit["detail"]["course_id"] == 42
    assert audit["detail"]["user_id"] == 10
    assert audit["detail"]["role_id"] == 99
    assert audit["detail"]["status_code"] == 400


def test_unassign_role_success_is_audited(client, monkeypatch):
    calls = []

    def _fake_moodle_call(function: str, params: dict | None = None, settings=None):
        calls.append((function, params))
        if function == "core_course_get_courses_by_field":
            return {"courses": [{"contextid": 999}]}
        return {}

    monkeypatch.setattr(moodle_router, "_moodle_call", _fake_moodle_call)

    response = client.post(
        "/api/moodle/courses/42/roles/unassign",
        json={"user_id": 10, "role_id": 5},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert [name for name, _ in calls] == [
        "core_course_get_courses_by_field",
        "core_role_unassign_roles",
    ]

    audit = _latest_audit()
    assert audit["area"] == "enrollment"
    assert audit["action"] == "unassign_role"
    assert audit["target_type"] == "course_user_role"
    assert audit["target_id"] == "42:10:5"
    assert audit["status"] == "ok"
    assert audit["detail"]["course_id"] == 42
    assert audit["detail"]["user_id"] == 10
    assert audit["detail"]["role_id"] == 5


def test_suspend_user_upstream_error_is_audited(client, monkeypatch):
    def _failing_call(function: str, params: dict | None = None, settings=None):
        raise HTTPException(400, "Moodle error: cannot update user")

    monkeypatch.setattr(moodle_router, "_moodle_call", _failing_call)

    response = client.post("/api/moodle/users/77/suspend", json={"suspended": True})

    assert response.status_code == 400
    assert "cannot update user" in response.json().get("detail", "")

    audit = _latest_audit()
    assert audit["area"] == "users"
    assert audit["action"] == "suspend"
    assert audit["target_type"] == "user"
    assert audit["target_id"] == "77"
    assert audit["status"] == "error"
    assert audit["detail"]["user_id"] == 77
    assert audit["detail"]["suspended"] is True
    assert audit["detail"]["status_code"] == 400
    assert "cannot update user" in audit["detail"]["error"]


def test_delete_user_upstream_error_is_audited(client, monkeypatch):
    def _failing_call(function: str, params: dict | None = None, settings=None):
        raise HTTPException(400, "Moodle error: cannot delete user")

    monkeypatch.setattr(moodle_router, "_moodle_call", _failing_call)

    response = client.delete("/api/moodle/users/88")

    assert response.status_code == 400
    assert "cannot delete user" in response.json().get("detail", "")

    audit = _latest_audit()
    assert audit["area"] == "users"
    assert audit["action"] == "delete"
    assert audit["target_type"] == "user"
    assert audit["target_id"] == "88"
    assert audit["status"] == "error"
    assert audit["detail"]["user_id"] == 88
    assert audit["detail"]["status_code"] == 400
    assert "cannot delete user" in audit["detail"]["error"]


def test_assign_role_upstream_error_is_audited(client, monkeypatch):
    calls = []

    def _failing_call(function: str, params: dict | None = None, settings=None):
        calls.append(function)
        if function == "core_course_get_courses_by_field":
            return {"courses": [{"contextid": 999}]}
        raise HTTPException(400, "Moodle error: cannot assign role")

    monkeypatch.setattr(moodle_router, "_moodle_call", _failing_call)

    response = client.post(
        "/api/moodle/courses/42/roles/assign",
        json={"user_id": 10, "role_id": 5},
    )

    assert response.status_code == 400
    assert calls == ["core_course_get_courses_by_field", "core_role_assign_roles"]
    assert "cannot assign role" in response.json().get("detail", "")

    audit = _latest_audit()
    assert audit["area"] == "enrollment"
    assert audit["action"] == "assign_role"
    assert audit["target_type"] == "course_user_role"
    assert audit["target_id"] == "42:10:5"
    assert audit["status"] == "error"
    assert audit["detail"]["course_id"] == 42
    assert audit["detail"]["user_id"] == 10
    assert audit["detail"]["role_id"] == 5
    assert audit["detail"]["status_code"] == 400
    assert "cannot assign role" in audit["detail"]["error"]


def test_unassign_role_upstream_error_is_audited(client, monkeypatch):
    calls = []

    def _failing_call(function: str, params: dict | None = None, settings=None):
        calls.append(function)
        if function == "core_course_get_courses_by_field":
            return {"courses": [{"contextid": 999}]}
        raise HTTPException(400, "Moodle error: cannot unassign role")

    monkeypatch.setattr(moodle_router, "_moodle_call", _failing_call)

    response = client.post(
        "/api/moodle/courses/42/roles/unassign",
        json={"user_id": 10, "role_id": 5},
    )

    assert response.status_code == 400
    assert calls == ["core_course_get_courses_by_field", "core_role_unassign_roles"]
    assert "cannot unassign role" in response.json().get("detail", "")

    audit = _latest_audit()
    assert audit["area"] == "enrollment"
    assert audit["action"] == "unassign_role"
    assert audit["target_type"] == "course_user_role"
    assert audit["target_id"] == "42:10:5"
    assert audit["status"] == "error"
    assert audit["detail"]["course_id"] == 42
    assert audit["detail"]["user_id"] == 10
    assert audit["detail"]["role_id"] == 5
    assert audit["detail"]["status_code"] == 400
    assert "cannot unassign role" in audit["detail"]["error"]
