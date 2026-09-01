"""Location history and geofencing.

The breadcrumb trail is reconstructed from `asset_events`, not from a dedicated
positions table. Every telemetry tick and location ping already carries lat/lng
in its payload, so the history was always there -- this is the event log paying
for itself. Add a positions table later if the read volume demands it; the API
contract below will not change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import NotFound
from app.domain.geo import distance_from_site, haversine_km
from app.models import AssetCurrentState, AssetEvent, Equipment, Rental, RentalStatus, Site

POSITION_EVENTS = ("LOCATION_PING", "TELEMETRY_TICK", "CHECK_OUT")


def track(db: Session, equipment_id: str, hours: int = 24, limit: int = 500) -> dict:
    """Breadcrumb trail for one asset, oldest first, plus distance travelled."""
    equipment_id = equipment_id.upper()
    if db.get(Equipment, equipment_id) is None:
        raise NotFound(f"unknown equipment {equipment_id}")

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = db.scalars(
        select(AssetEvent)
        .where(
            AssetEvent.equipment_id == equipment_id,
            AssetEvent.event_type.in_(POSITION_EVENTS),
            AssetEvent.occurred_at >= since.replace(tzinfo=None),
        )
        .order_by(AssetEvent.occurred_at)
        .limit(limit)
    )

    points = []
    for event in events:
        payload = event.payload or {}
        lat, lng = payload.get("lat"), payload.get("lng")
        if lat is None or lng is None:
            continue
        points.append(
            {
                "lat": lat,
                "lng": lng,
                "at": event.occurred_at,
                "source": event.source,
                "event_type": event.event_type,
            }
        )

    distance = 0.0
    for previous, current in zip(points, points[1:]):
        distance += haversine_km(previous["lat"], previous["lng"], current["lat"], current["lng"])

    state = db.get(AssetCurrentState, equipment_id)
    site = db.get(Site, state.site_id) if state and state.site_id else None

    return {
        "equipment_id": equipment_id,
        "window_hours": hours,
        "points": points,
        "point_count": len(points),
        "distance_km": round(distance, 3),
        "current": {
            "lat": state.lat if state else None,
            "lng": state.lng if state else None,
            "last_seen_at": state.last_seen_at if state else None,
            "status": state.status if state else None,
        },
        "site": _site_view(site),
        "distance_from_site_km": distance_from_site(
            state.lat if state else None,
            state.lng if state else None,
            site.lat if site else None,
            site.lng if site else None,
        ),
    }


def _site_view(site: Site | None) -> dict | None:
    if site is None:
        return None
    return {
        "site_id": site.site_id,
        "name": site.name,
        "lat": site.lat,
        "lng": site.lng,
        "radius_km": site.radius_km,
    }


def live_positions(db: Session) -> dict:
    """Everything the map needs in one call: markers, site rings, geofence state."""
    sites = {s.site_id: s for s in db.scalars(select(Site))}
    equipment = {e.equipment_id: e for e in db.scalars(select(Equipment))}

    markers = []
    for state in db.scalars(select(AssetCurrentState)):
        if state.lat is None or state.lng is None:
            continue
        site = sites.get(state.site_id) if state.site_id else None
        gap = distance_from_site(
            state.lat, state.lng, site.lat if site else None, site.lng if site else None
        )
        eq = equipment.get(state.equipment_id)
        markers.append(
            {
                "equipment_id": state.equipment_id,
                "type": eq.type if eq else None,
                "status": state.status,
                "lat": state.lat,
                "lng": state.lng,
                "site_id": state.site_id,
                "site_name": site.name if site else None,
                "last_seen_at": state.last_seen_at,
                "distance_from_site_km": gap,
                "outside_geofence": bool(site and gap is not None and gap > site.radius_km),
            }
        )

    return {
        "assets": markers,
        "sites": [_site_view(s) for s in sites.values() if s.lat is not None],
        "generated_at": datetime.now(timezone.utc),
    }


def geofence_breaches(db: Session) -> list[dict]:
    """On-rent assets sitting outside their assigned site's radius."""
    sites = {s.site_id: s for s in db.scalars(select(Site))}
    open_rentals = {
        r.equipment_id: r
        for r in db.scalars(
            select(Rental).where(
                Rental.status.in_([RentalStatus.ACTIVE.value, RentalStatus.OVERDUE.value])
            )
        )
    }

    out = []
    for state in db.scalars(select(AssetCurrentState)):
        rental = open_rentals.get(state.equipment_id)
        if rental is None or rental.site_id is None:
            continue
        site = sites.get(rental.site_id)
        gap = distance_from_site(
            state.lat, state.lng, site.lat if site else None, site.lng if site else None
        )
        if site is None or gap is None or gap <= site.radius_km:
            continue
        out.append(
            {
                "equipment_id": state.equipment_id,
                "site_id": site.site_id,
                "site_name": site.name,
                "distance_km": gap,
                "radius_km": site.radius_km,
                "overshoot_km": round(gap - site.radius_km, 3),
                "lat": state.lat,
                "lng": state.lng,
                "last_seen_at": state.last_seen_at,
            }
        )
    return sorted(out, key=lambda r: r["overshoot_km"], reverse=True)
