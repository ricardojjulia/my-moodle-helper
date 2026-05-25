from app.backend import database as dbmod


def _seed_audits():
    dbmod.save_admin_audit(
        area="users",
        action="create",
        target_type="user",
        target_id="u-1",
        detail={"email": "one@example.com", "note": "alpha"},
        status="ok",
        actor="admin-a",
    )
    dbmod.save_admin_audit(
        area="users",
        action="delete",
        target_type="user",
        target_id="u-2",
        detail={"email": "two@example.com", "note": "beta"},
        status="error",
        actor="admin-b",
    )
    dbmod.save_admin_audit(
        area="enrollment",
        action="enroll",
        target_type="course_user",
        target_id="42:10",
        detail={"course_id": 42, "user_id": 10, "note": "gamma"},
        status="ok",
        actor="admin-a",
    )


def test_admin_policy_defaults(client):
    response = client.get("/api/settings/admin-policy")

    assert response.status_code == 200
    body = response.json()
    assert body["allowed_role_ids"] == "3,4,5"
    assert body["parsed_role_ids"] == [3, 4, 5]


def test_admin_policy_set_normalizes_and_saves(client):
    response = client.post("/api/settings/admin-policy", json={"allowed_role_ids": "5,3,3,4"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["allowed_role_ids"] == "3,4,5"
    assert body["parsed_role_ids"] == [3, 4, 5]

    check = client.get("/api/settings/admin-policy")
    assert check.status_code == 200
    assert check.json()["allowed_role_ids"] == "3,4,5"


def test_admin_policy_rejects_invalid_role_tokens(client):
    response = client.post("/api/settings/admin-policy", json={"allowed_role_ids": "3,abc"})

    assert response.status_code == 400
    assert "Invalid role id 'abc'" in response.json().get("detail", "")


def test_audit_logs_filtering_and_pagination(client):
    _seed_audits()

    all_rows = client.get("/api/settings/audit-logs")
    assert all_rows.status_code == 200
    payload = all_rows.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 3

    only_users = client.get("/api/settings/audit-logs", params={"area": "users"})
    assert only_users.status_code == 200
    users_payload = only_users.json()
    assert users_payload["total"] == 2
    assert all(item["area"] == "users" for item in users_payload["items"])

    only_errors = client.get("/api/settings/audit-logs", params={"status": "error"})
    assert only_errors.status_code == 200
    err_payload = only_errors.json()
    assert err_payload["total"] == 1
    assert len(err_payload["items"]) == 1
    assert err_payload["items"][0]["status"] == "error"

    by_query = client.get("/api/settings/audit-logs", params={"q": "u-2"})
    assert by_query.status_code == 200
    q_payload = by_query.json()
    assert q_payload["total"] == 1
    assert q_payload["items"][0]["target_id"] == "u-2"

    paged = client.get("/api/settings/audit-logs", params={"limit": 1, "offset": 1})
    assert paged.status_code == 200
    paged_payload = paged.json()
    assert paged_payload["limit"] == 1
    assert paged_payload["offset"] == 1
    assert paged_payload["total"] == 3
    assert len(paged_payload["items"]) == 1


def test_audit_logs_limit_is_clamped(client):
    _seed_audits()

    response = client.get("/api/settings/audit-logs", params={"limit": 9999, "offset": -5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 500
    assert payload["offset"] == 0
