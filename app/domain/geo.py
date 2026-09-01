"""Geospatial helpers. Small enough to keep dependency-free."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = radians(lat1), radians(lat2)
    dp = p2 - p1
    dl = radians(lng2) - radians(lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def distance_from_site(
    lat: float | None, lng: float | None, site_lat: float | None, site_lng: float | None
) -> float | None:
    """None when either end has no fix -- absence is not distance zero."""
    if lat is None or lng is None or site_lat is None or site_lng is None:
        return None
    return round(haversine_km(lat, lng, site_lat, site_lng), 3)
