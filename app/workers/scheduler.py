"""Background jobs.

APScheduler in-process is right for a demo and a single node. The job functions
are plain callables taking a Session -- point Celery or a cron container at the
same functions when you outgrow one box. Nothing in them assumes a web request.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.adapters.telemetry_source import get_source
from app.config import settings
from app.db import SessionLocal
from app.domain import alert_service
from app.ml import anomaly, forecast

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None

_last_run: dict[str, dict] = {}


def _run(name: str, fn) -> None:
    db = SessionLocal()
    try:
        result = fn(db)
        _last_run[name] = {"ok": True, "result": result}
    except Exception as exc:
        db.rollback()
        log.exception("job %s failed", name)
        _last_run[name] = {"ok": False, "error": str(exc)}
    finally:
        db.close()


def job_overdue_scan() -> None:
    _run("overdue_scan", alert_service.scan_overdue)


def job_anomaly_scan() -> None:
    _run("anomaly_scan", anomaly.scan)


def job_forecast() -> None:
    _run("forecast", lambda db: {"generated": len(forecast.generate(db))})


def job_simulator_tick() -> None:
    source = get_source()
    _run("simulator", source.poll)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        job_overdue_scan,
        "interval",
        minutes=settings.overdue_scan_minutes,
        id="overdue_scan",
        max_instances=1,
    )
    sched.add_job(
        job_anomaly_scan,
        "interval",
        minutes=settings.anomaly_scan_minutes,
        id="anomaly_scan",
        max_instances=1,
    )
    sched.add_job(
        job_forecast,
        "cron",
        hour=settings.forecast_hour_utc,
        id="forecast",
        max_instances=1,
    )
    if settings.simulator_enabled:
        sched.add_job(
            job_simulator_tick,
            "interval",
            seconds=settings.simulator_tick_seconds,
            id="simulator",
            max_instances=1,
            coalesce=True,
        )

    sched.start()
    _scheduler = sched
    log.info("scheduler started with jobs: %s", [j.id for j in sched.get_jobs()])
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    if _scheduler is None:
        return {"running": False, "jobs": [], "last_run": _last_run}
    return {
        "running": True,
        "jobs": [
            {"id": j.id, "next_run": str(j.next_run_time) if j.next_run_time else None}
            for j in _scheduler.get_jobs()
        ],
        "last_run": _last_run,
    }


def pause_simulator(paused: bool) -> dict:
    if _scheduler is None:
        return {"running": False}
    job = _scheduler.get_job("simulator")
    if job is None:
        return {"simulator": "not scheduled"}
    if paused:
        job.pause()
    else:
        job.resume()
    return {"simulator": "paused" if paused else "running"}
