/**
 * MapLibre GL live map.
 *
 * MapLibre over Mapbox GL / Google Maps because it needs no API token and no
 * billing account -- the style below points at OSM raster tiles, so the map works
 * on a fresh clone with nothing to configure. Swapping in a vector style
 * (Mapbox, MapTiler, Protomaps) is a change to MAP_STYLE alone.
 *
 * Rendering choice: assets are GeoJSON in a single symbol/circle layer pair
 * rather than one DOM Marker each. 21 DOM markers would be fine; 10k would not,
 * and the layer approach costs nothing extra to write. Markers *animate* between
 * pings by interpolating each asset's position over the ~5s simulator tick, so a
 * moving machine slides instead of teleporting.
 */
import { useEffect, useMemo, useRef, useState } from "react";
// maplibre-gl v6 publishes named exports only -- there is no default export.
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { MapAsset, MapSite, TrackPoint } from "@/lib/types";
import { statusColor } from "@/lib/palette";
import { useTheme } from "@/store/ui";

/**
 * Free raster basemap: no token, no account.
 *
 * Built fresh per Map instance, NOT shared as a module constant: MapLibre
 * normalises and takes ownership of the style object it is handed, so a second
 * Map constructed from the same object gets a consumed style and silently never
 * fires `load` (no sources, no layers, blank canvas). React StrictMode mounts
 * every effect twice in dev, so a shared constant fails exactly there.
 */
function mapStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0d0d0d" } },
      { id: "osm", type: "raster", source: "osm", paint: { "raster-opacity": 1 } },
    ],
  };
}

/** Approximate metres-per-degree circle, good enough for a few-km geofence. */
function circlePolygon(lng: number, lat: number, radiusKm: number, steps = 64): number[][] {
  const coords: number[][] = [];
  const latR = radiusKm / 110.574;
  const lngR = radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= steps; i++) {
    const theta = (i / steps) * 2 * Math.PI;
    coords.push([lng + lngR * Math.cos(theta), lat + latR * Math.sin(theta)]);
  }
  return coords;
}

function sitesGeoJson(sites: MapSite[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: sites
      .filter((s) => s.lat != null && s.lng != null)
      .map((s) => ({
        type: "Feature" as const,
        properties: { site_id: s.site_id, name: s.name, radius_km: s.radius_km },
        geometry: { type: "Polygon" as const, coordinates: [circlePolygon(s.lng, s.lat, s.radius_km)] },
      })),
  };
}

/** One in-flight marker animation: where it was, where it is heading, when. */
interface Animated {
  from: [number, number];
  to: [number, number];
  start: number;
  duration: number;
}

