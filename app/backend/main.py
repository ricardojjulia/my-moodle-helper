"""FastAPI entry point."""

from contextlib import asynccontextmanager
from datetime import datetime
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


app = FastAPI(title="Moodle Course Administrator API", version="1.0.0", lifespan=lifespan)

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
    token = app_settings.get("auth_token", "")
    if not token:
        # Auth disabled — let request through
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {token}":
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
