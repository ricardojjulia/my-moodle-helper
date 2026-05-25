import builtins

import create_course as cc


def test_extract_json_works_without_json_repair(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "json_repair":
            raise ImportError("json_repair not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    parsed = cc.extract_json("```json\n{\"a\": 1, \"b\": [2, 3,],}\n```")

    assert parsed == {"a": 1, "b": [2, 3]}