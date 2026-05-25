from app.backend import database as dbmod
from app.backend.routers import moodle as moodle_router


def test_sensitive_write_rate_limit_blocks_excess_requests(client, monkeypatch):
    dbmod.set_setting("admin_write_rate_limit_max", "1")
    dbmod.set_setting("admin_write_rate_limit_window_s", "60")

    monkeypatch.setattr(moodle_router, "_moodle_call", lambda *a, **k: {})

    first = client.post("/api/moodle/users/77/suspend", json={"suspended": True})
    second = client.post("/api/moodle/users/77/suspend", json={"suspended": True})

    assert first.status_code == 200
    assert second.status_code == 429
    assert "Too many write requests" in second.json().get("detail", "")


def test_rate_limit_not_applied_to_read_requests(client):
    dbmod.set_setting("admin_write_rate_limit_max", "1")
    dbmod.set_setting("admin_write_rate_limit_window_s", "60")

    one = client.get("/api/settings/auth/status")
    two = client.get("/api/settings/auth/status")

    assert one.status_code == 200
    assert two.status_code == 200


def test_audit_policy_read_write_and_prune(client):
    # Create one old and one fresh row.
    with dbmod.db() as conn:
        conn.execute(
            """
            INSERT INTO admin_audit_logs
            (area, action, actor, target_type, target_id, detail_json, status, created_at)
            VALUES ('users', 'create', 'admin-a', 'user', 'old', '{}', 'ok', datetime('now', '-400 days'))
            """
        )
        conn.execute(
            """
            INSERT INTO admin_audit_logs
            (area, action, actor, target_type, target_id, detail_json, status, created_at)
            VALUES ('users', 'create', 'admin-a', 'user', 'new', '{}', 'ok', datetime('now'))
            """
        )

    policy_get = client.get("/api/settings/audit-policy")
    assert policy_get.status_code == 200
    assert "retention_days" in policy_get.json()

    policy_set = client.post("/api/settings/audit-policy", json={"retention_days": 30})
    assert policy_set.status_code == 200
    assert policy_set.json()["retention_days"] == 30

    dry_run = client.post("/api/settings/audit-logs/prune", json={"dry_run": True})
    assert dry_run.status_code == 200
    assert dry_run.json()["dry_run"] is True
    assert dry_run.json()["deleted"] >= 1

    apply = client.post("/api/settings/audit-logs/prune", json={"dry_run": False})
    assert apply.status_code == 200
    assert apply.json()["dry_run"] is False
    assert apply.json()["retention_days"] == 30
    assert apply.json()["deleted"] >= 1

    remaining = client.get("/api/settings/audit-logs", params={"q": "old"})
    assert remaining.status_code == 200
    assert remaining.json()["total"] == 0


def test_audit_policy_rejects_out_of_range_values(client):
    response = client.post("/api/settings/audit-policy", json={"retention_days": 0})
    assert response.status_code == 400
    assert "retention_days must be between 1 and 3650" in response.json().get("detail", "")
