"""Mira -- the dashboard assistant.

Two rules shape this module.

*Grounded.* Mira answers from the same read-models the dashboard renders, via
the tools below. She is never asked to recall anything about this fleet from
training, so she cannot narrate a number that is not on screen. Every turn also
carries a fresh snapshot of the fleet, which answers most questions without a
tool round trip at all.

*Scoped.* Her only capabilities reach this fleet's assets, rentals, alerts,
utilisation and costs. There is deliberately no tool for anything else, so an
off-topic question has nothing to draw on, and the system instruction tells her
to decline it in one line rather than improvise.

Transport is plain HTTPS to the Gemini REST API -- no vendor SDK, because the
request shape is a dozen lines of JSON and a pinned SDK is a dependency we would
have to carry.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import alert_service, cost_service, dashboard, telemetry_service
from app.domain.errors import Conflict
from app.models import Site

log = logging.getLogger(__name__)

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MAX_HISTORY_TURNS = 12
"""Older turns are dropped. A support chat that needs more than a dozen turns of
memory is a chat that should have been a filtered table view."""


def configured() -> bool:
    return bool(settings.gemini_api_key.strip())


# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------
SYSTEM = """\
You are Mira, the assistant embedded in the Smart Rental Tracking System \
dashboard. You help fleet managers understand the equipment rental operation \
this dashboard monitors: assets, sites, operators, rentals, check-in/check-out, \
utilisation, idle cost, alerts, anomalies and demand forecasts.

SCOPE -- this is strict.
- Answer only questions about this fleet and this dashboard.
- If asked about anything else (general knowledge, coding, writing, current \
events, other products, personal advice), decline in ONE short sentence and \
name something you can help with instead. Do not answer the off-topic part \
even partially, and do not apologise at length.
- You are not a general assistant that also knows about the fleet. You are a \
fleet assistant and nothing else.

GROUNDING.
- Every figure you state must come from the snapshot below or from a tool \
result in this conversation. Never estimate, never fill a gap from memory.
- If the data does not cover the question, say exactly what is missing and \
which page or filter would show it.
- Call tools when the snapshot is not enough. Prefer one precise call over \
guessing.

STYLE.
- Short. Two or three sentences, or a tight list when comparing several assets.
- Lead with the answer, then the evidence.
- Always name assets by their equipment id, e.g. EQX1004.
- Plain text only: no markdown headings, no bold, no tables. Short "- " \
bulleted lines are fine.
- Currency is Indian rupees, written as Rs 1,23,456.
- When an asset clearly needs action, say what to do in a final short line.

The user is looking at the dashboard right now, so refer to what they can see \
("the Alerts page shows...") rather than describing the system in the abstract.
"""


# ---------------------------------------------------------------------------
# Live snapshot -- the cheap answer to most questions
# ---------------------------------------------------------------------------
def snapshot(db: Session) -> str:
    """A compact fleet brief, refreshed on every turn.

    Kept deliberately small: this rides along with each request, so it carries
    the shape of the fleet, and the tools carry the detail.
    """
    ov = dashboard.overview(db)
    fleet = ov.get("fleet") or {}
    savings = ov.get("savings") or {}

    alerts = alert_service.list_alerts(db, unresolved_only=True, limit=200)
    by_severity: dict[str, int] = {}
    for a in alerts:
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1

    sites = list(db.scalars(select(Site)))
    site_line = ", ".join(f"{s.site_id} {s.name}" for s in sites) or "none"

    by_type = telemetry_service.usage_summary(db, group_by="type")
    type_line = (
        ", ".join(f"{t['key']} {t['utilization_pct']}%" for t in by_type[:8]) or "no usage yet"
    )

    top_alerts = "\n".join(
        f"- {a.equipment_id} [{a.severity}] {a.kind}: {a.reason_text}" for a in alerts[:6]
    ) or "- none open"

    return f"""\
LIVE FLEET SNAPSHOT (generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC)

