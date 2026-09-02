/**
 * The two ends of a hire, side by side.
 *
 * This is the whole point of condition photos: not a gallery, but a comparison.
 * The columns are equal width and the tiles are the same size on both sides, so
 * the eye can move straight across between the machine that left and the
 * machine that came back. Click either one to see it large.
 */
import { useEffect, useState } from "react";
import { timeAgo } from "@/lib/format";
import type { AssetPhoto } from "@/lib/types";

/** Either a stored photo or one staged in the browser but not yet uploaded. */
export interface ComparePhoto {
  key: string;
  src: string;
  label: string;
  sub?: string;
}

export function fromStored(rows: AssetPhoto[]): ComparePhoto[] {
  return rows.map((p) => ({
    key: `s${p.photo_id}`,
    src: p.url,
    label: p.caption ?? p.original_name ?? `Photo ${p.photo_id}`,
    sub: `${timeAgo(p.taken_at)}${p.actor ? ` · ${p.actor}` : ""}`,
  }));
}

export function PhotoCompare({
  left,
  right,
  leftLabel,
  rightLabel,
  leftEmpty,
  rightEmpty,
  loading = false,
}: {
  left: ComparePhoto[];
  right: ComparePhoto[];
  leftLabel: string;
  rightLabel: string;
  leftEmpty: string;
  rightEmpty: string;
  loading?: boolean;
}) {
  const [zoom, setZoom] = useState<ComparePhoto | null>(null);

  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setZoom(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoom]);

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <Column
          label={leftLabel}
          rows={left}
          empty={loading ? "Loading…" : leftEmpty}
          onZoom={setZoom}
        />
        <Column label={rightLabel} rows={right} empty={rightEmpty} onZoom={setZoom} accent />
      </div>

      {zoom && (
        <div
          role="dialog"
          aria-label={zoom.label}
          onClick={() => setZoom(null)}
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3 bg-black/85 p-6"
        >
          <img
            src={zoom.src}
            alt={zoom.label}
            className="max-h-[80vh] max-w-full rounded-lg object-contain"
          />
          <p className="text-center text-xs text-white/70">
            {zoom.label}
            {zoom.sub ? ` — ${zoom.sub}` : ""} · click anywhere or press Esc to close
          </p>
        </div>
      )}
    </>
  );
}

function Column({
  label,
  rows,
  empty,
  onZoom,
  accent = false,
}: {
  label: string;
  rows: ComparePhoto[];
  empty: string;
  onZoom: (p: ComparePhoto) => void;
  accent?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span
          className={
            "text-[11px] font-semibold uppercase tracking-wide " +
            (accent ? "text-[var(--accent)]" : "text-ink-2")
          }
        >
          {label}
        </span>
        <span className="text-[11px] text-ink-muted tnum">{rows.length}</span>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-hair px-2 py-6 text-center text-[11px] leading-snug text-ink-muted">
          {empty}
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-1.5">
          {rows.map((p) => (
            <li key={p.key}>
              <button
                type="button"
                onClick={() => onZoom(p)}
                className="block w-full"
                title={p.sub ? `${p.label} — ${p.sub}` : p.label}
              >
                <img
                  src={p.src}
                  alt={p.label}
                  loading="lazy"
                  className="aspect-square w-full rounded-lg border border-hair object-cover transition-opacity hover:opacity-80"
                />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
