/**
 * TanStack Query hooks -- one per backend endpoint.
 *
 * Polling intervals are deliberately conservative: the SSE stream (useLiveStream)
 * is the real-time path, and it patches the asset/map caches directly. Refetch
 * intervals here are only a safety net for derived data the stream does not carry
 * (aggregates, forecasts, cost rollups).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "@/lib/api";
import type {
  Alert,
  Anomaly,
  Asset,
  AssetDetail,
  AssetUsage,
  Breach,
  Equipment,
  EquipmentCreate,
  Forecast,
  IdleCostRow,
  MaintenanceRow,
  MapSnapshot,
  Operator,
  Overview,
  Recommendation,
  RegistryCounts,
  Rental,
  Savings,
  Shortage,
  Site,
  Track,
  UsageGroup,
  UsageStats,
} from "@/lib/types";

export interface AssetFilters {
  status?: string;
  site_id?: string;
  type?: string;
  search?: string;
}

export interface AlertFilters {
  severity?: string;
  kind?: string;
  equipment_id?: string;
  unresolved?: boolean;
}

export const keys = {
  overview: ["overview"] as const,
  assets: (f: AssetFilters) => ["assets", f] as const,
  asset: (id: string) => ["asset", id] as const,
  map: ["map"] as const,
  sites: ["sites"] as const,
  operators: ["operators"] as const,
  alerts: (f: AlertFilters) => ["alerts", f] as const,
  breaches: ["breaches"] as const,
  track: (id: string, hours: number) => ["track", id, hours] as const,
  usage: (g: string) => ["usage", g] as const,
  assetUsage: (id: string, d: number) => ["assetUsage", id, d] as const,
  kpis: (d: number) => ["kpis", d] as const,
  forecast: (w: number) => ["forecast", w] as const,
  shortages: ["shortages"] as const,
  anomalies: ["anomalies"] as const,
  recommendations: ["recommendations"] as const,
  idleCost: (d: number) => ["idleCost", d] as const,
  maintenance: ["maintenance"] as const,
  savings: ["savings"] as const,
  rentals: (id?: string) => ["rentals", id ?? "all"] as const,
  available: (t?: string) => ["available", t ?? "all"] as const,
  counts: ["counts"] as const,
};

export const useOverview = () =>
  useQuery({
    queryKey: keys.overview,
    queryFn: () => api.get<Overview>("/api/overview"),
    refetchInterval: 20_000,
  });

export const useAssets = (filters: AssetFilters = {}) =>
  useQuery({
    queryKey: keys.assets(filters),
    queryFn: () => api.get<Asset[]>("/api/assets" + qs(filters)),
    refetchInterval: 30_000,
  });

export const useAsset = (id: string | undefined) =>
  useQuery({
    queryKey: keys.asset(id ?? ""),
    queryFn: () => api.get<AssetDetail>("/api/assets/" + id),
    enabled: Boolean(id),
  });

export const useMapSnapshot = () =>
  useQuery({
    queryKey: keys.map,
    queryFn: () => api.get<MapSnapshot>("/api/map"),
    refetchInterval: 30_000,
  });

export const useSites = () =>
  useQuery({ queryKey: keys.sites, queryFn: () => api.get<Site[]>("/api/sites"), staleTime: 300_000 });

export const useOperators = () =>
  useQuery({
    queryKey: keys.operators,
    queryFn: () => api.get<Operator[]>("/api/operators"),
    staleTime: 300_000,
  });

export const useAlerts = (filters: AlertFilters = {}) =>
  useQuery({
    queryKey: keys.alerts(filters),
    queryFn: () => api.get<Alert[]>("/api/alerts" + qs({ ...filters, limit: 200 })),
    refetchInterval: 30_000,
  });

export const useBreaches = () =>
  useQuery({
    queryKey: keys.breaches,
    queryFn: () => api.get<Breach[]>("/api/geofence/breaches"),
    refetchInterval: 30_000,
  });

export const useTrack = (id: string | undefined, hours: number) =>
  useQuery({
    queryKey: keys.track(id ?? "", hours),
    queryFn: () => api.get<Track>("/api/assets/" + id + "/track" + qs({ hours, limit: 5000 })),
    enabled: Boolean(id),
  });

export const useUsage = (groupBy: "asset" | "site" | "type") =>
  useQuery({
    queryKey: keys.usage(groupBy),
    queryFn: () => api.get<UsageGroup[]>("/api/usage" + qs({ group_by: groupBy })),
  });

export const useAssetUsage = (id: string | undefined, days = 30) =>
  useQuery({
    queryKey: keys.assetUsage(id ?? "", days),
    queryFn: () => api.get<AssetUsage>("/api/usage/" + id + qs({ days })),
    enabled: Boolean(id),
  });

export const useKpis = (days = 30) =>
  useQuery({ queryKey: keys.kpis(days), queryFn: () => api.get<UsageStats>("/api/kpis" + qs({ days })) });

export const useForecast = (weeks = 4) =>
  useQuery({
    queryKey: keys.forecast(weeks),
    queryFn: () => api.get<Forecast[]>("/api/forecast" + qs({ weeks })),
  });

export const useShortages = () =>
  useQuery({ queryKey: keys.shortages, queryFn: () => api.get<Shortage[]>("/api/forecast/shortages") });

export const useAnomalies = () =>
  useQuery({
    queryKey: keys.anomalies,
    queryFn: () => api.get<Anomaly[]>("/api/anomalies?limit=100"),
    refetchInterval: 60_000,
  });

export const useRecommendations = () =>
  useQuery({
    queryKey: keys.recommendations,
    queryFn: () => api.get<Recommendation[]>("/api/optimize/recommendations"),
  });

export const useIdleCost = (days = 30) =>
  useQuery({
    queryKey: keys.idleCost(days),
    queryFn: () => api.get<IdleCostRow[]>("/api/optimize/idle-cost" + qs({ days })),
  });

export const useMaintenance = () =>
  useQuery({ queryKey: keys.maintenance, queryFn: () => api.get<MaintenanceRow[]>("/api/optimize/maintenance") });

export const useSavings = () =>
  useQuery({
    queryKey: keys.savings,
    queryFn: () => api.get<Savings>("/api/optimize/savings"),
    refetchInterval: 60_000,
  });

export const useRentals = (equipmentId?: string) =>
  useQuery({
    queryKey: keys.rentals(equipmentId),
    queryFn: () => api.get<Rental[]>("/api/rentals" + qs({ equipment_id: equipmentId })),
  });

export const useAvailableEquipment = (type?: string) =>
  useQuery({
    queryKey: keys.available(type),
    queryFn: () => api.get<Equipment[]>("/api/equipment/available" + qs({ type })),
  });

export const useCounts = () =>
  useQuery({ queryKey: keys.counts, queryFn: () => api.get<RegistryCounts>("/api/registry/counts"), staleTime: 60_000 });

/* --------------------------------- mutations -------------------------------- */