Fleet: {ov['total_assets']} assets. On rent {ov['on_rent']}, overdue {ov['overdue']}, \
unaccounted {ov['unaccounted']}.
Status counts: {json.dumps(ov.get('status_counts') or {})}
Alerts: {ov['open_alerts']} open, {ov['critical_alerts']} high or critical. \
By severity: {json.dumps(by_severity)}
Utilisation last 30 days: {fleet.get('utilization_pct')}% across \
{fleet.get('assets_reporting')} reporting assets \
({fleet.get('engine_hours')}h engine, {fleet.get('idle_hours')}h idle).
Idle cost to date: Rs {savings.get('total_idle_cost')}. Identified savings: \
Rs {savings.get('identified_savings')} across {savings.get('open_recommendations')} \
recommendations ({savings.get('critical_recommendations')} critical).
Utilisation by type: {type_line}
Sites: {site_line}

Most recent open alerts:
{top_alerts}
"""


# ---------------------------------------------------------------------------
# Tools -- the only reach Mira has
# ---------------------------------------------------------------------------
def _t_fleet_overview(db: Session) -> dict:
    ov = dashboard.overview(db)
    ov.pop("generated_at", None)
    return ov


def _t_find_assets(
    db: Session,
    status: str | None = None,
    type: str | None = None,
    site_id: str | None = None,
    search: str | None = None,
    limit: int = 25,
) -> dict:
    rows = dashboard.list_assets(
        db, status=status, site_id=site_id, equipment_type=type, search=search
    )
    slim = [
        {
            "equipment_id": r["equipment_id"],
            "type": r["type"],
            "status": r["status"],
            "site": r["site_name"],
            "operator": r["operator_name"],
            "utilization_pct": r["utilization_pct"],
            "idle_hours_today": r["idle_hours_today"],
            "days_until_due": r["days_until_due"],
            "open_alerts": r["open_alerts"],
            "mobility": r["mobility"],
        }
        for r in rows[: max(1, min(int(limit), 60))]
    ]
    return {"matched": len(rows), "returned": len(slim), "assets": slim}


def _t_asset_detail(db: Session, equipment_id: str) -> dict:
    equipment_id = equipment_id.upper().strip()
    detail = dashboard.asset_detail(db, equipment_id)
    usage = dict(detail["usage"])
    usage.pop("daily", None)  # 90 rows of dailies is not worth the tokens

    # "What is this costing me" is the other half of every question about one
    # asset, so it ships with the record rather than needing a second call.
    cost = next(
        (c for c in cost_service.idle_cost_report(db) if c["equipment_id"] == equipment_id),
        None,
    )

    return {
        "asset": detail["asset"],
        "usage": usage,
        "cost": cost,
        "maintenance": detail["maintenance"],
        "open_alerts": [
            {
                "kind": a.kind,
                "severity": a.severity,
                "reason": a.reason_text,
                "raised_at": str(a.raised_at),
            }
            for a in detail["alerts"]
        ],
        # timeline() yields AssetEvent rows, not dicts.
        "recent_events": [
            {"event": e.event_type, "at": str(e.occurred_at)} for e in detail["timeline"][:10]
        ],
    }


def _t_list_alerts(
    db: Session,
    severity: str | None = None,
    kind: str | None = None,
    equipment_id: str | None = None,
    limit: int = 25,
) -> dict:
    rows = alert_service.list_alerts(
        db,
        severity=severity,
        kind=kind,
        equipment_id=equipment_id,
        unresolved_only=True,
        limit=max(1, min(int(limit), 60)),
    )
    return {
        "count": len(rows),
        "alerts": [
            {
                "alert_id": a.alert_id,
                "equipment_id": a.equipment_id,
                "kind": a.kind,
                "severity": a.severity,
                "reason": a.reason_text,
                "raised_at": str(a.raised_at),
            }
            for a in rows
        ],
    }


def _t_usage_summary(db: Session, group_by: str = "type") -> dict:
    if group_by not in ("asset", "site", "type"):
        group_by = "type"
    rows = telemetry_service.usage_summary(db, group_by=group_by)
    return {"group_by": group_by, "rows": rows[:30]}


def _t_cost_insights(db: Session) -> dict:
    return {
        "savings": cost_service.savings_summary(db),
        "recommendations": cost_service.recommendations(db)[:10],
        "worst_idle": cost_service.idle_cost_report(db)[:10],
        "maintenance_risk": [
            m for m in cost_service.maintenance_risk(db) if m.get("risk_level") != "OK"
        ][:10],
    }


def _t_list_sites(db: Session) -> dict:
    sites = list(db.scalars(select(Site)))
    return {
        "sites": [
            {
                "site_id": s.site_id,
                "name": s.name,
                "region": s.region,
                "radius_km": s.radius_km,
            }
            for s in sites
        ]
    }


TOOL_IMPLS: dict[str, Callable[..., dict]] = {
    "fleet_overview": _t_fleet_overview,
    "find_assets": _t_find_assets,
    "asset_detail": _t_asset_detail,
    "list_alerts": _t_list_alerts,
    "usage_summary": _t_usage_summary,
    "cost_insights": _t_cost_insights,
    "list_sites": _t_list_sites,
}

TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "fleet_overview",
        "description": "Headline fleet numbers: totals, status counts, open alerts, 30-day utilisation, savings.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "find_assets",
        "description": (
            "Search and filter the fleet. Use this for questions like which assets are "
            "overdue, idle, at a given site, or of a given type."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "status": {
                    "type": "STRING",
                    "description": "IN_USE, IDLE, AVAILABLE, OVERDUE, UNACCOUNTED, MAINTENANCE or RENTED",
                },
                "type": {"type": "STRING", "description": "Equipment type, e.g. Excavator"},
                "site_id": {"type": "STRING", "description": "Site id such as S003"},
                "search": {
                    "type": "STRING",
                    "description": "Free text matched against id, type, model and site name",
                },
                "limit": {"type": "INTEGER", "description": "Max rows to return, default 25"},
            },
        },
    },
    {
        "name": "asset_detail",
        "description": (
            "Everything about one asset: current state, usage, what its idle time is "
            "costing, maintenance risk, open alerts and recent events."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "equipment_id": {"type": "STRING", "description": "e.g. EQX1004"},
            },
            "required": ["equipment_id"],
        },
    },
    {
        "name": "list_alerts",
        "description": "Open alerts, optionally filtered by severity, kind or asset.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "severity": {"type": "STRING", "description": "INFO, WARN, HIGH or CRITICAL"},
                "kind": {"type": "STRING", "description": "Alert kind, e.g. OVERDUE"},
                "equipment_id": {"type": "STRING"},
                "limit": {"type": "INTEGER"},
            },
        },
    },
    {
        "name": "usage_summary",
        "description": "Engine hours, idle hours and utilisation, grouped by asset, site or type.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "group_by": {"type": "STRING", "description": "asset, site or type"},
            },
        },
    },
    {
        "name": "cost_insights",
        "description": (
            "Money view: idle cost leaders, savings summary, optimisation recommendations "
            "and assets due for service."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "list_sites",
        "description": "All sites with their ids, names, regions and geofence radius.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]


def _jsonable(value: Any) -> Any:
    """Coerce a tool result into something the JSON encoder accepts.

    The read-models hand back real `date` and `datetime` objects, which is right
    for the ORM and fatal for a request body. Converting here rather than at the
    call site means a new tool cannot forget to do it.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return str(value)


