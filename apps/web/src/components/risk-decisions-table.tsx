"use client";

import { useCallback, useMemo } from "react";
import { getRiskDecisions, type RiskDecisionRow } from "@/lib/api";
import { dateTime, num } from "@/lib/format";
import { humanizeText } from "@/lib/labels";
import { usePolling } from "./use-polling";
import { Empty, SectionCard } from "./ui/card";
import { DataTable, type DataTableColumn } from "./ui/data-table";

const COLUMNS: DataTableColumn<RiskDecisionRow>[] = [
  {
    key: "time",
    header: "Horodatage",
    render: (row) => <span className="tnum">{dateTime(row.time)}</span>,
    value: (row) => row.time,
  },
  {
    key: "approved",
    header: "Verdict",
    render: (row) => (
      <span
        className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
          row.approved
            ? "bg-up/10 text-up ring-up/20"
            : "bg-warn/10 text-warn ring-warn/20"
        }`}
      >
        {row.approved ? "Approuvé" : "Bloqué"}
      </span>
    ),
    value: (row) => (row.approved ? "Approuvé" : "Bloqué"),
  },
  {
    key: "reason",
    header: "Motif",
    render: (row) => (
      <span className="text-muted">{humanizeText(row.reason)}</span>
    ),
    value: (row) => humanizeText(row.reason),
    className: "min-w-[18rem]",
  },
  {
    key: "units",
    header: "Taille",
    render: (row) => (
      <span className="tnum">{row.units ? num(row.units, 2) : "—"}</span>
    ),
    value: (row) => row.units ?? 0,
  },
];

export default function RiskDecisionsTable({ limit = 50 }: { limit?: number }) {
  const fetcher = useCallback(() => getRiskDecisions(limit), [limit]);
  const { data, error } = usePolling(fetcher, 20000);
  const columns = useMemo(() => COLUMNS, []);
  const blocked = data?.filter((row) => !row.approved).length ?? 0;

  return (
    <SectionCard
      title="Journal du moteur de risque"
      subtitle="Chaque signal soumis au risque, approuvé ou bloqué"
      bodyClassName="p-0"
      action={
        data && data.length > 0 ? (
          <span className="tnum rounded-md bg-surface-2 px-2 py-1 text-xs text-muted ring-1 ring-inset ring-line-soft">
            {blocked} bloqué(s) / {data.length}
          </span>
        ) : undefined
      }
    >
      {error ? (
        <div className="p-5">
          <Empty>API injoignable — journal indisponible.</Empty>
        </div>
      ) : !data || data.length === 0 ? (
        <div className="p-5">
          <Empty>
            Aucune décision de risque enregistrée. Le journal se remplit dès
            qu&apos;un signal atteint le moteur de risque.
          </Empty>
        </div>
      ) : (
        <DataTable
          title="Journal du moteur de risque"
          rows={data}
          columns={columns}
          initialPageSize={10}
          searchPlaceholder="Filtrer les décisions de risque..."
        />
      )}
    </SectionCard>
  );
}
