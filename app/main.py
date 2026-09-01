"""Smart Rental Tracking System -- API entrypoint.

Stateless by design: no session state lives in this process, so N replicas sit
behind a load balancer without coordination. The only in-process state is the
SSE subscriber set, which moves to Redis pub/sub when you scale out.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.bus import bus
from app.api import (
    admin,
    alerts,
    analytics,
    assets,
    mira,
    registry,
    rentals,
    stream,
    telemetry,
    tracking,
)
from app.config import settings
from app.db import SessionLocal, init_db
from app.domain import mira as mira_domain
from app.domain.errors import DomainError
from app.workers import scheduler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("smartrental")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bus.bind_loop(asyncio.get_running_loop())

    from app import seed

    result = seed.run(reset=False)
    log.info("seed: %s", result)

    # First pass so the dashboard has alerts and anomalies on the very first load.
    db = SessionLocal()
    try:
        from app.domain import alert_service
        from app.ml import anomaly, forecast

        alert_service.scan_overdue(db)
        anomaly.scan(db)
        forecast.generate(db)
    except Exception:
        log.exception("startup analytics pass failed (continuing)")
        db.rollback()
    finally:
        db.close()

    scheduler.start_scheduler()
    log.info("API ready")
    yield
    scheduler.stop_scheduler()


app = FastAPI(
    title="Smart Rental Tracking System",
    description=(
        "Event-sourced asset rental tracking: live dashboard, QR/RFID check-in-out, "
        "usage logging, overdue alerts, demand forecasting and anomaly detection."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_origin_regex=r"https?://localhost(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


API = "/api"
app.include_router(assets.router, prefix=API)
app.include_router(registry.router, prefix=API)
app.include_router(tracking.router, prefix=API)
app.include_router(rentals.router, prefix=API)
app.include_router(telemetry.router, prefix=API)
app.include_router(alerts.router, prefix=API)
app.include_router(analytics.router, prefix=API)
app.include_router(admin.router, prefix=API)
app.include_router(stream.router, prefix=API)
app.include_router(mira.router, prefix=API)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "database": settings.database_url.split("://", 1)[0],
        "simulator": settings.simulator_enabled,
        "sse_subscribers": bus.subscriber_count,
        "mira": mira_domain.configured(),
    }


@app.get("/")
def root():
    return {
        "service": "Smart Rental Tracking System",
        "docs": "/docs",
        "stream": f"{API}/stream/assets",
        "dashboard_entry": f"{API}/overview",
    }
