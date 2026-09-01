-- Postgres-only: turn telemetry_daily into a monthly-partitioned table.
-- Not needed for the demo (SQLite), needed the moment telemetry gets real.
--
-- Run once against an empty database, before the app creates its tables, then
-- add a partition per month from a cron job or pg_partman.

CREATE TABLE IF NOT EXISTS telemetry_daily (
    equipment_id VARCHAR(24)  NOT NULL,
    day          DATE         NOT NULL,
    engine_hours DOUBLE PRECISION DEFAULT 0,
    idle_hours   DOUBLE PRECISION DEFAULT 0,
    fuel_litres  DOUBLE PRECISION DEFAULT 0,
    site_id      VARCHAR(16),
    lat          DOUBLE PRECISION,
    lng          DOUBLE PRECISION,
    PRIMARY KEY (equipment_id, day)
) PARTITION BY RANGE (day);

CREATE TABLE IF NOT EXISTS telemetry_daily_2026_09
    PARTITION OF telemetry_daily FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS telemetry_daily_2026_10
    PARTITION OF telemetry_daily FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

CREATE INDEX IF NOT EXISTS ix_telemetry_site_day ON telemetry_daily (site_id, day);

-- The event log grows fastest of all. Partition it the same way when needed:
-- ALTER TABLE asset_events ... PARTITION BY RANGE (occurred_at);

-- Hot-path indexes the ORM does not create for you:
CREATE INDEX IF NOT EXISTS ix_alerts_unresolved
    ON alerts (equipment_id) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_rentals_open_only
    ON rentals (equipment_id) WHERE status IN ('ACTIVE', 'OVERDUE');
