"use client";

import { useMemo, useState, type ReactNode } from "react";

type SortDirection = "asc" | "desc";

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
  <p>${rows.length} ligne(s) exportee(s) - ${new Date().toLocaleString("fr-FR")}</p>
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
  initialPageSize = 10,
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

  function toggleSort(key: string) {
    setPage(1);
    setSort((current) => {
      if (current?.key !== key) return { key, direction: "asc" };
      return { key, direction: current.direction === "asc" ? "desc" : "asc" };
    });
  }

  return (
    <>
      <div className="flex flex-col gap-3 border-b border-line-soft p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder={searchPlaceholder}
            className="h-9 w-full max-w-sm rounded-md border border-line bg-surface-2 px-3 text-sm text-ink outline-none transition-colors placeholder:text-faint focus:border-gold"
          />
          <select
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(1);
            }}
            className="h-9 rounded-md border border-line bg-surface-2 px-2 text-sm text-muted outline-none focus:border-gold"
          >
            {[5, 10, 25, 50].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={() => exportPdf(title, columns, filtered)}
          disabled={filtered.length === 0}
          className="h-9 rounded-md bg-gold/10 px-3 text-xs font-medium text-gold ring-1 ring-inset ring-gold/20 transition-colors hover:bg-gold/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Export PDF
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line-soft text-left text-[11px] uppercase text-faint">
              {columns.map((column) => (
                <th key={column.key} className="px-5 py-2.5 font-medium">
                  <button
                    type="button"
                    onClick={() => toggleSort(column.key)}
                    className="inline-flex h-7 items-center gap-1 text-left uppercase text-faint hover:text-muted"
                  >
                    {column.header}
                    <span className="text-[10px]">
                      {sort?.key === column.key
                        ? sort.direction === "asc"
                          ? "A-Z"
                          : "Z-A"
                        : "-"}
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
            Precedent
          </button>
          <span className="tnum text-xs">
            {safePage} / {totalPages}
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
