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
import { useCheckIn, useCheckOut, useOperators, useResolveScan, useSites } from "@/hooks/queries";
import { useAuth } from "@/store/auth";
import { formatDate } from "@/lib/format";
import type { Rental } from "@/lib/types";

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

  const sites = useSites();
  const operators = useOperators();
  const resolve = useResolveScan();
  const checkOut = useCheckOut();
  const checkIn = useCheckIn();
  const user = useAuth((s) => s.user);

  const pending = checkOut.isPending || checkIn.isPending;
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
            onClick={() => setMode(m)}
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

          <div className="flex items-center justify-between gap-3 pt-1">
            <p className="text-[11px] leading-snug text-ink-muted">
              Idempotency key <code className="text-ink-2">{idempotencyKey.slice(0, 8)}…</code> — a retry of this
              submission returns the same rental instead of creating a second one.
            </p>
            <button type="submit" className={primaryButtonClass} disabled={!canSubmit}>
              {pending ? "Submitting…" : mode === "out" ? "Check out" : "Check in"}
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
