import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backend import database as dbmod
from app.backend import main as mainmod
from app.backend.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_db_path = tmp_path / "library.db"
    monkeypatch.setattr(dbmod, "DB_PATH", test_db_path)
    dbmod.init_db()
    dbmod.set_setting("moodle_url", "http://moodle.example")
    dbmod.set_setting("moodle_token", "test-token")
    mainmod._rate_limit_buckets.clear()

    with TestClient(app) as test_client:
        yield test_client
