"""FastAPI entry point."""

from contextlib import asynccontextmanager
from collections import deque
from datetime import datetime
from threading import Lock
from time import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .database import init_db, get_settings
from .routers import canvas, courses, llm, moodle, settings

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _HAS_APSCHEDULER = True
except ImportError:
    _HAS_APSCHEDULER = False

_scheduler = None
_rate_limit_lock = Lock()
_rate_limit_buckets: dict[str, deque[float]] = {}


def _is_sensitive_write(path: str, method: str) -> bool:
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    sensitive_prefixes = (
        "/api/moodle/users",
        "/api/moodle/courses/",
        "/api/settings/admin-policy",
        "/api/settings/audit-policy",
        "/api/settings/audit-logs/prune",
    )
    if path.startswith("/api/moodle/courses/"):
        # Limit only enrollment/role write operations under course routes.
        return (
            "/enrollments" in path
            or "/roles/assign" in path
            or "/roles/unassign" in path
        )
    return path.startswith(sensitive_prefixes)


def _allow_write_request(client_key: str, path: str, max_requests: int, window_s: int) -> bool:
    now = time()
    window = max(1, int(window_s))
    max_count = max(1, int(max_requests))
    bucket_key = f"{client_key}:{path}"

    with _rate_limit_lock:
        bucket = _rate_limit_buckets.get(bucket_key)
        if bucket is None:
            bucket = deque()
            _rate_limit_buckets[bucket_key] = bucket

        cutoff = now - window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= max_count:
            return False

        bucket.append(now)
        return True


def _scheduler_tick():
    try:
        result = courses._do_run_overdue_reviews()
        if result["triggered"] or result["errors"]:
            print(f"[scheduler] {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC — "
                  f"triggered={result['triggered']} errors={result['errors']}")
    except Exception as e:
        print(f"[scheduler] error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    init_db()

    if _HAS_APSCHEDULER:
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(_scheduler_tick, "interval", minutes=15, id="review_tick",
                           next_run_time=None)
        _scheduler.start()
        print("[scheduler] background review scheduler started (15-minute interval)")
    else:
        print("[scheduler] apscheduler not installed — scheduled reviews will only run on demand")

    yield

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="My Moodle Helper API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4101", "http://localhost:4102"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth middleware ────────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    _AUTH_EXEMPT = {"/api/auth/token", "/api/auth/verify", "/api/auth/status", "/docs",
                    "/openapi.json", "/redoc"}
    path = request.url.path

    # Static assets and SPA fallback always pass through
    if not path.startswith("/api/") or any(path.startswith(e) for e in _AUTH_EXEMPT):
        return await call_next(request)

    app_settings = get_settings()
    configured_actor = (app_settings.get("auth_operator_name", "") or "").strip()
    header_actor = (request.headers.get("X-Admin-Actor", "") or "").strip()[:120]
    request.state.audit_actor = configured_actor or header_actor or "local-admin"

    token = app_settings.get("auth_token", "")
    if not token:
        # Auth disabled — let request through after write-rate checks.
        if _is_sensitive_write(path, request.method):
            try:
                max_requests = int((app_settings.get("admin_write_rate_limit_max", "30") or "30").strip())
            except ValueError:
                max_requests = 30
            try:
                window_s = int((app_settings.get("admin_write_rate_limit_window_s", "60") or "60").strip())
            except ValueError:
                window_s = 60
            client_host = (request.client.host if request.client else "local") or "local"
            if not _allow_write_request(client_host, path, max_requests, window_s):
                return JSONResponse(status_code=429, content={"detail": "Too many write requests; please retry shortly."})
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {token}":
        request.state.audit_actor = configured_actor or "token-admin"
        if _is_sensitive_write(path, request.method):
            try:
                max_requests = int((app_settings.get("admin_write_rate_limit_max", "30") or "30").strip())
            except ValueError:
                max_requests = 30
            try:
                window_s = int((app_settings.get("admin_write_rate_limit_window_s", "60") or "60").strip())
            except ValueError:
                window_s = 60
            client_host = (request.client.host if request.client else "local") or "local"
            if not _allow_write_request(client_host, path, max_requests, window_s):
                return JSONResponse(status_code=429, content={"detail": "Too many write requests; please retry shortly."})
        return await call_next(request)

    return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


app.include_router(courses.router, prefix="/api")
app.include_router(llm.router,     prefix="/api")
app.include_router(moodle.router,  prefix="/api")
app.include_router(canvas.router,  prefix="/api")
app.include_router(settings.router,prefix="/api")

# Serve built frontend if it exists
STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        return FileResponse(STATIC_DIR / "index.html")
