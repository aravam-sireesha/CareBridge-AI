import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .fraud_detector import load_fraud_detector
from .diagnostics import health_report
from .routers import admin_dashboard, admin_hub, admin_users, admin_workflow, ai_lab, administration, anomalies, assistant, auth, career, children, dashboard, donations, donors, fraud, matching, needs, needs_alerts, needs_bulk, notifications, organizations, public, reports, resources, verification, volunteers
from .services import audit
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
    yield


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
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
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


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Log the real traceback and return a useful error response."""
    logger.exception(
        "UNHANDLED ERROR on %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Server error ({type(exc).__name__}). Open {request.base_url}health/db or run "
            "`python scripts/check_schema.py` in the backend folder to check the database, then see the backend terminal."
        },
    )


@app.get("/")
def health():
    return {"status": "running"}


@app.get("/health/db", tags=["health"])
def health_db():
    """Open http://127.0.0.1:8000/health/db to see database connectivity, schema drift,
    row counts and RAG knowledge-base status in one place."""
    return health_report(app.state)
