/**
 * Register a machine.
 *
 * The form's shape follows the one question that changes everything else:
 * is this asset movable or fixed?
 *
 *   MOVABLE — mobile plant. Gets checked out to a site, tracked, geofenced.
 *             Its site comes from whatever rental it is on, so the home site
 *             here is only the yard it returns to.
 *   FIXED   — installed plant: a tower crane, a generator, a batching plant.
 *             It is never rented out, so it has no rental to read a site from
 *             and the install site is mandatory — without one the backend
 *             would have nowhere to put it on the map.
 *
 * Everything except type and mobility has a server-side default, so the fast
 * path is three fields and Enter.
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Card,
  ErrorNote,
  Field,
  buttonClass,
  inputClass,
  primaryButtonClass,
} from "@/components/primitives";
import { useCreateEquipment, useSites } from "@/hooks/queries";
import { useAuth } from "@/store/auth";
import { money } from "@/lib/format";
import type { Equipment, EquipmentCreate, Mobility } from "@/lib/types";

/** Suggestions only -- the backend accepts any type string. */
const MOVABLE_TYPES = ["Excavator", "Bulldozer", "Crane", "Grader", "Loader", "Dump Truck", "Backhoe"];
const FIXED_TYPES = ["Tower Crane", "Generator", "Batching Plant", "Compressor", "Crusher", "Site Office"];

const MOBILITY: { value: Mobility; label: string; blurb: string; icon: string }[] = [
  {
    value: "MOVABLE",
    label: "Movable",
    icon: "⇄",
    blurb: "Mobile plant. Checked out to sites, tracked live, geofenced.",
  },
  {
    value: "FIXED",
    label: "Fixed",
    icon: "⚓",
    blurb: "Installed at one site and stays there. Never rented out.",
  },
];

