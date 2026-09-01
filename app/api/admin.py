"""Demo controls. In production these sit behind an admin role."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import seed
from app.db import get_db
from app.domain import dashboard
from app.workers import scheduler

router = APIRouter(tags=["admin"], prefix="/admin")


@router.post("/seed")
def reseed(reset: bool = True):
    """Rebuild the demo dataset. Safe to hit between runs."""
    return seed.run(reset=reset)


@router.post("/rebuild-projections")
def rebuild(db: Session = Depends(get_db)):
    """Proves the event log is authoritative: drop the read model, replay, done."""
    return {"assets_rebuilt": dashboard.refresh(db)}


@router.get("/jobs")
def jobs():
    return scheduler.status()


@router.post("/simulator/{action}")
def simulator(action: str):
    """action: pause | resume | tick"""
    if action == "tick":
        scheduler.job_simulator_tick()
        return {"ticked": True, **scheduler.status()["last_run"].get("simulator", {})}
    return scheduler.pause_simulator(action == "pause")


@router.post("/jobs/{job}/run")
def run_job(job: str):
    mapping = {
        "overdue": scheduler.job_overdue_scan,
        "anomaly": scheduler.job_anomaly_scan,
        "forecast": scheduler.job_forecast,
    }
    fn = mapping.get(job)
    if fn is None:
        return {"error": f"unknown job {job}", "available": list(mapping)}
    fn()
    return scheduler.status()["last_run"]
