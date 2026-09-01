"""Turns telemetry into money and next actions.

Business impact is the heaviest judging weight, and "87% idle" is not an action.
"EQX1001 wasted 34,650 in idle time this month; return it early" is.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import telemetry_service
from app.ml import forecast
from app.models import AssetCurrentState, Equipment, Rental, RentalStatus

LOW_UTILIZATION_PCT = 35.0
MAINTENANCE_WARN_RATIO = 0.85


def _explain_flags(flags: dict | None) -> str:
    """Turns the projection's health flags into something a dispatcher reads."""
    flags = flags or {}
    parts = []
    if flags.get("unassigned_site"):
        parts.append("no site on record")
    if flags.get("no_operator"):
        parts.append("no operator assigned")
    if flags.get("stale_ping"):
        hours = flags.get("hours_since_ping")
        parts.append(f"no telemetry for {hours:.0f}h" if hours else "no recent telemetry")
    if flags.get("zero_engine_hours"):
        parts.append("zero engine hours logged")
    if flags.get("days_overdue"):
        parts.append(f"{flags['days_overdue']} day(s) past due")
    return ", ".join(parts) or "status could not be confirmed"


def idle_cost_report(db: Session, days: int = 30) -> list[dict]:
    rates = {e.equipment_id: e.rental_rate_per_hour for e in db.scalars(select(Equipment))}
    types = {e.equipment_id: e.type for e in db.scalars(select(Equipment))}
    rows = telemetry_service.usage_summary(db, group_by="asset")

    out = []
    for r in rows:
        eid = r["key"]
        rate = rates.get(eid, 0.0)
        out.append(
            {
                "equipment_id": eid,
                "type": types.get(eid),
                "idle_hours": r["idle_hours"],
                "engine_hours": r["engine_hours"],
                "utilization_pct": r["utilization_pct"],
                "hourly_rate": rate,
                "idle_cost": round(r["idle_hours"] * rate, 2),
                "productive_cost": round(r["engine_hours"] * rate, 2),
            }
        )
    return sorted(out, key=lambda r: r["idle_cost"], reverse=True)


def maintenance_risk(db: Session) -> list[dict]:
    """Hours-since-service against the OEM interval, plus a burn-rate ETA."""
    out = []
    usage = {r["key"]: r for r in telemetry_service.usage_summary(db, group_by="asset")}

    for eq in db.scalars(select(Equipment)):
        used = (eq.lifetime_engine_hours or 0.0) - (eq.hours_at_last_service or 0.0)
        interval = eq.service_interval_hours or 500.0
        ratio = used / interval if interval else 0.0

        recent = usage.get(eq.equipment_id, {})
        days_observed = max(recent.get("operating_days", 0), 1)
        burn_per_day = recent.get("engine_hours", 0.0) / days_observed
        remaining = max(interval - used, 0.0)
        eta_days = round(remaining / burn_per_day) if burn_per_day > 0 else None

        risk_level = "DUE" if ratio >= 1 else "HIGH" if ratio >= MAINTENANCE_WARN_RATIO else "OK"

        if ratio >= 1:
            advice = (
                f"Schedule service for {eq.equipment_id} now "
                f"({used:.0f}h against a {interval:.0f}h interval)."
            )
        elif risk_level == "HIGH" and eta_days is not None:
            advice = f"Book service for {eq.equipment_id} within {eta_days} day(s)."
        elif risk_level == "HIGH":
            # Idle or unaccounted assets have no burn rate to project from, but
            # a flagged risk still needs an action attached to it.
            advice = (
                f"{eq.equipment_id} is at {ratio * 100:.0f}% of its service interval and "
                f"is not currently logging hours -- service it before the next deployment."
            )
        else:
            advice = None

        out.append(
            {
                "equipment_id": eq.equipment_id,
                "type": eq.type,
                "hours_since_service": round(used, 1),
                "service_interval_hours": interval,
                "risk_ratio": round(ratio, 3),
                "risk_level": risk_level,
                "engine_hours_per_day": round(burn_per_day, 2),
                "estimated_days_to_service": eta_days,
                "recommendation": advice,
            }
        )
    return sorted(out, key=lambda r: r["risk_ratio"], reverse=True)


