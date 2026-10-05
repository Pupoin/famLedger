import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from auth import get_current_user, COOKIE_SECURE, IS_DEV
from config import BACKUP_PATH, VALID_MODES, get_app_mode
from users import get_display_names, get_user_count, is_primary_user
from database import (
    create_db_and_tables,
    check_db_integrity,
    engine,
    DB_PATH,
    DATA_DIR,
    get_session,
)
from routes import analytics, export, insights
from routes import (
    v1_transactions,
    v1_accounts,
    v1_categories,
    v1_rules,
    v1_debts,
    v1_transfers,
    v1_refunds,
    v1_oidc,
    v1_dashboard,
    v1_family,
    v1_tags,
    v1_budgets,
    v1_api_keys,
    v1_pending_fx,
    v1_schedules,
)
from auth import router as auth_router
from services.audit import audit_logger
from services.backup import BackupManager
from services.card_sharing import detach_unshared_cards
from services.schema import (
    SCHEMA_VERSION,
    assert_schema_not_newer,
    set_db_schema_version,
    sync_schema,
)
from version import __version__

logger = logging.getLogger("famledger")
logging.basicConfig(level=logging.INFO)

# Backups always land locally. BACKUP_PATH, when set, is an *additional*
# destination -- it used to replace this one, which meant configuring a cloud
# folder silently switched local backups off. See services/backup.py.
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_MIRROR_DIR = Path(BACKUP_PATH) if BACKUP_PATH else None

# Avatar uploads. Passed to BackupManager because they are user data and were
# previously excluded from every backup.
UPLOADS_DIR = DATA_DIR / "uploads"

# Require BACKUP_PATH to be a real mountpoint rather than merely an existing
# directory. Off by default: an OS-level sync folder (the OneDrive client, or a
# Dropbox directory) is a plain directory, not a mount, so demanding a mount
# would reject a perfectly good setup. Turn it on when BACKUP_PATH is a genuine
# network or FUSE mount and you want an unmounted target to be fatal.
BACKUP_REQUIRE_MOUNT = os.getenv("BACKUP_REQUIRE_MOUNT", "false").lower() in (
    "true", "1", "yes",
)

# CORS_ORIGINS: comma-separated list of allowed origins.
# Defaults to localhost:5173 for dev. Set to empty string whenever the UI and API
# share an origin — which is both supported deployments, since FastAPI serves the
# built SPA itself (see FRONTEND_DIST below) — or when behind a same-origin
# reverse proxy.
_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# Frontend dist directory — present after `npm run build` (Method 1: git clone),
# and also present in Docker: the image's build stage produces it and the
# Dockerfile copies it to /app/frontend/dist, which is exactly this path. So this
# block is what serves the SPA in Docker too. (An earlier comment here claimed
# nginx served static files in Docker — there is no nginx in the image; see the
# header of the Dockerfile, "one image, one container".)
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
FRONTEND_DIST_RESOLVED = FRONTEND_DIST.resolve()

# Retention/cadence for backups. Both are deliberately-chosen, single values —
# previously main.py passed max_backups=1000 (unbounded disk growth) while
# services/backup.py's own default was 10, and nothing enforced which was in
# effect. 30 is roughly a month of daily backups plus headroom for the
# mutation-triggered ones below.
MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", "30"))
# Back up every N mutations (not only once at process startup), so a
# long-running container's backups stay correlated with actual data change.
BACKUP_EVERY_N_MUTATIONS = int(os.getenv("BACKUP_EVERY_N_MUTATIONS", "20"))


def _warn_if_insecure_cookie_config() -> None:
    """Emit a startup warning for the ENV=production + secure-cookie-default
    footgun: the browser silently drops the session cookie over plain HTTP,
    so login appears to succeed and then every request 401s. We can't detect
    TLS termination from inside the process (a reverse proxy may be doing
    it), so this is a heads-up, not a hard failure. Split out from
    `lifespan` so it's directly unit-testable. See README.md
    "Troubleshooting" and review_order/06-backend-security-access.md #3.
    """
    if not IS_DEV and COOKIE_SECURE:
        logger.warning(
            "Insecure cookie configuration detected: ENV=production with secure "
            "session cookies enabled. If you are serving over plain HTTP (e.g. a "
            "local network without TLS), the browser will silently discard the "
            "session cookie and login will appear to succeed then immediately "
            "401. Set COOKIE_SECURE=false in your environment if you are not "
            "using HTTPS. Ignore this warning if you are genuinely behind a "
            "TLS-terminating reverse proxy."
        )


