import asyncio
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .fraud_detector import load_fraud_detector
from .diagnostics import health_report
from .routers import admin_map, admin_forecast, need_assist, admin_alerts, locations, otp, deliveries, availability, email_verification, phone_verification, admin_llm, agent_runs, chat, admin_dashboard, admin_hub, admin_users, admin_workflow, ai_lab, administration, anomalies, assistant, auth, career, children, dashboard, donations, donors, fraud, matching, needs, needs_alerts, needs_bulk, notifications, organizations, public, reports, resources, verification, volunteers
from .routers import events as live_events
from .routers import maps as maps_router
from .routers import documents as documents_router
from .routers import payments as payments_router
from .routers import push as push_router
from .routers.administration import active_admin
from .jobs import joblog
from .services import audit, observability, redis_client
from .services import events as live
from .services.career_service import load_career_recommender
from .services.security import client_address

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for state_name, loader in (
        ("career_recommender", load_career_recommender),
        ("fraud_detector", load_fraud_detector),
    ):
        try:
            setattr(app.state, state_name, loader())
        except Exception:
            logger.exception("Failed to load %s model", state_name)
            setattr(app.state, state_name, None)
    # The embedding model takes seconds to load. Do it in the background at startup (not on the first user's question).
    # Skipped under pytest and when EMBEDDING_WARMUP=off; a failure only means the first question loads it as before.
    if os.getenv("EMBEDDING_WARMUP", "on").lower() != "off" and not os.getenv("PYTEST_CURRENT_TEST"):
        def _warm():
            try:
                from .services import embeddings
                embeddings.warm_up()
                logger.info("Embedding model warmed up")
            except Exception:
                logger.warning("Embedding warm-up skipped (the model loads on first use instead)")
        threading.Thread(target=_warm, name="embedding-warmup", daemon=True).start()
    joblog.install()   # background jobs record their status in the background_jobs table
    # Live events: with Redis, every worker listens on the shared channel so an event published by ANY process reaches the
    # browsers connected to THIS one. Without Redis, events stay in-process (correct for a single worker).
    fanout_stop, fanout_task = asyncio.Event(), None
    if redis_client.is_configured() and not os.getenv("PYTEST_CURRENT_TEST"):
        fanout_task = asyncio.create_task(live.run_redis_fanout(fanout_stop), name="event-fanout")
    try:
        yield
    finally:
        fanout_stop.set()
        if fanout_task is not None:
            fanout_task.cancel()
            try:
                await fanout_task
            except (asyncio.CancelledError, Exception):
                pass


observability.init("api")        # Sentry, only if SENTRY_DSN is set; events are scrubbed of credentials, personal data and coordinates
app = FastAPI(title="CareBridge AI", lifespan=lifespan)
_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Remember the client address for the audit trail and add defensive HTTP headers to every response."""
    token = audit.client_ip.set(client_address(request))
    try:
        response = await call_next(request)
    finally:
        audit.client_ip.reset(token)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
    if request.url.path.startswith(("/auth", "/admin")):
        response.headers["Cache-Control"] = "no-store"
    if os.getenv("FORCE_HTTPS", "").lower() == "true":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(administration.router)
app.include_router(admin_workflow.router)
app.include_router(admin_dashboard.router)
app.include_router(admin_users.router)
app.include_router(verification.router)
app.include_router(anomalies.router)
app.include_router(notifications.router)
app.include_router(reports.router)
app.include_router(public.router)
app.include_router(needs_bulk.router)
app.include_router(admin_hub.router)
app.include_router(ai_lab.router)
app.include_router(resources.router)
app.include_router(dashboard.router)
app.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
app.include_router(needs.router, prefix="/needs", tags=["needs"])
app.include_router(needs_alerts.router)
app.include_router(donors.router, prefix="/donors", tags=["donors"])
app.include_router(donations.router)
app.include_router(volunteers.router, prefix="/volunteers", tags=["volunteers"])
app.include_router(children.router, prefix="/children", tags=["children"])
app.include_router(career.router)
app.include_router(fraud.router, prefix="/fraud", tags=["fraud"])
app.include_router(matching.router)
app.include_router(assistant.router)
app.include_router(chat.router)
app.include_router(agent_runs.router)
app.include_router(admin_llm.router)
app.include_router(admin_alerts.router)
app.include_router(need_assist.router)
app.include_router(admin_forecast.router)
app.include_router(locations.router)
app.include_router(admin_map.router)
app.include_router(otp.router)
app.include_router(deliveries.router)
app.include_router(availability.router)
app.include_router(email_verification.router)
app.include_router(phone_verification.router)
app.include_router(live_events.router)
app.include_router(maps_router.router)
app.include_router(push_router.router)
app.include_router(documents_router.router)
app.include_router(payments_router.router)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Log the real traceback server-side; the client gets a generic message and a reference id, never internals."""
    request_id = uuid.uuid4().hex[:12]
    logger.exception("UNHANDLED ERROR %s on %s %s", request_id, request.method, request.url.path)
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except Exception:  # Sentry is optional; never let reporting break the error response
        pass
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on the server. Please try again, and quote this reference if it keeps happening.",
                 "request_id": request_id},
    )


@app.get("/")
def health():
    """Liveness (used by the container health check). Says nothing about dependencies."""
    return {"status": "running"}


@app.get("/health/live", tags=["health"])
def health_live():
    return {"status": "running"}


@app.get("/health/ready", tags=["health"])
def health_ready():
    """Readiness for a load balancer: can this instance serve traffic? 503 only when the database is down; "degraded" (HTTP 200) when Redis is
    configured but unreachable. Public, so it reports only status and yes/no per dependency: no versions, row counts, error text or configuration."""
    db_ok = True
    try:
        from sqlalchemy import text
        from .database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
        logger.exception("Readiness check: database unreachable")
    redis_state = redis_client.status()
    # Only the database makes an instance unfit to serve. A Redis outage DEGRADES the app (per-process rate limits, in-process events and jobs) but must
    # not make a load balancer pull every instance out of rotation at once, so it is reported as "degraded" with HTTP 200.
    status = "not_ready" if not db_ok else ("degraded" if redis_state == "unreachable" else "ready")
    return JSONResponse(status_code=200 if db_ok else 503, content={"status": status, "database": db_ok, "redis": redis_state})


@app.get("/health/db", tags=["health"])
def health_db(admin: dict = Depends(active_admin)):
    """Administrators only. Connectivity, schema drift, row counts and knowledge-base status in one place.
    (Earlier versions served this to anyone, which disclosed row counts including the children table.)"""
    return health_report(app.state)