def run_tool(db: Session, name: str, args: dict) -> dict:
    """Dispatch one model-requested tool call.

    A failure here comes back as data rather than an exception: the model can
    read "no such asset" and correct itself, where a 500 would just end the turn.
    """
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        return {"error": f"unknown tool {name}"}
    try:
        return _jsonable(impl(db, **(args or {})))
    except Exception as exc:  # noqa: BLE001 -- surfaced to the model, not swallowed
        log.warning("mira tool %s failed: %s", name, exc)
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Gemini transport
# ---------------------------------------------------------------------------
def _post(payload: dict) -> dict:
    url = ENDPOINT.format(model=settings.gemini_model)
    try:
        res = httpx.post(
            url,
            json=payload,
            headers={"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"},
            timeout=settings.gemini_timeout_seconds,
        )
    except httpx.TimeoutException:
        raise Conflict("Mira timed out reaching Gemini. Try again.") from None
    except httpx.HTTPError as exc:
        raise Conflict(f"Mira could not reach Gemini: {exc}") from None

    if res.status_code >= 400:
        detail = res.text
        try:
            detail = res.json().get("error", {}).get("message", detail)
        except Exception:  # noqa: BLE001
            pass
        if res.status_code in (401, 403):
            raise Conflict(f"Gemini rejected the API key: {detail}")
        if res.status_code == 429:
            raise Conflict("Gemini rate limit reached. Wait a moment and ask again.")
        if res.status_code == 404:
            raise Conflict(
                f"Gemini has no model named {settings.gemini_model!r}. "
                "Set GEMINI_MODEL to a model your key can use."
            )
        raise Conflict(f"Gemini error {res.status_code}: {detail}")

    return res.json()


