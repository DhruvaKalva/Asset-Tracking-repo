"""Alerts: raise, dedupe, resolve, and the overdue scanner the worker runs.

Every alert carries `evidence` so the UI can show the number that justifies it.
A red dot is noise; "4 days overdue, 7,040 accrued" is a decision.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.notifier import get_notifier
from app.config import settings
from app.domain.errors import NotFound
from app.domain.events import record_event
from app.models import (
    SEVERITY_ORDER,
    Alert,
    Equipment,
    EventType,
    Rental,
    RentalStatus,
    Severity,
)

NOMINAL_HOURS_PER_DAY = 8.0  # billing assumption for accrual estimates


def _dedupe_key(equipment_id: str, kind: str) -> str:
    return f"{equipment_id}:{kind}"


def find_open(db: Session, equipment_id: str, kind: str) -> Alert | None:
    return db.scalar(
        select(Alert).where(
            Alert.dedupe_key == _dedupe_key(equipment_id, kind),
            Alert.resolved_at.is_(None),
        )
    )


def raise_alert(
    db: Session,
    equipment_id: str,
    kind: str,
    severity: Severity | str,
    reason_text: str,
    evidence: dict | None = None,
    notify: bool = True,
) -> Alert:
    """Idempotent per (asset, kind). Re-raising only escalates severity."""
    sev = severity.value if isinstance(severity, Severity) else str(severity)
    existing = find_open(db, equipment_id, kind)

    if existing is not None:
        escalated = SEVERITY_ORDER.get(sev, 0) > SEVERITY_ORDER.get(existing.severity, 0)
        existing.reason_text = reason_text
        existing.evidence = evidence or {}
        if escalated:
            existing.severity = sev
            existing.acknowledged_at = None  # re-surface it
            if notify:
                _notify(existing)
        db.flush()
        return existing

    alert = Alert(
        equipment_id=equipment_id,
        kind=kind,
        severity=sev,
        reason_text=reason_text,
        evidence=evidence or {},
        dedupe_key=_dedupe_key(equipment_id, kind),
    )
    db.add(alert)
    db.flush()

    record_event(
        db,
        equipment_id,
        EventType.ALERT_RAISED,
        payload={"kind": kind, "severity": sev, "reason": reason_text, "evidence": evidence or {}},
        publish=False,
    )
    if notify:
        _notify(alert)
    return alert


def _notify(alert: Alert) -> None:
    get_notifier().send(
        {
            "alert_id": alert.alert_id,
            "equipment_id": alert.equipment_id,
            "kind": alert.kind,
            "severity": alert.severity,
            "reason_text": alert.reason_text,
            "evidence": alert.evidence,
            "raised_at": alert.raised_at,
        }
    )


def resolve_open_alerts(db: Session, equipment_id: str, kinds: list[str] | None = None) -> int:
    stmt = select(Alert).where(Alert.equipment_id == equipment_id, Alert.resolved_at.is_(None))
    if kinds:
        stmt = stmt.where(Alert.kind.in_(kinds))
    count = 0
    now = datetime.now(timezone.utc)
    for alert in db.scalars(stmt):
        alert.resolved_at = now
        count += 1
    db.flush()
    return count


def acknowledge(db: Session, alert_id: int, actor: str | None = None) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise NotFound(f"alert {alert_id} not found")
    alert.acknowledged_at = datetime.now(timezone.utc)
    record_event(
        db,
        alert.equipment_id,
        EventType.ALERT_ACKNOWLEDGED,
        payload={"alert_id": alert_id, "kind": alert.kind},
        actor=actor,
        source="manual",
    )
    db.commit()
    return alert


def list_alerts(
    db: Session,
    severity: str | None = None,
    kind: str | None = None,
    equipment_id: str | None = None,
    unresolved_only: bool = True,
    limit: int = 200,
) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.raised_at.desc()).limit(limit)
    if unresolved_only:
        stmt = stmt.where(Alert.resolved_at.is_(None))
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if kind:
        stmt = stmt.where(Alert.kind == kind)
    if equipment_id:
        stmt = stmt.where(Alert.equipment_id == equipment_id)
    return list(db.scalars(stmt))


# ---------------------------------------------------------------------------
# Worker entry point: overdue + due-soon scan
# ---------------------------------------------------------------------------
def scan_overdue(db: Session, today: date | None = None) -> dict:
    """Runs every few minutes. Escalates INFO -> WARN -> HIGH as the date slips."""
    today = today or datetime.now(timezone.utc).date()
    raised = {"due_soon": 0, "overdue": 0, "resolved": 0}

    open_rentals = db.scalars(
        select(Rental).where(
            Rental.status.in_([RentalStatus.ACTIVE.value, RentalStatus.OVERDUE.value])
        )
    )

    for rental in open_rentals:
        equipment = db.get(Equipment, rental.equipment_id)
        rate = equipment.rental_rate_per_hour if equipment else 0.0
        days_left = (rental.expected_check_in_date - today).days

        if days_left < 0:
            days_over = -days_left
            accrued = round(days_over * NOMINAL_HOURS_PER_DAY * rate, 2)
            severity = Severity.CRITICAL if days_over >= 7 else Severity.HIGH
            rental.status = RentalStatus.OVERDUE.value
            raise_alert(
                db,
                rental.equipment_id,
                "OVERDUE",
                severity,
                f"{rental.equipment_id} is {days_over} day(s) overdue at site {rental.site_id or 'UNKNOWN'}. "
                f"Extension charges accruing.",
                {
                    "days_overdue": days_over,
                    "expected_check_in_date": str(rental.expected_check_in_date),
                    "daily_rate": round(NOMINAL_HOURS_PER_DAY * rate, 2),
                    "accrued_cost": accrued,
                    "site_id": rental.site_id,
                    "rental_id": rental.rental_id,
                },
            )
            raised["overdue"] += 1

        elif days_left <= settings.overdue_reminder_days:
            severity = Severity.WARN if days_left == 0 else Severity.INFO
            when = "today" if days_left == 0 else f"in {days_left} day(s)"
            raise_alert(
                db,
                rental.equipment_id,
                "DUE_SOON",
                severity,
                f"{rental.equipment_id} is due back {when} from site {rental.site_id or 'UNKNOWN'}.",
                {
                    "days_until_due": days_left,
                    "expected_check_in_date": str(rental.expected_check_in_date),
                    "site_id": rental.site_id,
                    "rental_id": rental.rental_id,
                },
            )
            raised["due_soon"] += 1
        else:
            raised["resolved"] += resolve_open_alerts(db, rental.equipment_id, kinds=["DUE_SOON"])

    db.commit()
    return raised
