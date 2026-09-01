/**
 * Fleet table.
 *
 * TanStack Table (headless) rather than AG Grid: the grid features actually
 * needed here -- sort, filter, a handful of custom cells -- are the free tier of
 * either, and headless keeps the markup in the app's own design tokens instead
 * of theming someone else's DOM. AG Grid earns its place at virtualised
 * five-figure row counts; this fleet is 21.
 *
 * Server-side filters (status/site/type/search) go to the API so the list stays
 * correct as the fleet grows; sorting is client-side because the payload is small.
 */
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { ErrorNote, Spinner, StatusChip, Empty, inputClass, primaryButtonClass } from "@/components/primitives";
import { useAssets, useSites } from "@/hooks/queries";
import { useFilters } from "@/store/ui";
import { dueLabel, money, num, pct, timeAgo } from "@/lib/format";
import { TYPE_ORDER } from "@/lib/palette";
import type { Asset, AssetStatus } from "@/lib/types";

const STATUSES: AssetStatus[] = ["IN_USE", "IDLE", "AVAILABLE", "OVERDUE", "UNACCOUNTED"];
const columnHelper = createColumnHelper<Asset>();

export default function AssetsPage() {
  const [params] = useSearchParams();
  const { search, status, type, siteId, setFilter, reset } = useFilters();
  const [sorting, setSorting] = useState<SortingState>([{ id: "utilization_pct", desc: false }]);

  // Deep links like /assets?status=IN_USE seed the shared filter store once.
  const seeded = useState(() => {
    const s = params.get("status");
    if (s) useFilters.getState().setFilter("status", s);
    return true;
  })[0];
  void seeded;

  const sites = useSites();
  const { data, isLoading, isError, error } = useAssets({
    status: status || undefined,
    type: type || undefined,
    site_id: siteId || undefined,
    search: search.trim() || undefined,
  });

  const columns = useMemo(
    () => [
      columnHelper.accessor("equipment_id", {
        header: "Asset",
        cell: (c) => (
          <Link to={`/assets/${c.getValue()}`} className="font-medium text-ink hover:text-[var(--accent)]">
            {c.getValue()}
          </Link>
        ),
      }),
      columnHelper.accessor("type", {
        header: "Type",
        cell: (c) => (
          <span className="text-ink-2">
            {c.getValue()}
            {c.row.original.model && <span className="ml-1 text-ink-muted">· {c.row.original.model}</span>}
          </span>
        ),
      }),
      columnHelper.accessor("mobility", {
        header: "Mobility",
        cell: (c) =>
          c.getValue() === "FIXED" ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-hair px-2 py-0.5 text-xs text-ink-2">
              <span aria-hidden>⚓</span> Fixed
            </span>
          ) : (
            <span className="text-xs text-ink-muted">
              <span aria-hidden className="mr-1">
                ⇄
              </span>
              Movable
            </span>
          ),
      }),
      columnHelper.accessor("status", {
        header: "Status",
        cell: (c) => <StatusChip status={c.getValue()} />,
      }),
      columnHelper.accessor("site_name", {
        header: "Site",
        // No site is normal for an idle-in-the-yard asset and a problem only for
        // one that is out on rent, so only the latter is flagged.
        cell: (c) => {
          const name = c.getValue();
          if (name) return <span className="text-ink-2">{name}</span>;
          const expected =
            c.row.original.status !== "AVAILABLE" && c.row.original.status !== "MAINTENANCE";
          return expected ? (
            <span className="text-critical">Unassigned</span>
          ) : (
            <span className="text-ink-muted">In yard</span>
          );
        },
      }),
      columnHelper.accessor("operator_name", {
        header: "Operator",
        cell: (c) => <span className="text-ink-2">{c.getValue() ?? "—"}</span>,
      }),
      columnHelper.accessor("utilization_pct", {
        header: "Utilisation",
        cell: (c) => <UtilBar value={c.getValue()} />,
      }),
      columnHelper.accessor("engine_hours_today", {
        header: "Engine / Idle (today)",
        cell: (c) => (
          <span className="tnum text-ink-2">
            {num(c.getValue())} / {num(c.row.original.idle_hours_today)} h
          </span>
        ),
      }),
      columnHelper.accessor("days_until_due", {
        header: "Due",
        cell: (c) => {
          const v = c.getValue();
          if (v == null) return <span className="text-ink-muted">—</span>;
          return <span className={"tnum " + (v < 0 ? "text-serious" : v <= 3 ? "text-warning" : "text-ink-2")}>{dueLabel(v)}</span>;
        },
      }),
      columnHelper.accessor("open_alerts", {
        header: "Alerts",
        cell: (c) =>
          c.getValue() > 0 ? (
            <span className="rounded-full bg-critical/15 px-1.5 py-0.5 text-xs font-semibold text-critical tnum">
              {c.getValue()}
            </span>
          ) : (
            <span className="text-ink-muted">—</span>
          ),
      }),
      columnHelper.accessor("rental_rate_per_hour", {
        header: "Rate",
        cell: (c) => <span className="tnum text-ink-2">{money(c.getValue())}/h</span>,
      }),
      columnHelper.accessor("last_seen_at", {
        header: "Last seen",
        cell: (c) => <span className="text-ink-muted">{timeAgo(c.getValue())}</span>,
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-hair bg-surface px-5 py-3">
        <div className="mr-2">
          <h1 className="text-base font-semibold text-ink">Assets</h1>
          <p className="text-xs text-ink-muted">{data?.length ?? 0} matching</p>
        </div>
        <input
          className={inputClass + " w-52"}
          placeholder="Search id, type, model…"
          value={search}
          onChange={(e) => setFilter("search", e.target.value)}
        />
        <select className={inputClass} value={status} onChange={(e) => setFilter("status", e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace("_", " ")}
            </option>
          ))}
        </select>
        <select className={inputClass} value={type} onChange={(e) => setFilter("type", e.target.value)}>
          <option value="">All types</option>
          {TYPE_ORDER.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select className={inputClass} value={siteId} onChange={(e) => setFilter("siteId", e.target.value)}>
          <option value="">All sites</option>
          {(sites.data ?? []).map((s) => (
            <option key={s.site_id} value={s.site_id}>
              {s.name}
            </option>
          ))}
        </select>
        {(search || status || type || siteId) && (
          <button onClick={reset} className="text-xs text-ink-muted hover:text-ink">
            Clear
          </button>
        )}
        <Link to="/assets/new" className={primaryButtonClass + " ml-auto"}>
          + Add asset
        </Link>
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        {isLoading ? (
          <Spinner label="Loading assets" />
        ) : isError ? (
          <div className="p-5">
            <ErrorNote error={error} />
          </div>
        ) : (data?.length ?? 0) === 0 ? (
          <Empty>No assets match these filters.</Empty>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-surface">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-hair">
                  {hg.headers.map((h) => (
                    <th
                      key={h.id}
                      onClick={h.column.getToggleSortingHandler()}
                      className="cursor-pointer select-none whitespace-nowrap px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-ink-muted hover:text-ink"
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      <span className="ml-1 text-[10px]">
                        {{ asc: "▲", desc: "▼" }[h.column.getIsSorted() as string] ?? ""}
                      </span>
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="border-b border-hair transition-colors hover:bg-ink-muted/5">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="whitespace-nowrap px-4 py-2.5">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/** Inline magnitude bar: one sequential hue, value stated in text beside it. */
function UtilBar({ value }: { value: number }) {
  const tone = value >= 70 ? "bg-good" : value >= 40 ? "bg-warning" : "bg-serious";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-muted/20">
        <div className={"h-full rounded-full " + tone} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
      </div>
      <span className="tnum text-xs text-ink-2">{pct(value, 0)}</span>
    </div>
  );
}
