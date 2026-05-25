"""SQLite database setup — courses, versions, settings."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "library.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS courses (
            shortname   TEXT PRIMARY KEY,
            fullname    TEXT NOT NULL,
            professor   TEXT NOT NULL DEFAULT 'Ricardo Julia',
            category    TEXT NOT NULL DEFAULT '2025 - 2026 Spring Term',
            prompt      TEXT NOT NULL DEFAULT '',
            instance    TEXT NOT NULL DEFAULT 'Local',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS course_versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            shortname   TEXT NOT NULL REFERENCES courses(shortname) ON DELETE CASCADE,
            version_num INTEGER NOT NULL,
            model_used  TEXT NOT NULL DEFAULT '',
            start_date  TEXT NOT NULL DEFAULT '',
            end_date    TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(shortname, version_num)
        );

        CREATE TABLE IF NOT EXISTS mbz_builds (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
            built_at   TEXT NOT NULL DEFAULT (datetime('now')),
            filename   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            shortname     TEXT    NOT NULL,
            version_id    INTEGER,
            version_num   INTEGER,
            agent_id      TEXT    NOT NULL DEFAULT '',
            agent_label   TEXT    NOT NULL DEFAULT '',
            agent_color   TEXT    NOT NULL DEFAULT 'gray',
            overall       TEXT,
            score         INTEGER,
            summary       TEXT,
            sections_json TEXT    NOT NULL DEFAULT '[]',
            error         TEXT,
            run_at        TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS moodle_deploys (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id       INTEGER NOT NULL,
            shortname        TEXT    NOT NULL,
            moodle_course_id INTEGER NOT NULL,
            moodle_url       TEXT    NOT NULL DEFAULT '',
            sections_pushed  INTEGER NOT NULL DEFAULT 0,
            forums_seeded    INTEGER NOT NULL DEFAULT 0,
            deployed_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS review_schedules (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            shortname     TEXT    NOT NULL,
            version_id    INTEGER,
            agent_id      TEXT    NOT NULL DEFAULT '',
            agent_label   TEXT    NOT NULL DEFAULT 'Reviewer',
            agent_color   TEXT    NOT NULL DEFAULT 'gray',
            agent_context TEXT    NOT NULL DEFAULT '',
            model_id      TEXT    NOT NULL DEFAULT '',
            frequency     TEXT    NOT NULL DEFAULT 'weekly',
            next_run_at   TEXT    NOT NULL,
            last_run_at   TEXT,
            enabled       INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS curriculum_evaluations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            shortname    TEXT    NOT NULL UNIQUE,
            version_id   INTEGER,
            model_used   TEXT    NOT NULL DEFAULT '',
            scores_json  TEXT    NOT NULL DEFAULT '{}',
            reasoning    TEXT    NOT NULL DEFAULT '',
            evaluated_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            area         TEXT    NOT NULL,
            action       TEXT    NOT NULL,
            actor        TEXT    NOT NULL DEFAULT '',
            target_type  TEXT    NOT NULL,
            target_id    TEXT    NOT NULL DEFAULT '',
            detail_json  TEXT    NOT NULL DEFAULT '{}',
            status       TEXT    NOT NULL DEFAULT 'ok',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        """)

    # Migrations for existing databases
    with db() as conn:
        for stmt in [
            "ALTER TABLE courses ADD COLUMN instance TEXT NOT NULL DEFAULT 'Local'",
            ("CREATE TABLE IF NOT EXISTS moodle_deploys ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, version_id INTEGER NOT NULL, "
             "shortname TEXT NOT NULL, moodle_course_id INTEGER NOT NULL, "
             "moodle_url TEXT NOT NULL DEFAULT '', "
             "sections_pushed INTEGER NOT NULL DEFAULT 0, "
             "forums_seeded INTEGER NOT NULL DEFAULT 0, "
             "deployed_at TEXT NOT NULL DEFAULT (datetime('now')))"),
            ("CREATE TABLE IF NOT EXISTS reviews ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, shortname TEXT NOT NULL, "
             "version_id INTEGER, version_num INTEGER, "
             "agent_id TEXT NOT NULL DEFAULT '', agent_label TEXT NOT NULL DEFAULT '', "
             "agent_color TEXT NOT NULL DEFAULT 'gray', "
             "overall TEXT, score INTEGER, summary TEXT, "
             "sections_json TEXT NOT NULL DEFAULT '[]', error TEXT, "
             "run_at TEXT NOT NULL DEFAULT (datetime('now')))"),
            ("CREATE TABLE IF NOT EXISTS review_schedules ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, shortname TEXT NOT NULL, "
             "version_id INTEGER, agent_id TEXT NOT NULL DEFAULT '', "
             "agent_label TEXT NOT NULL DEFAULT 'Reviewer', "
             "agent_color TEXT NOT NULL DEFAULT 'gray', "
             "agent_context TEXT NOT NULL DEFAULT '', "
             "model_id TEXT NOT NULL DEFAULT '', frequency TEXT NOT NULL DEFAULT 'weekly', "
             "next_run_at TEXT NOT NULL DEFAULT (datetime('now')), last_run_at TEXT, "
             "enabled INTEGER NOT NULL DEFAULT 1, "
             "created_at TEXT NOT NULL DEFAULT (datetime('now')))"),
            ("CREATE TABLE IF NOT EXISTS curriculum_evaluations ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, shortname TEXT NOT NULL UNIQUE, "
             "version_id INTEGER, model_used TEXT NOT NULL DEFAULT '', "
             "scores_json TEXT NOT NULL DEFAULT '{}', reasoning TEXT NOT NULL DEFAULT '', "
             "evaluated_at TEXT NOT NULL DEFAULT (datetime('now')))"),
            ("CREATE TABLE IF NOT EXISTS admin_audit_logs ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, area TEXT NOT NULL, "
             "action TEXT NOT NULL, actor TEXT NOT NULL DEFAULT '', target_type TEXT NOT NULL, "
             "target_id TEXT NOT NULL DEFAULT '', detail_json TEXT NOT NULL DEFAULT '{}', "
             "status TEXT NOT NULL DEFAULT 'ok', "
             "created_at TEXT NOT NULL DEFAULT (datetime('now')))"),
            "ALTER TABLE admin_audit_logs ADD COLUMN actor TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                conn.execute(stmt)
            except Exception:
                pass

    _seed_settings()


def _seed_settings():
    defaults = {
        "moodle_url":   "",
        "moodle_token": "",
        "llm_url":      "http://192.168.86.41:1234/v1",
        "llm_api_key":  "",
        "last_model":   "",
        "auth_operator_name": "",
        "admin_allowed_role_ids": "3,4,5",
    }
    with db() as conn:
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )


