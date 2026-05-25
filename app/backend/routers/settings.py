"""App settings + named Moodle instance management."""

import json
import secrets
import csv
import io
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..database import get_settings, set_setting, list_admin_audits

router = APIRouter(prefix="/settings", tags=["settings"])


# ── Models ────────────────────────────────────────────────────────────────────

class SettingsIn(BaseModel):
    moodle_url:    str = ""
    moodle_token:  str = ""
    canvas_url:    str = ""
    canvas_token:  str = ""
    llm_url:       str = ""
    llm_api_key:   str = ""
    last_model:    str = ""


class MoodleInstanceIn(BaseModel):
    name:  str
    url:   str
    token: str


# ── Instance helpers ──────────────────────────────────────────────────────────

def _get_instances() -> list[dict]:
    raw = get_settings().get("moodle_instances", "[]")
    try:
        return json.loads(raw)
    except Exception:
        return []


def _save_instances(instances: list[dict]):
    set_setting("moodle_instances", json.dumps(instances, ensure_ascii=False))


def _mask(token: str) -> str:
    return ("*" * (len(token) - 4) + token[-4:]) if len(token) > 4 else token


# ── Settings endpoints ────────────────────────────────────────────────────────

@router.get("")
def read_settings():
    s = get_settings()
    token = s.get("moodle_token", "")
    s["moodle_token_masked"] = _mask(token)
    s["active_instance"] = s.get("active_instance", "")
    canvas_token = s.get("canvas_token", "")
    s["canvas_token_masked"] = _mask(canvas_token) if canvas_token else ""
    s.pop("canvas_token", None)   # never send raw token to frontend
    api_key = s.get("llm_api_key", "")
    s["llm_api_key_masked"] = _mask(api_key) if api_key else ""
    s.pop("llm_api_key", None)   # never send the raw key to the frontend
    return s


@router.put("")
def write_settings(body: SettingsIn):
    data = body.model_dump()

    # Trim whitespace from all string settings (common when pasting tokens/URLs).
    for key, value in list(data.items()):
        if isinstance(value, str):
            data[key] = value.strip()

    # Canvas tokens are frequently pasted with surrounding quotes or trailing
    # punctuation from chat/messages; normalize before persisting.
    if data.get("canvas_token"):
        data["canvas_token"] = data["canvas_token"].strip("\"'").rstrip(",;:")

    for url_key in ("moodle_url", "canvas_url", "llm_url"):
        if data.get(url_key) and not data[url_key].startswith(("http://", "https://")):
            data[url_key] = "http://" + data[url_key]

    for key, value in data.items():
        if value:
            set_setting(key, value)

    return get_settings()


# ── Instance endpoints ────────────────────────────────────────────────────────

@router.get("/instances")
def list_instances():
    """Return all saved Moodle instances with masked tokens."""
    instances = _get_instances()
    active = get_settings().get("active_instance", "")
    return [
        {
            "name":         inst["name"],
            "url":          inst["url"],
            "token_masked": _mask(inst.get("token", "")),
            "active":       inst["name"] == active,
            "added_at":     inst.get("added_at", ""),
        }
        for inst in instances
    ]


