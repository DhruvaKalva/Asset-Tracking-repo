/**
 * Wire types, mirrored from the FastAPI schemas (app/schemas.py) and the
 * hand-shaped dict endpoints. Kept deliberately close to the server payloads --
 * where the backend sends a loose `dict` (health_flags, evidence, reasons) that
 * looseness is preserved rather than invented away.
 */

export type AssetStatus =
  | "AVAILABLE"
  | "RENTED"
  | "IN_USE"
  | "IDLE"
  | "OVERDUE"
  | "UNACCOUNTED"
  | "MAINTENANCE";

export type Severity = "INFO" | "WARN" | "HIGH" | "CRITICAL";

/**
 * MOVABLE is mobile plant: checked out to a site, tracked, geofenced.
 * FIXED is installed plant that stays at one site and is never rented out.
 */
export type Mobility = "MOVABLE" | "FIXED";

export interface HealthFlags {
  idle_ratio?: number;
  hours_since_ping?: number;
  excessive_idle?: boolean;
  unassigned_site?: boolean;
  stale_ping?: boolean;
  [k: string]: unknown;
}

export interface Asset {
  equipment_id: string;
  type: string;
  model: string | null;
  status: AssetStatus;
  site_id: string | null;
  site_name: string | null;
  operator_id: string | null;
  operator_name: string | null;
  rental_id: number | null;
  check_out_date: string | null;
  expected_check_in_date: string | null;
  days_until_due: number | null;
  last_seen_at: string | null;
  lat: number | null;
  lng: number | null;
  engine_hours_today: number;
  idle_hours_today: number;
  utilization_pct: number;
  health_flags: HealthFlags;
  open_alerts: number;
  rental_rate_per_hour: number;
  mobility: Mobility;
  home_site_id: string | null;
}

export interface Site {
  site_id: string;
  name: string;
  region: string | null;
  lat: number | null;
  lng: number | null;
  radius_km: number;
}

export interface Operator {
  operator_id: string;
  name: string;
  certification: string | null;
  phone: string | null;
}

export interface Equipment {
  equipment_id: string;
  type: string;
  model: string | null;
  qr_payload: string;
  rfid_tag: string | null;
  rental_rate_per_hour: number;
  lifetime_engine_hours: number;
  mobility: Mobility;
  home_site_id: string | null;
  service_interval_hours: number;
}

/** POST /api/equipment. Everything but `type` and `mobility` has a server default. */
export interface EquipmentCreate {
  type: string;
  mobility: Mobility;
  model?: string;
  equipment_id?: string;
  home_site_id?: string;
  rental_rate_per_hour?: number;
  service_interval_hours?: number;
  lifetime_engine_hours?: number;
  hours_at_last_service?: number;
  qr_payload?: string;
  rfid_tag?: string;
  actor?: string;
}

export interface AssetEvent {
  event_id: number;
  equipment_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  source: string;
  actor: string | null;
  occurred_at: string;
}

