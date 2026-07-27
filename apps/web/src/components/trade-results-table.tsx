"use client";

import { useCallback, useMemo } from "react";
import { getTradeResults, type TradeResultRow } from "@/lib/api";
import { dateTime, num, signed } from "@/lib/format";
import {
  actionLabel,
  classificationLabel,
  errorCategoryLabel,
  exitSourceLabel,
} from "@/lib/labels";
import { usePolling } from "./use-polling";
import { Empty, SectionCard } from "./ui/card";
import { DataTable, type DataTableColumn } from "./ui/data-table";

const CLASSIFICATION_STYLE: Record<string, string> = {
  GOOD_DECISION_GOOD_RESULT: "bg-up/10 text-up ring-up/20",
  GOOD_DECISION_BAD_RESULT: "bg-warn/10 text-warn ring-warn/20",
  BAD_DECISION_GOOD_RESULT: "bg-ai/10 text-ai ring-ai/20",
  BAD_DECISION_BAD_RESULT: "bg-down/10 text-down ring-down/20",
  INCONCLUSIVE: "bg-muted/10 text-muted ring-muted/20",
};

function duration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${num(seconds / 3600, 1)} h`;
}

const COLUMNS: DataTableColumn<TradeResultRow>[] = [
  {
    key: "exit_time",
    header: "Clôture",
    render: (row) => <span className="tnum">{dateTime(row.exit_time)}</span>,
    value: (row) => row.exit_time,
  },
  {
    key: "side",
    header: "Sens",
    render: (row) => <span>{actionLabel(row.side)}</span>,
    value: (row) => actionLabel(row.side),
  },
  {
    key: "result_r",
    header: "Résultat (R)",
    render: (row) => (
      <span
        className={`tnum font-semibold ${
          (row.result_r ?? 0) > 0 ? "text-up" : "text-down"
        }`}
      >
        {row.result_r == null ? "—" : signed(row.result_r, 2)}
      </span>
    ),
    value: (row) => row.result_r ?? 0,
  },
  {
    key: "mfe_r",
    header: "MFE (R)",
    render: (row) => (
      <span className="tnum text-muted">
        {row.mfe_r == null ? "—" : num(row.mfe_r, 2)}
      </span>
    ),
    value: (row) => row.mfe_r ?? 0,
  },
  {
    key: "mae_r",
    header: "MAE (R)",
    render: (row) => (
      <span className="tnum text-muted">
        {row.mae_r == null ? "—" : num(row.mae_r, 2)}
      </span>
    ),
    value: (row) => row.mae_r ?? 0,
  },
  {
    key: "exit_source",
    header: "Sortie",
    render: (row) => <span>{exitSourceLabel(row.exit_source)}</span>,
    value: (row) => exitSourceLabel(row.exit_source),
  },
  {
    key: "holding",
    header: "Durée",
    render: (row) => (
      <span className="tnum text-muted">{duration(row.holding_seconds)}</span>
    ),
    value: (row) => row.holding_seconds,
  },
  {
    key: "classification",
    header: "Décision",
    render: (row) => (
      <span
        className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${
          CLASSIFICATION_STYLE[row.classification ?? ""] ??
          CLASSIFICATION_STYLE.INCONCLUSIVE
        }`}
      >
        {classificationLabel(row.classification)}
      </span>
    ),
    value: (row) => classificationLabel(row.classification),
    className: "min-w-[14rem]",
  },
  {
    key: "error_category",
    header: "Cause",
    render: (row) => (
      <span className="text-muted">{errorCategoryLabel(row.error_category)}</span>
    ),
    value: (row) => errorCategoryLabel(row.error_category),
  },
];

export default function TradeResultsTable({ limit = 50 }: { limit?: number }) {
  const fetcher = useCallback(() => getTradeResults(limit), [limit]);
  const { data, error } = usePolling(fetcher, 30000);
  const columns = useMemo(() => COLUMNS, []);

  return (
    <SectionCard
      title="Analyse post-trade"
      subtitle="Chaque clôture : résultat, excursions et qualité de la décision"
      bodyClassName="p-0"
    >
      {error ? (
        <div className="p-5">
          <Empty>API injoignable — analyses indisponibles.</Empty>
        </div>
      ) : !data || data.length === 0 ? (
        <div className="p-5">
          <Empty>
            Aucun trade analysé pour l&apos;instant. L&apos;analyse est produite
            à chaque clôture de position.
          </Empty>
        </div>
      ) : (
        <DataTable
          title="Analyse post-trade"
          rows={data}
          columns={columns}
          initialPageSize={10}
          searchPlaceholder="Filtrer les analyses..."
        />
      )}
    </SectionCard>
  );
}
