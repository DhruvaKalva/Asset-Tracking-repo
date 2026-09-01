"""Mira, the dashboard assistant.

The model call itself is not tested here -- that would be testing Google. What
is tested is everything we own: the grounding snapshot, the tool surface the
model is allowed to reach, and the refusal to run at all without a key.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.domain import mira, projections
from app.domain.events import record_event
from app.domain.errors import Conflict, NotFound
from app.models import EventType, RentalStatus
from tests.conftest import add_rental, add_usage


@pytest.fixture()
def loaded(fleet):
    """A fleet with one busy asset, one idler, and an overdue rental."""
    db = fleet
    add_rental(db, "EQX1001", "S001", "OP101", days_out=20, days_until_due=-4,
               status=RentalStatus.OVERDUE.value)
    add_rental(db, "EQX1003", "S002", "OP203", days_out=5, days_until_due=9)
    add_usage(db, "EQX1001", "S001", days=14, engine=1.0, idle=7.0)   # heavy idler
    add_usage(db, "EQX1003", "S002", days=14, engine=8.0, idle=1.0)   # healthy
    # An event on the timeline, so asset_detail's event path is exercised.
    record_event(db, "EQX1001", EventType.CHECK_OUT, payload={"site_id": "S001"},
                 source="manual", publish=False)
    db.commit()
    # Mira reads the projections, not the raw tables, so build them.
    projections.rebuild_all(db)
    return db


# ---------------------------------------------------------------------------
# Configuration gate
# ---------------------------------------------------------------------------
def test_chat_refuses_without_a_key(loaded, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(Conflict) as exc:
        mira.chat(loaded, [{"role": "user", "content": "how is the fleet"}])
    assert "not configured" in str(exc.value)


def test_health_reports_the_tool_surface(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert mira.health()["configured"] is False

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    health = mira.health()
    assert health["configured"] is True
    assert set(health["tools"]) == set(mira.TOOL_IMPLS)


def test_chat_rejects_an_empty_transcript(loaded, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with pytest.raises(Conflict):
        mira.chat(loaded, [])
    # Whitespace-only content is empty too, and must not reach the model.
    with pytest.raises(Conflict):
        mira.chat(loaded, [{"role": "user", "content": "   "}])


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------
def test_snapshot_carries_the_live_numbers(loaded):
    text = mira.snapshot(loaded)
    assert "LIVE FLEET SNAPSHOT" in text
    assert "3 assets" in text          # the fixture fleet
    assert "Site One" in text          # sites are named, so Mira can map ids
    assert "Excavator" in text         # utilisation is broken out by type


def test_snapshot_stays_small(loaded):
    """It rides along with every turn, so a regression here costs real money."""
    assert len(mira.snapshot(loaded)) < 6000


def test_history_is_trimmed_and_roles_are_mapped():
    history = [{"role": "user", "content": f"q{i}"} for i in range(30)]
    contents = mira._to_contents(history)
    assert len(contents) == mira.MAX_HISTORY_TURNS
    assert contents[-1]["parts"][0]["text"] == "q29"

    mapped = mira._to_contents(
        [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    )
    assert [c["role"] for c in mapped] == ["user", "model"]


# ---------------------------------------------------------------------------
# The tool surface -- the only reach Mira has
# ---------------------------------------------------------------------------
def test_every_declared_tool_is_implemented():
    """A declaration without an implementation is a tool call that always fails."""
    declared = {t["name"] for t in mira.TOOL_DECLARATIONS}
    assert declared == set(mira.TOOL_IMPLS)


def test_declarations_are_well_formed():
    for decl in mira.TOOL_DECLARATIONS:
        assert decl["description"], f"{decl['name']} needs a description"
        params = decl["parameters"]
        assert params["type"] == "OBJECT"
        for name in params.get("required", []):
            assert name in params["properties"], f"{decl['name']}: required {name} not declared"


def test_find_assets_filters(loaded):
    everything = mira.run_tool(loaded, "find_assets", {})
    assert everything["matched"] == 3

    excavators = mira.run_tool(loaded, "find_assets", {"type": "Excavator"})
    assert {a["equipment_id"] for a in excavators["assets"]} == {"EQX1001", "EQX1009"}

    at_site = mira.run_tool(loaded, "find_assets", {"site_id": "S002"})
    assert [a["equipment_id"] for a in at_site["assets"]] == ["EQX1003"]


def test_find_assets_caps_the_row_count(loaded):
    """A model that asks for 5000 rows must not get 5000 rows."""
    result = mira.run_tool(loaded, "find_assets", {"limit": 5000})
    assert result["returned"] <= 60


def test_asset_detail_is_complete_and_trimmed(loaded):
    detail = mira.run_tool(loaded, "asset_detail", {"equipment_id": "eqx1001"})
    assert "error" not in detail
    assert detail["asset"]["equipment_id"] == "EQX1001"
    # 90 rows of dailies would dominate the context for no benefit.
    assert "daily" not in detail["usage"]
    # "What is it costing me" must be answerable without a second call.
    assert detail["cost"]["idle_cost"] > 0
    # Events are ORM rows, not dicts -- this is the shape that broke once.
    assert detail["recent_events"] and set(detail["recent_events"][0]) == {"event", "at"}


def test_tool_failures_come_back_as_data(loaded):
    """The model has to be able to read the error and correct itself."""
    missing = mira.run_tool(loaded, "asset_detail", {"equipment_id": "NOPE"})
    assert "error" in missing and "NotFound" in missing["error"]

    unknown = mira.run_tool(loaded, "no_such_tool", {})
    assert unknown["error"] == "unknown tool no_such_tool"

    # A bad argument name is a model mistake, not a server crash.
    bad_args = mira.run_tool(loaded, "find_assets", {"nonsense": 1})
    assert "error" in bad_args


def test_asset_detail_raises_for_unknown_ids_when_called_directly(loaded):
    with pytest.raises(NotFound):
        mira._t_asset_detail(loaded, "NOPE")


def test_usage_summary_falls_back_to_type(loaded):
    assert mira.run_tool(loaded, "usage_summary", {"group_by": "site"})["group_by"] == "site"
    # An invalid grouping is coerced rather than raised: the answer is still useful.
    assert mira.run_tool(loaded, "usage_summary", {"group_by": "sideways"})["group_by"] == "type"


def test_cost_insights_reports_the_idler(loaded):
    insights = mira.run_tool(loaded, "cost_insights", {})
    assert insights["savings"]["total_idle_cost"] > 0
    assert "EQX1001" in {row["equipment_id"] for row in insights["worst_idle"]}


def test_every_tool_result_is_json_encodable(loaded):
    """Tool results go straight into the request body.

    Strict json.dumps, deliberately: the read-models return real date and
    datetime objects, and a `default=str` here would pass while the actual
    HTTP encoder -- which has no such fallback -- raised TypeError.
    """
    import json

    calls = {
        "fleet_overview": {},
        "list_sites": {},
        "list_alerts": {},
        "find_assets": {},
        "usage_summary": {},
        "cost_insights": {},
        "asset_detail": {"equipment_id": "EQX1001"},
    }
    assert set(calls) == set(mira.TOOL_IMPLS)

    for name, args in calls.items():
        result = mira.run_tool(loaded, name, args)
        assert "error" not in result, f"{name}: {result.get('error')}"
        json.dumps(result)


def test_jsonable_flattens_dates_but_keeps_scalars():
    from datetime import date

    out = mira._jsonable({"day": date(2026, 9, 1), "n": 3, "ok": True, "gone": None})
    assert out == {"day": "2026-09-01", "n": 3, "ok": True, "gone": None}
