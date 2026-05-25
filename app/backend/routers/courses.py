"""Course library CRUD + .mbz build endpoints."""

import json
import re
import sys
import tarfile
import threading
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests as http_requests

# Make create_course.py importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import create_course as cc

from ..database import (
    db as _db,
    list_courses, get_course, upsert_course,
    list_versions, get_version, save_version, update_version_content,
    record_build, get_settings, delete_course, delete_version,
    save_review, list_reviews, list_recent_reviews, delete_review,
    save_schedule, list_schedules, delete_schedule, clear_schedules,
    get_overdue_schedules, update_schedule_run,
    save_curriculum_eval, get_curriculum_eval, list_curriculum_evals,
)

router = APIRouter(prefix="/courses", tags=["courses"])

BUILD_DIR = Path(__file__).parent.parent.parent / "builds"
BUILD_DIR.mkdir(exist_ok=True)

_review_lock = threading.Lock()

# ── Request / Response models ─────────────────────────────────────────────────

class CourseIn(BaseModel):
    shortname: str
    fullname: str
    professor: str = "Ricardo Julia"
    category: str = "2025 - 2026 Spring Term"
    prompt: str = ""


class GenerateIn(BaseModel):
    shortname: str
    fullname: str
    professor: str = "Ricardo Julia"
    category: str = "2025 - 2026 Spring Term"
    prompt: str
    start_date: str = ""
    end_date: str = ""
    model_id: str
    num_questions: int = 50
    homework_spec: dict[str, str] = {}   # {"1": "assign", "3": "forum"}
    module_count:  int = 5               # 3–12 modules
    language:      str = "es"            # ISO 639-1 language code


class ImportVersionIn(BaseModel):
    shortname: str
    fullname: str
    professor: str = "Ricardo Julia"
    category: str = "2025 - 2026 Spring Term"
    model_used: str = "imported"
    start_date: str = ""
    end_date: str = ""
    content: dict


class ImportMbzIn(BaseModel):
    download_url: str
    filename: str = ""
    shortname: str = ""   # override parsed value if supplied
    fullname: str = ""    # override parsed value if supplied
    instance: str = "Local"


class _MbzReader:
    """Unified reader for .mbz files — handles both ZIP and tar.gz formats."""

    def __init__(self, mbz_bytes: bytes):
        if zipfile.is_zipfile(BytesIO(mbz_bytes)):
            self._zf       = zipfile.ZipFile(BytesIO(mbz_bytes))
            self._tf       = None
            self._name_map = {n: n for n in self._zf.namelist()}
        elif tarfile.is_tarfile(BytesIO(mbz_bytes)):
            self._zf = None
            self._tf = tarfile.open(fileobj=BytesIO(mbz_bytes), mode="r:*")
            raw = [m.name.lstrip("./") for m in self._tf.getmembers() if m.isfile()]
            # Strip common top-level directory prefix (e.g. "backup-moodle2-course-123-/")
            prefix = ""
            if raw:
                candidate = raw[0].split("/")[0] + "/"
                if len(candidate) > 1 and all(n.startswith(candidate) for n in raw):
                    prefix = candidate
            self._name_map = {n[len(prefix):]: n for n in raw}
        else:
            raise ValueError("File is not a recognised .mbz format (not ZIP or tar.gz)")
        self.names = set(self._name_map.keys())

    def open(self, name: str) -> BytesIO:
        if self._zf:
            return self._zf.open(self._name_map[name])
        raw = self._name_map[name]
        member = next(
            m for m in self._tf.getmembers()
            if m.name.lstrip("./") == raw and m.isfile()
        )
        return BytesIO(self._tf.extractfile(member).read())


def _parse_mbz(mbz_bytes: bytes) -> dict:
    """Extract course metadata and section structure from a .mbz file."""
    NULL = "$@NULL@$"

    def clean(text: str | None) -> str:
        if not text or text == NULL:
            return ""
        return re.sub(r"<[^>]+>", "", text).strip()

    zf = _MbzReader(mbz_bytes)
    names = zf.names

    shortname = fullname = start_date = end_date = ""

    # moodle_backup.xml — top-level info
    if "moodle_backup.xml" in names:
        try:
            root = ET.parse(zf.open("moodle_backup.xml")).getroot()
            info = root.find(".//information")
            if info is not None:
                shortname = info.findtext("original_course_shortname", "") or ""
                fullname  = info.findtext("original_course_fullname",  "") or ""
                if shortname == NULL: shortname = ""
                if fullname  == NULL: fullname  = ""
        except Exception:
            pass

    # course/course.xml — dates + fallback names
    if "course/course.xml" in names:
        try:
            root = ET.parse(zf.open("course/course.xml")).getroot()
            shortname = shortname or root.findtext("shortname", "") or ""
            fullname  = fullname  or root.findtext("fullname",  "") or ""
            sd = root.findtext("startdate", "0") or "0"
            ed = root.findtext("enddate",   "0") or "0"
            if int(sd) > 0:
                start_date = datetime.fromtimestamp(int(sd)).strftime("%Y-%m-%d")
            if int(ed) > 0:
                end_date   = datetime.fromtimestamp(int(ed)).strftime("%Y-%m-%d")
        except Exception:
            pass

    # ── Activity manifest from moodle_backup.xml ─────────────────────────────────
    # moduleid → {sectionid, modulename, title, directory}
    mod_info: dict[int, dict] = {}
    if "moodle_backup.xml" in names:
        try:
            root = ET.parse(zf.open("moodle_backup.xml")).getroot()
            for act in root.findall(".//contents/activities/activity"):
                mid   = int(act.findtext("moduleid",   "0") or 0)
                sid   = int(act.findtext("sectionid",  "0") or 0)
                mname = act.findtext("modulename", "") or ""
                title = act.findtext("title",      "") or ""
                # directory e.g. "activities/page_15" — strip any leading ./ or /
                directory = re.sub(r'^[./]+', '', (act.findtext("directory", "") or "").strip())
                if mid:
                    mod_info[mid] = {
                        "sectionid":  sid,
                        "modulename": mname,
                        "title":      title,
                        "directory":  directory,
                    }
        except Exception:
            pass

    # ── Sections ──────────────────────────────────────────────────────────────────
    section_pattern = re.compile(r"sections/section_\d+/section\.xml")
    sections_raw = []
    for name in names:
        if not section_pattern.match(name):
            continue
        try:
            root   = ET.parse(zf.open(name)).getroot()
            sec_id = int(root.get("id", "0") or 0)
            num         = int(root.findtext("number", "0") or 0)
            raw_name    = root.findtext("name",    "") or ""
            raw_summary = root.findtext("summary", "") or ""
            sections_raw.append({
                "number":    num,
                "sec_id":    sec_id,
                "title":     clean(raw_name) or ("General" if num == 0 else f"Module {num}"),
                "summary":   raw_summary,
                "objective": clean(raw_summary)[:300],
            })
        except Exception:
            continue

    sections_raw.sort(key=lambda s: s["number"])

    # ── Per-activity content: use directory from manifest to locate XML ──────────
    act_content: dict[int, str] = {}   # moduleid → content_html
    act_name_override: dict[int, str] = {}  # for labels whose title is empty

    for mod_id, info in mod_info.items():
        modname = info["modulename"]
        if not modname:
            continue

        # Resolve XML path: manifest directory → fallback by moduleid
        directory = info["directory"]
        directory = re.sub(r'^[./]+', '', directory) if directory else ""
        xml_path  = f"{directory}/{modname}.xml" if directory else ""

        # Fallback 1: infer from moduleid
        if not xml_path or xml_path not in names:
            xml_path = f"activities/{modname}_{mod_id}/{modname}.xml"

        # Fallback 2: search names for any matching file
        if xml_path not in names:
            pattern = re.compile(rf"activities/{re.escape(modname)}_\d+/{re.escape(modname)}\.xml")
            candidates = [n for n in names if pattern.match(n)]
            xml_path = candidates[0] if candidates else xml_path

        if xml_path not in names:
            continue

        try:
            root = ET.parse(zf.open(xml_path)).getroot()

            # Extract name from XML for activities where manifest title may be empty (e.g. label)
            xml_name = root.findtext(".//name", "") or ""
            if xml_name and xml_name != NULL:
                act_name_override[mod_id] = xml_name

            def _field(tag: str) -> str:
                v = root.findtext(f".//{tag}", "") or ""
                return "" if v == NULL else v

            if modname == "page":
                # Pages have both <intro> (shown before content) and <content> (main body)
                intro   = _field("intro")
                body    = _field("content")
                act_content[mod_id] = (intro + body).strip()
            else:
                # All other modules: try intro first, then fallback fields
                for field in ("intro", "content", "externalurl", "reference"):
                    val = _field(field)
                    if val:
                        act_content[mod_id] = val
                        break
        except Exception:
            continue

    # ── Group activities by section ───────────────────────────────────────────────
    sec_activities: dict[int, list[dict]] = {}
    for mod_id, info in mod_info.items():
        sid = info["sectionid"]
        if not sid:
            continue
        name = info["title"] or act_name_override.get(mod_id, "")
        sec_activities.setdefault(sid, []).append({
            "id":           mod_id,
            "name":         name,
            "modname":      info["modulename"],
            "content_html": act_content.get(mod_id, ""),
        })

    modules = [
        {"number": s["number"], "title": s["title"],
         "objective": s["objective"], "key_topics": []}
        for s in sections_raw
    ]
    module_contents = []
    for s in sections_raw:
        activities = sec_activities.get(s["sec_id"], [])
        # Use section summary as lecture; fall back to first page's content
        lecture_html = s["summary"]
        if not lecture_html.strip():
            page = next((a for a in activities if a["modname"] == "page"), None)
            if page:
                lecture_html = page["content_html"]
        # First forum intro → forum_question
        forum = next((a for a in activities if a["modname"] == "forum"), None)
        module_contents.append({
            "module_num":          s["number"],
            "lecture_html":        lecture_html,
            "glossary_terms":      [],
            "forum_question":      forum["content_html"] if forum else "",
            "activities_snapshot": activities,
        })

    return {
        "shortname":   shortname,
        "fullname":    fullname,
        "start_date":  start_date,
        "end_date":    end_date,
        "content": {
            "course_structure":  {"course_summary": "", "modules": modules},
            "module_contents":   module_contents,
            "syllabus":          {},
            "quiz_questions":    [],
            "homework_prompts":  {},
            "homework_spec":     {},
            "mbz_import":        True,
        },
    }


# ── Instance stats ────────────────────────────────────────────────────────────

