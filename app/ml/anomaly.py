"""Anomaly detection: deterministic rules fused with an unsupervised model.

Rules fire first and always explain themselves -- that is what an operator can
act on. IsolationForest catches the combinations nobody wrote a rule for. Final
severity is the max of the two, and every finding ships a reason string.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import alert_service
from app.ml import features
from app.models import SEVERITY_ORDER, AnomalyScore, Severity

MODEL_VERSION = "iforest-v1"
MIN_ROWS_FOR_ML = 12


# ---------------------------------------------------------------------------
# Tier 1: rules
# ---------------------------------------------------------------------------
def _rule_excessive_idle(row: pd.Series, ctx: dict) -> dict | None:
    streak = ctx.get("idle_streak", 0)
    if row["idle_ratio"] > settings.idle_ratio_threshold and streak >= settings.idle_streak_days:
        return {
            "kind": "EXCESSIVE_IDLE",
            "severity": Severity.HIGH.value,
            "reason": (
                f"{row['equipment_id']} idled {row['idle_hours']:.1f}h against "
                f"{row['engine_hours']:.1f}h of engine time "
                f"({row['idle_ratio'] * 100:.0f}% idle) for {streak} straight days."
            ),
            "evidence": {
                "idle_ratio": round(float(row["idle_ratio"]), 3),
                "idle_hours": float(row["idle_hours"]),
                "engine_hours": float(row["engine_hours"]),
                "streak_days": streak,
                "threshold": settings.idle_ratio_threshold,
            },
        }
    return None


def _rule_zero_engine(row: pd.Series, ctx: dict) -> dict | None:
    if row["engine_hours"] <= 0 and row["idle_hours"] > 0 and ctx.get("is_rented"):
        return {
            "kind": "ZERO_ENGINE_HOURS",
            "severity": Severity.HIGH.value,
            "reason": (
                f"{row['equipment_id']} is checked out and burning idle time "
                f"({row['idle_hours']:.1f}h) with zero engine hours -- rented but never worked."
            ),
            "evidence": {
                "engine_hours": 0.0,
                "idle_hours": float(row["idle_hours"]),
                "day": str(row["day"]),
            },
        }
    return None


def _rule_unassigned_site(row: pd.Series, ctx: dict) -> dict | None:
    if ctx.get("is_rented") and not row["has_site"]:
        return {
            "kind": "UNASSIGNED_SITE",
            "severity": Severity.CRITICAL.value,
            "reason": (
                f"{row['equipment_id']} is checked out with no site assigned. "
                f"Nobody can say where this asset is."
            ),
            "evidence": {"site_id": None, "status": ctx.get("status")},
        }
    return None


def _rule_no_operator(row: pd.Series, ctx: dict) -> dict | None:
    if ctx.get("is_rented") and not row["has_operator"] and row["engine_hours"] > 0:
        return {
            "kind": "NO_OPERATOR",
            "severity": Severity.WARN.value,
            "reason": (
                f"{row['equipment_id']} logged {row['engine_hours']:.1f} engine hours "
                f"with no operator on record."
            ),
            "evidence": {"engine_hours": float(row["engine_hours"])},
        }
    return None


def _rule_stale_ping(row: pd.Series, ctx: dict) -> dict | None:
    limit_days = settings.stale_ping_hours / 24
    if ctx.get("is_rented") and row["days_since_ping"] > limit_days:
        return {
            "kind": "STALE_PING",
            "severity": Severity.HIGH.value,
            "reason": (
                f"{row['equipment_id']} has not reported in "
                f"{row['days_since_ping']:.1f} days while on rent."
            ),
            "evidence": {
                "days_since_ping": float(row["days_since_ping"]),
                "limit_hours": settings.stale_ping_hours,
            },
        }
    return None


def _rule_geofence(row: pd.Series, ctx: dict) -> dict | None:
    """An asset outside its assigned site's radius is either stolen, borrowed by
    another crew, or transferred without paperwork. All three cost money."""
    if not ctx.get("is_rented") or not row.get("has_position_fix"):
        return None

    radius = row.get("geofence_radius_km")
    distance = row.get("distance_from_site_km")
    if radius is None or distance is None or distance <= radius:
        return None

    overshoot = distance - radius
    severity = Severity.CRITICAL.value if overshoot > radius else Severity.HIGH.value
    return {
        "kind": "GEOFENCE_BREACH",
        "severity": severity,
        "reason": (
            f"{row['equipment_id']} is {distance:.1f} km from site {row['site_id']}, "
            f"outside its {radius:.0f} km boundary. No transfer was recorded."
        ),
        "evidence": {
            "distance_km": round(float(distance), 2),
            "radius_km": float(radius),
            "overshoot_km": round(float(overshoot), 2),
            "site_id": row["site_id"],
        },
    }


MIN_TYPE_ROWS_FOR_ZSCORE = 15


def _rule_usage_spike(row: pd.Series, ctx: dict) -> dict | None:
    # A z-score over five rows means nothing; require a real sample first.
    if ctx.get("type_rows", 0) < MIN_TYPE_ROWS_FOR_ZSCORE:
        return None
    z = row.get("hours_vs_type_mean", 0.0)
    if abs(z) >= 3.0:
        direction = "above" if z > 0 else "below"
        return {
            "kind": "USAGE_OUTLIER",
            "severity": Severity.WARN.value,
            "reason": (
                f"{row['equipment_id']} ran {row['engine_hours']:.1f}h, "
                f"{abs(z):.1f} standard deviations {direction} the {row['type']} norm."
            ),
            "evidence": {"z_score": round(float(z), 2), "engine_hours": float(row["engine_hours"])},
        }
    return None


RULES = [
    _rule_unassigned_site,
    _rule_geofence,
    _rule_zero_engine,
    _rule_excessive_idle,
    _rule_stale_ping,
    _rule_no_operator,
    _rule_usage_spike,
]


def run_rules(row: pd.Series, ctx: dict) -> list[dict]:
    findings = []
    for rule in RULES:
        try:
            hit = rule(row, ctx)
        except Exception:  # a broken rule must not sink the scan
            hit = None
        if hit:
            findings.append(hit)
    return findings


# ---------------------------------------------------------------------------
# Tier 2: IsolationForest
# ---------------------------------------------------------------------------
def score_ml(df: pd.DataFrame) -> pd.Series:
    """Absolute outlier score per row, on the Isolation Forest 0..1 scale.

    Deliberately NOT min-max normalised: normalising forces the worst row in any
    batch to 1.0, so a perfectly healthy fleet would always produce a top
    "anomaly". `contamination="auto"` fixes the decision boundary at 0.5, which
    means a uniform fleet scores flat and nothing gets flagged.
    """
    if df.empty or len(df) < MIN_ROWS_FOR_ML:
        return pd.Series(np.zeros(len(df)), index=df.index)

    X = df[features.FEATURE_COLUMNS].fillna(0.0).to_numpy(dtype=float)
    X = StandardScaler().fit_transform(X)

    model = IsolationForest(
        n_estimators=200, contamination="auto", random_state=42, n_jobs=-1
    ).fit(X)

    # score_samples is the negative of the paper's s(x); s(x) > 0.5 == outlier.
    scores = -model.score_samples(X)
    return pd.Series(scores, index=df.index)


# Small fleets sit right on the 0.5 boundary, so require a margin before
# calling something an outlier on the model's word alone.
ML_FLAG_THRESHOLD = 0.62
ML_HIGH_THRESHOLD = 0.72


def _ml_severity(score: float) -> str:
    if score >= ML_HIGH_THRESHOLD:
        return Severity.HIGH.value
    if score >= ML_FLAG_THRESHOLD:
        return Severity.WARN.value
    return Severity.INFO.value


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------
def scan(db: Session, raise_alerts: bool = True) -> dict:
    df = features.build_asset_day_frame(db, days=60)
    if df.empty:
        return {"scanned": 0, "anomalies": 0, "findings": []}

    df = df.reset_index(drop=True)
    df["ml_score"] = score_ml(df)

    latest = features.latest_per_asset(df)
    today = datetime.now(timezone.utc).date()
    rented_statuses = {"RENTED", "IN_USE", "IDLE", "OVERDUE", "UNACCOUNTED"}

    results = []
    anomaly_count = 0

    for _, row in latest.iterrows():
        ctx = {
            "is_rented": row["status"] in rented_statuses,
            "status": row["status"],
            "idle_streak": features.idle_streak(
                df, row["equipment_id"], settings.idle_ratio_threshold
            ),
            "type_rows": int((df["type"] == row["type"]).sum()),
        }
        findings = run_rules(row, ctx)

        rule_sev = Severity.INFO.value
        if findings:
            rule_sev = max(findings, key=lambda f: SEVERITY_ORDER[f["severity"]])["severity"]

        ml_score = float(row["ml_score"])
        ml_sev = _ml_severity(ml_score)
        ml_flagged = ml_score >= ML_FLAG_THRESHOLD

        final_sev = max(
            [rule_sev, ml_sev if ml_flagged else Severity.INFO.value],
            key=lambda s: SEVERITY_ORDER[s],
        )
        is_anomaly = bool(findings) or ml_flagged

        reasons = {
            "rules": findings,
            "ml": {
                "score": round(ml_score, 3),
                "flagged": ml_flagged,
                "model": MODEL_VERSION,
                "explanation": (
                    "Usage pattern is unlike this asset's peers across engine hours, "
                    "idle ratio, assignment and reporting freshness."
                )
                if ml_flagged
                else "Within normal range for the fleet.",
            },
        }

        _upsert_score(db, row["equipment_id"], today, rule_sev, ml_score, final_sev, reasons, is_anomaly)

        if is_anomaly:
            anomaly_count += 1
            if raise_alerts:
                _raise_for_findings(db, row, findings, ml_flagged, ml_score, ml_sev)
            results.append(
                {
                    "equipment_id": row["equipment_id"],
                    "severity": final_sev,
                    "ml_score": round(ml_score, 3),
                    "reasons": [f["reason"] for f in findings]
                    or [reasons["ml"]["explanation"]],
                }
            )
        else:
            # asset recovered -- clear its rule-driven alerts
            alert_service.resolve_open_alerts(
                db,
                row["equipment_id"],
                kinds=[
                    "EXCESSIVE_IDLE",
                    "ZERO_ENGINE_HOURS",
                    "USAGE_OUTLIER",
                    "ML_OUTLIER",
                    "GEOFENCE_BREACH",
                ],
            )

    db.commit()
    return {"scanned": int(len(latest)), "anomalies": anomaly_count, "findings": results}


def _raise_for_findings(
    db: Session,
    row: pd.Series,
    findings: list[dict],
    ml_flagged: bool,
    ml_score: float,
    ml_sev: str,
) -> None:
    for f in findings:
        alert_service.raise_alert(
            db,
            row["equipment_id"],
            f["kind"],
            f["severity"],
            f["reason"],
            {**f["evidence"], "detector": "rule"},
        )
    if ml_flagged and not findings:
        alert_service.raise_alert(
            db,
            row["equipment_id"],
            "ML_OUTLIER",
            ml_sev,
            f"{row['equipment_id']} does not match normal {row['type']} usage patterns "
            f"(outlier score {ml_score:.2f}).",
            {
                "detector": MODEL_VERSION,
                "score": round(ml_score, 3),
                "engine_hours": float(row["engine_hours"]),
                "idle_hours": float(row["idle_hours"]),
            },
        )


def _upsert_score(
    db: Session,
    equipment_id: str,
    day,
    rule_sev: str,
    ml_score: float,
    final_sev: str,
    reasons: dict,
    is_anomaly: bool,
) -> None:
    existing = db.scalar(
        select(AnomalyScore).where(
            AnomalyScore.equipment_id == equipment_id, AnomalyScore.day == day
        )
    )
    if existing is None:
        existing = AnomalyScore(equipment_id=equipment_id, day=day)
        db.add(existing)
    existing.rule_severity = rule_sev
    existing.ml_score = ml_score
    existing.final_severity = final_sev
    existing.reasons = reasons
    existing.is_anomaly = is_anomaly
    existing.detected_at = datetime.now(timezone.utc)
    db.flush()


def list_anomalies(db: Session, limit: int = 100, only_anomalies: bool = True) -> list[AnomalyScore]:
    stmt = select(AnomalyScore).order_by(AnomalyScore.detected_at.desc()).limit(limit)
    if only_anomalies:
        stmt = stmt.where(AnomalyScore.is_anomaly.is_(True))
    return list(db.scalars(stmt))
