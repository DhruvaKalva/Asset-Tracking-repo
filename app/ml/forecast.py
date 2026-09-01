"""Demand forecasting per (site, equipment type), weekly buckets.

Model cascade with automatic fallback -- a hackathon dataset has 6 rows, a real
dealer has 3 years. The same endpoint has to answer in both cases, so the model
degrades instead of erroring, and always reports which model answered.
"""
from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml import features
from app.models import AssetCurrentState, Equipment, Forecast

warnings.filterwarnings("ignore")  # statsmodels is chatty on short series

MIN_FOR_HOLT_WINTERS = 12
MIN_FOR_SES = 6


def _fit_predict(series: pd.Series, horizon: int) -> tuple[np.ndarray, str]:
    """Returns (predictions, model_name)."""
    n = len(series)
    values = series.to_numpy(dtype=float)

    if n >= MIN_FOR_HOLT_WINTERS:
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            fit = ExponentialSmoothing(
                values, trend="add", seasonal=None, initialization_method="estimated"
            ).fit()
            return np.asarray(fit.forecast(horizon), dtype=float), "holt-winters-add-trend"
        except Exception:
            pass  # fall through to the simpler model

    if n >= MIN_FOR_SES:
        try:
            from statsmodels.tsa.holtwinters import SimpleExpSmoothing

            fit = SimpleExpSmoothing(values, initialization_method="estimated").fit()
            return np.asarray(fit.forecast(horizon), dtype=float), "simple-exp-smoothing"
        except Exception:
            pass

    # Cold start: blend a short moving average with the last observed week.
    window = values[-4:] if n >= 4 else values
    baseline = float(np.mean(window)) if len(window) else 0.0
    last = float(values[-1]) if n else 0.0
    point = 0.6 * baseline + 0.4 * last
    return np.full(horizon, point, dtype=float), "moving-average-naive"


def backtest_mape(series: pd.Series, holdout: int = 4) -> float | None:
    """Honest error number. None when there is not enough history to claim one."""
    if len(series) < MIN_FOR_SES + holdout:
        return None
    train, test = series[:-holdout], series[-holdout:]
    preds, _ = _fit_predict(train, holdout)
    actual = test.to_numpy(dtype=float)
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - preds[mask]) / actual[mask])) * 100)


def _driver_text(series: pd.Series, predicted: float, site_id: str, eq_type: str) -> str:
    if len(series) >= 8:
        recent = float(series[-4:].mean())
        prior = float(series[-8:-4].mean())
        if prior > 0:
            delta = (recent - prior) / prior * 100
            direction = "up" if delta >= 0 else "down"
            return (
                f"{eq_type} demand at {site_id} is {direction} {abs(delta):.0f}% "
                f"vs the previous month; {predicted:.1f} unit(s) expected next week."
            )
    avg = float(series.mean()) if len(series) else 0.0
    return (
        f"{eq_type} at {site_id} averages {avg:.1f} rental(s)/week; "
        f"{predicted:.1f} expected next week."
    )


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def generate(db: Session, horizon_weeks: int = 4) -> list[dict]:
    """Nightly job. Writes forecasts; the API just reads the table."""
    demand = features.weekly_demand_frame(db, weeks=52)
    out: list[dict] = []
    if demand.empty:
        return out

    generated_at = datetime.now(timezone.utc)
    next_week = _week_start(generated_at.date()) + timedelta(days=7)

    for (site_id, eq_type), _ in demand.groupby(["site_id", "type"]):
        series = features.dense_weekly_series(demand, site_id, eq_type)
        if series.empty:
            continue

        preds, model_name = _fit_predict(series, horizon_weeks)
        preds = np.clip(preds, 0, None)
        mape = backtest_mape(series)

        # Interval from residual spread; widens as the horizon extends.
        resid_std = float(series.std()) if len(series) > 1 else max(float(series.mean()), 1.0)

        for step in range(horizon_weeks):
            week_start = next_week + timedelta(days=7 * step)
            point = float(preds[step])
            spread = 1.28 * resid_std * np.sqrt(step + 1)  # ~80% interval
            record = {
                "site_id": site_id,
                "equipment_type": eq_type,
                "week_start": week_start,
                "predicted_demand": round(point, 2),
                "lower_ci": round(max(point - spread, 0.0), 2),
                "upper_ci": round(point + spread, 2),
                "model_version": f"{model_name}|n={len(series)}",
                "driver_text": _driver_text(series, point, site_id, eq_type) if step == 0 else None,
                "mape": round(mape, 1) if mape is not None else None,
            }
            _upsert(db, record, generated_at)
            out.append(record)

    db.commit()
    return out


def _upsert(db: Session, rec: dict, generated_at: datetime) -> None:
    existing = db.scalar(
        select(Forecast).where(
            Forecast.site_id == rec["site_id"],
            Forecast.equipment_type == rec["equipment_type"],
            Forecast.week_start == rec["week_start"],
        )
    )
    if existing is None:
        existing = Forecast(
            site_id=rec["site_id"],
            equipment_type=rec["equipment_type"],
            week_start=rec["week_start"],
        )
        db.add(existing)
    existing.predicted_demand = rec["predicted_demand"]
    existing.lower_ci = rec["lower_ci"]
    existing.upper_ci = rec["upper_ci"]
    existing.model_version = rec["model_version"]
    existing.driver_text = rec["driver_text"]
    existing.mape = rec["mape"]
    existing.generated_at = generated_at
    db.flush()


def read(
    db: Session,
    site_id: str | None = None,
    equipment_type: str | None = None,
    weeks: int = 4,
) -> list[Forecast]:
    stmt = select(Forecast).order_by(Forecast.week_start, Forecast.site_id)
    if site_id:
        stmt = stmt.where(Forecast.site_id == site_id)
    if equipment_type:
        stmt = stmt.where(Forecast.equipment_type == equipment_type)
    cutoff = _week_start(datetime.now(timezone.utc).date()) + timedelta(days=7 * weeks)
    stmt = stmt.where(Forecast.week_start <= cutoff)
    return list(db.scalars(stmt))


def shortages(db: Session) -> list[dict]:
    """Next week's predicted demand vs what is actually free. Pre-position advice."""
    next_week = _week_start(datetime.now(timezone.utc).date()) + timedelta(days=7)
    rows = list(db.scalars(select(Forecast).where(Forecast.week_start == next_week)))
    if not rows:
        return []

    equipment = {e.equipment_id: e for e in db.scalars(select(Equipment))}
    states = list(db.scalars(select(AssetCurrentState)))

    free_by_type: dict[str, int] = {}
    for s in states:
        if s.status == "AVAILABLE":
            eq = equipment.get(s.equipment_id)
            if eq:
                free_by_type[eq.type] = free_by_type.get(eq.type, 0) + 1

    out = []
    for f in rows:
        available = free_by_type.get(f.equipment_type, 0)
        gap = f.predicted_demand - available
        if gap > 0.5:
            out.append(
                {
                    "site_id": f.site_id,
                    "equipment_type": f.equipment_type,
                    "week_start": str(f.week_start),
                    "predicted_demand": f.predicted_demand,
                    "available_now": available,
                    "shortfall": round(gap, 1),
                    "recommendation": (
                        f"Pre-position {int(np.ceil(gap))} more {f.equipment_type.lower()}(s) "
                        f"at {f.site_id} before {f.week_start}."
                    ),
                    "confidence": f.model_version,
                }
            )
    return sorted(out, key=lambda r: r["shortfall"], reverse=True)
