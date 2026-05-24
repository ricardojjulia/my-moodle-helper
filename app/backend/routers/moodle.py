"""Moodle REST API proxy — fetch courses, inspect structure, push updates."""

import requests
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_settings, get_version, upsert_course, save_version, save_deploy, list_deploys

router = APIRouter(prefix="/moodle", tags=["moodle"])


def _moodle_call(function: str, params: dict = None, settings: dict = None) -> dict | list:
    s = settings or get_settings()
    url   = s.get("moodle_url", "").rstrip("/") + "/webservice/rest/server.php"
    token = s.get("moodle_token", "")
    if not token:
        raise HTTPException(400, "Moodle token not configured — set it in Settings")

    payload = {
        "wstoken":             token,
        "moodlewsrestformat":  "json",
        "wsfunction":          function,
        **(params or {}),
    }
    try:
        resp = requests.post(url, data=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(502, f"Moodle unreachable: {e}")

    data = resp.json()
    if isinstance(data, dict) and "exception" in data:
        raise HTTPException(400, f"Moodle error: {data.get('message', data)}")
    return data


# ── Connection test ───────────────────────────────────────────────────────────

@router.get("/ping")
def ping_moodle():
    data = _moodle_call("core_webservice_get_site_info")
    return {
        "ok":          True,
        "site_name":   data.get("sitename"),
        "moodle_version": data.get("release"),
        "username":    data.get("username"),
        "fullname":    data.get("fullname"),
    }


# ── Courses ───────────────────────────────────────────────────────────────────

@router.get("/courses")
def get_moodle_courses():
    data = _moodle_call("core_course_get_courses")

    # Build category id → name map
    cat_map: dict[int, str] = {}
    try:
        cats = _moodle_call("core_course_get_categories")
        cat_map = {c["id"]: c["name"] for c in cats}
    except Exception:
        pass

    courses = []
    for c in data:
        if c.get("id", 0) == 1:  # skip site-level course
            continue
        cat_id = c.get("categoryid", 0)
        courses.append({
            "id":            c["id"],
            "shortname":     c.get("shortname", ""),
            "fullname":      c.get("fullname", ""),
            "summary":       c.get("summary", ""),
            "startdate":     c.get("startdate", 0),
            "enddate":       c.get("enddate", 0),
            "visible":       c.get("visible", 1),
            "category":      cat_id,
            "category_name": cat_map.get(cat_id, ""),
        })
    return courses


@router.get("/courses/{course_id}/contents")
def get_course_contents(course_id: int):
    """Return sections + activities with their type and current name."""
    data = _moodle_call("core_course_get_contents",
                        {"courseid": course_id})
    sections = []
    for sec in data:
        activities = []
        for mod in sec.get("modules", []):
            activities.append({
                "id":       mod.get("id"),
                "name":     mod.get("name"),
                "modname":  mod.get("modname"),
                "visible":  mod.get("visible", 1),
                "url":      mod.get("url", ""),
                # what can be pushed via API
                "api_updatable": mod.get("modname") == "forum",
            })
        sections.append({
            "id":         sec.get("id"),
            "section":    sec.get("section"),
            "name":       sec.get("name") or f"Section {sec.get('section', 0)}",
            "summary":    sec.get("summary", ""),
            "activities": activities,
        })
    return sections


# ── Push updates ──────────────────────────────────────────────────────────────

class SectionUpdateIn(BaseModel):
    section_id: int
    summary: str


class ForumPostIn(BaseModel):
    forum_id: int         # cmid of the forum activity
    subject: str
    message: str


class CourseMetaIn(BaseModel):
    course_id: int
    fullname: str = ""
    shortname: str = ""
    summary: str = ""
    startdate: int = 0
    enddate: int = 0


@router.post("/courses/{course_id}/meta")
def update_course_meta(course_id: int, body: CourseMetaIn):
    """Update course name, dates, summary."""
    update = {"courses[0][id]": course_id}
    if body.fullname:
        update["courses[0][fullname]"] = body.fullname
    if body.shortname:
        update["courses[0][shortname]"] = body.shortname
    if body.summary:
        update["courses[0][summary]"]       = body.summary
        update["courses[0][summaryformat]"] = 1
    if body.startdate:
        update["courses[0][startdate]"] = body.startdate
    if body.enddate:
        update["courses[0][enddate]"] = body.enddate

    _moodle_call("core_course_update_courses", update)
    return {"ok": True}


@router.post("/sections/summary")
def update_section_summary(body: SectionUpdateIn):
    """Update a section's summary text."""
    _moodle_call("core_course_edit_section", {
        "sectionid": body.section_id,
        "summaryformat": 1,
        "summary": body.summary,
    })
    return {"ok": True}


@router.post("/forum/discussion")
def add_forum_discussion(body: ForumPostIn):
    """Add a new discussion post to a forum."""
    result = _moodle_call("mod_forum_add_discussion", {
        "forumid": body.forum_id,
        "subject": body.subject,
        "message": body.message,
        "messageformat": 1,
    })
    return {"ok": True, "discussion_id": result.get("discussionid")}


# ── Import live course into local library ────────────────────────────────────

class MoodleImportIn(BaseModel):
    shortname: str
    fullname: str
    start_date: str = ""
    end_date: str = ""
    professor: str = ""
    category: str = ""
    instance: str = "Local"


@router.post("/courses/{course_id}/import")
def import_course_to_library(course_id: int, body: MoodleImportIn):
    """Snapshot a live Moodle course's section structure into the local library."""
    import re

    # Fetch section structure — fall back to metadata-only if Moodle times out
    # or returns an error (hidden courses, rate-limiting, etc.)
    modules = []
    module_contents = []
    contents_warning = None
    try:
        sections_raw = _moodle_call("core_course_get_contents", {"courseid": course_id})
        real_sections = [s for s in sections_raw if s.get("section", 0) != 0]

        for i, sec in enumerate(real_sections[:5], start=1):
            summary = sec.get("summary") or ""
            plain = re.sub(r"<[^>]+>", "", summary).strip()

            activities = []
            for m in sec.get("modules", []):
                content_html = ""
                for c in m.get("contents", []):
                    if c.get("type") == "content":
                        content_html = c.get("content", "")
                        break
                if not content_html:
                    content_html = m.get("description", "") or ""
                activities.append({
                    "id":           m.get("id"),
                    "name":         m.get("name"),
                    "modname":      m.get("modname"),
                    "content_html": content_html,
                })

            modules.append({
                "number": i,
                "title": sec.get("name") or f"Module {i}",
                "objective": plain[:300],
                "key_topics": [],
            })
            module_contents.append({
                "module_num": i,
                "lecture_html": summary,
                "glossary_terms": [],
                "forum_question": "",
                "activities_snapshot": activities,
            })
    except Exception as e:
        # Save metadata-only version rather than failing the whole import
        contents_warning = str(e)

    content = {
        "course_structure":  {"course_summary": "", "modules": modules},
        "module_contents":   module_contents,
        "syllabus":          {},
        "quiz_questions":    [],
        "homework_prompts":  {},
        "homework_spec":     {},
        "moodle_import":     True,
        "moodle_course_id":  course_id,
        **({"contents_warning": contents_warning} if contents_warning else {}),
    }

    professor = body.professor or get_settings().get("professor", "")
    upsert_course(body.shortname, body.fullname, professor, body.category, "",
                  instance=body.instance or "Local")
    version = save_version(body.shortname, "moodle-import",
                           body.start_date, body.end_date, content)
    return version


# ── Single module content ─────────────────────────────────────────────────────

@router.get("/courses/{course_id}/modules/{cmid}")
def get_module_content(course_id: int, cmid: int):
    """Return the HTML body and description of a single course module."""
    sections = _moodle_call("core_course_get_contents", {"courseid": course_id})
    for sec in sections:
        for mod in sec.get("modules", []):
            if mod.get("id") != cmid:
                continue
            # Inline content (page body, label HTML, etc.)
            content_html = ""
            for c in mod.get("contents", []):
                if c.get("type") == "content":
                    content_html = c.get("content", "")
                    break
            # Assignment / forum description fallback
            if not content_html:
                content_html = mod.get("description", "")
            return {
                "id":           cmid,
                "name":         mod.get("name", ""),
                "modname":      mod.get("modname", ""),
                "content_html": content_html,
                "url":          mod.get("url", ""),
            }
    raise HTTPException(404, f"Module {cmid} not found in course {course_id}")


# ── Check for existing backup files ──────────────────────────────────────────

@router.get("/courses/{course_id}/backups")
def get_course_backups(course_id: int):
    """Check Moodle's automated backup area for existing .mbz files."""
    s = get_settings()
    moodle_url = s.get("moodle_url", "").rstrip("/")
    token = s.get("moodle_token", "")

    try:
        data = _moodle_call("core_files_get_files", {
            "contextid":    -1,
            "contextlevel": "course",
            "instanceid":   course_id,
            "component":    "backup",
            "filearea":     "automated",
            "itemid":       0,
            "filepath":     "/",
            "filename":     "",
        })
    except Exception:
        return {"files": []}

    files = []
    for f in data.get("files", []):
        name = f.get("filename", "")
        if not name or name == ".":
            continue
        ctx = f.get("contextid", "")
        dl_url = (
            f"{moodle_url}/webservice/pluginfile.php/{ctx}/backup/automated/1/{name}"
            f"?token={token}"
        )
        files.append({
            "filename":    name,
            "size_kb":     round(f.get("filesize", 0) / 1024, 1),
            "modified":    f.get("timemodified", 0),
            "download_url": dl_url,
        })
    return {"files": files}


# ── Site metrics dashboard ────────────────────────────────────────────────────

@router.get("/stats")
def get_moodle_stats():
    """Aggregate site-wide metrics from the connected Moodle instance."""
    import time as _time
    from collections import Counter

    s = get_settings()   # fetch once; pass to all concurrent calls
    result: dict = {}
    real_courses: list = []

    # 1 ── Site info
    try:
        info = _moodle_call("core_webservice_get_site_info", settings=s)
        functions = [f.get("name", "") for f in info.get("functions", [])]
        result.update({
            "site_name":              info.get("sitename", ""),
            "release":                info.get("release", ""),
            "current_user_fullname":  info.get("fullname", ""),
            "current_user_is_admin":  bool(info.get("userissiteadmin", False)),
            "mobile_service_enabled": any(n.startswith("tool_mobile") for n in functions),
            "api_functions_count":    len(functions),
        })
    except Exception as e:
        result["site_error"] = str(e)

    # 2 ── Courses  (also compute "currently active" from dates)
    try:
        courses = _moodle_call("core_course_get_courses", settings=s)
        real_courses = [c for c in courses if c.get("id", 0) != 1]
        now_ts  = int(_time.time())
        visible = sum(1 for c in real_courses if c.get("visible", 1))
        active  = sum(
            1 for c in real_courses
            if c.get("visible", 1)
            and (c.get("startdate") or 0) <= now_ts
            and ((c.get("enddate") or 0) == 0 or (c.get("enddate") or 0) >= now_ts)
        )
        result.update({
            "total_courses":   len(real_courses),
            "visible_courses": visible,
            "hidden_courses":  len(real_courses) - visible,
            "active_courses":  active,
        })
    except Exception as e:
        result["courses_error"] = str(e)

    # 3 ── Categories
    try:
        cats = _moodle_call("core_course_get_categories", settings=s)
        result["total_categories"] = len(cats)
        cat_map = {c["id"]: c["name"] for c in cats}
        cpc: dict[str, int] = {}
        for c in real_courses:
            name = cat_map.get(c.get("categoryid", 0), "Unknown")
            cpc[name] = cpc.get(name, 0) + 1
        result["courses_per_category"] = dict(sorted(cpc.items(), key=lambda x: -x[1]))
    except Exception as e:
        result["categories_error"] = str(e)

    # 4 ── Users via core_user_get_users (single fast call)
    try:
        data = _moodle_call("core_user_get_users", {
            "criteria[0][key]":   "email",
            "criteria[0][value]": "%",
        }, settings=s)
        raw = data.get("users", data) if isinstance(data, dict) else data
        cutoff = int(_time.time()) - 30 * 86400
        users_list = [u for u in raw
                      if u.get("username") not in ("guest",)
                      and not u.get("deleted", False)]
        auth_counts = Counter(u.get("auth", "manual") for u in users_list)
        result.update({
            "total_users":     len(users_list),
            "active_30d":      sum(1 for u in users_list if (u.get("lastaccess") or 0) > cutoff),
            "never_logged_in": sum(1 for u in users_list if not (u.get("lastaccess") or 0)),
            "suspended_users": sum(1 for u in users_list if u.get("suspended", False)),
            "auth_methods":    dict(auth_counts.most_common()),
        })
    except Exception as e:
        result["users_error"] = str(e)

    return result


# ── Grade report ─────────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/grades")
def get_course_grades(course_id: int):
    """Return a gradebook table: all enrolled students × all grade items."""
    data = _moodle_call("gradereport_user_get_grade_items", {
        "courseid": course_id,
        "userid":   0,   # 0 = all users
    })
    user_grades = data.get("usergrades", []) if isinstance(data, dict) else []
    if not user_grades:
        return {"columns": [], "rows": []}

    # Build column definitions from first student (same for all)
    columns = []
    for gi in user_grades[0].get("gradeitems", []):
        columns.append({
            "id":     gi["id"],
            "name":   gi.get("itemname") or "Course Total",
            "module": gi.get("itemmodule") or gi.get("itemtype", ""),
            "is_total": gi.get("itemtype") == "course",
            "max":    gi.get("grademax", 100),
        })

    rows = []
    for ug in user_grades:
        cells = []
        for gi in ug.get("gradeitems", []):
            pct_str = gi.get("percentageformatted", "") or ""
            try:
                pct = float(pct_str.replace(",", ".").replace("%", "").strip())
            except ValueError:
                pct = None
            cells.append({
                "formatted":  gi.get("gradeformatted", "-") or "-",
                "raw":        gi.get("graderaw"),
                "percentage": pct,
                "feedback":   gi.get("feedback", "") or "",
            })
        rows.append({
            "userid":   ug["userid"],
            "fullname": ug.get("userfullname", ""),
            "cells":    cells,
        })

    return {"columns": columns, "rows": rows}


# ── Student analytics ────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/analytics")
def get_course_analytics(course_id: int):
    """Enrollment stats, grade distribution, and per-quiz performance."""
    import time as _time

    result: dict = {}

    # 1 ── Enrollment
    try:
        enrolled = _moodle_call("core_enrol_get_enrolled_users", {"courseid": course_id})
        if not isinstance(enrolled, list):
            enrolled = []
        cutoff = int(_time.time()) - 30 * 86400
        result["enrollment"] = {
            "total":          len(enrolled),
            "active_30d":     sum(1 for u in enrolled if (u.get("lastaccess") or 0) > cutoff),
            "never_accessed": sum(1 for u in enrolled if not (u.get("lastaccess") or 0)),
            "suspended":      sum(1 for u in enrolled if u.get("suspended")),
        }
    except Exception as e:
        result["enrollment_error"] = str(e)
        result["enrollment"] = {"total": 0, "active_30d": 0, "never_accessed": 0, "suspended": 0}

    # 2 ── Grade distribution from course total
    try:
        data = _moodle_call("gradereport_user_get_grade_items",
                            {"courseid": course_id, "userid": 0})
        user_grades = data.get("usergrades", []) if isinstance(data, dict) else []

        totals = []
        for ug in user_grades:
            for gi in ug.get("gradeitems", []):
                if gi.get("itemtype") == "course":
                    raw  = gi.get("graderaw")
                    maxg = float(gi.get("grademax") or 100) or 100.0
                    if raw is not None:
                        totals.append(float(raw) / maxg * 100)
                    break

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
            "avg_grade":    round(avg, 1)       if avg       is not None else None,
            "pass_rate":    round(pass_rate, 1) if pass_rate is not None else None,
            "student_count": len(totals),
        })
    except Exception as e:
        result["grades_error"] = str(e)
        result.setdefault("grade_distribution", {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0})
        result.setdefault("avg_grade", None)
        result.setdefault("pass_rate", None)
        result.setdefault("student_count", 0)

    # 3 ── Quiz performance
    try:
        quiz_resp = _moodle_call("mod_quiz_get_quizzes_by_courses",
                                 {"courseids[0]": course_id})
        quizzes_raw = quiz_resp.get("quizzes", []) if isinstance(quiz_resp, dict) else []

        quizzes = []
        for q in quizzes_raw:
            qid  = q.get("id")
            maxg = float(q.get("grade") or 100) or 100.0
            try:
                att_resp = _moodle_call("mod_quiz_get_user_attempts",
                                        {"quizid": qid, "userid": 0, "status": "finished"})
                attempts = att_resp.get("attempts", []) if isinstance(att_resp, dict) else []
                grades   = [float(a["sumgrades"]) / maxg * 100
                            for a in attempts if a.get("sumgrades") is not None]
                quizzes.append({
                    "id":            qid,
                    "name":          q.get("name", ""),
                    "attempt_count": len(attempts),
                    "avg_grade":  round(sum(grades) / len(grades), 1)                  if grades else None,
                    "pass_rate":  round(sum(1 for g in grades if g >= 60) / len(grades) * 100, 1) if grades else None,
                })
            except Exception:
                quizzes.append({"id": qid, "name": q.get("name", ""),
                                "attempt_count": 0, "avg_grade": None, "pass_rate": None})

        result["quizzes"] = quizzes
    except Exception as e:
        result["quizzes_error"] = str(e)
        result.setdefault("quizzes", [])

    return result


