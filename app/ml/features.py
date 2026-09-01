"""Feature engineering shared by the anomaly and forecast models.

One place builds the frame so a rule and a model can never disagree about what
"idle ratio" means.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.geo import distance_from_site
from app.models import AssetCurrentState, Equipment, Rental, Site, TelemetryDaily

FEATURE_COLUMNS = [
    "engine_hours",
    "idle_hours",
    "total_hours",
    "idle_ratio",
    "hours_vs_type_mean",
    "days_since_ping",
    "has_site",
    "has_operator",
    "distance_from_site_km",
]


def build_asset_day_frame(db: Session, days: int = 60) -> pd.DataFrame:
    """One row per (equipment_id, day) with everything both models need."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days)

    rows = list(
        db.scalars(
            select(TelemetryDaily)
            .where(TelemetryDaily.day >= start)
            .order_by(TelemetryDaily.equipment_id, TelemetryDaily.day)
        )
    )
    if not rows:
        return pd.DataFrame(columns=["equipment_id", "day", "type", *FEATURE_COLUMNS])

    equipment = {e.equipment_id: e for e in db.scalars(select(Equipment))}
    states = {s.equipment_id: s for s in db.scalars(select(AssetCurrentState))}
    sites = {s.site_id: s for s in db.scalars(select(Site))}

    records = []
    for r in rows:
        eq = equipment.get(r.equipment_id)
        st = states.get(r.equipment_id)
        total = r.engine_hours + r.idle_hours

        if st and st.last_seen_at:
            seen = st.last_seen_at
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            days_since_ping = (datetime.now(timezone.utc) - seen).total_seconds() / 86400
        else:
            days_since_ping = float(days)

        site = sites.get(r.site_id) if r.site_id else None
        # Prefer the day's own fix; fall back to where the asset is right now.
        lat = r.lat if r.lat is not None else (st.lat if st else None)
        lng = r.lng if r.lng is not None else (st.lng if st else None)
        gap = distance_from_site(lat, lng, site.lat if site else None, site.lng if site else None)

        records.append(
            {
                "equipment_id": r.equipment_id,
                "day": r.day,
                "type": eq.type if eq else "UNKNOWN",
                "site_id": r.site_id,
                "engine_hours": float(r.engine_hours),
                "idle_hours": float(r.idle_hours),
                "total_hours": float(total),
                "idle_ratio": float(r.idle_hours / total) if total else 0.0,
                "days_since_ping": round(days_since_ping, 2),
                "has_site": 1 if (st and st.site_id) else 0,
                "has_operator": 1 if (st and st.operator_id) else 0,
                # None means "no fix", which is not the same as "at the site".
                "distance_from_site_km": gap if gap is not None else 0.0,
                "has_position_fix": 1 if gap is not None else 0,
                "geofence_radius_km": site.radius_km if site else None,
                "status": st.status if st else "UNKNOWN",
            }
        )

    df = pd.DataFrame.from_records(records)

    # How far this asset-day sits from the norm for its equipment type.
    type_mean = df.groupby("type")["engine_hours"].transform("mean")
    type_std = df.groupby("type")["engine_hours"].transform("std").fillna(0.0)
    df["hours_vs_type_mean"] = (df["engine_hours"] - type_mean) / type_std.replace(0, 1.0)
    df["hours_vs_type_mean"] = df["hours_vs_type_mean"].fillna(0.0)

    return df


def latest_per_asset(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sort_values("day").groupby("equipment_id", as_index=False).tail(1)


def idle_streak(df: pd.DataFrame, equipment_id: str, threshold: float) -> int:
    """Consecutive most-recent days above the idle-ratio threshold."""
    sub = df[df["equipment_id"] == equipment_id].sort_values("day", ascending=False)
    streak = 0
    for ratio in sub["idle_ratio"]:
        if ratio > threshold:
            streak += 1
        else:
            break
    return streak


def weekly_demand_frame(db: Session, weeks: int = 52) -> pd.DataFrame:
    """Rental starts bucketed into (site, type, week) counts -- the forecast input."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(weeks=weeks)

    rentals = list(db.scalars(select(Rental).where(Rental.check_out_date >= start)))
    if not rentals:
        return pd.DataFrame(columns=["site_id", "type", "week_start", "demand"])

    types = {e.equipment_id: e.type for e in db.scalars(select(Equipment))}
    records = [
        {
            "site_id": r.site_id or "UNASSIGNED",
            "type": types.get(r.equipment_id, "UNKNOWN"),
            "week_start": _week_start(r.check_out_date),
            "demand": 1,
        }
        for r in rentals
    ]
    df = pd.DataFrame.from_records(records)
    return df.groupby(["site_id", "type", "week_start"], as_index=False)["demand"].sum()


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def dense_weekly_series(df: pd.DataFrame, site_id: str, eq_type: str) -> pd.Series:
    """Zero-filled weekly series -- gaps are real zeros, not missing data."""
    sub = df[(df["site_id"] == site_id) & (df["type"] == eq_type)]
    if sub.empty:
        return pd.Series(dtype=float)
    sub = sub.set_index("week_start")["demand"].sort_index()
    full_index = pd.date_range(
        start=pd.Timestamp(sub.index.min()), end=pd.Timestamp(sub.index.max()), freq="W-MON"
    )
    if len(full_index) == 0:
        return sub.astype(float)
    sub.index = pd.to_datetime(sub.index)
    return sub.reindex(full_index, fill_value=0).astype(float)
