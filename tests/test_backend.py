"""Behaviour tests for the core journey and the intelligence layer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.domain import alert_service, dashboard, projections, rental_service, telemetry_service
from app.domain.errors import Conflict, NotFound
from app.ml import anomaly, forecast
from app.models import AssetStatus, RentalStatus
from tests.conftest import add_rental, add_usage


# ---------------------------------------------------------------------------
# Scanning + rental lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload,expected_source",
    [("CAT-QR-EQX1009", "qr"), ("RFID-EQX1009", "rfid"), ("eqx1009", "manual")],
)
def test_scanner_resolves_every_input_method(fleet, payload, expected_source):
    equipment_id, source = rental_service.resolve_asset(fleet, payload)
    assert equipment_id == "EQX1009"
    assert source == expected_source


def test_unknown_scan_payload_is_not_found(fleet):
    with pytest.raises(NotFound):
        rental_service.resolve_asset(fleet, "CAT-QR-NOPE")


def test_check_out_then_check_in_round_trip(fleet):
    rental = rental_service.check_out(
        fleet, "CAT-QR-EQX1009", site_id="S001", operator_id="OP101"
    )
    assert rental.status == RentalStatus.ACTIVE.value

    state = projections.recompute_state(fleet, "EQX1009")
    assert state.status in {AssetStatus.RENTED.value, AssetStatus.IN_USE.value}
    assert state.site_id == "S001"

    returned = rental_service.check_in(fleet, "EQX1009", notes="clean")
    assert returned.status == RentalStatus.RETURNED.value
    assert returned.actual_check_in_date is not None
    assert projections.recompute_state(fleet, "EQX1009").status == AssetStatus.AVAILABLE.value


def test_double_check_out_without_key_conflicts(fleet):
    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001")
    with pytest.raises(Conflict):
        rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S002")


def test_replayed_scan_returns_the_same_rental(fleet):
    """The offline PWA flushes its queue twice; that must not double-book."""
    first = rental_service.check_out(
        fleet, "CAT-QR-EQX1009", site_id="S001", client_idempotency_key="scan-1"
    )
    second = rental_service.check_out(
        fleet, "CAT-QR-EQX1009", site_id="S001", client_idempotency_key="scan-1"
    )
    assert first.rental_id == second.rental_id
    assert len(rental_service.rental_history(fleet, "EQX1009")) == 1


def test_check_in_without_open_rental_conflicts(fleet):
    with pytest.raises(Conflict):
        rental_service.check_in(fleet, "EQX1009")


def test_assign_operator_clears_the_gap(fleet):
    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001")
    rental = rental_service.assign_operator(fleet, "EQX1009", "OP203")
    assert rental.operator_id == "OP203"


# ---------------------------------------------------------------------------
# Telemetry + usage
# ---------------------------------------------------------------------------
def test_telemetry_accumulates_into_the_day_bucket(fleet):
    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001", operator_id="OP101")
    telemetry_service.ingest_tick(fleet, "EQX1009", engine_hours=3.0, idle_hours=1.0)
    row = telemetry_service.ingest_tick(fleet, "EQX1009", engine_hours=2.0, idle_hours=0.0)

    assert row.engine_hours == 5.0
    assert row.idle_hours == 1.0

    state = projections.recompute_state(fleet, "EQX1009")
    assert state.utilization_pct == pytest.approx(83.3, abs=0.2)
    assert state.status == AssetStatus.IN_USE.value


def test_duplicate_tick_with_same_key_is_ignored(fleet):
    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001")
    telemetry_service.ingest_tick(fleet, "EQX1009", engine_hours=4.0, idempotency_key="tick-1")
    row = telemetry_service.ingest_tick(
        fleet, "EQX1009", engine_hours=4.0, idempotency_key="tick-1"
    )
    # The event is deduped even though the bucket write is not replayed twice.
    assert row.engine_hours == 4.0


def test_a_day_cannot_exceed_twenty_four_hours(fleet):
    """A fast or misbehaving telemetry source must not produce impossible days."""
    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001")
    for _ in range(40):
        row = telemetry_service.ingest_tick(fleet, "EQX1009", engine_hours=1.0, idle_hours=0.5)

    assert row.engine_hours + row.idle_hours == pytest.approx(24.0, abs=0.01)
    assert row.engine_hours <= 24.0


def test_usage_summary_groups_by_site(fleet):
    add_rental(fleet, "EQX1001", "S001", "OP101", days_out=5, days_until_due=5)
    add_usage(fleet, "EQX1001", "S001", days=5, engine=2.0, idle=6.0)

    by_site = telemetry_service.usage_summary(fleet, group_by="site")
    row = next(r for r in by_site if r["key"] == "S001")
    assert row["engine_hours"] == 10.0
    assert row["idle_hours"] == 30.0
    assert row["utilization_pct"] == 25.0


def test_downtime_is_measured_per_asset_day(fleet):
    """A multi-asset rollup has N x 24 hours of capacity, not 24."""
    add_rental(fleet, "EQX1001", "S001", "OP101", days_out=2, days_until_due=5)
    add_rental(fleet, "EQX1003", "S001", "OP203", days_out=2, days_until_due=5)
    add_usage(fleet, "EQX1001", "S001", days=2, engine=4.0, idle=2.0)
    add_usage(fleet, "EQX1003", "S001", days=2, engine=4.0, idle=2.0)

    site = next(r for r in telemetry_service.usage_summary(fleet, group_by="site")
                if r["key"] == "S001")

    assert site["asset_days"] == 4          # 2 assets x 2 days
    assert site["total_hours"] == 24.0
    assert site["downtime_hours"] == 72.0   # 4 x 24 - 24, not 2 x 24 - 24


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------
def test_available_when_no_open_rental():
    status, _ = projections.derive_status(None, 0, 0, None)
    assert status == AssetStatus.AVAILABLE.value


def test_overdue_beats_every_other_signal(fleet):
    rental = add_rental(fleet, "EQX1001", "S001", "OP101", days_out=20, days_until_due=-3)
    status, flags = projections.derive_status(rental, 2.0, 9.0, datetime.now(timezone.utc))
    assert status == AssetStatus.OVERDUE.value
    assert flags["days_overdue"] == 3


def test_missing_site_reads_as_unaccounted(fleet):
    rental = add_rental(fleet, "EQX1001", None, None, days_out=10, days_until_due=5)
    status, flags = projections.derive_status(rental, 0.0, 11.0, datetime.now(timezone.utc))
    assert status == AssetStatus.UNACCOUNTED.value
    assert flags["unassigned_site"] is True


def test_stale_ping_reads_as_unaccounted(fleet):
    rental = add_rental(fleet, "EQX1001", "S001", "OP101", days_out=10, days_until_due=5)
    stale = datetime.now(timezone.utc) - timedelta(days=4)
    status, flags = projections.derive_status(rental, 5.0, 1.0, stale)
    assert status == AssetStatus.UNACCOUNTED.value
    assert flags["stale_ping"] is True


def test_high_idle_ratio_reads_as_idle(fleet):
    rental = add_rental(fleet, "EQX1001", "S001", "OP101", days_out=10, days_until_due=5)
    status, flags = projections.derive_status(rental, 1.5, 10.0, datetime.now(timezone.utc))
    assert status == AssetStatus.IDLE.value
    assert flags["excessive_idle"] is True


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def test_overdue_scan_raises_priced_alert(fleet):
    add_rental(fleet, "EQX1001", "S001", "OP101", days_out=20, days_until_due=-4)
    result = alert_service.scan_overdue(fleet)

    assert result["overdue"] == 1
    alert = alert_service.find_open(fleet, "EQX1001", "OVERDUE")
    assert alert is not None
    assert alert.severity == "HIGH"
    assert alert.evidence["days_overdue"] == 4
    # 4 days x 8h x 1850/h -- the number that makes a dispatcher act
    assert alert.evidence["accrued_cost"] == pytest.approx(59200.0)


def test_due_soon_alert_is_informational(fleet):
    add_rental(fleet, "EQX1001", "S001", "OP101", days_out=10, days_until_due=2)
    alert_service.scan_overdue(fleet)
    alert = alert_service.find_open(fleet, "EQX1001", "DUE_SOON")
    assert alert is not None
    assert alert.severity == "INFO"


def test_alerts_dedupe_and_escalate(fleet):
    alert_service.raise_alert(fleet, "EQX1001", "OVERDUE", "WARN", "first", {})
    alert_service.raise_alert(fleet, "EQX1001", "OVERDUE", "CRITICAL", "worse", {})
    open_alerts = alert_service.list_alerts(fleet, equipment_id="EQX1001")

    assert len(open_alerts) == 1
    assert open_alerts[0].severity == "CRITICAL"


def test_check_in_resolves_the_overdue_alert(fleet):
    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001")
    alert_service.raise_alert(fleet, "EQX1009", "OVERDUE", "HIGH", "late", {})
    rental_service.check_in(fleet, "EQX1009")
    assert alert_service.find_open(fleet, "EQX1009", "OVERDUE") is None


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------
def test_idle_asset_is_flagged_with_a_reason(fleet):
    add_rental(fleet, "EQX1001", "S001", "OP101", days_out=15, days_until_due=4)
    add_usage(fleet, "EQX1001", "S001", days=15, engine=1.5, idle=10.0)
    add_rental(fleet, "EQX1003", "S002", "OP203", days_out=15, days_until_due=9)
    add_usage(fleet, "EQX1003", "S002", days=15, engine=7.5, idle=0.5)
    projections.rebuild_all(fleet)

    result = anomaly.scan(fleet)
    flagged = {f["equipment_id"] for f in result["findings"]}

    assert "EQX1001" in flagged
    assert "EQX1003" not in flagged
    reason = next(f for f in result["findings"] if f["equipment_id"] == "EQX1001")["reasons"][0]
    assert "idle" in reason.lower()


def test_ghost_asset_is_critical(fleet):
    add_rental(fleet, "EQX1001", None, None, days_out=20, days_until_due=6)
    add_usage(fleet, "EQX1001", None, days=20, engine=0.0, idle=11.0)
    projections.rebuild_all(fleet)

    anomaly.scan(fleet)
    alert = alert_service.find_open(fleet, "EQX1001", "UNASSIGNED_SITE")
    assert alert is not None
    assert alert.severity == "CRITICAL"


def test_healthy_asset_produces_no_alerts(fleet):
    add_rental(fleet, "EQX1003", "S002", "OP203", days_out=15, days_until_due=9)
    add_usage(fleet, "EQX1003", "S002", days=15, engine=7.5, idle=0.5)
    projections.rebuild_all(fleet)

    anomaly.scan(fleet)
    assert alert_service.list_alerts(fleet, equipment_id="EQX1003") == []


def test_ml_scoring_is_stable_on_tiny_datasets():
    tiny = pd.DataFrame(
        [{c: 0.0 for c in ["engine_hours", "idle_hours", "total_hours", "idle_ratio",
                            "hours_vs_type_mean", "days_since_ping", "has_site", "has_operator"]}]
    )
    scores = anomaly.score_ml(tiny)
    assert len(scores) == 1
    assert scores.iloc[0] == 0.0


def test_maintenance_risk_always_carries_an_action(fleet):
    """A flagged risk with no advice attached is a dead end in the UI."""
    from app.domain import cost_service
    from app.models import Equipment

    idle_asset = fleet.get(Equipment, "EQX1001")
    idle_asset.lifetime_engine_hours = 495.0  # 99% of a 500h interval
    idle_asset.hours_at_last_service = 0.0
    fleet.commit()

    row = next(
        m for m in cost_service.maintenance_risk(fleet) if m["equipment_id"] == "EQX1001"
    )
    assert row["risk_level"] == "HIGH"
    assert row["estimated_days_to_service"] is None  # no telemetry, no burn rate
    assert row["recommendation"]


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------
def test_forecast_falls_back_on_short_history():
    series = pd.Series([1.0, 2.0, 1.0])
    preds, model = forecast._fit_predict(series, horizon=4)
    assert len(preds) == 4
    assert model == "moving-average-naive"
    assert all(p >= 0 for p in preds)


def test_forecast_uses_holt_winters_when_history_allows():
    series = pd.Series([float(i % 4 + 1) for i in range(24)])
    _, model = forecast._fit_predict(series, horizon=4)
    assert model == "holt-winters-add-trend"


def test_backtest_returns_none_without_enough_history():
    assert forecast.backtest_mape(pd.Series([1.0, 2.0])) is None


def test_generate_writes_forecast_rows(fleet):
    for week in range(16, 0, -1):
        add_rental(fleet, "EQX1009", "S001", "OP101", days_out=week * 7, days_until_due=-1)
    rows = forecast.generate(fleet, horizon_weeks=2)

    assert rows
    assert all(r["lower_ci"] <= r["predicted_demand"] <= r["upper_ci"] for r in rows)
    assert rows[0]["driver_text"]


# ---------------------------------------------------------------------------
# Projections are rebuildable -- the property the architecture rests on
# ---------------------------------------------------------------------------
def test_projections_rebuild_to_the_same_answer(fleet):
    add_rental(fleet, "EQX1001", "S001", "OP101", days_out=15, days_until_due=4)
    add_usage(fleet, "EQX1001", "S001", days=15, engine=1.5, idle=10.0)
    projections.rebuild_all(fleet)
    before = dashboard.list_assets(fleet)

    fleet.query(type(projections.get_or_create_state(fleet, "EQX1001"))).delete()
    fleet.commit()

    projections.rebuild_all(fleet)
    after = dashboard.list_assets(fleet)

    assert [a["status"] for a in before] == [a["status"] for a in after]


# ---------------------------------------------------------------------------
# Fleet registry (onboarding)
# ---------------------------------------------------------------------------
def test_new_asset_is_scannable_the_moment_it_is_created(fleet):
    from app.domain import registry

    eq = registry.create_equipment(
        fleet, type="Loader", model="CAT 950M", rental_rate_per_hour=1250.0
    )
    assert eq.equipment_id == "EQX1010"          # continues the EQX series
    assert eq.qr_payload == "CAT-QR-EQX1010"     # tags minted automatically
    assert eq.rfid_tag

    # scannable immediately, by every input method
    assert rental_service.resolve_asset(fleet, eq.qr_payload)[0] == "EQX1010"
    assert rental_service.resolve_asset(fleet, eq.rfid_tag)[0] == "EQX1010"

    # and on the dashboard as AVAILABLE without waiting for a rebuild
    row = next(a for a in dashboard.list_assets(fleet) if a["equipment_id"] == "EQX1010")
    assert row["status"] == AssetStatus.AVAILABLE.value


def test_used_intake_is_not_instantly_service_overdue(fleet):
    """A machine bought at 4,800 hours has not missed nine services."""
    from app.domain import cost_service, registry

    registry.create_equipment(
        fleet, type="Crane", equipment_id="EQX2001", lifetime_engine_hours=4800.0
    )
    risk = next(
        m for m in cost_service.maintenance_risk(fleet) if m["equipment_id"] == "EQX2001"
    )
    assert risk["risk_ratio"] == 0.0
    assert risk["risk_level"] == "OK"


def test_duplicate_equipment_id_conflicts(fleet):
    from app.domain import registry

    with pytest.raises(Conflict):
        registry.create_equipment(fleet, type="Excavator", equipment_id="EQX1001")


def test_service_log_resets_the_maintenance_clock(fleet):
    from app.domain import cost_service, registry

    eq = fleet.get(type(registry.get_equipment(fleet, "EQX1001")), "EQX1001")
    eq.lifetime_engine_hours = 495.0
    eq.hours_at_last_service = 0.0
    fleet.commit()

    registry.log_service(fleet, "EQX1001", notes="filters + hydraulics")
    risk = next(
        m for m in cost_service.maintenance_risk(fleet) if m["equipment_id"] == "EQX1001"
    )
    assert risk["risk_ratio"] == 0.0


def test_asset_on_rent_cannot_be_retired(fleet):
    from app.domain import registry

    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001")
    with pytest.raises(Conflict):
        registry.retire_equipment(fleet, "EQX1009")


def test_site_needs_both_coordinates_or_neither(fleet):
    from app.domain import registry

    with pytest.raises(Conflict):
        registry.create_site(fleet, site_id="S900", name="Half a fix", lat=13.0)


# ---------------------------------------------------------------------------
# Live tracking + geofence
# ---------------------------------------------------------------------------
def test_trail_is_replayed_from_the_event_log(fleet):
    """No positions table exists -- the history comes out of asset_events."""
    from app.domain import telemetry_service, tracking

    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001")
    telemetry_service.record_location(fleet, "EQX1009", 13.00, 80.00)
    telemetry_service.record_location(fleet, "EQX1009", 13.01, 80.00)
    telemetry_service.record_location(fleet, "EQX1009", 13.02, 80.00)

    trail = tracking.track(fleet, "EQX1009", hours=24)
    assert trail["point_count"] >= 3
    assert trail["points"] == sorted(trail["points"], key=lambda p: p["at"])  # oldest first
    assert trail["distance_km"] == pytest.approx(2.22, abs=0.1)  # ~0.02 deg of latitude


def test_geofence_breach_is_detected_and_priced_by_distance(fleet):
    from app.domain import telemetry_service, tracking

    rental_service.check_out(fleet, "CAT-QR-EQX1009", site_id="S001")  # site at 13.0, 80.0
    telemetry_service.record_location(fleet, "EQX1009", 13.0, 80.0)
    assert tracking.geofence_breaches(fleet) == []  # sitting on the site

    telemetry_service.record_location(fleet, "EQX1009", 13.2, 80.05)  # ~22 km away
    breaches = tracking.geofence_breaches(fleet)
    assert len(breaches) == 1
    assert breaches[0]["equipment_id"] == "EQX1009"
    assert breaches[0]["distance_km"] > 5.0
    assert breaches[0]["overshoot_km"] > 0


def test_geofence_rule_raises_a_critical_alert(fleet):
    from app.domain import telemetry_service

    add_rental(fleet, "EQX1001", "S001", "OP101", days_out=10, days_until_due=5)
    add_usage(fleet, "EQX1001", "S001", days=10, engine=6.0, idle=1.0)
    telemetry_service.record_location(fleet, "EQX1001", 13.3, 80.1)  # far outside 5 km
    projections.rebuild_all(fleet)

    anomaly.scan(fleet)
    alert = alert_service.find_open(fleet, "EQX1001", "GEOFENCE_BREACH")
    assert alert is not None
    assert alert.severity == "CRITICAL"
    assert alert.evidence["overshoot_km"] > 0
    assert "no transfer was recorded" in alert.reason_text.lower()


def test_asset_without_a_position_fix_is_not_a_breach(fleet):
    """Missing coordinates mean unknown, not 'at the site' and not 'off site'."""
    from app.domain import tracking

    add_rental(fleet, "EQX1001", "S001", "OP101", days_out=5, days_until_due=5)
    add_usage(fleet, "EQX1001", "S001", days=5, engine=6.0, idle=1.0)
    projections.rebuild_all(fleet)

    assert tracking.geofence_breaches(fleet) == []


# ---------------------------------------------------------------------------
# Fixed vs movable plant
# ---------------------------------------------------------------------------
def test_fixed_asset_must_be_installed_at_a_site(fleet):
    """A fixed asset with no site has no location and could never be found."""
    from app.domain import registry

    with pytest.raises(Conflict):
        registry.create_equipment(fleet, type="Tower Crane", mobility="FIXED")


def test_fixed_asset_is_located_at_its_site_without_a_rental(fleet):
    """Installed plant is never checked out, so it has no rental to read a site
    from -- it must still land on the map at the site it is bolted to."""
    from app.domain import registry

    eq = registry.create_equipment(
        fleet, type="Tower Crane", mobility="FIXED", home_site_id="S001"
    )
    assert eq.mobility == "FIXED"

    row = next(a for a in dashboard.list_assets(fleet) if a["equipment_id"] == eq.equipment_id)
    assert row["site_id"] == "S001"
    assert (row["lat"], row["lng"]) == (13.0, 80.0)
    # ...and specifically NOT unaccounted-for, which is what a site-less asset reads as
    assert row["status"] != AssetStatus.UNACCOUNTED.value
    assert row["health_flags"].get("unassigned_site") is not True


def test_movable_is_the_default_so_existing_assets_are_unaffected(fleet):
    from app.domain import registry

    eq = registry.create_equipment(fleet, type="Loader")
    assert eq.mobility == "MOVABLE"
    assert eq.home_site_id is None
    # An unrented movable asset is available in the yard, with no site.
    row = next(a for a in dashboard.list_assets(fleet) if a["equipment_id"] == eq.equipment_id)
    assert row["status"] == AssetStatus.AVAILABLE.value
    assert row["site_id"] is None


def test_fixed_asset_goes_unaccounted_when_it_stops_reporting(fleet, today):
    """The one failure mode installed plant does have: it went quiet."""
    from app.domain import registry

    eq = registry.create_equipment(
        fleet, type="Generator", mobility="FIXED", home_site_id="S002"
    )
    state = projections.get_or_create_state(fleet, eq.equipment_id)
    state.last_seen_at = datetime.now(timezone.utc) - timedelta(days=30)
    fleet.flush()

    refreshed = projections.recompute_state(fleet, eq.equipment_id, publish=False)
    assert refreshed.status == AssetStatus.UNACCOUNTED.value
    assert refreshed.health_flags["stale_ping"] is True
    # It is still pinned to its site -- "unaccounted" here means silent, not lost.
    assert refreshed.site_id == "S002"