def _to_contents(messages: list[dict]) -> list[dict]:
    """Client history -> Gemini `contents`. Anything not user/assistant is dropped."""
    out: list[dict] = []
    for m in messages[-MAX_HISTORY_TURNS:]:
        role = "model" if m.get("role") == "assistant" else "user"
        text = (m.get("content") or "").strip()
        if not text:
            continue
        out.append({"role": role, "parts": [{"text": text}]})
    return out


def _parts_of(data: dict) -> list[dict]:
    candidates = data.get("candidates") or []
    if not candidates:
        blocked = (data.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise Conflict(f"Gemini blocked that message ({blocked}).")
        return []
    return (candidates[0].get("content") or {}).get("parts") or []


def chat(db: Session, messages: list[dict]) -> dict:
    """One assistant turn: model call, tool calls, model call, until it answers."""
    if not configured():
        raise Conflict(
            "Mira is not configured. Set GEMINI_API_KEY in .env and restart the API."
        )
    if not messages:
        raise Conflict("no messages")

    contents = _to_contents(messages)
    if not contents:
        raise Conflict("no usable message content")

    system_text = f"{SYSTEM}\n\n{snapshot(db)}"
    used: list[dict] = []

    for _ in range(max(1, settings.mira_max_tool_rounds)):
        data = _post(
            {
                "systemInstruction": {"parts": [{"text": system_text}]},
                "contents": contents,
                "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
                "generationConfig": {
                    # Low temperature: this is a reporting assistant, and a
                    # differently-worded answer to the same question every time
                    # reads as unreliable.
                    "temperature": 0.2,
                    "topP": 0.9,
                    "maxOutputTokens": 900,
                },
            }
        )

        parts = _parts_of(data)
        calls = [p["functionCall"] for p in parts if "functionCall" in p]

        if not calls:
            text = "".join(p["text"] for p in parts if "text" in p).strip()
            finish = ((data.get("candidates") or [{}])[0]).get("finishReason")
            if not text:
                text = (
                    "I could not put an answer together for that."
                    if finish != "MAX_TOKENS"
                    else "That answer ran long. Ask me for a narrower slice of it."
                )
            return {
                "reply": text,
                "tools_used": used,
                "model": settings.gemini_model,
                "usage": data.get("usageMetadata") or {},
            }

        # Echo the model's own call back before the results: Gemini requires the
        # functionCall part to precede its functionResponse in the transcript.
        contents.append({"role": "model", "parts": [{"functionCall": c} for c in calls]})

        responses = []
        for call in calls:
            name = call.get("name", "")
            args = call.get("args") or {}
            result = run_tool(db, name, args)
            used.append({"name": name, "args": args})
            responses.append({"functionResponse": {"name": name, "response": result}})
        contents.append({"role": "user", "parts": responses})

    return {
        "reply": (
            "I looked that up several times without settling on an answer. "
            "Try asking about one asset or one site at a time."
        ),
        "tools_used": used,
        "model": settings.gemini_model,
        "usage": {},
    }


def health() -> dict[str, Any]:
    return {
        "configured": configured(),
        "model": settings.gemini_model if configured() else None,
        "tools": [t["name"] for t in TOOL_DECLARATIONS],
    }
