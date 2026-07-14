"use client";

import { useMemo, useState, type ReactNode } from "react";

type SortDirection = "asc" | "desc";
const PAGE_SIZES = [5, 10, 25, 50];

export interface DataTableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  value: (row: T) => string | number | null | undefined;
  sortValue?: (row: T) => string | number | null | undefined;
  pdfValue?: (row: T) => string | number | null | undefined;
  className?: string;
}

function printable(value: string | number | null | undefined) {
  if (value == null || value === "") return "-";
  return String(value);
}

function compareValues(a: string | number | null | undefined, b: string | number | null | undefined) {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return printable(a).localeCompare(printable(b), "fr", {
    numeric: true,
    sensitivity: "base",
  });
}

function sortLabel(direction: SortDirection | undefined) {
  if (direction === "asc") return "Asc";
  if (direction === "desc") return "Desc";
  return "Trier";
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function exportPdf<T>(title: string, columns: DataTableColumn<T>[], rows: T[]) {
  const htmlRows = rows
    .map(
      (row) =>
        `<tr>${columns
          .map((column) =>
            `<td>${escapeHtml(printable((column.pdfValue ?? column.value)(row)))}</td>`,
          )
          .join("")}</tr>`,
    )
    .join("");
  const html = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(title)}</title>
  <style>
    body { font-family: Arial, sans-serif; color: #111827; margin: 24px; }
    h1 { font-size: 18px; margin: 0 0 6px; }
    p { margin: 0 0 16px; color: #4b5563; font-size: 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 10px; }
    th, td { border: 1px solid #d1d5db; padding: 6px; text-align: left; vertical-align: top; }
    th { background: #f3f4f6; font-weight: 700; }
    tr:nth-child(even) td { background: #fafafa; }
  </style>
</head>
<body>
  <h1>${escapeHtml(title)}</h1>
  <p>${rows.length} ligne(s) exportée(s) - ${new Date().toLocaleString("fr-FR")}</p>
  <table>
    <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.header)}</th>`).join("")}</tr></thead>
    <tbody>${htmlRows}</tbody>
  </table>
  <script>window.addEventListener("load", () => { window.print(); });</script>
</body>
</html>`;
  const win = window.open("", "_blank", "width=1200,height=800");
  if (!win) return;
  win.document.write(html);
  win.document.close();
}

export function DataTable<T>({
  title,
  rows,
  columns,
  initialPageSize = 5,
  searchPlaceholder = "Filtrer...",
}: {
  title: string;
  rows: T[];
  columns: DataTableColumn<T>[];
  initialPageSize?: number;
  searchPlaceholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: string; direction: SortDirection } | null>(
    null,
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const base = needle
      ? rows.filter((row) =>
          columns.some((column) =>
            printable(column.value(row)).toLowerCase().includes(needle),
          ),
        )
      : rows;
    if (!sort) return base;
    const column = columns.find((item) => item.key === sort.key);
    if (!column) return base;
    const sorted = [...base].sort((a, b) =>
      compareValues(
        (column.sortValue ?? column.value)(a),
        (column.sortValue ?? column.value)(b),
      ),
    );
    return sort.direction === "asc" ? sorted : sorted.reverse();
  }, [columns, query, rows, sort]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const visible = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);
  const hasFilter = query.trim().length > 0;

  function toggleSort(key: string) {
    setPage(1);
    setSort((current) => {
      if (current?.key !== key) return { key, direction: "asc" };
      return { key, direction: current.direction === "asc" ? "desc" : "asc" };
    });
  }

  return (
    <>
      <div className="border-b border-line-soft bg-surface/40 p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center">
            <label className="sr-only" htmlFor={`${title}-filter`}>
              Filtrer le tableau
            </label>
            <input
              id={`${title}-filter`}
              type="search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(1);
              }}
              placeholder={searchPlaceholder}
              className="h-9 w-full max-w-md rounded-md border border-line bg-surface-2 px-3 text-sm text-ink outline-none transition-colors placeholder:text-faint focus:border-gold"
            />
            {hasFilter ? (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setPage(1);
                }}
                className="h-9 rounded-md border border-line px-3 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink"
              >
                Effacer
              </button>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs font-medium text-faint" htmlFor={`${title}-size`}>
              Lignes
            </label>
            <select
              id={`${title}-size`}
              value={pageSize}
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}
              className="h-9 rounded-md border border-line bg-surface-2 px-2 text-sm text-muted outline-none focus:border-gold"
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => exportPdf(title, columns, filtered)}
              disabled={filtered.length === 0}
              className="h-9 rounded-md bg-gold/10 px-3 text-xs font-medium text-gold ring-1 ring-inset ring-gold/20 transition-colors hover:bg-gold/15 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Export PDF
            </button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-faint">
          <span className="tnum rounded-md bg-surface-2 px-2 py-1 ring-1 ring-inset ring-line-soft">
            {filtered.length} / {rows.length} ligne(s)
          </span>
          {sort ? (
            <span className="rounded-md bg-surface-2 px-2 py-1 ring-1 ring-inset ring-line-soft">
              Tri: {columns.find((column) => column.key === sort.key)?.header}{" "}
              {sortLabel(sort.direction).toLowerCase()}
            </span>
          ) : null}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line-soft bg-surface-2/40 text-left text-[11px] uppercase text-faint">
              {columns.map((column) => (
                <th key={column.key} className="px-5 py-2.5 font-medium" scope="col">
                  <button
                    type="button"
                    onClick={() => toggleSort(column.key)}
                    className="inline-flex h-7 max-w-full items-center gap-2 text-left uppercase text-faint transition-colors hover:text-muted"
                  >
                    <span className="truncate">{column.header}</span>
                    <span className="rounded border border-line-soft px-1.5 py-0.5 text-[9px] normal-case text-faint">
                      {sortLabel(sort?.key === column.key ? sort.direction : undefined)}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                className="border-b border-line-soft last:border-0 hover:bg-surface-2/40"
              >
                {columns.map((column) => (
                  <td key={column.key} className={column.className ?? "px-5 py-3"}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col gap-3 border-t border-line-soft px-4 py-3 text-sm text-muted sm:flex-row sm:items-center sm:justify-between">
        <span className="tnum">
          {filtered.length === 0
            ? "0 ligne"
            : `${(safePage - 1) * pageSize + 1}-${Math.min(
                safePage * pageSize,
                filtered.length,
              )} / ${filtered.length}`}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            disabled={safePage <= 1}
            className="h-8 rounded-md border border-line px-3 text-xs transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Précédent
          </button>
          <span className="tnum rounded-md bg-surface-2 px-2 py-1 text-xs ring-1 ring-inset ring-line-soft">
            Page {safePage} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            disabled={safePage >= totalPages}
            className="h-8 rounded-md border border-line px-3 text-xs transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Suivant
          </button>
        </div>
      </div>
    </>
  );
}