export interface LiveMapProps {
  assets: MapAsset[];
  sites: MapSite[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Optional breadcrumb trail (asset detail / playback). */
  trail?: TrackPoint[];
  /** Marker for the playback head. */
  playhead?: { lat: number; lng: number } | null;
  fitTo?: [number, number][] | null;
}

export function LiveMap({ assets, sites, selectedId, onSelect, trail, playhead, fitTo }: LiveMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  // `ready` is state, not just a ref: the data effects below must RE-RUN once the
  // style finishes loading. A ref would let them bail on first render and never
  // fire again, which silently drops the geofence rings and markers.
  const [ready, setReady] = useState(false);
  const readyRef = useRef(false);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const theme = useTheme((s) => s.theme);

  // Animation bookkeeping, kept in refs so a frame never triggers a React render.
  const positionsRef = useRef<Map<string, Animated>>(new Map());
  const assetsRef = useRef<MapAsset[]>(assets);
  const rafRef = useRef<number | null>(null);
  const selectedRef = useRef<string | null>(selectedId);

  // Mirrored into refs in an effect, not during render: the requestAnimationFrame
  // loop needs the latest values without re-subscribing, and writing a ref during
  // render is a React rules violation (and unsafe under concurrent rendering).
  useEffect(() => {
    assetsRef.current = assets;
    selectedRef.current = selectedId;
  }, [assets, selectedId]);

  /* ------------------------------- init once ------------------------------- */
  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: mapStyle(),
      center: [80.2707, 13.0827], // Chennai — the seed fleet's centre of gravity
      zoom: 6.2,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    // Dev-only handle so the map can be inspected from the console
    // (queryRenderedFeatures, getStyle) without wiring a debug UI.
    if (import.meta.env.DEV) (window as unknown as { __map?: maplibregl.Map }).__map = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      map.addSource("sites", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("trail", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("assets", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("playhead", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

      // Geofence ring: fill + edge, kept recessive so markers stay the subject.
      map.addLayer({
        id: "site-fill",
        type: "fill",
        source: "sites",
        paint: { "fill-color": "#3987e5", "fill-opacity": 0.07 },
      });
      map.addLayer({
        id: "site-line",
        type: "line",
        source: "sites",
        paint: { "line-color": "#3987e5", "line-width": 1.5, "line-opacity": 0.55, "line-dasharray": [2, 2] },
      });
      // Site names are DOM markers, not a symbol layer: a symbol layer needs a
      // glyph server, and the raster style deliberately has no external font
      // dependency. Seven sites is nothing for the DOM.
      map.addLayer({
        id: "trail-line",
        type: "line",
        source: "trail",
        paint: { "line-color": "#eda100", "line-width": 2, "line-opacity": 0.9 },
      });

      // Halo ring marks a geofence breach — a second channel beside colour.
      map.addLayer({
        id: "asset-halo",
        type: "circle",
        source: "assets",
        filter: ["==", ["get", "breach"], true],
        paint: {
          "circle-radius": 13,
          "circle-color": "transparent",
          "circle-stroke-color": "#d03b3b",
          "circle-stroke-width": 2,
          "circle-stroke-opacity": 0.9,
        },
      });

      map.addLayer({
        id: "asset-selected",
        type: "circle",
        source: "assets",
        filter: ["==", ["get", "selected"], true],
        paint: {
          "circle-radius": 17,
          "circle-color": "transparent",
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      });

      map.addLayer({
        id: "asset-dot",
        type: "circle",
        source: "assets",
        paint: {
          "circle-radius": ["case", ["==", ["get", "selected"], true], 9, 7],
          "circle-color": ["get", "color"],
          // 2px surface ring keeps overlapping marks separable.
          "circle-stroke-color": "#1a1a19",
          "circle-stroke-width": 2,
        },
      });

      map.addLayer({
        id: "playhead-dot",
        type: "circle",
        source: "playhead",
        paint: {
          "circle-radius": 8,
          "circle-color": "#eda100",
          "circle-stroke-color": "#1a1a19",
          "circle-stroke-width": 2,
        },
      });

      map.on("click", "asset-dot", (e: MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties?.equipment_id as string | undefined;
        if (id) onSelect(id);
      });
      map.on("mouseenter", "asset-dot", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "asset-dot", () => (map.getCanvas().style.cursor = ""));

      readyRef.current = true;
      setReady(true);
      pushAssets(map, assetsRef.current, positionsRef.current, selectedRef.current);
    });

    const tick = () => {
      const m = mapRef.current;
      if (m && readyRef.current) pushAssets(m, assetsRef.current, positionsRef.current, selectedRef.current);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      popupRef.current?.remove();
      readyRef.current = false;
      setReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, [onSelect]);

  /* --------------------- retarget animation on new data --------------------- */
  useEffect(() => {
    const now = performance.now();
    const store = positionsRef.current;
    const seen = new Set<string>();

    for (const a of assets) {
      if (a.lat == null || a.lng == null) continue;
      seen.add(a.equipment_id);
      const target: [number, number] = [a.lng, a.lat];
      const existing = store.get(a.equipment_id);

      if (!existing) {
        store.set(a.equipment_id, { from: target, to: target, start: now, duration: 0 });
        continue;
      }
      if (existing.to[0] === target[0] && existing.to[1] === target[1]) continue;

      // Start the next leg from where the marker actually is right now, so a
      // mid-flight update does not snap backwards.
      store.set(a.equipment_id, {
        from: interpolate(existing, now),
        to: target,
        start: now,
        duration: 1600,
      });
    }
    for (const id of [...store.keys()]) if (!seen.has(id)) store.delete(id);
  }, [assets]);

  /* ------------------------------ static layers ----------------------------- */
  const siteData = useMemo(() => sitesGeoJson(sites), [sites]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("sites") as GeoJSONSource | undefined)?.setData(siteData);
  }, [siteData, theme, ready]);

  // Site name labels as DOM markers (no glyph server needed).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const markers = sites
      .filter((s) => s.lat != null && s.lng != null)
      .map((s) => {
        const el = document.createElement("div");
        el.textContent = s.name;
        el.style.cssText =
          "font:500 10px system-ui,-apple-system,'Segoe UI',sans-serif;color:#e8e8e6;" +
          "background:rgba(0,0,0,.55);padding:2px 6px;border-radius:4px;white-space:nowrap;" +
          "pointer-events:none;transform:translateY(14px)";
        return new maplibregl.Marker({ element: el }).setLngLat([s.lng, s.lat]).addTo(map);
      });
    return () => markers.forEach((m) => m.remove());
  }, [sites, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource("trail") as GeoJSONSource | undefined;
    if (!source) return;
    const coords = (trail ?? []).map((p) => [p.lng, p.lat]);
    source.setData(
      coords.length > 1
        ? { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } }
        : { type: "FeatureCollection", features: [] },
    );
  }, [trail, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource("playhead") as GeoJSONSource | undefined;
    source?.setData(
      playhead
        ? {
            type: "FeatureCollection",
            features: [
              { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [playhead.lng, playhead.lat] } },
            ],
          }
        : { type: "FeatureCollection", features: [] },
    );
  }, [playhead, ready]);

  /* ------------------------------- fit bounds ------------------------------- */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !fitTo || fitTo.length === 0) return;
    const bounds = fitTo.reduce(
      (b, c) => b.extend(c as [number, number]),
      new maplibregl.LngLatBounds(fitTo[0] as [number, number], fitTo[0] as [number, number]),
    );
    map.fitBounds(bounds, { padding: 80, maxZoom: 13, duration: 800 });
  }, [fitTo]);

  /* --------------------------- popup on selection --------------------------- */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    popupRef.current?.remove();
    popupRef.current = null;
    if (!selectedId) return;

    const asset = assets.find((a) => a.equipment_id === selectedId);
    if (!asset || asset.lat == null || asset.lng == null) return;

    popupRef.current = new maplibregl.Popup({ offset: 16, closeButton: true, maxWidth: "260px" })
      .setLngLat([asset.lng, asset.lat])
      .setHTML(popupHtml(asset))
      .addTo(map);

    map.easeTo({ center: [asset.lng, asset.lat], zoom: Math.max(map.getZoom(), 10), duration: 700 });
  }, [selectedId, assets, ready]);

  return <div ref={containerRef} className="h-full w-full" />;
}