def _assert_backup_mirror_usable() -> None:
    """Fail loudly when BACKUP_PATH is configured but unusable.

    The previous behaviour was the dangerous one: create_backup() called
    mkdir(parents=True), so pointing BACKUP_PATH at an unmounted path simply
    created a plain directory there and wrote backups to the container's own
    disk -- while logging "Backup created and verified". You would discover it
    only when you went looking for an off-site copy that had never existed.

    So: never create this directory. If it isn't already there, that is a
    misconfiguration or an unmounted volume, and both should stop the app.
    """
    if BACKUP_MIRROR_DIR is None:
        return
    if not BACKUP_MIRROR_DIR.is_dir():
        raise RuntimeError(
            f"BACKUP_PATH is set to {BACKUP_MIRROR_DIR}, which does not exist "
            f"(or is not a directory). Refusing to start rather than creating it "
            f"and writing backups nowhere useful. Mount the target, or unset "
            f"BACKUP_PATH to keep local-only backups."
        )
    if BACKUP_REQUIRE_MOUNT and not os.path.ismount(BACKUP_MIRROR_DIR):
        raise RuntimeError(
            f"BACKUP_REQUIRE_MOUNT is enabled but {BACKUP_MIRROR_DIR} is not a "
            f"mountpoint — the volume is probably not mounted. Refusing to start."
        )
    if not os.access(BACKUP_MIRROR_DIR, os.W_OK):
        raise RuntimeError(
            f"BACKUP_PATH {BACKUP_MIRROR_DIR} is not writable by this process. "
            f"Refusing to start rather than failing every backup silently."
        )
    logger.info("Backups will also be mirrored to %s", BACKUP_MIRROR_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warn_if_insecure_cookie_config()
    if os.getenv("ENV", "development") != "development":
        _assert_backup_mirror_usable()

    # Integrity is checked BEFORE any DDL runs. The previous order created
    # tables and ran ALTERs first, i.e. it wrote to a database it had not yet
    # established was readable. A corrupt database must never be written to,
    # never serve traffic, and never get backed up over a good prior backup.
    if not check_db_integrity():
        raise RuntimeError(
            f"Database integrity check FAILED for {DB_PATH}. Refusing to start "
            f"to avoid serving corrupt data or overwriting a good backup with a "
            f"corrupt one. Restore from the most recent backup in {BACKUP_DIR} "
            f"before restarting (see `python -m cli import`)."
        )

    # Refuse a database written by a newer Mosaic before touching it — older
    # code cannot safely write to a schema it doesn't know about.
    assert_schema_not_newer(engine)
    create_db_and_tables()
    sync_schema(engine)
    set_db_schema_version(engine)
    from services.account_types import repair_account_types
    with Session(engine) as account_session:
        repaired_accounts = repair_account_types(account_session)
        if repaired_accounts:
            logger.info('Normalized %s account types and financial classifications', repaired_accounts)
    from services.rules.defaults import initialize_existing_families
    with Session(engine) as rules_session:
        initialize_existing_families(rules_session)

    from services.mutations import set_listener
    set_listener(None)
    # Development does not create startup or mutation-triggered backups.
    # Production keeps the current-format recovery facility.
    if os.getenv("ENV", "development") != "development":
        backup_mgr = BackupManager(
            db_path=DB_PATH, audit_log_path=audit_logger.log_path,
            backup_dir=BACKUP_DIR, max_backups=MAX_BACKUPS,
            backup_every_n_mutations=BACKUP_EVERY_N_MUTATIONS,
            uploads_dir=UPLOADS_DIR, mirror_dir=BACKUP_MIRROR_DIR,
        )
        backup_mgr.create_backup()
        set_listener(backup_mgr.notify_mutation)

    from routes.v1_pending_fx import start_retry_worker
    stopped, worker = start_retry_worker(engine)
    from services.schedules import start_worker
    schedules_stopped, schedules_worker = start_worker(engine)
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=1)
        schedules_stopped.set()
        schedules_worker.join(timeout=2)
        set_listener(None)