# ── Categories list ───────────────────────────────────────────────────────────

@router.get("/categories")
def get_categories():
    """Return all Moodle category names for UI autocomplete."""
    try:
        cats = _moodle_call("core_course_get_categories")
        return [{"id": c["id"], "name": c["name"]} for c in cats]
    except Exception:
        return []


# ── Deploy local version to Moodle ───────────────────────────────────────────

class DeployIn(BaseModel):
    version_id: int
    shortname: str
    fullname: str
    category_id: int
    start_date: str = ""   # YYYY-MM-DD
    end_date:   str = ""


def _date_to_ts(d: str) -> int:
    try:
        return int(datetime.strptime(d, "%Y-%m-%d").timestamp()) if d else 0
    except ValueError:
        return 0


@router.post("/deploy")
def deploy_to_moodle(body: DeployIn):
    """Create a course in Moodle and push section names + lecture content."""
    v = get_version(body.version_id)
    if not v:
        raise HTTPException(404, "Version not found")

    content  = v["content"]
    modules  = content.get("course_structure", {}).get("modules", [])
    mcs      = content.get("module_contents", [])

    s          = get_settings()
    moodle_url = s.get("moodle_url", "").rstrip("/")

    # 1 ── Create the course shell
    create_result = _moodle_call("core_course_create_courses", {
        "courses[0][shortname]":                       body.shortname,
        "courses[0][fullname]":                        body.fullname,
        "courses[0][categoryid]":                      body.category_id,
        "courses[0][startdate]":                       _date_to_ts(body.start_date),
        "courses[0][enddate]":                         _date_to_ts(body.end_date),
        "courses[0][format]":                          "topics",
        "courses[0][summaryformat]":                   1,
        "courses[0][courseformatoptions][0][name]":    "numsections",
        "courses[0][courseformatoptions][0][value]":   len(modules),
    })

    if not create_result or not isinstance(create_result, list):
        raise HTTPException(502, "Moodle did not return a course ID")
    moodle_id = create_result[0]["id"]

    # 2 ── Fetch sections to get their IDs
    sections_raw = _moodle_call("core_course_get_contents", {"courseid": moodle_id})
    sec_map = {sec["section"]: sec["id"] for sec in sections_raw}  # num → id

    # 3 ── Push section 0 summary (course overview / syllabus intro)
    overview = (content.get("course_structure") or {}).get("course_summary", "") or ""
    if overview and 0 in sec_map:
        _moodle_call("core_course_edit_section", {
            "sectionid":     sec_map[0],
            "summary":       overview,
            "summaryformat": 1,
        })

    # 4 ── Push each module section: name + lecture HTML as summary
    pushed = 0
    for mod in modules:
        num    = mod["number"]
        sec_id = sec_map.get(num)
        if not sec_id:
            continue
        mc           = next((m for m in mcs if m.get("module_num") == num), {})
        lecture_html = mc.get("lecture_html", "") or ""
        _moodle_call("core_course_edit_section", {
            "sectionid":     sec_id,
            "name":          mod["title"],
            "summary":       lecture_html,
            "summaryformat": 1,
        })
        pushed += 1

    # 5 ── Seed forum discussions with each module's forum question
    forums_seeded = 0
    try:
        # Re-fetch contents now that sections are populated; Moodle may have
        # auto-created a News forum in section 0 — we want section N forums.
        fresh_sections = _moodle_call("core_course_get_contents", {"courseid": moodle_id})
        # Build map: section_number → list of forum module IDs
        sec_forum_map: dict[int, list[int]] = {}
        for sec in fresh_sections:
            sec_num = sec.get("section", -1)
            forum_ids = [
                m["id"] for m in sec.get("modules", [])
                if m.get("modname") == "forum"
            ]
            if forum_ids:
                sec_forum_map[sec_num] = forum_ids

        for mod in modules:
            num       = mod["number"]
            mc        = next((m for m in mcs if m.get("module_num") == num), {})
            forum_q   = (mc.get("forum_question") or mc.get("discussion_question") or "").strip()
            forum_ids = sec_forum_map.get(num, [])
            if not forum_q or not forum_ids:
                continue
            _moodle_call("mod_forum_add_discussion", {
                "forumid":       forum_ids[0],
                "subject":       mod["title"],
                "message":       forum_q,
                "messageformat": 1,
            })
            forums_seeded += 1
    except Exception:
        pass  # forum seeding is best-effort; don't fail the whole deploy

    course_url = f"{moodle_url}/course/view.php?id={moodle_id}"

    # 6 ── Persist deploy record
    try:
        save_deploy(
            version_id=body.version_id,
            shortname=body.shortname,
            moodle_course_id=moodle_id,
            moodle_url=course_url,
            sections_pushed=pushed,
            forums_seeded=forums_seeded,
        )
    except Exception:
        pass

    # 7 ── Build .mbz for full-course restore (best-effort; does not block deploy)
    mbz_download_url: str | None = None
    try:
        from .courses import build_mbz as _build_mbz
        _build_mbz(body.shortname, body.version_id)
        mbz_download_url = (
            f"/api/courses/{body.shortname}/versions/{body.version_id}/download"
        )
    except Exception:
        pass

    return {
        "moodle_course_id": moodle_id,
        "url":              course_url,
        "sections_pushed":  pushed,
        "forums_seeded":    forums_seeded,
        "mbz_url":          mbz_download_url,
        "restore_url":      f"{moodle_url}/backup/restorefile.php",
    }


# ── Capabilities summary (what each modtype supports via API) ─────────────────

@router.get("/deploys")
def get_deploys(version_id: int):
    """Return deploy history for a specific course version."""
    return list_deploys(version_id)


@router.get("/capabilities")
def get_capabilities():
    return [
        {"modname": "page",   "can_push": False,
         "note": "Page body content has no REST update endpoint — use .mbz restore"},
        {"modname": "forum",  "can_push": True,
         "note": "Can add new discussion posts via mod_forum_add_discussion"},
        {"modname": "assign", "can_push": False,
         "note": "Assignment description requires .mbz restore to update"},
        {"modname": "quiz",   "can_push": False,
         "note": "Quiz questions require .mbz restore to update"},
        {"modname": "course", "can_push": True,
         "note": "Course name, dates, summary updatable via core_course_update_courses"},
        {"modname": "section","can_push": True,
         "note": "Section summary updatable via core_course_edit_section"},
    ]