export default function AddAssetPage() {
  const navigate = useNavigate();
  const sites = useSites();
  const create = useCreateEquipment();
  const user = useAuth((s) => s.user);

  const [mobility, setMobility] = useState<Mobility>("MOVABLE");
  const [type, setType] = useState("");
  const [model, setModel] = useState("");
  const [homeSiteId, setHomeSiteId] = useState("");
  const [rate, setRate] = useState("");
  const [serviceInterval, setServiceInterval] = useState("500");
  const [lifetimeHours, setLifetimeHours] = useState("");
  const [hoursAtLastService, setHoursAtLastService] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [equipmentId, setEquipmentId] = useState("");
  const [rfidTag, setRfidTag] = useState("");

  const [created, setCreated] = useState<Equipment | null>(null);

  const isFixed = mobility === "FIXED";
  const typeSuggestions = isFixed ? FIXED_TYPES : MOVABLE_TYPES;

  // The one hard requirement the backend enforces, mirrored here so the reader
  // finds out before submitting rather than after a 409.
  const siteMissing = isFixed && !homeSiteId;
  const canSubmit = type.trim().length > 0 && !siteMissing && !create.isPending;

  const siteName = useMemo(
    () => sites.data?.find((s) => s.site_id === homeSiteId)?.name ?? null,
    [sites.data, homeSiteId],
  );

  function reset() {
    setCreated(null);
    setType("");
    setModel("");
    setRate("");
    setLifetimeHours("");
    setHoursAtLastService("");
    setEquipmentId("");
    setRfidTag("");
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const num = (v: string) => (v.trim() === "" ? undefined : Number(v));

    const body: EquipmentCreate = {
      type: type.trim(),
      mobility,
      model: model.trim() || undefined,
      // A movable asset's yard is optional; a fixed asset's install site is not.
      home_site_id: homeSiteId || undefined,
      rental_rate_per_hour: num(rate),
      service_interval_hours: num(serviceInterval),
      lifetime_engine_hours: num(lifetimeHours),
      hours_at_last_service: num(hoursAtLastService),
      equipment_id: equipmentId.trim().toUpperCase() || undefined,
      rfid_tag: rfidTag.trim() || undefined,
      actor: user?.name,
    };

    create.mutate(body, { onSuccess: setCreated });
  }

  /* ------------------------------ success view ------------------------------ */
  if (created) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 p-5">
        <header>
          <h1 className="text-xl font-semibold text-ink">Asset registered</h1>
          <p className="text-sm text-ink-muted">
            {created.equipment_id} is on the dashboard and scannable right now.
          </p>
        </header>

        <Card title="Print this label" subtitle="What the yard puts on the sticker">
          <div className="space-y-2 text-sm">
            <Row label="Equipment ID" value={created.equipment_id} mono />
            <Row label="QR payload" value={created.qr_payload} mono />
            <Row label="RFID tag" value={created.rfid_tag ?? "—"} mono />
          </div>
          <p className="mt-3 border-t border-hair pt-2 text-xs leading-snug text-ink-muted">
            Both tags resolve at check-out, and so does the raw ID typed by hand —
            the yard is never blocked by a damaged sticker.
          </p>
        </Card>

        <Card title="Registered as">
          <div className="space-y-2 text-sm">
            <Row label="Type" value={`${created.type}${created.model ? ` · ${created.model}` : ""}`} />
            <Row label="Mobility" value={created.mobility === "FIXED" ? "Fixed — installed plant" : "Movable — mobile plant"} />
            <Row label={created.mobility === "FIXED" ? "Installed at" : "Home yard"} value={created.home_site_id ?? "—"} />
            <Row label="Rate" value={`${money(created.rental_rate_per_hour)}/h`} />
            <Row label="Service interval" value={`${created.service_interval_hours} h`} />
          </div>
        </Card>

        <div className="flex flex-wrap gap-2">
          <Link to={`/assets/${created.equipment_id}`} className={primaryButtonClass}>
            Open {created.equipment_id} →
          </Link>
          <button className={buttonClass} onClick={reset}>
            + Add another
          </button>
          <button className={buttonClass} onClick={() => navigate("/assets")}>
            Back to fleet
          </button>
        </div>
      </div>
    );
  }

  /* -------------------------------- the form -------------------------------- */
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Add asset</h1>
          <p className="text-sm text-ink-muted">
            The ID, QR payload and RFID tag are minted for you.
          </p>
        </div>
        <Link to="/assets" className={buttonClass}>
          ← All assets
        </Link>
      </header>

      <form onSubmit={submit} className="space-y-4">
        <Card title="What kind of asset is this?" subtitle="This decides how the system tracks it">
          <div className="grid gap-2 sm:grid-cols-2">
            {MOBILITY.map((m) => (
              <label
                key={m.value}
                className={
                  "flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 transition-colors " +
                  (mobility === m.value
                    ? "border-[var(--accent)] bg-[var(--accent)]/8"
                    : "border-hair hover:border-ink-muted/40")
                }
              >
                <input
                  type="radio"
                  name="mobility"
                  className="mt-1 accent-[var(--accent)]"
                  checked={mobility === m.value}
                  onChange={() => setMobility(m.value)}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-ink">
                    <span className="mr-1.5 opacity-70" aria-hidden>
                      {m.icon}
                    </span>
                    {m.label}
                  </span>
                  <span className="mt-0.5 block text-xs leading-snug text-ink-muted">{m.blurb}</span>
                </span>
              </label>
            ))}
          </div>
        </Card>

        <Card title="Identity">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Type (required)">
              <input
                className={inputClass}
                value={type}
                onChange={(e) => setType(e.target.value)}
                list="type-suggestions"
                placeholder={isFixed ? "Tower Crane" : "Excavator"}
                autoFocus
              />
              <datalist id="type-suggestions">
                {typeSuggestions.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </Field>

            <Field label="Model">
              <input
                className={inputClass}
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={isFixed ? "Potain MDT 219" : "CAT 320"}
              />
            </Field>

            <div className="sm:col-span-2">
              <Field label={isFixed ? "Installed at (required)" : "Home yard (optional)"}>
                <select
                  className={inputClass + (siteMissing ? " border-critical" : "")}
                  value={homeSiteId}
                  onChange={(e) => setHomeSiteId(e.target.value)}
                >
                  <option value="">{isFixed ? "Select a site…" : "No home yard"}</option>
                  {(sites.data ?? []).map((s) => (
                    <option key={s.site_id} value={s.site_id}>
                      {s.name} ({s.site_id})
                    </option>
                  ))}
                </select>
              </Field>
              <p className="mt-1 text-[11px] leading-snug text-ink-muted">
                {isFixed ? (
                  siteMissing ? (
                    <span className="text-critical">
                      A fixed asset needs a site — it has no rental to take a location from, so
                      without one it could never be placed on the map.
                    </span>
                  ) : (
                    <>
                      Pinned to {siteName} permanently. It will not be checked out, and geofence
                      breach alerts do not apply to it.
                    </>
                  )
                ) : (
                  <>Its live site comes from whatever rental it is on; this is just where it returns.</>
                )}
              </p>
            </div>
          </div>
        </Card>

        <Card title="Commercial and service">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Rate per hour (₹)">
              <input
                className={inputClass}
                type="number"
                min={0}
                step="any"
                value={rate}
                onChange={(e) => setRate(e.target.value)}
                placeholder="0"
              />
            </Field>
            <Field label="Service interval (h)">
              <input
                className={inputClass}
                type="number"
                min={1}
                step="any"
                value={serviceInterval}
                onChange={(e) => setServiceInterval(e.target.value)}
              />
            </Field>
            <Field label="Hours on the clock">
              <input
                className={inputClass}
                type="number"
                min={0}
                step="any"
                value={lifetimeHours}
                onChange={(e) => setLifetimeHours(e.target.value)}
                placeholder="0"
              />
            </Field>
          </div>
          {Number(lifetimeHours) > 0 && (
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">
              A used intake is not treated as overdue for service on day one — the maintenance
              clock starts at these hours unless you set the last service below.
            </p>
          )}
        </Card>

        <Card
          title="Advanced"
          subtitle="Leave blank unless you are matching an existing sticker"
          actions={
            <button
              type="button"
              className="text-xs text-[var(--accent)] hover:underline"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? "Hide" : "Show"}
            </button>
          }
        >
          {showAdvanced ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Equipment ID">
                <input
                  className={inputClass}
                  value={equipmentId}
                  onChange={(e) => setEquipmentId(e.target.value)}
                  placeholder="auto (EQX####)"
                />
              </Field>
              <Field label="RFID tag">
                <input
                  className={inputClass}
                  value={rfidTag}
                  onChange={(e) => setRfidTag(e.target.value)}
                  placeholder="auto"
                />
              </Field>
              <Field label="Hours at last service">
                <input
                  className={inputClass}
                  type="number"
                  min={0}
                  step="any"
                  value={hoursAtLastService}
                  onChange={(e) => setHoursAtLastService(e.target.value)}
                  placeholder="defaults to hours on the clock"
                />
              </Field>
            </div>
          ) : (
            <p className="text-xs text-ink-muted">
              ID, QR payload and RFID tag are generated automatically.
            </p>
          )}
        </Card>

        {create.isError && <ErrorNote error={create.error} />}

        <div className="flex items-center justify-end gap-2">
          <Link to="/assets" className={buttonClass}>
            Cancel
          </Link>
          <button type="submit" className={primaryButtonClass} disabled={!canSubmit}>
            {create.isPending ? "Registering…" : "Register asset"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-ink-muted">{label}</span>
      <span className={"text-ink " + (mono ? "font-mono text-xs tnum" : "text-sm")}>{value}</span>
    </div>
  );
}