@router.get("/stats")
def get_instance_stats(instance: str = "Local"):
    """Aggregate stats for all courses belonging to an instance."""
    with _db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(DISTINCT c.shortname)  AS total_courses,
                COUNT(DISTINCT c.category)   AS total_categories
            FROM courses c
            WHERE c.instance = ?
        """, (instance,)).fetchone()

        total_courses     = row["total_courses"]    if row else 0
        total_categories  = row["total_categories"] if row else 0

        # Avg versions per course
        avg_row = conn.execute("""
            SELECT AVG(vc) AS avg_versions
            FROM (
                SELECT COUNT(v.id) AS vc
                FROM courses c
                LEFT JOIN course_versions v ON v.shortname = c.shortname
                WHERE c.instance = ?
                GROUP BY c.shortname
            ) sub
        """, (instance,)).fetchone()

        avg_versions = round(avg_row["avg_versions"], 1) if avg_row and avg_row["avg_versions"] is not None else None

        # Last activity: most recent version added for this instance
        last_row = conn.execute("""
            SELECT MAX(v.created_at) AS last_at
            FROM course_versions v
            JOIN courses c ON c.shortname = v.shortname
            WHERE c.instance = ?
        """, (instance,)).fetchone()

        last_activity_at = last_row["last_at"] if last_row else None

        # Version distribution: count courses by number of versions
        vdist_row = conn.execute("""
            SELECT
                SUM(CASE WHEN vc = 1 THEN 1 ELSE 0 END) AS v1_count,
                SUM(CASE WHEN vc = 2 THEN 1 ELSE 0 END) AS v2_count,
                SUM(CASE WHEN vc >= 3 THEN 1 ELSE 0 END) AS v3plus_count
            FROM (
                SELECT c.shortname, COUNT(v.id) AS vc
                FROM courses c
                LEFT JOIN course_versions v ON v.shortname = c.shortname
                WHERE c.instance = ?
                GROUP BY c.shortname
            ) sub
        """, (instance,)).fetchone()

        v1_count     = int(vdist_row["v1_count"]     or 0) if vdist_row else 0
        v2_count     = int(vdist_row["v2_count"]     or 0) if vdist_row else 0
        v3plus_count = int(vdist_row["v3plus_count"] or 0) if vdist_row else 0

    return {
        "total_courses":    total_courses,
        "total_categories": total_categories,
        "avg_versions":     avg_versions,
        "last_activity_at": last_activity_at,
        "v1_count":         v1_count,
        "v2_count":         v2_count,
        "v3plus_count":     v3plus_count,
    }


# ── Autonomous review ─────────────────────────────────────────────────────────

_JSON_OUTPUT_INSTRUCTION = """