export interface Alert {
  alert_id: number;
  equipment_id: string;
  kind: string;
  severity: Severity;
  reason_text: string;
  evidence: Record<string, unknown>;
  raised_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface UsageStats {
  engine_hours: number;
  idle_hours: number;
  total_hours: number;
  utilization_pct: number;
  idle_ratio: number;
  operating_days: number;
  asset_days: number;
  downtime_hours: number;
  fuel_litres: number;
  window_days?: number;
  assets_reporting?: number;
}

export interface UsageGroup extends UsageStats {
  key: string;
  group_by: "asset" | "site" | "type";
}

export interface DailyUsage {
  day: string;
  engine_hours: number;
  idle_hours: number;
  utilization_pct: number;
}

export interface AssetUsage extends UsageStats {
  equipment_id: string;
  daily: DailyUsage[];
}

export interface Savings {
  total_idle_cost: number;
  identified_savings: number;
  open_recommendations: number;
  critical_recommendations: number;
}

export interface Overview {
  total_assets: number;
  status_counts: Partial<Record<AssetStatus, number>>;
  on_rent: number;
  unaccounted: number;
  overdue: number;
  open_alerts: number;
  critical_alerts: number;
  fleet: UsageStats;
  savings: Savings;
  generated_at: string;
}

export interface MapAsset {
  equipment_id: string;
  type: string;
  status: AssetStatus;
  lat: number | null;
  lng: number | null;
  site_id: string | null;
  site_name: string | null;
  last_seen_at: string | null;
  distance_from_site_km: number | null;
  outside_geofence: boolean;
}

export interface MapSite {
  site_id: string;
  name: string;
  lat: number;
  lng: number;
  radius_km: number;
}

export interface MapSnapshot {
  assets: MapAsset[];
  sites: MapSite[];
  generated_at: string;
}

export interface TrackPoint {
  lat: number;
  lng: number;
  at: string;
  source: string;
  event_type: string;
}

export interface Track {
  equipment_id: string;
  window_hours: number;
  points: TrackPoint[];
  point_count: number;
  distance_km: number;
  current: {
    lat: number | null;
    lng: number | null;
    last_seen_at: string | null;
    status: AssetStatus;
  } | null;
  site: MapSite | null;
  distance_from_site_km: number | null;
}

export interface Breach {
  equipment_id: string;
  site_id: string;
  site_name: string;
  distance_km: number;
  radius_km: number;
  overshoot_km: number;
  lat: number;
  lng: number;
  last_seen_at: string;
}

export interface Forecast {
  site_id: string;
  equipment_type: string;
  week_start: string;
  predicted_demand: number;
  lower_ci: number;
  upper_ci: number;
  model_version: string;
  driver_text: string | null;
  mape: number | null;
  generated_at: string;
}

export interface Shortage {
  site_id: string;
  equipment_type: string;
  week_start: string;
  predicted_demand: number;
  available_now: number;
  shortfall: number;
  recommendation: string;
  confidence: string;
}

export interface AnomalyRule {
  kind: string;
  severity: Severity;
  reason: string;
  evidence: Record<string, unknown>;
}

export interface AnomalyReasons {
  rules?: AnomalyRule[];
  ml?: {
    score: number;
    flagged: boolean;
    model: string;
    explanation: string;
  };
}

export interface Anomaly {
  equipment_id: string;
  day: string;
  rule_severity: Severity;
  ml_score: number;
  final_severity: Severity;
  reasons: AnomalyReasons;
  is_anomaly: boolean;
  detected_at: string;
}

export interface Recommendation {
  kind: string;
  equipment_id: string;
  site_id: string | null;
  severity: Severity;
  estimated_saving: number;
  detail: string;
  evidence: Record<string, unknown>;
}

export interface IdleCostRow {
  equipment_id: string;
  type: string;
  idle_hours: number;
  engine_hours: number;
  utilization_pct: number;
  hourly_rate: number;
  idle_cost: number;
  productive_cost: number;
}

export interface MaintenanceRow {
  equipment_id: string;
  type: string;
  hours_since_service: number;
  service_interval_hours: number;
  /** Hours consumed as a fraction of the interval (0.802 = 80.2%). */
  risk_ratio: number;
  risk_level: "OK" | "HIGH" | "DUE";
  engine_hours_per_day: number;
  estimated_days_to_service: number | null;
  /** Null when the asset is not near its interval -- there is nothing to advise. */
  recommendation: string | null;
}

export interface AssetDetail {
  asset: Asset;
  usage: AssetUsage;
  timeline: AssetEvent[];
  alerts: Alert[];
  maintenance: MaintenanceRow | null;
}

export interface Rental {
  rental_id: number;
  equipment_id: string;
  site_id: string | null;
  operator_id: string | null;
  check_out_date: string;
  expected_check_in_date: string;
  actual_check_in_date: string | null;
  status: "RESERVED" | "ACTIVE" | "RETURNED" | "OVERDUE";
}

export interface RegistryCounts {
  equipment: number;
  sites: number;
  operators: number;
  open_rentals: number;
}

/* ----- SSE frames (topics published by app/adapters/bus.py) ----- */

export interface AssetStateFrame {
  equipment_id: string;
  status: AssetStatus;
  site_id: string | null;
  operator_id: string | null;
  utilization_pct: number;
  engine_hours_today: number;
  idle_hours_today: number;
  lat: number | null;
  lng: number | null;
  health_flags: HealthFlags;
}

export interface AlertFrame {
  alert_id?: number;
  equipment_id: string;
  kind: string;
  severity: Severity;
  reason_text: string;
  evidence?: Record<string, unknown>;
  raised_at?: string;
}

export interface EventFrame {
  equipment_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
}

/* -- Mira, the dashboard assistant -------------------------------------- */

export interface MiraMessage {
  role: "user" | "assistant";
  content: string;
}

export interface MiraToolCall {
  name: string;
  args: Record<string, unknown>;
}

export interface MiraReply {
  reply: string;
  /** Which read-models produced the answer, so a number can be traced. */
  tools_used: MiraToolCall[];
  model: string;
  usage: Record<string, number>;
}

export interface MiraHealth {
  configured: boolean;
  model: string | null;
  tools: string[];
}
