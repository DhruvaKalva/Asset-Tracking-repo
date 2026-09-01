"""Assembles the dashboard read model. One query pass, no N+1 per asset."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import cost_service, projections, telemetry_service
from app.domain.errors import NotFound
from app.domain.events import timeline
from app.models import (
    Alert,
    AssetCurrentState,
    Equipment,
    Operator,
    Rental,
    RentalStatus,
    Site,
)


def list_assets(
    db: Session,
    status: str | None = None,
    site_id: str | None = None,
    equipment_type: str | None = None,
    search: str | None = None,
) -> list[dict]:
    equipment = {e.equipment_id: e for e in db.scalars(select(Equipment))}
    states = {s.equipment_id: s for s in db.scalars(select(AssetCurrentState))}
    sites = {s.site_id: s for s in db.scalars(select(Site))}
    operators = {o.operator_id: o for o in db.scalars(select(Operator))}

    rentals = {
        r.equipment_id: r
        for r in db.scalars(
            select(Rental).where(
                Rental.status.in_([RentalStatus.ACTIVE.value, RentalStatus.OVERDUE.value])
            )
        )
    }

    alert_counts = dict(
        db.execute(
            select(Alert.equipment_id, func.count(Alert.alert_id))
            .where(Alert.resolved_at.is_(None))
            .group_by(Alert.equipment_id)
        ).all()
    )

    today = datetime.now(timezone.utc).date()
    out = []

    for eid, eq in equipment.items():
        state = states.get(eid)
        rental = rentals.get(eid)
        # Named row_site_id, not site_id: the parameter of the same name is the
        # filter, and shadowing it here silently turned that filter into a no-op.
        row_site_id = (state.site_id if state else None) or eq.home_site_id
        site = sites.get(row_site_id) if row_site_id else None
        operator = operators.get(state.operator_id) if state and state.operator_id else None

        row = {
            "equipment_id": eid,
            "type": eq.type,
            "model": eq.model,
            "status": state.status if state else "AVAILABLE",
            "site_id": row_site_id,
            "site_name": site.name if site else None,
            "operator_id": state.operator_id if state else None,
            "operator_name": operator.name if operator else None,
            "rental_id": rental.rental_id if rental else None,
            "check_out_date": rental.check_out_date if rental else None,
            "expected_check_in_date": rental.expected_check_in_date if rental else None,
            "days_until_due": (rental.expected_check_in_date - today).days if rental else None,
            "last_seen_at": state.last_seen_at if state else None,
            "lat": state.lat if state else (site.lat if site else None),
            "lng": state.lng if state else (site.lng if site else None),
            "engine_hours_today": state.engine_hours_today if state else 0.0,
            "idle_hours_today": state.idle_hours_today if state else 0.0,
            "utilization_pct": state.utilization_pct if state else 0.0,
            "health_flags": (state.health_flags if state else {}) or {},
            "open_alerts": alert_counts.get(eid, 0),
            "rental_rate_per_hour": eq.rental_rate_per_hour,
            "mobility": eq.mobility,
            "home_site_id": eq.home_site_id,
        }

        if status and row["status"] != status.upper():
            continue
        if site_id and row_site_id != site_id:
            continue
        if equipment_type and row["type"].lower() != equipment_type.lower():
            continue
        if search:
            hay = f"{eid} {eq.type} {eq.model or ''} {row['site_name'] or ''}".lower()
            if search.lower() not in hay:
                continue
        out.append(row)

    return sorted(out, key=lambda r: (r["open_alerts"] == 0, r["equipment_id"]))


def asset_detail(db: Session, equipment_id: str) -> dict:
    eq = db.get(Equipment, equipment_id)
    if eq is None:
        raise NotFound(f"unknown equipment {equipment_id}")

    matches = list_assets(db)
    asset = next((a for a in matches if a["equipment_id"] == equipment_id), None)
    if asset is None:
        raise NotFound(f"unknown equipment {equipment_id}")

    maintenance = next(
        (m for m in cost_service.maintenance_risk(db) if m["equipment_id"] == equipment_id),
        None,
    )
    open_alerts = list(
        db.scalars(
            select(Alert)
            .where(Alert.equipment_id == equipment_id, Alert.resolved_at.is_(None))
            .order_by(Alert.raised_at.desc())
        )
    )
    return {
        "asset": asset,
        "usage": telemetry_service.asset_usage(db, equipment_id),
        "timeline": timeline(db, equipment_id, limit=50),
        "alerts": open_alerts,
        "maintenance": maintenance,
    }


def status_counts(db: Session) -> dict:
    rows = db.execute(
        select(AssetCurrentState.status, func.count(AssetCurrentState.equipment_id)).group_by(
            AssetCurrentState.status
        )
    ).all()
    return {status: count for status, count in rows}


def overview(db: Session) -> dict:
    """Everything the dashboard header needs, in one call."""
    counts = status_counts(db)
    total = db.scalar(select(func.count(Equipment.equipment_id))) or 0
    open_alerts = db.scalar(
        select(func.count(Alert.alert_id)).where(Alert.resolved_at.is_(None))
    ) or 0
    critical = db.scalar(
        select(func.count(Alert.alert_id)).where(
            Alert.resolved_at.is_(None), Alert.severity.in_(["HIGH", "CRITICAL"])
        )
    ) or 0

    return {
        "total_assets": total,
        "status_counts": counts,
        "on_rent": sum(counts.get(s, 0) for s in ("RENTED", "IN_USE", "IDLE", "OVERDUE")),
        "unaccounted": counts.get("UNACCOUNTED", 0),
        "overdue": counts.get("OVERDUE", 0),
        "open_alerts": open_alerts,
        "critical_alerts": critical,
        "fleet": telemetry_service.fleet_kpis(db, days=30),
        "savings": cost_service.savings_summary(db),
        "generated_at": datetime.now(timezone.utc),
    }


def refresh(db: Session) -> int:
    return projections.rebuild_all(db)