# ── Settings helpers ──────────────────────────────────────────────────────────

def get_settings() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_setting(key: str, value: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ── Course helpers ────────────────────────────────────────────────────────────

def list_courses() -> list[dict]:
    with db() as conn:
        rows = conn.execute("""
            SELECT c.shortname, c.fullname, c.professor, c.category,
                   c.prompt, c.instance, c.created_at,
                   COUNT(v.id) AS version_count,
                   MAX(v.version_num) AS latest_version
            FROM courses c
            LEFT JOIN course_versions v ON v.shortname = c.shortname
            GROUP BY c.shortname
            ORDER BY c.instance, c.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_course(shortname: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM courses WHERE shortname=?", (shortname,)
        ).fetchone()
    return dict(row) if row else None


def upsert_course(shortname: str, fullname: str, professor: str,
                  category: str, prompt: str, instance: str = "Local") -> dict:
    with db() as conn:
        conn.execute("""
            INSERT INTO courses(shortname, fullname, professor, category, prompt, instance)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(shortname) DO UPDATE SET
                fullname=excluded.fullname,
                professor=excluded.professor,
                category=excluded.category,
                prompt=excluded.prompt,
                instance=excluded.instance
        """, (shortname, fullname, professor, category, prompt, instance))
    return get_course(shortname)


# ── Version helpers ───────────────────────────────────────────────────────────

def list_versions(shortname: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute("""
            SELECT v.id, v.shortname, v.version_num, v.model_used,
                   v.start_date, v.end_date, v.created_at,
                   COUNT(b.id) AS build_count
            FROM course_versions v
            LEFT JOIN mbz_builds b ON b.version_id = v.id
            WHERE v.shortname=?
            GROUP BY v.id
            ORDER BY v.version_num DESC
        """, (shortname,)).fetchall()
    return [dict(r) for r in rows]


def get_version(version_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM course_versions WHERE id=?", (version_id,)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["content"] = json.loads(result["content"])
    return result


def save_version(shortname: str, model_used: str, start_date: str,
                 end_date: str, content: dict) -> dict:
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version_num), 0) AS max_v "
            "FROM course_versions WHERE shortname=?", (shortname,)
        ).fetchone()
        next_v = row["max_v"] + 1
        cur = conn.execute("""
            INSERT INTO course_versions
                (shortname, version_num, model_used, start_date, end_date, content)
            VALUES (?,?,?,?,?,?)
        """, (shortname, next_v, model_used, start_date, end_date,
              json.dumps(content, ensure_ascii=False)))
        version_id = cur.lastrowid
    return get_version(version_id)


def record_build(version_id: int, filename: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO mbz_builds(version_id, filename) VALUES(?,?)",
            (version_id, filename),
        )


def update_version_content(version_id: int, content: dict) -> dict | None:
    with db() as conn:
        conn.execute(
            "UPDATE course_versions SET content=? WHERE id=?",
            (json.dumps(content, ensure_ascii=False), version_id),
        )
    return get_version(version_id)


def delete_version(version_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM course_versions WHERE id=?", (version_id,)
        )
    return cur.rowcount > 0


def delete_course(shortname: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM courses WHERE shortname=?", (shortname,)
        )
    return cur.rowcount > 0


# ── Review helpers ────────────────────────────────────────────────────────────

def _review_row(row) -> dict:
    d = dict(row)
    d["sections"] = json.loads(d.pop("sections_json", "[]"))
    return d


def save_review(shortname: str, version_id: int | None, version_num: int | None,
                agent_id: str, agent_label: str, agent_color: str,
                result: dict) -> dict:
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO reviews
               (shortname, version_id, version_num, agent_id, agent_label, agent_color,
                overall, score, summary, sections_json, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                shortname, version_id, version_num,
                agent_id, agent_label, agent_color,
                result.get("overall"), result.get("score"),
                result.get("summary"),
                json.dumps(result.get("sections", []), ensure_ascii=False),
                result.get("error"),
            ),
        )
        return _review_row(conn.execute(
            "SELECT * FROM reviews WHERE id=?", (cur.lastrowid,)
        ).fetchone())


def list_reviews(shortname: str, version_id: int | None = None, limit: int = 50) -> list[dict]:
    with db() as conn:
        if version_id is not None:
            rows = conn.execute(
                "SELECT * FROM reviews WHERE shortname=? AND version_id=? "
                "ORDER BY run_at DESC LIMIT ?",
                (shortname, version_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reviews WHERE shortname=? ORDER BY run_at DESC LIMIT ?",
                (shortname, limit),
            ).fetchall()
    return [_review_row(r) for r in rows]


def list_recent_reviews(limit: int = 100) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM reviews ORDER BY run_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_review_row(r) for r in rows]


def delete_review(review_id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM reviews WHERE id=?", (review_id,))
    return cur.rowcount > 0


# ── Deploy helpers ────────────────────────────────────────────────────────────

def save_deploy(version_id: int, shortname: str, moodle_course_id: int,
                moodle_url: str, sections_pushed: int, forums_seeded: int) -> dict:
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO moodle_deploys
               (version_id, shortname, moodle_course_id, moodle_url,
                sections_pushed, forums_seeded)
               VALUES (?,?,?,?,?,?)""",
            (version_id, shortname, moodle_course_id, moodle_url,
             sections_pushed, forums_seeded),
        )
        row = conn.execute(
            "SELECT * FROM moodle_deploys WHERE id=?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


def list_deploys(version_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM moodle_deploys WHERE version_id=? ORDER BY deployed_at DESC",
            (version_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Review schedule helpers ───────────────────────────────────────────────────

def save_schedule(shortname: str, agent_id: str, agent_label: str, agent_color: str,
                  agent_context: str, model_id: str, frequency: str, next_run_at: str,
                  version_id: int | None = None) -> dict:
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO review_schedules
               (shortname, version_id, agent_id, agent_label, agent_color,
                agent_context, model_id, frequency, next_run_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (shortname, version_id, agent_id, agent_label, agent_color,
             agent_context, model_id, frequency, next_run_at),
        )
        row = conn.execute(
            "SELECT * FROM review_schedules WHERE id=?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


def list_schedules() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM review_schedules ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_schedule(schedule_id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM review_schedules WHERE id=?", (schedule_id,))
    return cur.rowcount > 0


def get_overdue_schedules() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM review_schedules "
            "WHERE enabled=1 AND next_run_at <= datetime('now') "
            "ORDER BY next_run_at"
        ).fetchall()
    return [dict(r) for r in rows]


def update_schedule_run(schedule_id: int, last_run_at: str, next_run_at: str):
    with db() as conn:
        conn.execute(
            "UPDATE review_schedules SET last_run_at=?, next_run_at=? WHERE id=?",
            (last_run_at, next_run_at, schedule_id),
        )


# ── Curriculum evaluations ────────────────────────────────────────────────────

def save_curriculum_eval(shortname: str, version_id: int | None, model_used: str,
                         scores: dict, reasoning: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO curriculum_evaluations"
            "(shortname, version_id, model_used, scores_json, reasoning) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(shortname) DO UPDATE SET "
            "version_id=excluded.version_id, model_used=excluded.model_used, "
            "scores_json=excluded.scores_json, reasoning=excluded.reasoning, "
            "evaluated_at=datetime('now')",
            (shortname, version_id, model_used, json.dumps(scores), reasoning),
        )


def get_curriculum_eval(shortname: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM curriculum_evaluations WHERE shortname=?", (shortname,)
        ).fetchone()
    if not row:
        return None
    r = dict(row)
    r["scores"] = json.loads(r.get("scores_json", "{}"))
    return r


def list_curriculum_evals() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM curriculum_evaluations").fetchall()
    result = []
    for row in rows:
        r = dict(row)
        r["scores"] = json.loads(r.get("scores_json", "{}"))
        result.append(r)
    return result


# ── Admin audit logs ─────────────────────────────────────────────────────────

def save_admin_audit(area: str, action: str, target_type: str,
                     target_id: str = "", detail: dict | None = None,
                            status: str = "ok", actor: str = "") -> dict:
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO admin_audit_logs
                    (area, action, actor, target_type, target_id, detail_json, status)
                    VALUES (?,?,?,?,?,?,?)""",
                (area, action, actor, target_type, target_id,
                 json.dumps(detail or {}, ensure_ascii=False), status),
        )
        row = conn.execute(
            "SELECT * FROM admin_audit_logs WHERE id=?", (cur.lastrowid,)
        ).fetchone()
    record = dict(row)
    record["detail"] = json.loads(record.pop("detail_json", "{}"))
    return record


def list_admin_audits(limit: int = 100, offset: int = 0,
                      area: str = "", action: str = "", actor: str = "",
                      status: str = "", query: str = "") -> tuple[list[dict], int]:
    where = []
    params: list = []

    if area:
        where.append("area = ?")
        params.append(area)
    if action:
        where.append("action = ?")
        params.append(action)
    if actor:
        where.append("actor LIKE ?")
        params.append(f"%{actor}%")
    if status:
        where.append("status = ?")
        params.append(status)
    if query:
        where.append("(target_id LIKE ? OR target_type LIKE ? OR detail_json LIKE ?)")
        q = f"%{query}%"
        params.extend([q, q, q])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM admin_audit_logs {where_sql}",
            tuple(params),
        ).fetchone()["c"]

        rows = conn.execute(
            f"SELECT * FROM admin_audit_logs {where_sql} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        ).fetchall()

    result = []
    for row in rows:
        record = dict(row)
        record["detail"] = json.loads(record.pop("detail_json", "{}"))
        result.append(record)
    return result, int(total)
