"""Canvas LMS REST API proxy — feature parity with Moodle integration."""

import re
import time as _time
from datetime import datetime
from collections import Counter

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import (
    get_settings,
    upsert_course,
    save_version,
    save_deploy,
    list_deploys,
    get_version,
)

router = APIRouter(prefix="/canvas", tags=["canvas"])


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _canvas_get(path: str, params: dict = None, settings: dict = None) -> dict | list:
    """Paginated GET — follows Link headers and collects all pages."""
    s = settings or get_settings()
    base  = s.get("canvas_url", "").strip().rstrip("/")
    token = s.get("canvas_token", "").strip()
    if not token:
        raise HTTPException(400, "Canvas token not configured — set it in Settings")
    if not base:
        raise HTTPException(400, "Canvas URL not configured — set it in Settings")

    url         = f"{base}/api/v1{path}"
    headers     = {"Authorization": f"Bearer {token}"}
    all_results = []
    page_params = {"per_page": 100, **(params or {})}

    while url:
        try:
            resp = requests.get(url, headers=headers, params=page_params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise HTTPException(502, f"Canvas unreachable: {e}")

        data = resp.json()
        if isinstance(data, dict) and "errors" in data:
            raise HTTPException(400, f"Canvas error: {data['errors']}")

        if isinstance(data, list):
            all_results.extend(data)
        else:
            return data

        link_header = resp.headers.get("Link", "")
        url = None
        page_params = {}
        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                break

    return all_results


def _canvas_req(method: str, path: str, payload: dict = None,
                params: dict = None, settings: dict = None) -> dict | list:
    """Single non-paginated request (POST / PUT / DELETE)."""
    s = settings or get_settings()
    base  = s.get("canvas_url", "").strip().rstrip("/")
    token = s.get("canvas_token", "").strip()
    if not token:
        raise HTTPException(400, "Canvas token not configured — set it in Settings")
    if not base:
        raise HTTPException(400, "Canvas URL not configured — set it in Settings")

    url     = f"{base}/api/v1{path}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.request(
            method, url, headers=headers,
            data=payload, params=params, timeout=30
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(502, f"Canvas unreachable: {e}")

    if resp.status_code == 204 or not resp.text.strip():
        return {}
    result = resp.json()
    if isinstance(result, dict) and "errors" in result:
        raise HTTPException(400, f"Canvas error: {result['errors']}")
    return result


# ── Utility ───────────────────────────────────────────────────────────────────

def _iso_to_epoch(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return 0


def _date_to_iso(d: str) -> str:
    """Convert YYYY-MM-DD → ISO 8601 UTC string."""
    if not d:
        return ""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%dT00:00:00Z")
    except ValueError:
        return ""


# ── Connection test ───────────────────────────────────────────────────────────

@router.get("/ping")
def ping_canvas():
    data = _canvas_get("/users/self")
    if not isinstance(data, dict):
        raise HTTPException(502, "Unexpected Canvas response")
    return {
        "ok":       True,
        "username": data.get("login_id") or data.get("email", ""),
        "fullname": data.get("name", ""),
        "id":       data.get("id"),
    }


# ── Site stats dashboard ──────────────────────────────────────────────────────

@router.get("/stats")
def canvas_stats():
    """Aggregate site-wide metrics (mirrors /moodle/stats)."""
    s      = get_settings()
    result: dict = {}

    # 1 ── Account + user info
    try:
        account = _canvas_get("/accounts/self", settings=s)
        me      = _canvas_get("/users/self",    settings=s)
        result.update({
            "site_name":             account.get("name", "Canvas LMS"),
            "release":               account.get("canvas_product_version", ""),
            "current_user_fullname": me.get("name", ""),
            "current_user_is_admin": isinstance(account, dict) and bool(account.get("id")),
        })
    except Exception as e:
        result["site_error"] = str(e)

    # 2 ── Courses
    try:
        courses_raw = _canvas_get(
            "/courses",
            {"enrollment_type": "teacher", "include[]": "total_students"},
            settings=s,
        )
        if not isinstance(courses_raw, list):
            courses_raw = []
        now_ts  = int(_time.time())
        visible = sum(1 for c in courses_raw if c.get("workflow_state") != "unpublished")
        active  = sum(
            1 for c in courses_raw
            if c.get("workflow_state") not in ("unpublished", "deleted")
            and (not c.get("start_at") or _iso_to_epoch(c.get("start_at")) <= now_ts)
            and (not c.get("end_at")   or _iso_to_epoch(c.get("end_at"))   >= now_ts)
        )
        result.update({
            "total_courses":   len(courses_raw),
            "visible_courses": visible,
            "hidden_courses":  len(courses_raw) - visible,
            "active_courses":  active,
        })
    except Exception as e:
        result["courses_error"] = str(e)
        courses_raw = []

    # 3 ── Sub-accounts (≈ categories)
    try:
        subs = _canvas_get("/accounts/1/sub_accounts", {"recursive": "true"}, settings=s)
        if isinstance(subs, list):
            result["total_categories"] = len(subs)
            cat_map = {sub["id"]: sub["name"] for sub in subs}
            cpc: dict[str, int] = {}
            for c in courses_raw:
                name = cat_map.get(c.get("account_id", 0), "Root")
                cpc[name] = cpc.get(name, 0) + 1
            result["courses_per_category"] = dict(sorted(cpc.items(), key=lambda x: -x[1]))
    except Exception as e:
        result["categories_error"] = str(e)

    # 4 ── Site-level user statistics
    try:
        stats = _canvas_get("/accounts/1/statistics", settings=s)
        if isinstance(stats, dict):
            result.update({
                "total_users":     stats.get("users", 0),
                "active_30d":      None,
                "never_logged_in": None,
                "suspended_users": None,
            })
    except Exception as e:
        result["users_error"] = str(e)

    return result


# ── Courses ───────────────────────────────────────────────────────────────────

@router.get("/courses")
def get_canvas_courses():
    raw = _canvas_get(
        "/courses",
        {"enrollment_type": "teacher", "include[]": "total_students"}
    )
    if not isinstance(raw, list):
        raw = []

    try:
        subs    = _canvas_get("/accounts/1/sub_accounts", {"recursive": "true"})
        cat_map = {sub["id"]: sub["name"] for sub in subs} if isinstance(subs, list) else {}
    except Exception:
        cat_map = {}

    courses = []
    for c in raw:
        if c.get("workflow_state") == "deleted":
            continue
        acct_id = c.get("account_id", 0)
        courses.append({
            "id":             c["id"],
            "shortname":      c.get("course_code", ""),
            "fullname":       c.get("name", ""),
            "summary":        c.get("public_description") or "",
            "startdate":      _iso_to_epoch(c.get("start_at")),
            "enddate":        _iso_to_epoch(c.get("end_at")),
            "visible":        0 if c.get("workflow_state") == "unpublished" else 1,
            "category":       acct_id,
            "category_name":  cat_map.get(acct_id, ""),
            "workflow_state": c.get("workflow_state", ""),
            "total_students": c.get("total_students", 0),
        })
    return courses


# ── Course modules (Canvas modules ≈ Moodle sections) ─────────────────────────

@router.get("/courses/{course_id}/contents")
def get_canvas_course_contents(course_id: int):
    """Return Canvas modules with items (equivalent of Moodle sections)."""
    modules_raw = _canvas_get(f"/courses/{course_id}/modules", {"include[]": "items"})
    if not isinstance(modules_raw, list):
        modules_raw = []

    sections = []
    for i, mod in enumerate(modules_raw):
        items      = mod.get("items") or []
        activities = []
        for item in items:
            activities.append({
                "id":            item.get("id"),
                "name":          item.get("title", ""),
                "modname":       item.get("type", "").lower(),
                "visible":       1,
                "url":           item.get("html_url", ""),
                "content_id":    item.get("content_id"),
                "api_updatable": item.get("type") in ("Page", "Discussion"),
            })
        sections.append({
            "id":         mod.get("id"),
            "section":    i,
            "name":       mod.get("name", f"Module {i + 1}"),
            "summary":    "",
            "activities": activities,
        })
    return sections


# ── Single module item content ────────────────────────────────────────────────

@router.get("/courses/{course_id}/modules/{item_id}")
def get_canvas_module_item(course_id: int, item_id: int):
    """Return the content of a single Canvas module item (Page or Discussion)."""
    modules_raw = _canvas_get(f"/courses/{course_id}/modules", {"include[]": "items"})
    for mod in (modules_raw if isinstance(modules_raw, list) else []):
        for item in (mod.get("items") or []):
            if item.get("id") != item_id:
                continue
            item_type    = item.get("type", "")
            content_html = ""
            url          = item.get("html_url", "")

            if item_type == "Page":
                page_url = item.get("page_url") or item.get("url", "").split("/")[-1]
                try:
                    page = _canvas_req("GET", f"/courses/{course_id}/pages/{page_url}")
                    content_html = page.get("body", "") or ""
                except Exception:
                    pass
            elif item_type == "Discussion":
                topic_id = item.get("content_id")
                try:
                    topic = _canvas_req("GET", f"/courses/{course_id}/discussion_topics/{topic_id}")
                    content_html = topic.get("message", "") or ""
                except Exception:
                    pass

            return {
                "id":           item_id,
                "name":         item.get("title", ""),
                "modname":      item_type.lower(),
                "content_html": content_html,
                "url":          url,
            }

    raise HTTPException(404, f"Item {item_id} not found in course {course_id}")


# ── Update course metadata ────────────────────────────────────────────────────

class CourseMetaIn(BaseModel):
    course_id: int
    fullname:  str = ""
    shortname: str = ""
    summary:   str = ""
    startdate: int = 0
    enddate:   int = 0


@router.post("/courses/{course_id}/meta")
def update_course_meta(course_id: int, body: CourseMetaIn):
    """Update Canvas course name, code, description, and dates."""
    payload: dict = {}
    if body.fullname:
        payload["course[name]"] = body.fullname
    if body.shortname:
        payload["course[course_code]"] = body.shortname
    if body.summary:
        payload["course[public_description]"] = body.summary
    if body.startdate:
        payload["course[start_at]"] = datetime.utcfromtimestamp(body.startdate).strftime("%Y-%m-%dT%H:%M:%SZ")
    if body.enddate:
        payload["course[end_at]"] = datetime.utcfromtimestamp(body.enddate).strftime("%Y-%m-%dT%H:%M:%SZ")

    if payload:
        _canvas_req("PUT", f"/courses/{course_id}", payload=payload)
    return {"ok": True}


# ── Update module name (≈ Moodle section summary) ─────────────────────────────

class ModuleNameIn(BaseModel):
    course_id: int
    module_id: int
    name:      str


@router.post("/modules/name")
def update_module_name(body: ModuleNameIn):
    """Rename a Canvas module (equivalent of Moodle section name)."""
    _canvas_req("PUT", f"/courses/{body.course_id}/modules/{body.module_id}",
                payload={"module[name]": body.name})
    return {"ok": True}


# ── Add discussion (≈ Moodle forum/discussion) ────────────────────────────────

class DiscussionIn(BaseModel):
    course_id: int
    title:     str
    message:   str


@router.post("/courses/{course_id}/discussion")
def add_discussion(course_id: int, body: DiscussionIn):
    """Create a new discussion topic in a Canvas course."""
    result = _canvas_req("POST", f"/courses/{course_id}/discussion_topics", payload={
        "title":           body.title,
        "message":         body.message,
        "discussion_type": "threaded",
        "published":       "true",
    })
    return {"ok": True, "discussion_id": result.get("id")}


# ── Import live Canvas course into local library ──────────────────────────────

class CanvasImportIn(BaseModel):
    shortname:  str
    fullname:   str
    start_date: str = ""
    end_date:   str = ""
    professor:  str = ""
    category:   str = ""
    instance:   str = "Canvas"


@router.post("/courses/{course_id}/import")
def import_course_to_library(course_id: int, body: CanvasImportIn):
    """Snapshot a live Canvas course's module structure into the local library."""
    modules_list    = []
    module_contents = []
    contents_warning: str | None = None

    try:
        raw_mods = _canvas_get(f"/courses/{course_id}/modules", {"include[]": "items"})
        real_mods = [m for m in (raw_mods if isinstance(raw_mods, list) else []) if m.get("name")]

        for i, mod in enumerate(real_mods[:8], start=1):
            items      = mod.get("items") or []
            activities = []
            for item in items:
                content_html = ""
                item_type    = item.get("type", "")
                if item_type == "Page":
                    page_slug = item.get("page_url") or item.get("url", "").split("/")[-1]
                    try:
                        page = _canvas_req("GET", f"/courses/{course_id}/pages/{page_slug}")
                        content_html = page.get("body", "") or ""
                    except Exception:
                        pass
                elif item_type == "Discussion":
                    topic_id = item.get("content_id")
                    try:
                        topic = _canvas_req("GET", f"/courses/{course_id}/discussion_topics/{topic_id}")
                        content_html = topic.get("message", "") or ""
                    except Exception:
                        pass
                activities.append({
                    "id":           item.get("id"),
                    "name":         item.get("title", ""),
                    "modname":      item_type.lower(),
                    "content_html": content_html,
                })

            plain = ", ".join(a["name"] for a in activities[:5] if a["name"])
            modules_list.append({
                "number":     i,
                "title":      mod.get("name", f"Module {i}"),
                "objective":  plain[:300],
                "key_topics": [],
            })
            module_contents.append({
                "module_num":          i,
                "lecture_html":        "",
                "glossary_terms":      [],
                "forum_question":      "",
                "activities_snapshot": activities,
            })
    except Exception as e:
        contents_warning = str(e)

    content = {
        "course_structure":  {"course_summary": "", "modules": modules_list},
        "module_contents":   module_contents,
        "syllabus":          {},
        "quiz_questions":    [],
        "homework_prompts":  {},
        "homework_spec":     {},
        "canvas_import":     True,
        "canvas_course_id":  course_id,
        **({"contents_warning": contents_warning} if contents_warning else {}),
    }

    professor = body.professor or get_settings().get("professor", "")
    upsert_course(body.shortname, body.fullname, professor, body.category, "",
                  instance=body.instance or "Canvas")
    version = save_version(body.shortname, "canvas-import",
                           body.start_date, body.end_date, content)
    return version


# ── Grade report ──────────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/grades")
def get_course_grades(course_id: int):
    """Return gradebook: assignments as columns, students as rows."""
    # Columns from assignments
    assignments_raw = _canvas_get(f"/courses/{course_id}/assignments")
    if not isinstance(assignments_raw, list):
        assignments_raw = []

    columns = [
        {
            "id":       a["id"],
            "name":     a.get("name", f"Assignment {a['id']}"),
            "module":   "assignment",
            "is_total": False,
            "max":      float(a.get("points_possible") or 100),
        }
        for a in assignments_raw
    ]
    columns.append({
        "id": 0, "name": "Course Total", "module": "course", "is_total": True, "max": 100,
    })

    # Enrollments for course total + student names
    enrollments = _canvas_get(
        f"/courses/{course_id}/enrollments",
        {"type[]": "StudentEnrollment", "include[]": "grades"}
    )
    if not isinstance(enrollments, list):
        enrollments = []
    enroll_map = {e["user_id"]: e for e in enrollments}

    # All submissions
    subs_raw = _canvas_get(
        f"/courses/{course_id}/students/submissions",
        {"student_ids[]": "all"}
    )
    if not isinstance(subs_raw, list):
        subs_raw = []

    sub_map: dict[int, dict[int, dict]] = {}
    for sub in subs_raw:
        uid = sub.get("user_id")
        aid = sub.get("assignment_id")
        if uid is not None and aid is not None:
            sub_map.setdefault(uid, {})[aid] = sub

    student_ids = sorted({sub.get("user_id") for sub in subs_raw if sub.get("user_id")})

    rows = []
    for uid in student_ids:
        enroll = enroll_map.get(uid, {})
        cells  = []
        for col in columns[:-1]:
            sub  = sub_map.get(uid, {}).get(col["id"], {})
            raw  = sub.get("score")
            maxg = col["max"] or 100.0
            pct  = round(float(raw) / maxg * 100, 1) if raw is not None else None
            cells.append({
                "formatted":  sub.get("grade") or ("-" if raw is None else str(raw)),
                "raw":        raw,
                "percentage": pct,
                "feedback":   "",
            })
        grades    = enroll.get("grades", {})
        total_pct = grades.get("current_score")
        cells.append({
            "formatted":  grades.get("current_grade") or (f"{total_pct}%" if total_pct is not None else "-"),
            "raw":        total_pct,
            "percentage": total_pct,
            "feedback":   "",
        })
        rows.append({
            "userid":   uid,
            "fullname": enroll.get("user", {}).get("name", f"User {uid}"),
            "cells":    cells,
        })

    # Fallback: only enrollment grades available (no submission access)
    if not rows and enrollments:
        columns = [{"id": 0, "name": "Course Total", "module": "course", "is_total": True, "max": 100}]
        for e in enrollments:
            uid    = e["user_id"]
            grades = e.get("grades", {})
            pct    = grades.get("current_score")
            rows.append({
                "userid":   uid,
                "fullname": e.get("user", {}).get("name", f"User {uid}"),
                "cells": [{
                    "formatted":  grades.get("current_grade") or (f"{pct}%" if pct is not None else "-"),
                    "raw":        pct,
                    "percentage": pct,
                    "feedback":   "",
                }],
            })

    return {"columns": columns, "rows": rows}


# ── Student analytics ─────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/analytics")
def get_course_analytics(course_id: int):
    """Enrollment stats, grade distribution, and per-quiz performance."""
    result: dict = {}
    now_ts = int(_time.time())
    cutoff = now_ts - 30 * 86400

    # 1 ── Enrollments
    try:
        enrollments = _canvas_get(
            f"/courses/{course_id}/enrollments",
            {"type[]": "StudentEnrollment", "include[]": "grades"}
        )
        if not isinstance(enrollments, list):
            enrollments = []
        result["enrollment"] = {
            "total":          len(enrollments),
            "active_30d":     sum(1 for e in enrollments
                                  if e.get("last_activity_at") and
                                  _iso_to_epoch(e.get("last_activity_at")) > cutoff),
            "never_accessed": sum(1 for e in enrollments if not e.get("last_activity_at")),
            "suspended":      sum(1 for e in enrollments if e.get("enrollment_state") == "inactive"),
        }
    except Exception as e:
        result["enrollment_error"] = str(e)
        enrollments = []
        result["enrollment"] = {"total": 0, "active_30d": 0, "never_accessed": 0, "suspended": 0}

    # 2 ── Grade distribution
    try:
        totals = [
            float(e["grades"]["current_score"])
            for e in enrollments
            if e.get("grades", {}).get("current_score") is not None
        ]
        dist = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        for pct in totals:
            if pct >= 90:   dist["A"] += 1
            elif pct >= 80: dist["B"] += 1
            elif pct >= 70: dist["C"] += 1
            elif pct >= 60: dist["D"] += 1
            else:           dist["F"] += 1

        avg       = sum(totals) / len(totals) if totals else None
        pass_rate = sum(1 for p in totals if p >= 60) / len(totals) * 100 if totals else None
        result.update({
            "grade_distribution": dist,
            "avg_grade":     round(avg, 1)       if avg       is not None else None,
            "pass_rate":     round(pass_rate, 1) if pass_rate is not None else None,
            "student_count": len(totals),
        })
    except Exception as e:
        result["grades_error"] = str(e)
        result.setdefault("grade_distribution", {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0})
        result.setdefault("avg_grade", None)
        result.setdefault("pass_rate", None)
        result.setdefault("student_count", 0)

    # 3 ── Quiz performance (capped at 10 quizzes to limit API calls)
    try:
        quizzes_raw = _canvas_get(f"/courses/{course_id}/quizzes")
        quizzes_raw = quizzes_raw[:10] if isinstance(quizzes_raw, list) else []
        quizzes     = []
        for q in quizzes_raw:
            qid  = q.get("id")
            maxg = float(q.get("points_possible") or 100) or 100.0
            try:
                sub_resp  = _canvas_get(f"/courses/{course_id}/quizzes/{qid}/submissions")
                subs_list = sub_resp.get("quiz_submissions", sub_resp) if isinstance(sub_resp, dict) else sub_resp
                grades    = [
                    float(s["kept_score"]) / maxg * 100
                    for s in subs_list if s.get("kept_score") is not None
                ]
                quizzes.append({
                    "id":            qid,
                    "name":          q.get("title", ""),
                    "attempt_count": len(subs_list),
                    "avg_grade":  round(sum(grades) / len(grades), 1)                               if grades else None,
                    "pass_rate":  round(sum(1 for g in grades if g >= 60) / len(grades) * 100, 1)   if grades else None,
                })
            except Exception:
                quizzes.append({
                    "id": qid, "name": q.get("title", ""),
                    "attempt_count": 0, "avg_grade": None, "pass_rate": None,
                })
        result["quizzes"] = quizzes
    except Exception as e:
        result["quizzes_error"] = str(e)
        result.setdefault("quizzes", [])

    return result


# ── Categories (sub-accounts) ─────────────────────────────────────────────────

@router.get("/categories")
def get_categories():
    """Return Canvas sub-accounts for UI autocomplete (≈ Moodle categories)."""
    try:
        subs = _canvas_get("/accounts/1/sub_accounts", {"recursive": "true"})
        result = [{"id": 1, "name": "Root Account"}]
        if isinstance(subs, list):
            result.extend({"id": s["id"], "name": s["name"]} for s in subs)
        return result
    except Exception:
        return [{"id": 1, "name": "Default"}]


# ── Deploy local version to Canvas ───────────────────────────────────────────

class DeployIn(BaseModel):
    version_id: int
    shortname:  str
    fullname:   str
    account_id: int = 1
    start_date: str = ""
    end_date:   str = ""


@router.post("/deploy")
def deploy_to_canvas(body: DeployIn):
    """Create a course in Canvas and push module content as Pages + Discussions."""
    v = get_version(body.version_id)
    if not v:
        raise HTTPException(404, "Version not found")

    content  = v["content"]
    modules  = content.get("course_structure", {}).get("modules", [])
    mcs      = content.get("module_contents", [])

    s          = get_settings()
    canvas_url = s.get("canvas_url", "").rstrip("/")

    # 1 ── Create the course shell
    course_payload: dict = {
        "course[name]":        body.fullname,
        "course[course_code]": body.shortname,
    }
    if body.start_date:
        course_payload["course[start_at]"] = _date_to_iso(body.start_date)
    if body.end_date:
        course_payload["course[end_at]"]   = _date_to_iso(body.end_date)

    new_course = _canvas_req("POST", f"/accounts/{body.account_id}/courses",
                             payload=course_payload)
    if not isinstance(new_course, dict) or not new_course.get("id"):
        raise HTTPException(502, "Canvas did not return a course ID")
    canvas_id = new_course["id"]

    # 2 ── Push each module
    pushed             = 0
    discussions_seeded = 0

    for mod in modules:
        num          = mod["number"]
        mc           = next((m for m in mcs if m.get("module_num") == num), {})
        lecture_html = mc.get("lecture_html", "") or ""
        forum_q      = (mc.get("forum_question") or mc.get("discussion_question") or "").strip()

        mod_resp  = _canvas_req("POST", f"/courses/{canvas_id}/modules",
                                payload={"module[name]": mod["title"]})
        module_id = mod_resp.get("id") if isinstance(mod_resp, dict) else None
        if not module_id:
            continue

        try:
            _canvas_req("PUT", f"/courses/{canvas_id}/modules/{module_id}",
                        payload={"module[published]": "true"})
        except Exception:
            pass

        if lecture_html:
            try:
                page_title = mod["title"]
                page_resp  = _canvas_req("POST", f"/courses/{canvas_id}/pages", payload={
                    "wiki_page[title]":     page_title,
                    "wiki_page[body]":      lecture_html,
                    "wiki_page[published]": "true",
                })
                page_slug = page_resp.get("url", "") if isinstance(page_resp, dict) else ""
                if page_slug:
                    _canvas_req("POST", f"/courses/{canvas_id}/modules/{module_id}/items", payload={
                        "module_item[title]":    page_title,
                        "module_item[type]":     "Page",
                        "module_item[page_url]": page_slug,
                    })
            except Exception:
                pass

        if forum_q:
            try:
                disc_resp = _canvas_req("POST", f"/courses/{canvas_id}/discussion_topics", payload={
                    "title":           mod["title"],
                    "message":         forum_q,
                    "discussion_type": "threaded",
                    "published":       "true",
                })
                topic_id = disc_resp.get("id") if isinstance(disc_resp, dict) else None
                if topic_id:
                    _canvas_req("POST", f"/courses/{canvas_id}/modules/{module_id}/items", payload={
                        "module_item[title]":      mod["title"] + " Discussion",
                        "module_item[type]":       "Discussion",
                        "module_item[content_id]": topic_id,
                    })
                    discussions_seeded += 1
            except Exception:
                pass

        pushed += 1

    course_url = f"{canvas_url}/courses/{canvas_id}"

    # 3 ── Persist deploy record (reuses moodle_deploys table)
    try:
        save_deploy(
            version_id=body.version_id,
            shortname=body.shortname,
            moodle_course_id=canvas_id,
            moodle_url=course_url,
            sections_pushed=pushed,
            forums_seeded=discussions_seeded,
        )
    except Exception:
        pass

    return {
        "canvas_course_id":   canvas_id,
        "url":                course_url,
        "modules_pushed":     pushed,
        "discussions_seeded": discussions_seeded,
    }


# ── Deploy history ─────────────────────────────────────────────────────────────

@router.get("/deploys")
def get_deploys(version_id: int):
    """Return deploy history for a specific course version."""
    rows = list_deploys(version_id)
    return [
        {
            **r,
            "canvas_course_id":   r.get("moodle_course_id"),
            "canvas_url":         r.get("moodle_url"),
            "modules_pushed":     r.get("sections_pushed"),
            "discussions_seeded": r.get("forums_seeded"),
        }
        for r in rows
    ]


# ── Capabilities ──────────────────────────────────────────────────────────────

@router.get("/capabilities")
def get_capabilities():
    return [
        {"modname": "page",       "can_push": True,
         "note": "Page body can be created/updated via Canvas Pages API"},
        {"modname": "discussion", "can_push": True,
         "note": "Discussion topics can be created via Canvas Discussion Topics API"},
        {"modname": "assignment", "can_push": False,
         "note": "Assignment rubrics and instructions require manual setup"},
        {"modname": "quiz",       "can_push": False,
         "note": "Quiz questions require the Canvas Quiz Engine API (not REST)"},
        {"modname": "course",     "can_push": True,
         "note": "Course name, code, dates, description updatable via Courses API"},
        {"modname": "module",     "can_push": True,
         "note": "Module names updatable via Modules API"},
    ]