def recommendations(db: Session) -> list[dict]:
    """The one screen a dispatcher acts from. Ranked by rupees saved."""
    recs: list[dict] = []
    today = datetime.now(timezone.utc).date()

    equipment = {e.equipment_id: e for e in db.scalars(select(Equipment))}
    states = {s.equipment_id: s for s in db.scalars(select(AssetCurrentState))}
    open_rentals = {
        r.equipment_id: r
        for r in db.scalars(
            select(Rental).where(
                Rental.status.in_([RentalStatus.ACTIVE.value, RentalStatus.OVERDUE.value])
            )
        )
    }

    # 1. Under-utilised assets still on rent -> return early
    for row in idle_cost_report(db):
        eid = row["equipment_id"]
        rental = open_rentals.get(eid)
        if rental is None or row["idle_cost"] <= 0:
            continue
        if row["utilization_pct"] < LOW_UTILIZATION_PCT:
            days_left = max((rental.expected_check_in_date - today).days, 0)
            eq = equipment.get(eid)
            projected_waste = round(
                days_left * 8 * (eq.rental_rate_per_hour if eq else 0.0) * (1 - row["utilization_pct"] / 100),
                2,
            )
            recs.append(
                {
                    "kind": "RETURN_EARLY",
                    "equipment_id": eid,
                    "site_id": rental.site_id,
                    "severity": "HIGH" if row["utilization_pct"] < 20 else "WARN",
                    "estimated_saving": projected_waste,
                    "detail": (
                        f"{eid} is running at {row['utilization_pct']:.0f}% utilization with "
                        f"{row['idle_hours']:.0f} idle hours logged. Returning it "
                        f"{days_left} day(s) early avoids about {projected_waste:,.0f} in idle spend."
                    ),
                    "evidence": row,
                }
            )

    # 2. Forecast shortfalls -> pre-position
    for gap in forecast.shortages(db):
        recs.append(
            {
                "kind": "PRE_POSITION",
                "equipment_id": None,
                "site_id": gap["site_id"],
                "severity": "WARN",
                "estimated_saving": None,
                "detail": gap["recommendation"],
                "evidence": gap,
            }
        )

    # 3. Unaccounted assets -> recover
    for eid, state in states.items():
        if state.status == "UNACCOUNTED":
            eq = equipment.get(eid)
            recs.append(
                {
                    "kind": "RECOVER_ASSET",
                    "equipment_id": eid,
                    "site_id": state.site_id,
                    "severity": "CRITICAL",
                    "estimated_saving": round((eq.rental_rate_per_hour if eq else 0.0) * 8 * 7, 2),
                    "detail": (
                        f"{eid} is unaccounted for: {_explain_flags(state.health_flags)}. "
                        f"Dispatch a scan before the next billing cycle."
                    ),
                    "evidence": {"health_flags": state.health_flags, "status": state.status},
                }
            )

    # 4. Maintenance due
    for m in maintenance_risk(db):
        if m["recommendation"]:
            recs.append(
                {
                    "kind": "SCHEDULE_SERVICE",
                    "equipment_id": m["equipment_id"],
                    "site_id": None,
                    "severity": "HIGH" if m["risk_level"] == "DUE" else "WARN",
                    "estimated_saving": None,
                    "detail": m["recommendation"],
                    "evidence": m,
                }
            )

    order = {"CRITICAL": 0, "HIGH": 1, "WARN": 2, "INFO": 3}
    return sorted(
        recs,
        key=lambda r: (order.get(r["severity"], 9), -(r["estimated_saving"] or 0)),
    )


def savings_summary(db: Session) -> dict:
    recs = recommendations(db)
    idle = idle_cost_report(db)
    return {
        "total_idle_cost": round(sum(r["idle_cost"] for r in idle), 2),
        "identified_savings": round(sum(r["estimated_saving"] or 0 for r in recs), 2),
        "open_recommendations": len(recs),
        "critical_recommendations": sum(1 for r in recs if r["severity"] == "CRITICAL"),
    }
