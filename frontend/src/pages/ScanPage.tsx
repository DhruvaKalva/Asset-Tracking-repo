/**
 * Check-in / check-out.
 *
 * The backend's idempotency contract is the interesting part here: a client
 * key is minted per attempt and reused across retries, so a flaky-connection
 * double submit returns the rental that already exists instead of double-booking.
 * The key is regenerated only once a submission actually succeeds.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Card, ErrorNote, Field, Spinner, buttonClass, inputClass, primaryButtonClass } from "@/components/primitives";
import {
  useAssetPhotos,
  useAssets,
  useCheckIn,
  useCheckOut,
  useOperators,
  useResolveScan,
  useSites,
  useUploadPhotos,
} from "@/hooks/queries";
import { PhotoCapture, type StagedPhoto } from "@/components/PhotoCapture";
import { PhotoCompare, fromStored, type ComparePhoto } from "@/components/PhotoCompare";
import { useAuth } from "@/store/auth";
import { formatDate } from "@/lib/format";
import type { PhotoUploadResult, Rental } from "@/lib/types";

function newKey(): string {
  return crypto.randomUUID();
}

export default function ScanPage() {
  const [mode, setMode] = useState<"out" | "in">("out");
  const [scan, setScan] = useState("");
  const [siteId, setSiteId] = useState("");
  const [operatorId, setOperatorId] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [notes, setNotes] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);
  const [result, setResult] = useState<Rental | null>(null);
  const [photos, setPhotos] = useState<StagedPhoto[]>([]);
  const [photoResult, setPhotoResult] = useState<PhotoUploadResult | null>(null);

  const sites = useSites();
  const operators = useOperators();
  const resolve = useResolveScan();
  const checkOut = useCheckOut();
  const checkIn = useCheckIn();
  const uploadPhotos = useUploadPhotos();
  const assets = useAssets({});
  const user = useAuth((s) => s.user);

  const pending = checkOut.isPending || checkIn.isPending || uploadPhotos.isPending;
  const error = checkOut.error ?? checkIn.error;

  // Preview what the scan resolved to, the way the scanner screen does.
  useEffect(() => {
    const payload = scan.trim();
    if (payload.length < 3) return;
    const t = setTimeout(() => resolve.mutate(payload), 350);
    return () => clearTimeout(t);
    // resolve is a stable mutation object; re-running on it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scan]);

  const resolved = resolve.data;

  /**
   * A default payload for check-in.
   *
   * Check-in only succeeds against an asset that is actually out, so the
   * default is drawn from the live fleet rather than hard-coded -- a static
   * example would fail the moment that machine came back.
   */
  const onRent = useMemo(
    () => (assets.data ?? []).find((a) => a.rental_id != null),
    [assets.data],
  );
  const defaultPayload = onRent ? `CAT-QR-${onRent.equipment_id}` : "";

  useEffect(() => {
    // Only when arriving at check-in with an empty field. `scan` is not a
    // dependency on purpose: refilling as the user clears it would trap them.
    if (mode === "in" && defaultPayload) setScan((cur) => cur || defaultPayload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, defaultPayload]);

  // The hire being returned, so the comparison shows this handover's photos
  // rather than every check-out this machine has ever had.
  const returning = useMemo(
    () => (assets.data ?? []).find((a) => a.equipment_id === resolved?.equipment_id),
    [assets.data, resolved?.equipment_id],
  );

  const outPhotos = useAssetPhotos(
    mode === "in" ? resolved?.equipment_id : undefined,
    "CHECK_OUT",
    returning?.rental_id ?? undefined,
  );

  const stagedForCompare: ComparePhoto[] = photos.map((ph) => ({
    key: ph.id,
    src: ph.preview,
    label: ph.name,
    sub: ph.source === "camera" ? "just captured" : "from file",
  }));
  const canSubmit = useMemo(
    () => scan.trim().length > 0 && (mode === "in" || siteId.length > 0) && !pending,
    [scan, mode, siteId, pending],
  );

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setResult(null);
    const common = { scan_payload: scan.trim(), actor: user?.name, notes: notes || undefined, idempotency_key: idempotencyKey };

    const onDone = (rental: Rental) => {
      setResult(rental);
      setIdempotencyKey(newKey()); // fresh key only after a real success
      setScan("");
      setNotes("");

      // Photos go up only now, because only now is there a rental to attach
      // them to. The handover is already recorded either way -- a failed upload
      // must not read as a failed check-in.
      if (photos.length > 0) {
        uploadPhotos.mutate(
          {
            equipmentId: rental.equipment_id,
            kind: mode === "out" ? "CHECK_OUT" : "CHECK_IN",
            rentalId: rental.rental_id,
            files: photos.map((p) => p.blob),
            actor: user?.name,
            caption: notes || undefined,
          },
          {
            onSuccess: (res) => {
              setPhotoResult(res);
              photos.forEach((p) => URL.revokeObjectURL(p.preview));
              setPhotos([]);
            },
          },
        );
      }
    };

    if (mode === "out") {
      checkOut.mutate(
        { ...common, site_id: siteId, operator_id: operatorId || undefined, expected_check_in_date: dueDate || undefined },
        { onSuccess: onDone },
      );
    } else {
      checkIn.mutate(common, { onSuccess: onDone });
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-5">
      <header>
        <h1 className="text-xl font-semibold text-ink">Check In / Check Out</h1>
        <p className="text-sm text-ink-muted">Scan a QR payload, RFID tag, or type an equipment id.</p>
      </header>

      <div className="flex gap-1 rounded-lg border border-hair p-1">
        {(["out", "in"] as const).map((m) => (
          <button
            key={m}
            onClick={() => {
              setMode(m);
              setPhotoResult(null);
              // Photos staged for a check-out must not silently become
              // check-in evidence, so switching ends discards them.
              photos.forEach((ph) => URL.revokeObjectURL(ph.preview));
              setPhotos([]);
            }}
            className={
              "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors " +
              (mode === m ? "bg-[var(--accent)] text-white" : "text-ink-2 hover:text-ink")
            }
          >
            {m === "out" ? "Check out" : "Check in"}
          </button>
        ))}
      </div>

      <Card>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Scan payload">
            <input
              className={inputClass}
              value={scan}
              onChange={(e) => setScan(e.target.value)}
              placeholder="CAT-QR-EQX1001 · RFID tag · EQX1001"
              autoFocus
            />
          </Field>

          {scan.trim().length >= 3 && (
            <div className="rounded-lg border border-hair bg-raised px-3 py-2 text-xs">
              {resolve.isPending ? (
                <span className="text-ink-muted">Resolving…</span>
              ) : resolve.isError ? (
                <span className="text-critical">Not found — check the code.</span>
              ) : resolved ? (
                <span className="text-ink-2">
                  Resolves to <span className="font-semibold text-ink">{resolved.equipment_id}</span> via{" "}
                  {resolved.resolved_via}
                </span>
              ) : null}
            </div>
          )}

          {mode === "out" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Site (required)">
                <select className={inputClass} value={siteId} onChange={(e) => setSiteId(e.target.value)}>
                  <option value="">Select a site…</option>
                  {(sites.data ?? []).map((s) => (
                    <option key={s.site_id} value={s.site_id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Operator">
                <select className={inputClass} value={operatorId} onChange={(e) => setOperatorId(e.target.value)}>
                  <option value="">Unassigned</option>
                  {(operators.data ?? []).map((o) => (
                    <option key={o.operator_id} value={o.operator_id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Expected return">
                <input type="date" className={inputClass} value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </Field>
            </div>
          )}

          <Field label="Notes">
            <input className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
          </Field>

          <Field label={mode === "out" ? "Condition photos going out" : "Condition photos coming back"}>
            <PhotoCapture
              key={mode}
              photos={photos}
              onChange={setPhotos}
              disabled={pending}
              // In check-in the comparison below shows the staged set already.
              showStrip={mode === "out"}
            />
            <p className="mt-1.5 text-[11px] leading-snug text-ink-muted">
              {mode === "out"
                ? "Shot now, these are the record of how the machine left. Compare them against the return set to settle a damage claim."
                : "Photograph anything that changed. The two sets sit side by side below."}
            </p>
          </Field>

          {mode === "in" && resolved && (
            <div className="rounded-lg border border-hair bg-raised p-3">
              <div className="mb-2.5 flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium text-ink">
                  Condition check — {resolved.equipment_id}
                </span>
                {returning?.rental_id && (
                  <span className="text-[11px] text-ink-muted tnum">
                    rental #{returning.rental_id}
                  </span>
                )}
              </div>
              <PhotoCompare
                leftLabel="How it went out"
                rightLabel="How it came back"
                left={fromStored(outPhotos.data ?? [])}
                right={stagedForCompare}
                loading={outPhotos.isLoading}
                leftEmpty="No photos were taken when this machine went out."
                rightEmpty="Capture or upload the return photos above."
              />
            </div>
          )}

          <div className="flex items-center justify-between gap-3 pt-1">
            <p className="text-[11px] leading-snug text-ink-muted">
              Idempotency key <code className="text-ink-2">{idempotencyKey.slice(0, 8)}…</code> — a retry of this
              submission returns the same rental instead of creating a second one.
            </p>
            <button type="submit" className={primaryButtonClass} disabled={!canSubmit}>
              {uploadPhotos.isPending
                ? "Uploading photos…"
                : pending
                  ? "Submitting…"
                  : mode === "out"
                    ? "Check out"
                    : "Check in"}
            </button>
          </div>
        </form>
      </Card>

      {error && <ErrorNote error={error} />}

      {result && (
        <Card title={mode === "out" ? "Checked out" : "Checked in"}>
          <div className="space-y-1.5 text-sm">
            <Row label="Rental" value={`#${result.rental_id}`} />
            <Row label="Asset" value={result.equipment_id} />
            <Row label="Site" value={result.site_id ?? "—"} />
            <Row label="Out" value={formatDate(result.check_out_date)} />
            <Row label="Expected back" value={formatDate(result.expected_check_in_date)} />
            {result.actual_check_in_date && <Row label="Returned" value={formatDate(result.actual_check_in_date)} />}
            <Row label="Status" value={result.status} />
          </div>
          {photoResult && (
            <div className="mt-3 border-t border-hair pt-3">
              <p className="text-xs text-ink-2">
                {photoResult.saved.length} photo{photoResult.saved.length === 1 ? "" : "s"} attached to
                rental #{result.rental_id}
              </p>
              {photoResult.saved.length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-2">
                  {photoResult.saved.map((ph) => (
                    <li key={ph.photo_id}>
                      <img
                        src={ph.url}
                        alt={ph.original_name ?? `photo ${ph.photo_id}`}
                        className="h-14 w-14 rounded-lg border border-hair object-cover"
                      />
                    </li>
                  ))}
                </ul>
              )}
              {photoResult.rejected.length > 0 && (
                <ul className="mt-2 space-y-0.5">
                  {photoResult.rejected.map((r) => (
                    <li key={r.file} className="text-[11px] leading-snug text-warning">
                      {r.file} — {r.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {uploadPhotos.isError && (
            <p className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-2.5 py-2 text-xs leading-snug text-warning">
              The {mode === "out" ? "check-out" : "check-in"} was recorded, but the photos did not
              upload: {(uploadPhotos.error as Error).message}
            </p>
          )}

          <Link to={`/assets/${result.equipment_id}`} className={buttonClass + " mt-3"}>
            Open asset →
          </Link>
        </Card>
      )}

      {(sites.isLoading || operators.isLoading) && <Spinner label="Loading sites and operators" />}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-ink-muted">{label}</span>
      <span className="tnum text-ink">{value}</span>
    </div>
  );
}