---
RESPONSE FORMAT: Reply with ONLY a valid JSON object — no markdown fences, no prose before or after.
Required structure:
{
  "overall": "Passed" | "Needs Revision" | "Incomplete",
  "score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "sections": [
    {
      "title": "<category from your review criteria>",
      "items": [
        {
          "label": "<specific check>",
          "status": "Passed" | "Needs Revision" | "Missing",
          "note": "<one sentence explanation>"
        }
      ]
    }
  ]
}"""


def _strip_html(text: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', text)).strip()


def _format_for_review(shortname: str, ver: dict) -> str:
    """Render course content as structured plain text for LLM review."""
    content = ver.get("content", {}) if isinstance(ver.get("content"), dict) else {}
    structure = content.get("course_structure", {})
    modules   = structure.get("modules", [])
    mcs       = content.get("module_contents", [])

    lines = [
        f"COURSE SHORTNAME: {shortname}",
        f"TITLE: {structure.get('course_title', shortname)}",
        f"OBJECTIVE: {structure.get('course_objective', '—')}",
        f"VERSION: v{ver.get('version_num', '?')} | MODEL: {ver.get('model_used', '—')}",
        "",
    ]

    # Syllabus
    syllabus = content.get("syllabus")
    if syllabus:
        lines.append("=== SYLLABUS ===")
        if isinstance(syllabus, dict):
            for k, v in list(syllabus.items())[:8]:
                lines.append(f"  {k}: {str(v)[:250]}")
        else:
            lines.append(str(syllabus)[:800])
        lines.append("")

    # Modules
    for mod in modules:
        num   = mod.get("number") or mod.get("module_num", "?")
        title = mod.get("title", f"Module {num}")
        lines.append(f"=== MODULE {num}: {title} ===")
        lines.append(f"  Objective : {mod.get('objective', '—')}")
        lines.append(f"  Key Topics: {', '.join(mod.get('key_topics', []))}")

        mc = next((m for m in mcs if m.get("module_num") == num), None)
        if mc:
            lecture = mc.get("lecture_html", "")
            if lecture:
                clean = _strip_html(lecture)
                lines.append(f"  Lecture excerpt: {clean[:500]}")

            q = mc.get("discussion_question") or mc.get("forum_question", "")
            if q:
                lines.append(f"  Discussion question: {q}")

            glossary = mc.get("glossary") or mc.get("glossary_terms", [])
            if glossary:
                lines.append(f"  Glossary terms: {len(glossary)}")

            # Activities snapshot (Moodle imports)
            acts = mc.get("activities_snapshot", [])
            if acts:
                lines.append(f"  Activities: {', '.join(a.get('modname','?') + ':' + a.get('name','') for a in acts[:6])}")
        lines.append("")

    # Quiz
    quiz = content.get("quiz_questions", [])
    lines.append(f"=== ASSESSMENT ===")
    lines.append(f"  Quiz questions: {len(quiz)}")
    if quiz:
        sample = "; ".join(str(q.get("question", q))[:80] for q in quiz[:3])
        lines.append(f"  Sample: {sample}")

    # Homework
    hw = content.get("homework_spec", {})
    lines.append(f"  Homework modules: {len(hw)} ({', '.join(f'Mod {k}:{v}' for k, v in hw.items())})")

    return "\n".join(lines)


def _extract_json_block(text: str) -> str:
    m = re.search(r'\{.*\}', text, re.DOTALL)
    return m.group(0) if m else ""


@router.post("/{shortname}/review")
def review_course(shortname: str, body: dict):
    """Run an autonomous LLM audit on a course version (defaults to latest)."""
    agent_context = (body.get("agent_context") or "").strip()
    model_id      = (body.get("model_id")      or "").strip()
    version_id    = body.get("version_id")

    if not agent_context:
        raise HTTPException(400, detail="agent_context is required and cannot be empty")

    vers = list_versions(shortname)
    if not vers:
        raise HTTPException(404, detail=f"No versions found for '{shortname}'")

    if version_id:
        ver = get_version(int(version_id))
        if not ver or ver.get("shortname") != shortname:
            raise HTTPException(404, detail=f"Version {version_id} not found for '{shortname}'")
    else:
        ver = get_version(vers[0]["id"])
    if not ver:
        raise HTTPException(404, detail="Version record not found")

    course_text = _format_for_review(shortname, ver)

    settings = get_settings()
    llm_url  = settings.get("llm_url", "")
    api_key  = settings.get("llm_api_key", "")

    if not llm_url:
        raise HTTPException(400, detail="LLM URL not configured — visit Settings.")

    system_msg = agent_context + _JSON_OUTPUT_INSTRUCTION
    messages   = [
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": f"Audit this course:\n\n{course_text}"},
    ]

    try:
        raw = cc.call_llm(
            messages, llm_url,
            model_id=model_id or "local-model",
            temperature=0.2, max_tokens=2048,
            api_key=api_key,
        )
    except RuntimeError as exc:
        raise HTTPException(502, detail=str(exc))

    result = None
    for candidate in [raw, _extract_json_block(raw)]:
        if not candidate:
            continue
        try:
            result = json.loads(candidate)
            break
        except (json.JSONDecodeError, ValueError):
            pass

    if result is None:
        raise HTTPException(500, detail=f"LLM returned non-JSON: {raw[:300]}")

    response = {
        "shortname":   shortname,
        "version_num": ver.get("version_num"),
        **result,
    }

    # Persist to DB — agent metadata comes from body if the frontend provides it
    agent_id    = (body.get("agent_id")    or "").strip()
    agent_label = (body.get("agent_label") or agent_id or "Reviewer").strip()
    agent_color = (body.get("agent_color") or "gray").strip()
    save_review(
        shortname, ver.get("id"), ver.get("version_num"),
        agent_id, agent_label, agent_color, response,
    )

    return response


# ── Regenerate course from review feedback ────────────────────────────────────

@router.post("/{shortname}/regenerate-from-review")
def regenerate_from_review(shortname: str, body: dict):
    """Fork the latest version and regenerate all modules using review findings as improvement instructions."""
    reviews  = body.get("reviews", [])
    model_id = (body.get("model_id") or "").strip()

    if not reviews:
        raise HTTPException(400, "reviews list is required")

    vers = list_versions(shortname)
    if not vers:
        raise HTTPException(404, f"No versions found for '{shortname}'")

    ver = get_version(vers[0]["id"])
    if not ver:
        raise HTTPException(404, "Version record not found")

    # ── Collect all failing/missing items from every review ───────────────────
    failing_items = []
    for review in reviews:
        agent_label = review.get("agent_label") or "Reviewer"
        for section in review.get("sections", []):
            section_title = section.get("title", "")
            for item in section.get("items", []):
                if item.get("status") in ("Needs Revision", "Missing"):
                    label = item.get("label", "")
                    note  = item.get("note", "")
                    failing_items.append(
                        f"[{agent_label} · {section_title}] {label}: {note}"
                    )

    if not failing_items:
        raise HTTPException(400, "No revision items found in the reviews — all checks passed")

    review_instructions = (
        "Apply ALL of the following improvements identified by expert reviewers:\n\n"
        + "\n".join(f"- {item}" for item in failing_items)
        + "\n\n"
        "Ensure every revision item above is directly addressed in the content you produce. "
        "Where content is flagged as Missing, add it in full. "
        "Where content Needs Revision, rewrite it to meet the standard described. "
        "Maintain the existing course structure and module titles."
    )

    # ── Fork the current version ──────────────────────────────────────────────
    new_rec = save_version(
        shortname,
        model_id or "reviewed",
        ver["start_date"], ver["end_date"],
        ver["content"],
    )
    new_vid = new_rec["id"]
    new_ver = get_version(new_vid)
    content = new_ver["content"]

    settings  = get_settings()
    llm_url   = settings.get("llm_url", cc.DEFAULT_LLM_URL)
    api_key   = settings.get("llm_api_key", "")
    course    = get_course(shortname)
    professor = (course or {}).get("professor", "")
    fullname  = (course or {}).get("fullname", shortname)
    eff_model = model_id or ver["model_used"]
    # Imported courses have non-LLM model_used values — fall back to last_model
    if eff_model in NON_REGENERABLE or not eff_model:
        eff_model = settings.get("last_model") or "local-model"

    modules = content.get("course_structure", {}).get("modules", [])
    mc_list = content.get("module_contents", [])

    # ── Regenerate every module with improvement instructions ─────────────────
    # For imported courses include the existing lecture as context so the LLM
    # can improve the actual content rather than generating from titles alone.
    for mod in modules:
        existing_mc = next(
            (m for m in mc_list if m.get("module_num") == mod["number"]), None
        )
        existing_text = ""
        if existing_mc:
            existing_text = _strip_html(existing_mc.get("lecture_html", ""))[:1200]

        mod_instructions = review_instructions
        if existing_text:
            mod_instructions = (
                "EXISTING MODULE CONTENT (use this as your starting point and improve it):\n"
                f"{existing_text}\n\n"
                + review_instructions
            )

        raw_mc = cc.generate_module_content(
            mod["number"], mod["title"], mod["objective"],
            mod.get("key_topics", []), fullname, professor,
            llm_url, eff_model,
            extra_instructions=mod_instructions,
            api_key=api_key,
        )
        normalized = {
            **raw_mc,
            "module_num":     mod["number"],
            "lecture_html":   cc.sections_to_html(raw_mc.get("sections", [])),
            "glossary_terms": [g.get("term", "") for g in raw_mc.get("glossary", [])],
            "forum_question": raw_mc.get("discussion_question", ""),
        }
        replaced = False
        for i, item in enumerate(mc_list):
            if item.get("module_num") == mod["number"]:
                mc_list[i] = normalized
                replaced = True
                break
        if not replaced:
            mc_list.append(normalized)

    content["module_contents"] = mc_list

    # ── Regenerate quiz if flagged or under-count ──────────────────────────────
    quiz_flagged = any(
        item.get("status") in ("Needs Revision", "Missing")
        and ("quiz" in (item.get("label", "") + item.get("note", "")).lower()
             or "question" in (item.get("label", "") + item.get("note", "")).lower())
        for review in reviews
        for section in review.get("sections", [])
        for item in section.get("items", [])
    )
    if quiz_flagged or len(content.get("quiz_questions", [])) < 30:
        content["quiz_questions"] = cc.generate_quiz_questions(
            fullname, modules, 40, llm_url, eff_model, api_key=api_key)

    # ── Regenerate syllabus to reflect improvements ───────────────────────────
    content["syllabus"] = cc.generate_syllabus(
        fullname, shortname, professor,
        modules, llm_url, eff_model, api_key=api_key)

    update_version_content(new_vid, content)
    return get_version(new_vid)


# ── Finalize review: quiz + syllabus only (frontend drives module steps) ──────

@router.post("/{shortname}/versions/{version_id}/finalize-review")
def finalize_review(shortname: str, version_id: int, body: dict):
    """Regenerate quiz (if flagged or < 30 q's) and syllabus. Called after all modules are done."""
    reviews  = body.get("reviews", [])
    model_id = (body.get("model_id") or "").strip()

    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")

    settings  = get_settings()
    llm_url   = settings.get("llm_url", cc.DEFAULT_LLM_URL)
    api_key   = settings.get("llm_api_key", "")
    course    = get_course(shortname)
    professor = (course or {}).get("professor", "")
    fullname  = (course or {}).get("fullname", shortname)
    eff_model = model_id or v["model_used"]
    if eff_model in NON_REGENERABLE or not eff_model:
        eff_model = settings.get("last_model") or "local-model"

    content = v["content"]
    modules = content.get("course_structure", {}).get("modules", [])

    quiz_flagged = any(
        item.get("status") in ("Needs Revision", "Missing")
        and ("quiz" in (item.get("label", "") + item.get("note", "")).lower()
             or "question" in (item.get("label", "") + item.get("note", "")).lower())
        for review in reviews
        for section in review.get("sections", [])
        for item in section.get("items", [])
    )
    if quiz_flagged or len(content.get("quiz_questions", [])) < 30:
        content["quiz_questions"] = cc.generate_quiz_questions(
            fullname, modules, 40, llm_url, eff_model, api_key=api_key)

    content["syllabus"] = cc.generate_syllabus(
        fullname, shortname, professor,
        modules, llm_url, eff_model, api_key=api_key)

    update_version_content(version_id, content)
    return get_version(version_id)


# ── Inline field edit ─────────────────────────────────────────────────────────

@router.patch("/{shortname}/versions/{version_id}/field")
def patch_version_field(shortname: str, version_id: int, body: dict):
    """Update a single field inside a module's content without LLM regeneration."""
    module_num = body.get("module_num")
    field      = (body.get("field") or "").strip()
    value      = body.get("value", "")

    if not field:
        raise HTTPException(400, "field is required")

    ALLOWED_FIELDS = {"lecture_html", "forum_question", "discussion_question", "summary"}
    if field not in ALLOWED_FIELDS:
        raise HTTPException(400, f"field must be one of {sorted(ALLOWED_FIELDS)}")

    v = get_version(version_id)
    if not v or v.get("shortname") != shortname:
        raise HTTPException(404, "Version not found")

    content = v["content"]

    if module_num is not None:
        mc_list = content.get("module_contents", [])
        for i, item in enumerate(mc_list):
            if item.get("module_num") == int(module_num):
                mc_list[i][field] = value
                break
        content["module_contents"] = mc_list
    else:
        content[field] = value

    update_version_content(version_id, content)
    return {"ok": True}


# ── Review history ────────────────────────────────────────────────────────────

@router.get("/{shortname}/reviews")
def get_course_reviews(shortname: str, version_id: int = None):
    return list_reviews(shortname, version_id=version_id)


@router.delete("/{shortname}/reviews/{review_id}")
def remove_review(shortname: str, review_id: int):
    if not delete_review(review_id):
        raise HTTPException(404, "Review not found")
    return {"deleted": review_id}


@router.get("/reviews/recent")
def get_recent_reviews(limit: int = 100):
    return list_recent_reviews(limit)


# ── Quiz editor ───────────────────────────────────────────────────────────────

@router.put("/{shortname}/versions/{version_id}/quiz")
def save_quiz(shortname: str, version_id: int, body: dict):
    """Replace the full quiz question bank for a version."""
    questions = body.get("questions", [])
    v = get_version(version_id)
    if not v or v.get("shortname") != shortname:
        raise HTTPException(404, "Version not found")
    content = v["content"]
    content["quiz_questions"] = questions
    update_version_content(version_id, content)
    return {"ok": True, "count": len(questions)}


# ── Bible Reference Validator ─────────────────────────────────────────────────

# Maps Spanish AND English abbreviations/full-names → (canonical Spanish name, max chapters).
# English entries resolve to the same Spanish canonical name so output is consistent.
_BIBLE_BOOKS: dict[str, tuple[str, int]] = {
    # ══ OLD TESTAMENT ══════════════════════════════════════════════════════════
    # Genesis
    "gn": ("Génesis", 50), "gén": ("Génesis", 50), "gen": ("Génesis", 50),
    "génesis": ("Génesis", 50), "genesis": ("Génesis", 50),
    "ge": ("Génesis", 50),                                          # EN abbrev
    # Exodus
    "ex": ("Éxodo", 40), "éx": ("Éxodo", 40), "éxodo": ("Éxodo", 40), "exodo": ("Éxodo", 40),
    "exod": ("Éxodo", 40), "exodus": ("Éxodo", 40),                 # EN
    # Leviticus
    "lv": ("Levítico", 27), "lev": ("Levítico", 27), "levítico": ("Levítico", 27),
    "le": ("Levítico", 27), "leviticus": ("Levítico", 27),          # EN
    # Numbers
    "nm": ("Números", 36), "núm": ("Números", 36), "num": ("Números", 36), "números": ("Números", 36),
    "numb": ("Números", 36), "numbers": ("Números", 36),            # EN
    # Deuteronomy
    "dt": ("Deuteronomio", 34), "deut": ("Deuteronomio", 34), "deuteronomio": ("Deuteronomio", 34),
    "deu": ("Deuteronomio", 34), "de": ("Deuteronomio", 34), "deuteronomy": ("Deuteronomio", 34),  # EN
    # Joshua
    "jos": ("Josué", 24), "josué": ("Josué", 24), "josue": ("Josué", 24),
    "josh": ("Josué", 24), "joshua": ("Josué", 24),                 # EN
    # Judges
    "jue": ("Jueces", 21), "jueces": ("Jueces", 21),
    "judg": ("Jueces", 21), "jdg": ("Jueces", 21), "jg": ("Jueces", 21), "judges": ("Jueces", 21),  # EN
    # Ruth
    "rt": ("Rut", 4), "rut": ("Rut", 4),
    "ru": ("Rut", 4), "ruth": ("Rut", 4),                           # EN
    # 1 Samuel
    "1s": ("1 Samuel", 31), "1sam": ("1 Samuel", 31), "1 sam": ("1 Samuel", 31), "1 samuel": ("1 Samuel", 31),
    "1sa": ("1 Samuel", 31), "1 sa": ("1 Samuel", 31), "1samuel": ("1 Samuel", 31),  # EN
    # 2 Samuel
    "2s": ("2 Samuel", 24), "2sam": ("2 Samuel", 24), "2 sam": ("2 Samuel", 24), "2 samuel": ("2 Samuel", 24),
    "2sa": ("2 Samuel", 24), "2 sa": ("2 Samuel", 24), "2samuel": ("2 Samuel", 24),  # EN
    # 1 Kings
    "1r": ("1 Reyes", 22), "1re": ("1 Reyes", 22), "1rey": ("1 Reyes", 22), "1 reyes": ("1 Reyes", 22),
    "1 kgs": ("1 Reyes", 22), "1kgs": ("1 Reyes", 22), "1ki": ("1 Reyes", 22),      # EN
    "1 ki": ("1 Reyes", 22), "1kings": ("1 Reyes", 22), "1 kings": ("1 Reyes", 22), # EN
    # 2 Kings
    "2r": ("2 Reyes", 25), "2re": ("2 Reyes", 25), "2rey": ("2 Reyes", 25), "2 reyes": ("2 Reyes", 25),
    "2 kgs": ("2 Reyes", 25), "2kgs": ("2 Reyes", 25), "2ki": ("2 Reyes", 25),      # EN
    "2 ki": ("2 Reyes", 25), "2kings": ("2 Reyes", 25), "2 kings": ("2 Reyes", 25), # EN
    # 1 Chronicles
    "1cr": ("1 Crónicas", 29), "1cro": ("1 Crónicas", 29), "1 crónicas": ("1 Crónicas", 29),
    "1 chr": ("1 Crónicas", 29), "1chr": ("1 Crónicas", 29), "1ch": ("1 Crónicas", 29),   # EN
    "1chron": ("1 Crónicas", 29), "1 chron": ("1 Crónicas", 29),                           # EN
    "1chronicles": ("1 Crónicas", 29), "1 chronicles": ("1 Crónicas", 29),                 # EN
    # 2 Chronicles
    "2cr": ("2 Crónicas", 36), "2cro": ("2 Crónicas", 36), "2 crónicas": ("2 Crónicas", 36),
    "2 chr": ("2 Crónicas", 36), "2chr": ("2 Crónicas", 36), "2ch": ("2 Crónicas", 36),   # EN
    "2chron": ("2 Crónicas", 36), "2 chron": ("2 Crónicas", 36),                           # EN
    "2chronicles": ("2 Crónicas", 36), "2 chronicles": ("2 Crónicas", 36),                 # EN
    # Ezra
    "esd": ("Esdras", 10), "esdras": ("Esdras", 10),
    "ezr": ("Esdras", 10), "ezra": ("Esdras", 10),                  # EN
    # Nehemiah
    "neh": ("Nehemías", 13), "nehemías": ("Nehemías", 13), "nehemias": ("Nehemías", 13),
    "ne": ("Nehemías", 13), "nehemiah": ("Nehemías", 13),           # EN
    # Esther
    "est": ("Ester", 10), "ester": ("Ester", 10),
    "esth": ("Ester", 10), "esther": ("Ester", 10),                 # EN
    # Job
    "job": ("Job", 42),
    # Psalms
    "sal": ("Salmos", 150), "sl": ("Salmos", 150), "salmo": ("Salmos", 150), "salmos": ("Salmos", 150),
    "ps": ("Salmos", 150), "psa": ("Salmos", 150), "psalm": ("Salmos", 150), "psalms": ("Salmos", 150),  # EN
    # Proverbs
    "pr": ("Proverbios", 31), "pro": ("Proverbios", 31), "prov": ("Proverbios", 31), "proverbios": ("Proverbios", 31),
    "prv": ("Proverbios", 31), "proverbs": ("Proverbios", 31),      # EN
    # Ecclesiastes
    "ec": ("Eclesiastés", 12), "ecl": ("Eclesiastés", 12), "ecles": ("Eclesiastés", 12), "eclesiastés": ("Eclesiastés", 12),
    "eccl": ("Eclesiastés", 12), "ecc": ("Eclesiastés", 12),        # EN
    "ecclesiastes": ("Eclesiastés", 12), "qoh": ("Eclesiastés", 12), "qoheleth": ("Eclesiastés", 12),  # EN
    # Song of Solomon / Cantares
    "cnt": ("Cantares", 8), "cant": ("Cantares", 8), "cantar": ("Cantares", 8), "cantares": ("Cantares", 8),
    "song": ("Cantares", 8), "ss": ("Cantares", 8), "sos": ("Cantares", 8),  # EN
    "songofsolomon": ("Cantares", 8), "songofsongs": ("Cantares", 8),         # EN (no spaces)
    # Isaiah
    "is": ("Isaías", 66), "isa": ("Isaías", 66), "isaías": ("Isaías", 66), "isaias": ("Isaías", 66),
    "isaiah": ("Isaías", 66),                                        # EN
    # Jeremiah
    "jr": ("Jeremías", 52), "jer": ("Jeremías", 52), "jeremías": ("Jeremías", 52), "jeremias": ("Jeremías", 52),
    "je": ("Jeremías", 52), "jeremiah": ("Jeremías", 52),           # EN
    # Lamentations
    "lm": ("Lamentaciones", 5), "lam": ("Lamentaciones", 5), "lamentaciones": ("Lamentaciones", 5),
    "la": ("Lamentaciones", 5), "lamentations": ("Lamentaciones", 5),  # EN
    # Ezekiel
    "ez": ("Ezequiel", 48), "eze": ("Ezequiel", 48), "ezequiel": ("Ezequiel", 48),
    "ezek": ("Ezequiel", 48), "ezekiel": ("Ezequiel", 48),          # EN
    # Daniel
    "dn": ("Daniel", 12), "dan": ("Daniel", 12), "daniel": ("Daniel", 12),
    "da": ("Daniel", 12),                                            # EN
    # Hosea
    "os": ("Oseas", 14), "ose": ("Oseas", 14), "oseas": ("Oseas", 14),
    "hos": ("Oseas", 14), "ho": ("Oseas", 14), "hosea": ("Oseas", 14),  # EN
    # Joel
    "jl": ("Joel", 3), "joel": ("Joel", 3),
    # Amos
    "am": ("Amós", 9), "amós": ("Amós", 9), "amos": ("Amós", 9),
    # Obadiah
    "abd": ("Abdías", 1), "ob": ("Abdías", 1), "abdías": ("Abdías", 1),
    "obad": ("Abdías", 1), "obadiah": ("Abdías", 1),                # EN
    # Jonah
    "jon": ("Jonás", 4), "jonás": ("Jonás", 4), "jonas": ("Jonás", 4),
    "jnh": ("Jonás", 4), "jonah": ("Jonás", 4),                     # EN
    # Micah
    "miq": ("Miqueas", 7), "mi": ("Miqueas", 7), "miqueas": ("Miqueas", 7),
    "mic": ("Miqueas", 7), "micah": ("Miqueas", 7),                 # EN
    # Nahum
    "nah": ("Nahúm", 3), "nahúm": ("Nahúm", 3), "nahum": ("Nahúm", 3),
    "na": ("Nahúm", 3),                                             # EN
    # Habakkuk
    "hab": ("Habacuc", 3), "habacuc": ("Habacuc", 3),
    "hb": ("Habacuc", 3), "habakkuk": ("Habacuc", 3),              # EN
    # Zephaniah
    "sof": ("Sofonías", 3), "sf": ("Sofonías", 3), "sofonías": ("Sofonías", 3),
    "zeph": ("Sofonías", 3), "zep": ("Sofonías", 3), "zp": ("Sofonías", 3), "zephaniah": ("Sofonías", 3),  # EN
    # Haggai
    "hag": ("Hageo", 2), "ag": ("Hageo", 2), "hageo": ("Hageo", 2),
    "hg": ("Hageo", 2), "haggai": ("Hageo", 2),                     # EN
    # Zechariah
    "zac": ("Zacarías", 14), "zacarías": ("Zacarías", 14), "zacarias": ("Zacarías", 14),
    "zech": ("Zacarías", 14), "zec": ("Zacarías", 14), "zch": ("Zacarías", 14), "zechariah": ("Zacarías", 14),  # EN
    # Malachi
    "mal": ("Malaquías", 4), "malaquías": ("Malaquías", 4), "malaquias": ("Malaquías", 4),
    "ml": ("Malaquías", 4), "malachi": ("Malaquías", 4),            # EN

    # ══ NEW TESTAMENT ══════════════════════════════════════════════════════════
    # Matthew
    "mt": ("Mateo", 28), "mat": ("Mateo", 28), "mateo": ("Mateo", 28),
    "matt": ("Mateo", 28), "matthew": ("Mateo", 28),                # EN
    # Mark
    "mr": ("Marcos", 16), "mc": ("Marcos", 16), "mar": ("Marcos", 16), "marcos": ("Marcos", 16),
    "mark": ("Marcos", 16), "mk": ("Marcos", 16), "mrk": ("Marcos", 16),  # EN
    # Luke
    "lc": ("Lucas", 24), "luc": ("Lucas", 24), "lucas": ("Lucas", 24),
    "luke": ("Lucas", 24), "lk": ("Lucas", 24),                     # EN
    # John
    "jn": ("Juan", 21), "juan": ("Juan", 21),
    "john": ("Juan", 21), "jhn": ("Juan", 21),                      # EN
    # Acts
    "hch": ("Hechos", 28), "hech": ("Hechos", 28), "hechos": ("Hechos", 28),
    "acts": ("Hechos", 28), "ac": ("Hechos", 28),                   # EN
    # Romans
    "ro": ("Romanos", 16), "rom": ("Romanos", 16), "romanos": ("Romanos", 16),
    "rm": ("Romanos", 16), "romans": ("Romanos", 16),               # EN
    # 1 Corinthians
    "1co": ("1 Corintios", 16), "1cor": ("1 Corintios", 16), "1 cor": ("1 Corintios", 16), "1 corintios": ("1 Corintios", 16),
    "1 corinthians": ("1 Corintios", 16), "1corinthians": ("1 Corintios", 16),  # EN
    # 2 Corinthians
    "2co": ("2 Corintios", 13), "2cor": ("2 Corintios", 13), "2 cor": ("2 Corintios", 13), "2 corintios": ("2 Corintios", 13),
    "2 corinthians": ("2 Corintios", 13), "2corinthians": ("2 Corintios", 13),  # EN
    # Galatians
    "gl": ("Gálatas", 6), "gal": ("Gálatas", 6), "gálatas": ("Gálatas", 6), "galatas": ("Gálatas", 6),
    "ga": ("Gálatas", 6), "galatians": ("Gálatas", 6),             # EN
    # Ephesians
    "ef": ("Efesios", 6), "efe": ("Efesios", 6), "efesios": ("Efesios", 6),
    "eph": ("Efesios", 6), "ep": ("Efesios", 6), "ephesians": ("Efesios", 6),  # EN
    # Philippians
    "fil": ("Filipenses", 4), "flp": ("Filipenses", 4), "filipenses": ("Filipenses", 4),
    "phil": ("Filipenses", 4), "php": ("Filipenses", 4), "phl": ("Filipenses", 4), "philippians": ("Filipenses", 4),  # EN
    # Colossians
    "col": ("Colosenses", 4), "colosenses": ("Colosenses", 4),
    "colossians": ("Colosenses", 4),                                 # EN
    # 1 Thessalonians
    "1ts": ("1 Tesalonicenses", 5), "1tes": ("1 Tesalonicenses", 5), "1 tes": ("1 Tesalonicenses", 5),
    "1 thess": ("1 Tesalonicenses", 5), "1thess": ("1 Tesalonicenses", 5),      # EN
    "1th": ("1 Tesalonicenses", 5), "1 th": ("1 Tesalonicenses", 5),            # EN
    "1 thessalonians": ("1 Tesalonicenses", 5), "1thessalonians": ("1 Tesalonicenses", 5),  # EN
    # 2 Thessalonians
    "2ts": ("2 Tesalonicenses", 3), "2tes": ("2 Tesalonicenses", 3), "2 tes": ("2 Tesalonicenses", 3),
    "2 thess": ("2 Tesalonicenses", 3), "2thess": ("2 Tesalonicenses", 3),      # EN
    "2th": ("2 Tesalonicenses", 3), "2 th": ("2 Tesalonicenses", 3),            # EN
    "2 thessalonians": ("2 Tesalonicenses", 3), "2thessalonians": ("2 Tesalonicenses", 3),  # EN
    # 1 Timothy
    "1ti": ("1 Timoteo", 6), "1tim": ("1 Timoteo", 6), "1 tim": ("1 Timoteo", 6), "1 timoteo": ("1 Timoteo", 6),
    "1tm": ("1 Timoteo", 6), "1 timothy": ("1 Timoteo", 6), "1timothy": ("1 Timoteo", 6),  # EN
    # 2 Timothy
    "2ti": ("2 Timoteo", 4), "2tim": ("2 Timoteo", 4), "2 tim": ("2 Timoteo", 4), "2 timoteo": ("2 Timoteo", 4),
    "2tm": ("2 Timoteo", 4), "2 timothy": ("2 Timoteo", 4), "2timothy": ("2 Timoteo", 4),  # EN
    # Titus
    "tt": ("Tito", 3), "tit": ("Tito", 3), "tito": ("Tito", 3),
    "titus": ("Tito", 3),                                            # EN
    # Philemon
    "flm": ("Filemón", 1), "fim": ("Filemón", 1), "filemón": ("Filemón", 1),
    "philem": ("Filemón", 1), "phm": ("Filemón", 1), "phlm": ("Filemón", 1), "philemon": ("Filemón", 1),  # EN
    # Hebrews
    "he": ("Hebreos", 13), "heb": ("Hebreos", 13), "hebreos": ("Hebreos", 13),
    "hebrews": ("Hebreos", 13),                                      # EN
    # James
    "stg": ("Santiago", 5), "snt": ("Santiago", 5), "santiago": ("Santiago", 5),
    "jas": ("Santiago", 5), "jms": ("Santiago", 5), "jm": ("Santiago", 5), "james": ("Santiago", 5),  # EN
    # 1 Peter
    "1p": ("1 Pedro", 5), "1pe": ("1 Pedro", 5), "1 pe": ("1 Pedro", 5), "1 pedro": ("1 Pedro", 5),
    "1 pet": ("1 Pedro", 5), "1pet": ("1 Pedro", 5), "1pt": ("1 Pedro", 5),    # EN
    "1 peter": ("1 Pedro", 5), "1peter": ("1 Pedro", 5),                        # EN
    # 2 Peter
    "2p": ("2 Pedro", 3), "2pe": ("2 Pedro", 3), "2 pe": ("2 Pedro", 3), "2 pedro": ("2 Pedro", 3),
    "2 pet": ("2 Pedro", 3), "2pet": ("2 Pedro", 3), "2pt": ("2 Pedro", 3),    # EN
    "2 peter": ("2 Pedro", 3), "2peter": ("2 Pedro", 3),                        # EN
    # 1 John
    "1jn": ("1 Juan", 5), "1 jn": ("1 Juan", 5), "1juan": ("1 Juan", 5), "1 juan": ("1 Juan", 5),
    "1jo": ("1 Juan", 5), "1 jo": ("1 Juan", 5), "1john": ("1 Juan", 5), "1 john": ("1 Juan", 5),  # EN
    # 2 John
    "2jn": ("2 Juan", 1), "2 jn": ("2 Juan", 1), "2juan": ("2 Juan", 1), "2 juan": ("2 Juan", 1),
    "2jo": ("2 Juan", 1), "2 jo": ("2 Juan", 1), "2john": ("2 Juan", 1), "2 john": ("2 Juan", 1),  # EN
    # 3 John
    "3jn": ("3 Juan", 1), "3 jn": ("3 Juan", 1), "3juan": ("3 Juan", 1), "3 juan": ("3 Juan", 1),
    "3jo": ("3 Juan", 1), "3 jo": ("3 Juan", 1), "3john": ("3 Juan", 1), "3 john": ("3 Juan", 1),  # EN
    # Jude
    "jud": ("Judas", 1), "judas": ("Judas", 1),
    "jude": ("Judas", 1), "jd": ("Judas", 1),                       # EN
    # Revelation / Apocalipsis
    "ap": ("Apocalipsis", 22), "apo": ("Apocalipsis", 22), "apoc": ("Apocalipsis", 22),
    "apocalipsis": ("Apocalipsis", 22),
    "rev": ("Apocalipsis", 22), "rv": ("Apocalipsis", 22),          # EN
    "revelation": ("Apocalipsis", 22), "apocalypse": ("Apocalipsis", 22),       # EN
}

# Verse counts per chapter for each canonical book (Protestant 66-book canon, KJV)
_VERSE_COUNTS: dict[str, list[int]] = {
    # ── Old Testament ─────────────────────────────────────────────────────────
    "Génesis":       [31,25,24,26,32,22,24,22,29,32,32,20,18,24,21,16,27,33,38,18,34,24,20,67,34,35,46,22,35,43,55,32,20,31,29,43,36,30,23,23,57,38,34,34,28,34,31,22,33,26],
    "Éxodo":         [22,25,22,31,23,30,25,32,35,29,10,51,22,31,27,36,16,27,25,26,36,31,33,18,40,37,21,43,46,38],
    "Levítico":      [17,16,17,35,19,30,38,36,24,20,47,8,59,57,33,34,16,30,24,16,30,33,36,38,21,13,14],
    "Números":       [54,34,51,49,31,27,89,26,23,36,35,16,33,45,41,50,13,32,22,29,35,41,30,25,18,65,23,31,40,16,54,42,56,29,34,13],
    "Deuteronomio":  [46,37,29,49,33,25,26,20,29,22,32,32,18,29,23,22,20,22,21,20,23,30,25,22,19,19,26,68,29,20,30,52,29,12],
    "Josué":         [18,24,17,24,15,27,26,35,27,43,23,24,33,15,63,10,18,28,51,9,45,34,16,33],
    "Jueces":        [36,23,31,24,31,40,25,35,57,18,40,15,25,20,20,31,13,31,30,48,25],
    "Rut":           [22,23,18,22],
    "1 Samuel":      [28,36,21,22,12,21,17,22,27,27,15,25,14,23,29,23,22,19,19,17,21,29,25,28,15,20,22,18,24,36,37],
    "2 Samuel":      [27,32,39,12,25,23,29,18,13,19,27,31,39,33,37,23,29,33,43,26,22,51,39,25],
    "1 Reyes":       [53,46,28,34,18,38,51,66,28,29,43,33,34,31,34,34,24,46,21,43,29,53],
    "2 Reyes":       [18,25,27,44,27,33,20,29,37,36,21,21,25,29,38,20,41,37,37,21,26,20,37,20,30],
    "1 Crónicas":    [54,55,24,43,26,81,40,40,44,14,47,40,14,17,29,43,27,17,19,8,30,19,32,31,31,32,34,21,30],
    "2 Crónicas":    [17,18,17,22,14,42,22,18,31,19,23,16,22,15,19,14,19,34,11,37,20,12,21,27,28,23,9,27,36,27,21,33,25,33,27,23],
    "Esdras":        [11,70,13,24,17,22,28,36,15,44],
    "Nehemías":      [11,20,32,23,19,19,73,18,38,39,36,47,31],
    "Ester":         [22,23,15,17,14,14,10,17,32,3],
    "Job":           [22,13,26,21,27,30,21,22,35,22,20,25,28,22,35,22,16,21,29,29,34,30,17,25,6,14,23,28,25,31,40,22,33,37,16,33,24,41,30,24,34,17],
    "Salmos":        [6,12,8,8,12,10,17,9,20,18,7,8,6,7,5,11,15,50,14,9,13,31,6,10,22,12,14,9,11,13,25,11,22,23,28,13,40,23,14,18,14,12,5,27,18,12,10,15,21,23,21,11,7,9,24,14,12,12,18,14,9,13,12,11,14,20,8,36,37,6,24,20,28,23,11,13,21,72,13,20,17,8,19,13,14,17,7,19,53,17,16,16,5,23,11,13,12,9,9,5,8,29,22,35,45,48,43,13,31,7,10,10,9,8,18,19,2,29,176,7,8,9,4,8,5,6,5,6,8,8,3,18,3,3,21,26,9,8,24,14,10,8,12,15,21,10,20,14,9,6],
    "Proverbios":    [33,22,35,27,23,35,27,36,18,32,31,28,25,35,33,33,28,24,29,30,31,29,35,34,28,28,27,28,27,33,31],
    "Eclesiastés":   [18,26,22,16,20,12,29,17,18,20,10,14],
    "Cantares":      [17,17,11,16,16,13,13,14],
    "Isaías":        [31,22,26,6,30,13,25,22,21,34,16,6,22,32,9,14,14,7,25,6,17,25,18,23,12,21,13,29,24,33,9,20,24,17,10,22,38,22,8,31,29,25,28,28,25,13,15,22,26,11,23,15,12,17,13,12,21,14,21,22,11,12,19,12,25,24],
    "Jeremías":      [19,37,25,31,31,30,34,22,26,25,23,17,27,22,21,21,27,23,15,18,14,30,40,10,38,24,22,17,32,24,40,44,26,22,19,32,21,28,18,16,18,22,13,30,5,28,7,47,39,46,64,34],
    "Lamentaciones": [22,22,66,22,22],
    "Ezequiel":      [28,10,27,17,17,14,27,18,11,22,25,28,23,23,8,63,24,32,14,49,32,31,49,27,17,21,36,26,21,26,18,32,33,31,15,38,28,23,29,49,26,20,27,31,25,24,23,35],
    "Daniel":        [21,49,30,37,31,28,28,27,27,21,45,13],
    "Oseas":         [11,23,5,19,15,11,16,14,17,15,12,14,16,9],
    "Joel":          [20,32,21],
    "Amós":          [15,16,15,13,27,14,17,14,15],
    "Abdías":        [21],
    "Jonás":         [17,10,10,11],
    "Miqueas":       [16,13,12,13,15,16,20],
    "Nahúm":         [15,13,19],
    "Habacuc":       [17,20,19],
    "Sofonías":      [18,15,20],
    "Hageo":         [15,23],
    "Zacarías":      [21,13,10,14,11,15,14,23,17,12,17,14,9,21],
    "Malaquías":     [14,17,18,6],
    # ── New Testament ─────────────────────────────────────────────────────────
    "Mateo":         [25,23,17,25,48,34,29,34,38,42,30,50,58,36,39,28,27,35,30,34,46,46,39,51,46,75,66,20],
    "Marcos":        [45,28,35,41,43,56,37,38,50,52,33,44,37,72,47,20],
    "Lucas":         [80,52,38,44,39,49,50,56,62,42,54,59,35,35,32,31,37,43,48,47,38,71,56,53],
    "Juan":          [51,25,36,54,47,71,53,59,41,42,57,50,38,31,27,33,26,40,42,31,25],
    "Hechos":        [26,47,26,37,42,15,60,40,43,48,30,25,52,28,41,40,34,28,41,38,40,30,35,27,27,32,44,31],
    "Romanos":       [32,29,31,25,21,23,25,39,33,21,36,21,14,23,33,27],
    "1 Corintios":   [31,16,23,21,13,20,40,13,27,33,34,31,13,40,58,24],
    "2 Corintios":   [24,17,18,18,21,18,16,24,15,18,33,21,13],
    "Gálatas":       [24,21,29,31,26,18],
    "Efesios":       [23,22,21,28,30,14],
    "Filipenses":    [30,18,19,16],
    "Colosenses":    [29,23,25,18],
    "1 Tesalonicenses": [10,20,13,18,28],
    "2 Tesalonicenses": [12,17,18],
    "1 Timoteo":     [20,15,16,16,25,21],
    "2 Timoteo":     [18,26,17,22],
    "Tito":          [16,15,15],
    "Filemón":       [25],
    "Hebreos":       [14,18,19,16,14,20,28,13,28,39,40,29,25],
    "Santiago":      [27,26,18,17,20],
    "1 Pedro":       [25,25,22,19,14],
    "2 Pedro":       [21,22,18],
    "1 Juan":        [10,29,24,21,21],
    "2 Juan":        [13],
    "3 Juan":        [14],
    "Judas":         [25],
    "Apocalipsis":   [20,29,22,11,14,17,17,13,21,11,19,17,18,20,8,21,18,24,21,15,27,21],
}

# Regex: optional num prefix + book name + chapter:verse (colon or period)
_REF_PATTERN = re.compile(
    r'\b([1-3]\s?)?'                          # optional: 1, 2, 3 (with optional space)
    r'([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)'             # book name (accented letters included)
    r'\.?\s+'                                 # optional period, then whitespace
    r'(\d{1,3})'                              # chapter
    r'[:.]\s*'                                # separator (colon or period)
    r'(\d{1,3})'                              # verse
    r'(?:\s*[-–]\s*\d{1,3})?',               # optional end verse (range)
    re.IGNORECASE,
)


def _clean_text(html_str: str) -> str:
    """Strip HTML tags and normalize whitespace for reference parsing."""
    text = re.sub(r"<[^>]+>", " ", html_str or "")
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&[a-z]+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_refs(text: str, source_field: str) -> list[dict]:
    """Find all Bible references in text and validate them."""
    results = []
    seen = set()

    for m in _REF_PATTERN.finditer(text):
        num_prefix = (m.group(1) or "").replace(" ", "").strip()
        book_raw   = m.group(2).strip()
        chapter    = int(m.group(3))
        verse      = int(m.group(4))
        ref_text   = m.group(0).strip()

        # Build lookup key: optional num + book (lowercased, no accents stripped)
        key_parts  = []
        if num_prefix:
            key_parts.append(num_prefix)
        key_parts.append(book_raw.lower())
        lookup_key = " ".join(key_parts)

        # Also try combined (no space between num and book)
        lookup_key2 = (num_prefix + book_raw).lower() if num_prefix else None

        book_entry = _BIBLE_BOOKS.get(lookup_key) or (
            _BIBLE_BOOKS.get(lookup_key2) if lookup_key2 else None
        )

        # Skip obvious non-references: single-letter "books", numbers-only, etc.
        if len(book_raw) < 2:
            continue

        dedup_key = (lookup_key, chapter, verse)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Build context snippet (±60 chars around match)
        start = max(0, m.start() - 60)
        end   = min(len(text), m.end() + 60)
        context = ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")
        context = re.sub(r"\s+", " ", context).strip()

        if not book_entry:
            status = "unknown_book"
            canonical = book_raw
            max_ch = 0
        else:
            canonical, max_ch = book_entry
            if chapter > max_ch:
                status = "chapter_out_of_range"
            else:
                verse_list = _VERSE_COUNTS.get(canonical, [])
                if verse_list and verse > verse_list[chapter - 1]:
                    status = "verse_out_of_range"
                else:
                    status = "valid"

        results.append({
            "ref_text":       ref_text,
            "book_canonical": canonical,
            "chapter":        chapter,
            "verse":          verse,
            "source_field":   source_field,
            "context":        context,
            "status":         status,
        })

    return results


@router.get("/{shortname}/versions/{version_id}/bible-refs")
def get_bible_refs(shortname: str, version_id: int):
    """Parse all text fields in a course version for Bible citations and validate them."""
    v = get_version(version_id)
    if not v or v.get("shortname") != shortname:
        raise HTTPException(404, "Version not found")

    content = v["content"]
    all_refs: list[dict] = []

    # Scan module contents
    for mc in content.get("module_contents", []):
        num = mc.get("module_num", "?")
        if lecture := mc.get("lecture_html", ""):
            all_refs.extend(_extract_refs(_clean_text(lecture), f"module_{num}.lecture"))
        if forum_q := (mc.get("forum_question") or mc.get("discussion_question") or ""):
            all_refs.extend(_extract_refs(forum_q, f"module_{num}.forum_question"))
        for entry in mc.get("glossary", []):
            if defn := entry.get("definition", ""):
                all_refs.extend(_extract_refs(defn, f"module_{num}.glossary"))

    # Scan syllabus
    syllabus = content.get("syllabus", {})
    for key in ("intro_html", "content_html"):
        if val := syllabus.get(key, ""):
            all_refs.extend(_extract_refs(_clean_text(val), f"syllabus.{key}"))

    # Scan course summary
    summary = content.get("course_structure", {}).get("course_summary", "")
    if summary:
        all_refs.extend(_extract_refs(_clean_text(summary), "course_summary"))

    return all_refs


# ── Print / export ────────────────────────────────────────────────────────────

@router.get("/{shortname}/versions/{version_id}/export-html", response_class=None)
def export_html(shortname: str, version_id: int):
    """Return a print-friendly HTML page for the course version."""
    from fastapi.responses import HTMLResponse
    import html as _html

    v = get_version(version_id)
    if not v or v.get("shortname") != shortname:
        raise HTTPException(404, "Version not found")

    course   = get_course(shortname) or {}
    content  = v["content"]
    modules  = content.get("course_structure", {}).get("modules", [])
    mcs      = content.get("module_contents", [])
    quiz     = content.get("quiz_questions", [])
    syllabus = content.get("syllabus") or {}

    mc_by_num = {m.get("module_num"): m for m in mcs}

    e = _html.escape

    def mc_for(num):
        return mc_by_num.get(num) or next(
            (m for i, m in enumerate(mcs) if i == num - 1), {}
        )

    sections_html = ""
    for mod in modules:
        mc  = mc_for(mod.get("number", 0))
        lec = mc.get("lecture_html") or ""
        fq  = mc.get("forum_question") or mc.get("discussion_question") or ""
        glossary = mc.get("glossary") or []
        topics = ", ".join(mod.get("key_topics") or [])
        sections_html += f"""
        <section class="module">
          <h2>Module {mod.get('number')}: {e(mod.get('title',''))}</h2>
          <p class="objective"><em>Objective:</em> {e(mod.get('objective',''))}</p>
          {f'<p class="topics"><em>Topics:</em> {e(topics)}</p>' if topics else ''}
          {lec}
          {f'<div class="forum-q"><strong>Discussion Question</strong><p>{e(fq)}</p></div>' if fq else ''}
          {('<div class="glossary"><strong>Glossary (' + str(len(glossary)) + ' terms)</strong><ul>'
            + ''.join(f'<li><strong>{e(g.get("term",""))}</strong>' + (f' — {e(g.get("definition",""))}' if g.get("definition") else '') + '</li>' for g in glossary)
            + '</ul></div>') if glossary else ''}
        </section>"""

    quiz_html = ""
    if quiz:
        items = ""
        for i, q in enumerate(quiz, 1):
            opts = q.get("options", [])
            ci   = int(q.get("correct_index", 0))
            opts_html = "".join(
                f'<li class="{"correct" if j==ci else ""}">{e(str(opt))}</li>'
                for j, opt in enumerate(opts)
            )
            items += f'<div class="question"><p><strong>{i}.</strong> {e(str(q.get("question","")))}</p><ul>{opts_html}</ul></div>'
        quiz_html = f'<section class="quiz"><h2>Quiz Bank ({len(quiz)} questions)</h2>{items}</section>'

    syl_html = ""
    if isinstance(syllabus, dict):
        intro   = syllabus.get("intro_html") or ""
        content_s = syllabus.get("content_html") or ""
        if intro or content_s:
            syl_html = f'<section class="syllabus"><h2>Syllabus</h2>{intro}{content_s}</section>'

    page = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{e(course.get('fullname', shortname))}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 860px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.7; font-size: 15px; }}
  h1   {{ font-size: 1.8em; border-bottom: 2px solid #333; padding-bottom: 8px; margin-bottom: 4px; }}
  h2   {{ font-size: 1.3em; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 2em; color: #333; }}
  h3   {{ font-size: 1.1em; color: #444; }}
  .meta {{ color: #555; font-size: 0.9em; margin-bottom: 2em; }}
  .module {{ margin-bottom: 2.5em; page-break-inside: avoid; }}
  .objective, .topics {{ color: #444; font-size: 0.9em; }}
  .forum-q {{ background: #f0f7ff; border-left: 3px solid #3b82f6; padding: 8px 14px; margin: 1em 0; }}
  .glossary {{ font-size: 0.88em; color: #444; }}
  .glossary ul {{ padding-left: 1.2em; }}
  .question {{ margin-bottom: 1.4em; page-break-inside: avoid; }}
  .question ul {{ list-style: none; padding-left: 1.2em; margin-top: 4px; }}
  .question li {{ padding: 2px 0; color: #444; }}
  .question li.correct {{ font-weight: bold; color: #166534; }}
  .syllabus {{ margin-top: 2em; }}
  @media print {{
    body {{ margin: 0; font-size: 12pt; }}
    h1 {{ font-size: 18pt; }}
    h2 {{ font-size: 14pt; }}
    .module, .question {{ page-break-inside: avoid; }}
    a {{ color: inherit; text-decoration: none; }}
  }}
</style>
</head>
<body>
<h1>{e(course.get('fullname', shortname))}</h1>
<div class="meta">
  <strong>Code:</strong> {e(shortname)} &nbsp;|&nbsp;
  <strong>Professor:</strong> {e(course.get('professor',''))} &nbsp;|&nbsp;
  <strong>Category:</strong> {e(course.get('category',''))} &nbsp;|&nbsp;
  <strong>Version:</strong> v{v.get('version_num','')}
  {f" &nbsp;|&nbsp; <strong>Dates:</strong> {e(v.get('start_date',''))} → {e(v.get('end_date',''))}" if v.get('start_date') else ''}
</div>
{syl_html}
{sections_html}
{quiz_html}
<script>window.onload = function(){{ window.print(); }}</script>
</body>
</html>"""

    return HTMLResponse(content=page)


@router.get("/{shortname}/versions/{version_id}/export-docx")
def export_docx(shortname: str, version_id: int):
    from fastapi.responses import Response
    try:
        from docx import Document
        from docx.shared import Pt, Inches, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise HTTPException(500, "python-docx not installed — run: pip install python-docx")

    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")
    course = get_course(shortname)
    if not course:
        raise HTTPException(404, "Course not found")

    content   = v["content"]
    structure = content.get("course_structure", {})
    modules   = structure.get("modules", [])
    mc_list   = content.get("module_contents", [])
    syllabus  = content.get("syllabus", {})
    questions = content.get("quiz_questions", [])

    doc = Document()

    # Title
    title = doc.add_heading(course["fullname"], 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Metadata table
    meta = doc.add_table(rows=4, cols=2)
    meta.style = "Table Grid"
    for i, (label, value) in enumerate([
        ("Course Code", shortname),
        ("Professor",   course.get("professor", "")),
        ("Category",    course.get("category", "")),
        ("Version",     str(v.get("version_num", 1))),
    ]):
        row = meta.rows[i]
        row.cells[0].text = label
        row.cells[1].text = value
    doc.add_paragraph()

    # Course summary
    summary = structure.get("course_summary", "")
    if summary:
        doc.add_heading("Course Overview", level=1)
        doc.add_paragraph(_strip_html(summary))

    # Syllabus
    if syllabus:
        doc.add_heading("Syllabus", level=1)
        for field, val in syllabus.items():
            if val:
                doc.add_heading(field.replace("_", " ").title(), level=2)
                doc.add_paragraph(_strip_html(str(val)))

    # Modules
    doc.add_heading("Course Modules", level=1)
    for i, mod in enumerate(modules):
        mc = mc_list[i] if i < len(mc_list) else {}
        doc.add_heading(mod.get("title", f"Module {i+1}"), level=2)

        obj = mod.get("objective", "")
        if obj:
            p = doc.add_paragraph()
            p.add_run("Objective: ").bold = True
            p.add_run(obj)

        topics = mod.get("key_topics", [])
        if topics:
            p = doc.add_paragraph()
            p.add_run("Key Topics: ").bold = True
            p.add_run(", ".join(topics))

        # Lecture content
        for sec in mc.get("sections", []):
            doc.add_heading(sec.get("heading", ""), level=3)
            doc.add_paragraph(_strip_html(sec.get("text", "")))

        # Discussion question
        dq = mc.get("forum_question", mc.get("discussion_question", ""))
        if dq:
            p = doc.add_paragraph()
            p.add_run("Discussion: ").bold = True
            p.add_run(_strip_html(dq))

        # Glossary
        glossary = mc.get("glossary", [])
        if glossary:
            doc.add_heading("Glossary", level=3)
            for item in glossary:
                if isinstance(item, dict):
                    p = doc.add_paragraph(style="List Bullet")
                    p.add_run(f"{item.get('term', '')}: ").bold = True
                    p.add_run(item.get("definition", ""))
                elif isinstance(item, str):
                    doc.add_paragraph(item, style="List Bullet")

    # Quiz bank
    if questions:
        doc.add_heading("Quiz Bank", level=1)
        for idx, q in enumerate(questions, 1):
            doc.add_heading(f"Q{idx}. {_strip_html(q.get('question', ''))}", level=3)
            for opt in q.get("options", []):
                is_correct = opt == q.get("answer", "")
                p = doc.add_paragraph(style="List Bullet")
                run = p.add_run(f"{'✓ ' if is_correct else ''}{_strip_html(opt)}")
                if is_correct:
                    run.bold = True

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    filename = f"{shortname}_v{v['version_num']}.docx"
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Curriculum mapper (AI-based) ──────────────────────────────────────────────

_CURRICULUM_DOMAINS = [
    "Old Testament",
    "New Testament",
    "Systematic Theology",
    "Church History",
    "Pastoral Ministry",
    "Biblical Languages",
    "Ethics",
    "Missions & Evangelism",
]

_CURRICULUM_EVAL_PROMPT = """You are a seminary curriculum analyst with deep expertise in theological education.
Evaluate the course below and assign a score from 0 to 100 for each theological domain.

Scoring guide:
  0     — domain not covered at all
  1-25  — brief or incidental mention
  26-50 — some coverage, secondary topic
  51-75 — significant coverage, important component of the course
  76-100 — primary focus of the course

Important: Course content may be in English, Spanish, or both. Recognize equivalent terms in both languages
(e.g., "Antiguo Testamento" = Old Testament, "Misiones" = Missions & Evangelism, "Teología" = Systematic Theology, etc.).

Domains to score:
  Old Testament, New Testament, Systematic Theology, Church History,
  Pastoral Ministry, Biblical Languages, Ethics, Missions & Evangelism

Respond with ONLY valid JSON, no markdown, no explanation outside the JSON:
{
  "scores": {
    "Old Testament": <0-100>,
    "New Testament": <0-100>,
    "Systematic Theology": <0-100>,
    "Church History": <0-100>,
    "Pastoral Ministry": <0-100>,
    "Biblical Languages": <0-100>,
    "Ethics": <0-100>,
    "Missions & Evangelism": <0-100>
  },
  "reasoning": "<2-3 sentences explaining the main scores>"
}"""


def _build_course_text_for_eval(course: dict, version: dict) -> str:
    """Build a concise course summary for AI evaluation (keeps tokens reasonable)."""
    content  = version.get("content", {})
    modules  = content.get("course_structure", {}).get("modules", [])
    mcs      = content.get("module_contents", [])
    syllabus = content.get("syllabus", {})

    lines = [
        f"Course: {course.get('fullname', '')} ({course.get('shortname', '')})",
        f"Category: {course.get('category', '')}",
        f"Prompt/Description: {course.get('prompt', '')}",
    ]
    summary = content.get("course_structure", {}).get("course_summary", "")
    if summary:
        lines.append(f"Summary: {_strip_html(summary)[:500]}")

    if syllabus:
        syl_text = " | ".join(f"{k}: {str(v)[:120]}" for k, v in syllabus.items() if v)
        lines.append(f"Syllabus: {syl_text[:600]}")

    for i, mod in enumerate(modules[:12]):
        parts = [mod.get("title", ""), mod.get("objective", "")]
        parts += mod.get("key_topics", [])
        mc = mcs[i] if i < len(mcs) else {}
        dq = mc.get("forum_question", mc.get("discussion_question", ""))
        if dq:
            parts.append(f"Discussion: {_strip_html(dq)[:120]}")
        glossary = mc.get("glossary", [])
        terms = [g.get("term", "") if isinstance(g, dict) else str(g) for g in glossary[:6]]
        if terms:
            parts.append(f"Terms: {', '.join(terms)}")
        lines.append(f"Module {i+1}: {' | '.join(p for p in parts if p)}")

    return "\n".join(lines)


def _run_curriculum_eval(shortname: str, version_id: int | None = None):
    """Call LLM to evaluate a course's curriculum domain scores and persist result."""
    course = get_course(shortname)
    if not course:
        return

    versions = list_versions(shortname)
    if not versions:
        return

    vid = version_id or versions[0]["id"]
    v   = get_version(vid)
    if not v:
        return

    settings  = get_settings()
    llm_url   = settings.get("llm_url", "")
    api_key   = settings.get("llm_api_key", "")
    model_id  = settings.get("last_model") or "local-model"

    if not llm_url:
        return

    course_text = _build_course_text_for_eval(course, v)
    messages = [
        {"role": "system", "content": _CURRICULUM_EVAL_PROMPT},
        {"role": "user",   "content": f"Evaluate this course:\n\n{course_text}"},
    ]

    try:
        raw = cc.call_llm(
            messages, llm_url,
            model_id=model_id,
            temperature=0.1,
            max_tokens=512,
            api_key=api_key,
        )
    except Exception:
        return

    result = None
    for candidate in [raw, _extract_json_block(raw)]:
        if not candidate:
            continue
        try:
            result = json.loads(candidate)
            break
        except (json.JSONDecodeError, ValueError):
            pass

    if not result or "scores" not in result:
        return

    scores = {d: max(0, min(100, int(result["scores"].get(d, 0)))) for d in _CURRICULUM_DOMAINS}
    reasoning = str(result.get("reasoning", ""))
    save_curriculum_eval(shortname, vid, model_id, scores, reasoning)


def _schedule_curriculum_eval(shortname: str, version_id: int | None = None):
    """Trigger curriculum evaluation in a background thread (non-blocking)."""
    t = threading.Thread(target=_run_curriculum_eval, args=(shortname, version_id), daemon=True)
    t.start()


@router.post("/{shortname}/curriculum-eval")
def evaluate_curriculum(shortname: str):
    """Re-evaluate a course's curriculum domain scores via AI (blocking)."""
    course = get_course(shortname)
    if not course:
        raise HTTPException(404, "Course not found")

    settings = get_settings()
    if not settings.get("llm_url"):
        raise HTTPException(400, "LLM URL not configured — visit Settings.")

    _run_curriculum_eval(shortname)
    result = get_curriculum_eval(shortname)
    if not result:
        raise HTTPException(502, "Evaluation failed — check LLM connection and model.")
    return result


@router.get("/curriculum")
def get_curriculum():
    """Return AI-evaluated curriculum domain coverage for all library courses."""
    courses = list_courses()
    evals   = {e["shortname"]: e for e in list_curriculum_evals()}

    course_data = []
    for course in courses:
        versions = list_versions(course["shortname"])
        module_count = 0
        if versions:
            v = get_version(versions[0]["id"])
            if v:
                module_count = len(v.get("content", {}).get("course_structure", {}).get("modules", []))

        ev = evals.get(course["shortname"])
        if ev:
            domains      = ev["scores"]
            evaluated_at = ev.get("evaluated_at", "")
            model_used   = ev.get("model_used", "")
            eval_status  = "evaluated"
        else:
            domains      = {d: 0 for d in _CURRICULUM_DOMAINS}
            evaluated_at = ""
            model_used   = ""
            eval_status  = "pending"

        course_data.append({
            "shortname":    course["shortname"],
            "fullname":     course["fullname"],
            "category":     course.get("category", ""),
            "instance":     course.get("instance", ""),
            "module_count": module_count,
            "domains":      domains,
            "eval_status":  eval_status,
            "evaluated_at": evaluated_at,
            "model_used":   model_used,
        })

    return {"courses": course_data, "domains": _CURRICULUM_DOMAINS}


# ── Review schedules ──────────────────────────────────────────────────────────

class ScheduleIn(BaseModel):
    shortname:     str
    version_id:    int | None = None
    agent_id:      str
    agent_label:   str
    agent_color:   str = "gray"
    agent_context: str
    model_id:      str
    frequency:     str = "weekly"


@router.get("/schedules")
def list_review_schedules():
    return list_schedules()


def _do_run_overdue_reviews() -> dict:
    """Run all overdue scheduled reviews. Called by the HTTP route and the background scheduler."""
    from datetime import timedelta

    if not _review_lock.acquire(blocking=False):
        return {"triggered": 0, "errors": ["review run already in progress"]}

    try:
        overdue   = get_overdue_schedules()
        settings  = get_settings()
        triggered = 0
        errors: list[str] = []

        for sched in overdue:
            shortname = sched["shortname"]
            try:
                vers = list_versions(shortname)
                if not vers:
                    errors.append(f"{shortname}: no versions")
                    continue

                vid = sched.get("version_id")
                ver = get_version(int(vid)) if vid else get_version(vers[0]["id"])
                if not ver:
                    errors.append(f"{shortname}: version not found")
                    continue

                course_text = _format_for_review(shortname, ver)
                system_msg  = sched["agent_context"] + _JSON_OUTPUT_INSTRUCTION
                messages    = [
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": f"Audit this course:\n\n{course_text}"},
                ]

                raw = cc.call_llm(
                    messages,
                    settings.get("llm_url", ""),
                    model_id=sched.get("model_id") or "local-model",
                    temperature=0.2,
                    max_tokens=2048,
                    api_key=settings.get("llm_api_key", ""),
                )

                result = None
                for candidate in [raw, _extract_json_block(raw)]:
                    if not candidate:
                        continue
                    try:
                        result = json.loads(candidate)
                        break
                    except Exception:
                        pass

                if result is None:
                    errors.append(f"{shortname}: LLM returned non-JSON")
                    continue

                response = {"shortname": shortname, "version_num": ver.get("version_num"), **result}
                save_review(shortname, ver.get("id"), ver.get("version_num"),
                            sched["agent_id"], sched["agent_label"], sched["agent_color"], response)

                freq_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(
                    sched.get("frequency", "weekly"), 7)
                now_str  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
                next_run = (datetime.now(UTC) + timedelta(days=freq_days)).strftime("%Y-%m-%d %H:%M:%S")
                update_schedule_run(sched["id"], now_str, next_run)
                triggered += 1

            except Exception as e:
                errors.append(f"{shortname}: {e}")

        return {"triggered": triggered, "errors": errors}
    finally:
        _review_lock.release()


@router.post("/schedules/run-overdue")
def run_overdue_reviews():
    return _do_run_overdue_reviews()


@router.post("/schedules")
def create_review_schedule(body: ScheduleIn):
    from datetime import timedelta

    freq_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(body.frequency, 7)
    next_run  = (datetime.now(UTC) + timedelta(days=freq_days)).strftime("%Y-%m-%d %H:%M:%S")
    return save_schedule(
        shortname=body.shortname,
        agent_id=body.agent_id,
        agent_label=body.agent_label,
        agent_color=body.agent_color,
        agent_context=body.agent_context,
        model_id=body.model_id,
        frequency=body.frequency,
        next_run_at=next_run,
        version_id=body.version_id,
    )


@router.delete("/schedules")
def clear_review_schedules():
    return {"deleted": clear_schedules()}


@router.delete("/schedules/{schedule_id}")
def delete_review_schedule(schedule_id: int):
    if not delete_schedule(schedule_id):
        raise HTTPException(404, "Schedule not found")
    return {"deleted": schedule_id}


# ── Courses ───────────────────────────────────────────────────────────────────

@router.get("")
def get_courses():
    return list_courses()


@router.get("/{shortname}")
def get_one_course(shortname: str):
    course = get_course(shortname)
    if not course:
        raise HTTPException(404, f"Course {shortname} not found")
    return course


@router.put("/{shortname}")
def update_course(shortname: str, body: CourseIn):
    return upsert_course(shortname, body.fullname, body.professor,
                         body.category, body.prompt)


# ── Versions ──────────────────────────────────────────────────────────────────

@router.get("/{shortname}/versions")
def get_versions(shortname: str):
    return list_versions(shortname)


@router.get("/{shortname}/versions/{version_id}")
def get_one_version(shortname: str, version_id: int):
    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")
    return v


@router.delete("/{shortname}")
def remove_course(shortname: str):
    if not delete_course(shortname):
        raise HTTPException(404, f"Course {shortname} not found")
    return {"deleted": shortname}


@router.delete("/{shortname}/versions/{version_id}")
def remove_version(shortname: str, version_id: int):
    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")
    delete_version(version_id)
    return {"deleted": version_id}


@router.post("/{shortname}/versions/import")
def import_version(shortname: str, body: ImportVersionIn):
    """Save an existing content dict as a new version (no LLM needed)."""
    upsert_course(shortname, body.fullname, body.professor,
                  body.category, "", instance="Local")
    version = save_version(shortname, body.model_used,
                           body.start_date, body.end_date, body.content)
    _schedule_curriculum_eval(shortname, version["id"])
    return version


# ── Bulk delete ───────────────────────────────────────────────────────────────

class BulkDeleteIn(BaseModel):
    shortnames: list[str]


@router.post("/bulk-delete")
def bulk_delete_courses(body: BulkDeleteIn):
    """Delete multiple courses and all their versions."""
    deleted, not_found = [], []
    for sn in body.shortnames:
        if delete_course(sn):
            deleted.append(sn)
        else:
            not_found.append(sn)
    return {"deleted": deleted, "not_found": not_found}


# ── Import .mbz from a URL (e.g. Moodle backup download) ────────────────────

@router.post("/import-mbz")
def import_mbz_from_url(body: ImportMbzIn):
    """Download a .mbz from a URL, parse its structure, save as a library version."""
    try:
        resp = http_requests.get(body.download_url, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"Failed to download backup file: {e}")

    try:
        parsed = _parse_mbz(resp.content)
    except Exception as e:
        raise HTTPException(422, f"Could not parse .mbz file: {e}")

    shortname = body.shortname or parsed["shortname"] or "mbz-import"
    fullname  = body.fullname  or parsed["fullname"]  or shortname

    upsert_course(shortname, fullname, "", "", "", instance=body.instance)
    version = save_version(
        shortname, "mbz-import",
        parsed["start_date"], parsed["end_date"],
        parsed["content"],
    )
    _schedule_curriculum_eval(shortname, version["id"])
    return version


# ── Debug: inspect .mbz without saving ───────────────────────────────────────

@router.post("/debug-mbz")
async def debug_mbz(file: UploadFile = File(...)):
    """Return raw parse diagnostics for a .mbz without saving anything."""
    mbz_bytes = await file.read()
    zf = _MbzReader(mbz_bytes)
    all_names = sorted(zf.names)

    manifest_activities = []
    if "moodle_backup.xml" in zf.names:
        root = ET.parse(zf.open("moodle_backup.xml")).getroot()
        for act in root.findall(".//contents/activities/activity"):
            manifest_activities.append({
                "moduleid":   act.findtext("moduleid"),
                "sectionid":  act.findtext("sectionid"),
                "modulename": act.findtext("modulename"),
                "title":      act.findtext("title"),
                "directory":  act.findtext("directory"),
            })

    sec_pat = re.compile(r"sections/section_\d+/section\.xml")
    sections_found = []
    for name in all_names:
        if not sec_pat.match(name):
            continue
        root    = ET.parse(zf.open(name)).getroot()
        summary = root.findtext("summary", "") or ""
        sections_found.append({
            "file":            name,
            "id_attr":         root.get("id"),
            "number":          root.findtext("number"),
            "name":            root.findtext("name"),
            "summary_len":     len(summary),
            "summary_preview": summary[:120],
        })

    act_samples = []
    for act in manifest_activities:
        d    = (act["directory"] or "").strip()
        mn   = act["modulename"] or ""
        path = re.sub(r'^[./]+', '', d) + f"/{mn}.xml"
        exists = path in zf.names
        content_preview = ""
        if exists:
            r = ET.parse(zf.open(path)).getroot()
            if mn == "page":
                intro = r.findtext(".//intro",   "") or ""
                body  = r.findtext(".//content", "") or ""
                val   = (intro + body).strip()
            else:
                val = r.findtext(".//intro", "") or r.findtext(".//content", "") or ""
            content_preview = val[:200]
        act_samples.append({
            "moduleid":        act["moduleid"],
            "modulename":      mn,
            "title":           act["title"],
            "directory_raw":   act["directory"],
            "resolved_path":   path,
            "path_exists":     exists,
            "content_preview": content_preview,
        })

    return {
        "total_files":         len(all_names),
        "sections_found":      sections_found,
        "manifest_activities": manifest_activities,
        "activity_samples":    act_samples,
        "file_list_sample":    all_names[:80],
    }


# ── Import .mbz from a local file upload ─────────────────────────────────────

@router.post("/upload-mbz")
async def upload_mbz_file(file: UploadFile = File(...)):
    """Accept a .mbz file upload, parse its structure, save as a library version."""
    mbz_bytes = await file.read()
    try:
        parsed = _parse_mbz(mbz_bytes)
    except Exception as e:
        raise HTTPException(422, f"Could not parse .mbz file: {e}")

    shortname = parsed["shortname"] or (file.filename or "mbz-import").removesuffix(".mbz")
    fullname  = parsed["fullname"]  or shortname

    upsert_course(shortname, fullname, "", "", "", instance="Local")
    version = save_version(
        shortname, "mbz-import",
        parsed["start_date"], parsed["end_date"],
        parsed["content"],
    )
    _schedule_curriculum_eval(shortname, version["id"])
    return version


# ── Patch version content (homework_spec etc.) ───────────────────────────────

class PatchVersionIn(BaseModel):
    homework_spec: dict[str, str] | None = None


@router.patch("/{shortname}/versions/{version_id}")
def patch_version(shortname: str, version_id: int, body: PatchVersionIn):
    """Partially update a version's content (e.g. homework_spec)."""
    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")
    content = v["content"]
    if body.homework_spec is not None:
        content["homework_spec"] = {int(k): val for k, val in body.homework_spec.items()}
    updated = update_version_content(version_id, content)
    return updated


# ── Regenerate a single module's content ─────────────────────────────────────

NON_REGENERABLE = {"mbz-import", "moodle-import", "imported"}


class RegenerateModuleIn(BaseModel):
    instructions: str = ""
    model_id: str = ""
    custom_prompt: str = ""


@router.post("/{shortname}/versions/{version_id}/modules/{module_num}/regenerate")
def regenerate_module(shortname: str, version_id: int, module_num: int,
                      body: RegenerateModuleIn = None):
    """Re-run the LLM for one module and update the stored version in place."""
    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")
    if v["model_used"] in NON_REGENERABLE:
        raise HTTPException(400, "Cannot regenerate content for imported courses — use Generate Course instead")

    course = get_course(shortname)
    content = v["content"]
    modules = content.get("course_structure", {}).get("modules", [])
    mod = next((m for m in modules if m["number"] == module_num), None)
    if not mod:
        raise HTTPException(404, f"Module {module_num} not found in course structure")

    settings  = get_settings()
    llm_url   = settings.get("llm_url", cc.DEFAULT_LLM_URL)
    api_key   = settings.get("llm_api_key", "")
    professor = (course or {}).get("professor", "")
    fullname  = (course or {}).get("fullname", shortname)

    b = body or RegenerateModuleIn()
    model_id  = b.model_id.strip() or v["model_used"]
    raw_mc = cc.generate_module_content(
        mod["number"], mod["title"], mod["objective"],
        mod.get("key_topics", []), fullname, professor,
        llm_url, model_id,
        extra_instructions=b.instructions,
        custom_prompt=b.custom_prompt,
        api_key=api_key,
    )
    normalized = {
        **raw_mc,
        "module_num":     mod["number"],
        "lecture_html":   cc.sections_to_html(raw_mc.get("sections", [])),
        "glossary_terms": [item.get("term", "") for item in raw_mc.get("glossary", [])],
        "forum_question": raw_mc.get("discussion_question", ""),
    }

    mc_list = content.get("module_contents", [])
    replaced = False
    for i, item in enumerate(mc_list):
        if item.get("module_num") == module_num:
            mc_list[i] = normalized
            replaced = True
            break
    if not replaced:
        mc_list.append(normalized)
    content["module_contents"] = mc_list

    update_version_content(version_id, content)
    return {"ok": True, "module_content": normalized}


# ── Fork: save current version content as a new version ─────────────────────

@router.post("/{shortname}/versions/{version_id}/fork")
def fork_version(shortname: str, version_id: int):
    """Copy this version's content into a new version (version_num + 1)."""
    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")
    new_version = save_version(
        shortname, v["model_used"],
        v["start_date"], v["end_date"],
        v["content"],
    )
    return new_version


# ── Generate (calls LLM pipeline) ────────────────────────────────────────────

@router.post("/generate")
def generate_course(body: GenerateIn):
    """Run full LLM pipeline and store result as a new version."""
    settings = get_settings()
    llm_url  = settings.get("llm_url", cc.DEFAULT_LLM_URL)
    api_key  = settings.get("llm_api_key", "")

    from datetime import datetime, timedelta
    start_dt = (datetime.strptime(body.start_date, "%Y-%m-%d")
                if body.start_date else datetime.now())
    end_dt   = (datetime.strptime(body.end_date, "%Y-%m-%d")
                if body.end_date else start_dt + timedelta(weeks=8))

    num_modules = max(3, min(12, body.module_count))
    language    = body.language or "es"

    # Step 1 — course structure
    course_structure = cc.generate_course_structure(
        body.shortname, body.fullname, body.prompt, llm_url, body.model_id, api_key=api_key,
        num_modules=num_modules, language=language)
    modules = course_structure["modules"]

    # Step 2 — module content
    module_contents = []
    for m in modules:
        mc = cc.generate_module_content(
            m["number"], m["title"], m["objective"],
            m.get("key_topics", []), body.fullname, body.professor,
            llm_url, body.model_id, api_key=api_key, language=language)
        # Normalise to the same shape as .mbz imports so the UI viewer works
        module_contents.append({
            **mc,
            "module_num":     m["number"],
            "lecture_html":   cc.sections_to_html(mc.get("sections", [])),
            "glossary_terms": [item.get("term", "") for item in mc.get("glossary", [])],
            "forum_question": mc.get("discussion_question", ""),
        })

    # Step 3 — syllabus
    syllabus = cc.generate_syllabus(
        body.fullname, body.shortname, body.professor,
        modules, llm_url, body.model_id, api_key=api_key, language=language)

    # Step 4 — quiz questions
    quiz_questions = cc.generate_quiz_questions(
        body.fullname, modules, body.num_questions, llm_url, body.model_id, api_key=api_key,
        language=language)

    # Step 5 — homework prompts (if requested)
    hw_spec = {int(k): v for k, v in body.homework_spec.items()}
    homework_prompts = {}
    if hw_spec:
        homework_prompts = cc.generate_homework_prompts(
            body.fullname, modules, hw_spec, llm_url, body.model_id, api_key=api_key,
            language=language)

    content = {
        "course_structure":  course_structure,
        "module_contents":   module_contents,
        "syllabus":          syllabus,
        "quiz_questions":    quiz_questions,
        "homework_prompts":  homework_prompts,
        "homework_spec":     hw_spec,
    }

    upsert_course(body.shortname, body.fullname, body.professor,
                  body.category, body.prompt, instance="Local")
    version = save_version(body.shortname, body.model_id,
                           body.start_date, body.end_date, content)
    _schedule_curriculum_eval(body.shortname, version["id"])
    return version


# ── Build .mbz ────────────────────────────────────────────────────────────────

@router.post("/{shortname}/versions/{version_id}/build")
def build_mbz(shortname: str, version_id: int):
    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")

    course = get_course(shortname)
    if not course:
        raise HTTPException(404, "Course not found")

    from datetime import datetime
    start_date = v.get("start_date", "")
    end_date   = v.get("end_date", "")
    start_dt   = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now()
    from datetime import timedelta
    end_dt     = datetime.strptime(end_date, "%Y-%m-%d") if end_date else start_dt + timedelta(weeks=8)

    # homework_spec may be stored in content as {str_key: str} — normalise to {int: str}
    raw_hw = v["content"].get("homework_spec", {})
    hw_spec = {int(k): val for k, val in raw_hw.items()}

    config = {
        "shortname":     shortname,
        "fullname":      course["fullname"],
        "professor":     course["professor"],
        "category":      course["category"],
        "start_ts":      int(start_dt.timestamp()),
        "end_ts":        int(end_dt.timestamp()),
        "homework_spec": hw_spec,
    }

    mbz_bytes = cc.build_mbz(config, v["content"])
    filename  = f"{shortname}_v{v['version_num']}.mbz"
    out_path  = BUILD_DIR / filename
    out_path.write_bytes(mbz_bytes)
    record_build(version_id, filename)

    return {"filename": filename, "size_kb": round(len(mbz_bytes) / 1024, 1)}


@router.get("/{shortname}/versions/{version_id}/download")
def download_mbz(shortname: str, version_id: int):
    v = get_version(version_id)
    if not v or v["shortname"] != shortname:
        raise HTTPException(404, "Version not found")

    filename = f"{shortname}_v{v['version_num']}.mbz"
    path     = BUILD_DIR / filename
    if not path.exists():
        # Auto-build if not cached
        build_mbz(shortname, version_id)
    return FileResponse(path, media_type="application/octet-stream",
                        filename=filename)
