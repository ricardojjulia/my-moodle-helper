from app.backend import database as dbmod


def test_curriculum_list_tolerates_malformed_scores_json(client):
    dbmod.upsert_course(
        shortname="TH100",
        fullname="Intro Theology",
        professor="Prof Test",
        category="Test Cat",
        prompt="Test prompt",
        instance="Local",
    )

    with dbmod.db() as conn:
        conn.execute(
            """
            INSERT INTO curriculum_evaluations(shortname, version_id, model_used, scores_json, reasoning)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("TH100", None, "test-model", "{'Old Testament': 85, 'Ethics': '40', 'Bad': 'x'}", "legacy format"),
        )

    res = client.get("/api/courses/curriculum")
    assert res.status_code == 200

    payload = res.json()
    assert "courses" in payload

    course = next(c for c in payload["courses"] if c["shortname"] == "TH100")
    assert course["eval_status"] == "evaluated"
    assert course["domains"]["Old Testament"] == 85
    assert course["domains"]["Ethics"] == 40
