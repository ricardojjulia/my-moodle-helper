"""Tests for the .mbz builder in create_course.py."""
import json
import sys
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import create_course as cc


def _minimal_content(n_modules: int) -> dict:
    modules = [
        {
            "number": i + 1,
            "title": f"Module {i + 1}: Test",
            "objective": f"Objective {i + 1}",
            "key_topics": ["topic a", "topic b"],
        }
        for i in range(n_modules)
    ]
    mc = [
        {
            "module_num": i + 1,
            "lecture_html": f"<p>Content {i + 1}</p>",
            "forum_question": f"Question {i + 1}",
            "glossary_terms": ["alpha", "beta"],
            "glossary": [{"term": "alpha", "definition": "First"}, {"term": "beta", "definition": "Second"}],
            "sections": [{"heading": "Section 1", "text": "Body text " * 20}],
            "discussion_question": f"Discussion {i + 1}",
        }
        for i in range(n_modules)
    ]
    return {
        "course_structure": {
            "course_summary": "A test course",
            "modules": modules,
        },
        "module_contents": mc,
        "syllabus": {"description": "Test syllabus"},
        "quiz_questions": [
            {"question": "What is theology?", "options": ["A", "B", "C", "D"], "answer": "A"}
        ],
        "homework_prompts": {},
        "homework_spec": {},
    }


def _build(n_modules: int) -> zipfile.ZipFile:
    import time
    content = _minimal_content(n_modules)
    config = {
        "shortname":     f"TEST{n_modules}",
        "fullname":      f"Test Course {n_modules} Modules",
        "professor":     "Test Prof",
        "category":      "Test Category",
        "start_ts":      int(time.time()),
        "end_ts":        int(time.time()) + 86400 * 56,
        "homework_spec": {},
    }
    mbz_bytes = cc.build_mbz(config, content)
    assert mbz_bytes, "build_mbz returned empty bytes"
    assert zipfile.is_zipfile(BytesIO(mbz_bytes)), "Output is not a valid ZIP"
    return zipfile.ZipFile(BytesIO(mbz_bytes))


def test_build_5_modules():
    zf = _build(5)
    names = set(zf.namelist())
    assert "moodle_backup.xml" in names
    assert "course/course.xml"  in names
    for i in range(5):
        assert f"sections/section_{i + 2}/section.xml" in names, f"Missing section {i + 2}"
        page_id  = 109 + i * 2
        forum_id = 110 + i * 2
        assert f"activities/page_{page_id}/page.xml"   in names
        assert f"activities/forum_{forum_id}/forum.xml" in names


def test_build_3_modules():
    zf = _build(3)
    names = set(zf.namelist())
    for i in range(3):
        assert f"sections/section_{i + 2}/section.xml" in names
    # section 5 and 6 (modules 4+5) must NOT exist
    assert "sections/section_5/section.xml" not in names
    assert "sections/section_6/section.xml" not in names


def test_build_10_modules():
    zf = _build(10)
    names = set(zf.namelist())
    for i in range(10):
        assert f"sections/section_{i + 2}/section.xml" in names, f"Missing section {i + 2}"
        page_id  = 109 + i * 2
        forum_id = 110 + i * 2
        assert f"activities/page_{page_id}/page.xml"   in names
        assert f"activities/forum_{forum_id}/forum.xml" in names


def test_backup_xml_contains_all_sections():
    zf  = _build(7)
    xml = zf.read("moodle_backup.xml").decode()
    for i in range(7):
        sid = i + 2
        assert f"section_{sid}" in xml, f"moodle_backup.xml missing section_{sid}"


def test_course_xml_present():
    zf  = _build(5)
    xml = zf.read("course/course.xml").decode()
    assert "TEST5" in xml
    assert "Test Course 5 Modules" in xml


def test_homework_module_added():
    content = _minimal_content(5)
    content["homework_spec"] = {1: "assign"}
    content["homework_prompts"] = {1: {"title": "HW Assignment 1", "description": "Do the work."}}
    import time
    config = {
        "shortname": "TESTHW",
        "fullname":  "HW Test",
        "professor": "Prof",
        "category":  "Cat",
        "start_ts":  int(time.time()),
        "end_ts":    int(time.time()) + 86400 * 56,
        "homework_spec": {1: "assign"},
    }
    mbz = cc.build_mbz(config, content)
    zf = zipfile.ZipFile(BytesIO(mbz))
    names = set(zf.namelist())
    # homework module ID for 5-module course = 109 + 2*5 = 119
    assert any("assign_119" in n for n in names), f"No assign_119 in {names}"