app = FastAPI(title="famLedger API", lifespan=lifespan)
app.include_router(v1_schedules.router, prefix="/api")

from services.csrf import protect_cookie_write
app.middleware("http")(protect_cookie_write)

from sqlalchemy.exc import IntegrityError

@app.exception_handler(IntegrityError)
async def integrity_conflict(request, exc):
    return JSONResponse(status_code=409, content={"detail": "数据约束冲突，请刷新后重试或检查重复记录"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from services.booking_money import PendingExchangeRate
@app.exception_handler(PendingExchangeRate)
async def unavailable_booking_rate(request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=502, content={"detail": "指定日期汇率暂不可用，请稍后重试或确认实际结算金额"})

app.include_router(auth_router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(v1_transactions.router, prefix="/api")
app.include_router(v1_pending_fx.router, prefix="/api")
app.include_router(v1_accounts.router, prefix="/api")
app.include_router(v1_categories.router, prefix="/api")
app.include_router(v1_rules.router, prefix="/api")
app.include_router(v1_debts.router, prefix="/api")
app.include_router(v1_transfers.router, prefix="/api")
app.include_router(v1_refunds.router, prefix="/api")
app.include_router(v1_oidc.router, prefix="/api")
app.include_router(v1_dashboard.router, prefix="/api")
app.include_router(v1_family.router, prefix="/api")
app.include_router(v1_tags.router, prefix="/api")
app.include_router(v1_budgets.router, prefix="/api")
app.include_router(v1_api_keys.router, prefix="/api")


@app.get("/api/health")
def health():
    """Liveness + version, for container health checks and deploy verification.

    Unauthenticated on purpose: a health check that needs a session cookie is
    useless to Docker. It leaks only the version and schema number, which the
    image tag already tells anyone who can reach this port.

    It actually touches the database, because the failure worth catching is a
    process that still holds the port while being unable to serve — a liveness
    probe that only proves "uvicorn is running" would report that as healthy.
    `restart: unless-stopped` alone cannot see it either, since it reacts to
    the process *exiting*, not to it wedging.
    """
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check could not query the database")
        db_ok = False

    payload = {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "database": "ok" if db_ok else "unavailable",
    }
    return JSONResponse(payload, status_code=200 if db_ok else 503)


@app.get("/api/config")
def get_app_config(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    """Endpoint returning display names and app mode. Scoped to current user's family or placeholders."""
    from models import User
    from sqlmodel import select
    mode = get_app_mode(session)
    count = get_user_count(session)
    try:
        user = get_current_user(request, response, session)
    except Exception:
        user = None

    if user:
        user_db = session.exec(select(User).where(User.username == user)).first()
        if user_db and user_db.family_id:
            fam_users = session.exec(
                select(User).where(User.family_id == user_db.family_id).order_by(User.created_at)
            ).all()
            a = fam_users[0].display_name if len(fam_users) > 0 else "用户A"
            b = fam_users[1].display_name if len(fam_users) > 1 else "用户B"
            return {"userA": a, "userB": b, "mode": mode, "user_count": len(fam_users)}

    return {"userA": "用户A", "userB": "用户B", "mode": mode, "user_count": 0}


@app.get("/api/settings")
def get_settings(session: Session = Depends(get_session)):
    mode = get_app_mode(session)
    return {"app_mode": mode}


class SettingsUpdate(BaseModel):
    app_mode: str


@app.put("/api/settings")
def update_settings(
    payload: SettingsUpdate,
    session: Session = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    from models import Settings, User
    from sqlmodel import select

    user_db = session.exec(select(User).where(User.username == current_user)).first()
    if not user_db or user_db.role != "admin":
        raise HTTPException(status_code=403, detail="仅系统管理员有权修改全局系统设置")

    new_mode = payload.app_mode
    if new_mode not in VALID_MODES:
        raise HTTPException(status_code=422, detail=f"app_mode must be one of: {', '.join(VALID_MODES)}")
    if new_mode in ("shared", "blended") and get_user_count(session) < 2:
        raise HTTPException(status_code=409, detail="A second user must create an account before switching to this mode.")
    old_mode = get_app_mode(session)
    row = session.get(Settings, 1)
    if row:
        row.app_mode = new_mode
    else:
        row = Settings(id=1, app_mode=new_mode)
    session.add(row)
    session.commit()
    # A mode switch changes how every subsequent entry is interpreted (who can
    # log in, which splits are valid) — audit it like any other mutation.
    if old_mode != new_mode:
        audit_logger.log("MODE_CHANGE", current_user, {"old_mode": old_mode, "new_mode": new_mode})
    return {"app_mode": new_mode}


# ── User Preferences (per-user) ──────────────────────────────────────

@app.get("/api/user-preferences")
def get_user_preferences(
    session: Session = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    from models import UserPreference
    from sqlmodel import select
    row = session.exec(select(UserPreference).where(UserPreference.username == current_user)).first()
    if row:
        return {
            "date_format": row.date_format,
            "currency": row.currency,
            "income_mode_enabled": row.income_mode_enabled,
            "auto_refund_enabled": row.auto_refund_enabled,
            "has_chosen_currency": bool(row.has_chosen_currency) if row.has_chosen_currency is not None else True,
            "language": row.language,
            "has_chosen_language": row.has_chosen_language,
        }
    return {
        "date_format": "DD/MM/YYYY",
        "currency": "CAD",
        "income_mode_enabled": False,
        "auto_refund_enabled": True,
        "has_chosen_currency": False,
        "language": "en",
        "has_chosen_language": False,
    }


class UserPreferencesUpdate(BaseModel):
    auto_refund_enabled: Optional[bool] = None
    language: Optional[str] = None
    date_format: Optional[str] = None
    currency: Optional[str] = None
    income_mode_enabled: Optional[bool] = None
    has_chosen_currency: Optional[bool] = None


@app.put("/api/user-preferences")
def update_user_preferences(
    payload: UserPreferencesUpdate,
    session: Session = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    from models import UserPreference, VALID_DATE_FORMATS, VALID_CURRENCIES
    from sqlmodel import select
    if payload.language is not None and payload.language not in ('en', 'zh'):
        raise HTTPException(status_code=422, detail='language must be en or zh')
    if payload.date_format is not None and payload.date_format not in VALID_DATE_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"date_format must be one of: {', '.join(sorted(VALID_DATE_FORMATS))}",
        )
    if payload.currency is not None and payload.currency not in VALID_CURRENCIES:
        raise HTTPException(
            status_code=422,
            detail=f"currency must be one of: {', '.join(sorted(VALID_CURRENCIES))}",
        )
    row = session.exec(select(UserPreference).where(UserPreference.username == current_user)).first()
    if not row:
        row = UserPreference(username=current_user, has_chosen_language=False)
    if payload.language is not None:
        row.language = payload.language
        row.has_chosen_language = True
    if payload.date_format is not None:
        row.date_format = payload.date_format
    if payload.currency is not None:
        row.currency = payload.currency
    if payload.has_chosen_currency is not None:
        row.has_chosen_currency = payload.has_chosen_currency
    if payload.income_mode_enabled is not None:
        row.income_mode_enabled = payload.income_mode_enabled
    if payload.auto_refund_enabled is not None:
        row.auto_refund_enabled = payload.auto_refund_enabled
    session.add(row)

    # 若用户处于单人独立家庭空间，且自主更新了币种，联动将其个人空间基准币种同步
    if payload.currency is not None:
        from models import User, Family
        user_rec = session.exec(select(User).where(User.username == current_user)).first()
        if user_rec and user_rec.family_id:
            fam = session.get(Family, user_rec.family_id)
            if fam and (getattr(fam, "is_solo", False) or fam.kind == "personal"):
                fam.currency = payload.currency
                session.add(fam)

    session.commit()
    return {
        "date_format": row.date_format,
        "currency": row.currency,
        "income_mode_enabled": row.income_mode_enabled,
        "auto_refund_enabled": row.auto_refund_enabled,
        "has_chosen_currency": getattr(row, "has_chosen_currency", True),
        "language": row.language,
        "has_chosen_language": row.has_chosen_language,
    }


def resolve_spa_path(full_path: str, dist_dir: Path = FRONTEND_DIST, dist_dir_resolved: Path = FRONTEND_DIST_RESOLVED) -> Path | None:
    """Resolve a requested SPA path and confirm it stays inside dist_dir.

    Returns the resolved Path if safe, or None if it escapes dist_dir (e.g. an
    encoded `../` trying to reach backend/.env or mosaic.db) — the caller must
    treat None as a hard 404, never a fallback to index.html. Split out as a
    standalone function so the containment check is unit-testable without
    frontend/dist needing to exist (it's a build artifact, absent in dev/test).
    """
    candidate = (dist_dir / full_path).resolve()
    if not candidate.is_relative_to(dist_dir_resolved):
        return None
    return candidate


# ── Static file serving ───────────────────────────────────────────────────────
# Only activates when frontend/dist/ exists. API routes above take priority.
# Active in BOTH deployment methods: after `npm run build` on a git clone, and in
# Docker, where the image ships the built SPA at this same path. There is no
# nginx in the image — which means nothing else is setting cache headers, so
# this module is the only place they can come from.

# Everything under /assets is content-hashed by Vite (index-<hash>.js,
# Analytics-<hash>.js, ...), so a given URL's bytes never change — a changed
# file gets a new name. Those are safe to cache forever.
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"

# index.html is the opposite case and must never be cached without
# revalidation. It keeps the same URL across every build while being the index
# of *which* hashed chunks are current. FileResponse sets only last-modified
# and etag, and a response carrying neither Cache-Control nor Expires is
# heuristically cacheable (RFC 9111 s4.2.2) — browsers commonly reuse it for
# ~10% of its age without asking. The failure that produces is confusing out of
# all proportion to its cause: after a rebuild, a browser holding the previous
# build's index.html keeps rendering the old UI from its already-cached main
# bundle (so the app looks like it simply never received the update), while the
# lazily loaded routes — Analytics, Insights, Calendar — request chunk names
# that the new build no longer has and 404. Same root cause, two symptoms that
# look unrelated.
NO_CACHE_CONTROL = "no-cache, must-revalidate"


class _ImmutableStaticFiles(StaticFiles):
    """StaticFiles that stamps the immutable Cache-Control on what it serves.

    *args/**kwargs rather than the real signature: file_response() is internal
    Starlette API and has changed shape before, and a pinned-version bump
    should not be able to break static serving here.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = IMMUTABLE_CACHE_CONTROL
        return response


def mount_spa(target_app: FastAPI, dist_dir: Path) -> None:
    """Attach the built SPA at dist_dir to target_app.

    Takes the app and directory as arguments rather than closing over the
    module globals so a test can mount a throwaway dist from tmp_path — the
    real frontend/dist is a build artifact and is absent in CI's backend job,
    which is exactly where the cache headers below would otherwise go
    unverified. Same reasoning as resolve_spa_path() being a free function.
    """
    dist_dir_resolved = dist_dir.resolve()
    target_app.mount(
        "/assets",
        _ImmutableStaticFiles(directory=str(dist_dir / "assets")),
        name="assets",
    )

    @target_app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"], include_in_schema=False)
    async def serve_spa(request: Request, full_path: str):
        # 排除 API 路由，确保未匹配的 API 请求始终返回 404 而不是 SPA HTML 或 405
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")

        if request.method not in ("GET", "HEAD"):
            raise HTTPException(status_code=405, detail="Method Not Allowed")

        candidate = resolve_spa_path(full_path, dist_dir, dist_dir_resolved)
        if candidate is None:
            raise HTTPException(status_code=404)
        if candidate.is_file():
            # Files reaching here are the un-fingerprinted ones copied from
            # frontend/public (logo.png and friends): stable URLs, mutable
            # bytes, so they must be revalidated like index.html.
            return FileResponse(str(candidate), headers={"Cache-Control": NO_CACHE_CONTROL})
        return FileResponse(
            str(dist_dir / "index.html"),
            headers={"Cache-Control": NO_CACHE_CONTROL},
        )


if FRONTEND_DIST.exists():
    mount_spa(app, FRONTEND_DIST)