function invalidateFleet(qc: ReturnType<typeof useQueryClient>) {
  for (const k of ["assets", "asset", "map", "overview", "alerts", "breaches", "savings", "recommendations"]) {
    void qc.invalidateQueries({ queryKey: [k] });
  }
}

export function useAcknowledgeAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, actor }: { alertId: number; actor?: string }) =>
      api.post<Alert>("/api/alerts/" + alertId + "/acknowledge" + qs({ actor })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      void qc.invalidateQueries({ queryKey: keys.overview });
    },
  });
}

export interface CheckOutBody {
  scan_payload: string;
  site_id: string;
  operator_id?: string;
  expected_check_in_date?: string;
  actor?: string;
  notes?: string;
  idempotency_key?: string;
}

export function useCheckOut() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CheckOutBody) => api.post<Rental>("/api/checkout", body),
    onSuccess: () => invalidateFleet(qc),
  });
}

export interface CheckInBody {
  scan_payload: string;
  actor?: string;
  notes?: string;
  idempotency_key?: string;
}

export function useCheckIn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CheckInBody) => api.post<Rental>("/api/checkin", body),
    onSuccess: () => invalidateFleet(qc),
  });
}

export function useCreateEquipment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: EquipmentCreate) => api.post<Equipment>("/api/equipment", body),
    onSuccess: () => {
      invalidateFleet(qc);
      void qc.invalidateQueries({ queryKey: keys.counts });
      void qc.invalidateQueries({ queryKey: ["available"] });
    },
  });
}

export function useResolveScan() {
  return useMutation({
    mutationFn: (scan_payload: string) =>
      api.post<{ equipment_id: string; resolved_via: string }>("/api/scan/resolve", { scan_payload }),
  });
}

export function useRunJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (job: "overdue" | "anomaly" | "forecast") => api.post<unknown>("/api/admin/jobs/" + job + "/run"),
    onSuccess: () => {
      invalidateFleet(qc);
      void qc.invalidateQueries({ queryKey: ["anomalies"] });
      void qc.invalidateQueries({ queryKey: ["forecast"] });
      void qc.invalidateQueries({ queryKey: ["shortages"] });
    },
  });
}

export function useSimulator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (action: "pause" | "resume" | "tick") => api.post<unknown>("/api/admin/simulator/" + action),
    onSuccess: () => invalidateFleet(qc),
  });
}