function interpolate(a: Animated, now: number): [number, number] {
  if (a.duration <= 0) return a.to;
  const t = Math.min(1, (now - a.start) / a.duration);
  // easeOutCubic: quick departure, soft landing — reads as machine movement.
  const e = 1 - Math.pow(1 - t, 3);
  return [a.from[0] + (a.to[0] - a.from[0]) * e, a.from[1] + (a.to[1] - a.from[1]) * e];
}

function pushAssets(
  map: maplibregl.Map,
  assets: MapAsset[],
  store: Map<string, Animated>,
  selectedId: string | null,
) {
  const source = map.getSource("assets") as GeoJSONSource | undefined;
  if (!source) return;
  const now = performance.now();

  source.setData({
    type: "FeatureCollection",
    features: assets
      .filter((a) => a.lat != null && a.lng != null)
      .map((a) => {
        const anim = store.get(a.equipment_id);
        const [lng, lat] = anim ? interpolate(anim, now) : [a.lng as number, a.lat as number];
        return {
          type: "Feature" as const,
          properties: {
            equipment_id: a.equipment_id,
            color: statusColor(a.status),
            breach: a.outside_geofence,
            selected: a.equipment_id === selectedId,
          },
          geometry: { type: "Point" as const, coordinates: [lng, lat] },
        };
      }),
  });
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function popupHtml(a: MapAsset): string {
  const breach =
    a.outside_geofence && a.distance_from_site_km != null
      ? `<div style="margin-top:6px;color:#d03b3b;font-size:11px">⚠ ${a.distance_from_site_km.toFixed(1)} km from site — outside geofence</div>`
      : "";
  const site = a.site_name ? esc(a.site_name) : "Unassigned";
  return `
    <div style="padding:10px 12px;font-family:system-ui,-apple-system,'Segoe UI',sans-serif">
      <div style="font-weight:600;font-size:13px">${esc(a.equipment_id)}</div>
      <div style="font-size:11px;opacity:.75;margin-top:2px">${esc(a.type)} · ${esc(a.status)}</div>
      <div style="font-size:11px;opacity:.75;margin-top:4px">Site: ${site}</div>
      ${breach}
    </div>`;
}
