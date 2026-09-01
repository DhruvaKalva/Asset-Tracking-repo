/**
 * The live half of the dashboard.
 *
 * One EventSource for the whole app, mounted once in the layout. Rather than
 * refetching on every frame (the simulator emits ~13 asset_state frames every
 * 5s, which would be a stampede), frames are written straight into the
 * TanStack Query cache. The map and the asset table re-render from that cache,
 * so both stay in sync without either one owning the socket.
 *
 * The backend already sends `retry: 3000`, so the browser reconnects on its own;
 * we only track status for the connection pill.
 */
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import { streamUrl } from "@/lib/api";
import type { AlertFrame, Asset, AssetStateFrame, EventFrame, MapSnapshot } from "@/lib/types";

export type StreamStatus = "connecting" | "live" | "offline";

export interface LiveEvent {
  id: string;
  equipment_id: string;
  event_type: string;
  occurred_at: string;
}

interface LiveState {
  status: StreamStatus;
  lastFrameAt: number | null;
  frames: number;
  /** Newest first, capped -- this is a ticker, not a log. */
  recent: LiveEvent[];
  toasts: AlertFrame[];
  setStatus: (s: StreamStatus) => void;
  pushEvent: (e: LiveEvent) => void;
  pushToast: (a: AlertFrame) => void;
  dismissToast: (index: number) => void;
}

export const useLive = create<LiveState>((set) => ({
  status: "connecting",
  lastFrameAt: null,
  frames: 0,
  recent: [],
  toasts: [],
  setStatus: (status) => set({ status }),
  pushEvent: (e) =>
    set((s) => ({
      lastFrameAt: Date.now(),
      frames: s.frames + 1,
      recent: [e, ...s.recent].slice(0, 40),
    })),
  pushToast: (a) => set((s) => ({ toasts: [a, ...s.toasts].slice(0, 4) })),
  dismissToast: (index) => set((s) => ({ toasts: s.toasts.filter((_, i) => i !== index) })),
}));

export function useLiveStream() {
  const qc = useQueryClient();

  useEffect(() => {
    const { setStatus, pushEvent, pushToast } = useLive.getState();
    setStatus("connecting");

    const es = new EventSource(streamUrl());

    es.onopen = () => setStatus("live");
    es.onerror = () => {
      // EventSource retries by itself; surface the gap without tearing down.
      setStatus(es.readyState === EventSource.CLOSED ? "offline" : "connecting");
    };

    es.addEventListener("asset_state", (ev) => {
      let frame: AssetStateFrame;
      try {
        frame = JSON.parse((ev as MessageEvent).data) as AssetStateFrame;
      } catch {
        return;
      }
      useLive.getState().pushEvent({
        id: `${frame.equipment_id}-${Date.now()}-${Math.random()}`,
        equipment_id: frame.equipment_id,
        event_type: "STATE " + frame.status,
        occurred_at: new Date().toISOString(),
      });
      patchAssetCaches(qc, frame);
    });

    es.addEventListener("alert", (ev) => {
      let frame: AlertFrame;
      try {
        frame = JSON.parse((ev as MessageEvent).data) as AlertFrame;
      } catch {
        return;
      }
      pushToast(frame);
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      void qc.invalidateQueries({ queryKey: ["overview"] });
    });

    es.addEventListener("event", (ev) => {
      let frame: EventFrame;
      try {
        frame = JSON.parse((ev as MessageEvent).data) as EventFrame;
      } catch {
        return;
      }
      pushEvent({
        id: `${frame.equipment_id}-${frame.occurred_at}-${Math.random()}`,
        equipment_id: frame.equipment_id,
        event_type: frame.event_type,
        occurred_at: frame.occurred_at,
      });
      // Check-in/out changes rentals and availability, which the state frame
      // alone does not describe.
      if (frame.event_type === "CHECK_OUT" || frame.event_type === "CHECK_IN") {
        void qc.invalidateQueries({ queryKey: ["assets"] });
        void qc.invalidateQueries({ queryKey: ["overview"] });
      }
    });

    return () => {
      es.close();
      setStatus("offline");
    };
  }, [qc]);
}

/**
 * Patch every cached asset list and the map snapshot in place.
 *
 * Filtered lists are patched rather than invalidated: a frame can move an asset
 * in or out of a filtered set, but re-running the query on every frame would
 * hammer the API. The periodic refetch in queries.ts reconciles membership.
 */
function patchAssetCaches(qc: ReturnType<typeof useQueryClient>, frame: AssetStateFrame) {
  qc.setQueriesData<Asset[]>({ queryKey: ["assets"] }, (prev) => {
    if (!prev) return prev;
    let hit = false;
    const next = prev.map((a) => {
      if (a.equipment_id !== frame.equipment_id) return a;
      hit = true;
      return {
        ...a,
        status: frame.status,
        site_id: frame.site_id,
        operator_id: frame.operator_id,
        utilization_pct: frame.utilization_pct,
        engine_hours_today: frame.engine_hours_today,
        idle_hours_today: frame.idle_hours_today,
        lat: frame.lat,
        lng: frame.lng,
        health_flags: frame.health_flags,
        last_seen_at: new Date().toISOString(),
      };
    });
    return hit ? next : prev;
  });

  qc.setQueryData<MapSnapshot>(["map"], (prev) => {
    if (!prev) return prev;
    let hit = false;
    const assets = prev.assets.map((a) => {
      if (a.equipment_id !== frame.equipment_id) return a;
      hit = true;
      return {
        ...a,
        status: frame.status,
        site_id: frame.site_id,
        lat: frame.lat,
        lng: frame.lng,
        last_seen_at: new Date().toISOString(),
      };
    });
    return hit ? { ...prev, assets } : prev;
  });
}

/** Alert frames carry no id until the row is read back; used only for toast keys. */
export function toastKey(a: AlertFrame, i: number): string {
  return `${a.alert_id ?? "x"}-${a.equipment_id}-${a.kind}-${i}`;
}