@router.post("/instances")
def save_instance(body: MoodleInstanceIn):
    """Add or update a named Moodle instance."""
    url = body.url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url

    instances = _get_instances()
    for inst in instances:
        if inst["name"] == body.name:
            inst["url"] = url
            if body.token:
                inst["token"] = body.token
            _save_instances(instances)
            return {"ok": True, "updated": True}

    instances.append({
        "name":     body.name,
        "url":      url,
        "token":    body.token,
        "added_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_instances(instances)
    return {"ok": True, "updated": False}


@router.post("/instances/{name}/activate")
def activate_instance(name: str):
    """Set a saved instance as the active Moodle connection."""
    inst = next((i for i in _get_instances() if i["name"] == name), None)
    if not inst:
        raise HTTPException(404, f"Instance '{name}' not found")
    set_setting("moodle_url",        inst["url"])
    set_setting("moodle_token",      inst["token"])
    set_setting("active_instance",   name)
    return {"ok": True, "activated": name}


@router.delete("/instances/{name}")
def remove_instance(name: str):
    """Delete a saved instance."""
    instances = _get_instances()
    filtered  = [i for i in instances if i["name"] != name]
    if len(filtered) == len(instances):
        raise HTTPException(404, f"Instance '{name}' not found")
    _save_instances(filtered)
    if get_settings().get("active_instance") == name:
        set_setting("active_instance", "")
    return {"ok": True}


# ── Auth endpoints ─────────────────────────────────────────────────────────────

class TokenIn(BaseModel):
    token: str = ""


class OperatorIn(BaseModel):
    name: str = ""


class AdminPolicyIn(BaseModel):
    allowed_role_ids: str = ""


@router.get("/auth/status")
def auth_status():
    """Return whether a token is configured (never returns the token itself)."""
    token = get_settings().get("auth_token", "")
    return {"enabled": bool(token)}


@router.get("/auth/verify")
def auth_verify():
    """Return 200 if the caller's Authorization header is valid (checked by middleware)."""
    return {"ok": True}


@router.post("/auth/token")
def set_auth_token(body: TokenIn):
    """Set or replace the auth token. Pass an empty string to disable auth."""
    token = body.token.strip()
    if not token:
        set_setting("auth_token", "")
        return {"ok": True, "enabled": False}
    set_setting("auth_token", token)
    return {"ok": True, "enabled": True}


@router.post("/auth/token/generate")
def generate_auth_token():
    """Generate a secure random token and save it."""
    token = secrets.token_urlsafe(32)
    set_setting("auth_token", token)
    return {"ok": True, "token": token, "enabled": True}


@router.delete("/auth/token")
def clear_auth_token():
    """Remove the auth token, disabling authentication."""
    set_setting("auth_token", "")
    return {"ok": True, "enabled": False}


@router.get("/auth/operator")
def get_auth_operator():
    return {"name": (get_settings().get("auth_operator_name", "") or "").strip()}


@router.post("/auth/operator")
def set_auth_operator(body: OperatorIn):
    name = body.name.strip()[:120]
    set_setting("auth_operator_name", name)
    return {"ok": True, "name": name}


@router.get("/audit-logs")
def get_audit_logs(limit: int = 100, offset: int = 0,
                   area: str = "", action: str = "", actor: str = "",
                   status: str = "", q: str = ""):
    """Return recent admin audit records with optional filters."""
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    items, total = list_admin_audits(
        limit=safe_limit,
        offset=safe_offset,
        area=area.strip(),
        action=action.strip(),
        actor=actor.strip(),
        status=status.strip(),
        query=q.strip(),
    )
    return {
        "items": items,
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/audit-logs/export")
def export_audit_logs(limit: int = 500):
    safe_limit = max(1, min(limit, 5000))
    rows, _ = list_admin_audits(limit=safe_limit, offset=0)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "actor", "area", "action", "target_type", "target_id", "status", "detail_json"])
    for row in rows:
        writer.writerow([
            row.get("id", ""),
            row.get("created_at", ""),
            row.get("actor", ""),
            row.get("area", ""),
            row.get("action", ""),
            row.get("target_type", ""),
            row.get("target_id", ""),
            row.get("status", ""),
            json.dumps(row.get("detail", {}), ensure_ascii=False),
        ])

    csv_data = output.getvalue()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=admin-audit-{ts}.csv"},
    )


@router.get("/admin-policy")
def get_admin_policy():
    raw = (get_settings().get("admin_allowed_role_ids", "3,4,5") or "3,4,5").strip()
    parsed = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            parsed.append(int(token))
        except ValueError:
            continue
    if not parsed:
        parsed = [3, 4, 5]
    return {"allowed_role_ids": ",".join(str(v) for v in parsed), "parsed_role_ids": parsed}


@router.post("/admin-policy")
def set_admin_policy(body: AdminPolicyIn):
    raw = (body.allowed_role_ids or "").strip()
    if not raw:
        raw = "3,4,5"

    parsed = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if not token.isdigit():
            raise HTTPException(400, f"Invalid role id '{token}'")
        role_id = int(token)
        if role_id <= 0:
            raise HTTPException(400, f"Invalid role id '{token}'")
        parsed.append(role_id)

    if not parsed:
        raise HTTPException(400, "At least one role id is required")

    normalized = ",".join(str(v) for v in sorted(set(parsed)))
    set_setting("admin_allowed_role_ids", normalized)
    return {"ok": True, "allowed_role_ids": normalized, "parsed_role_ids": sorted(set(parsed))}
