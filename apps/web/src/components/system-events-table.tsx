"use client";

import { useCallback, useMemo } from "react";
import { getSystemEvents, type SystemEventRow } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { eventTypeLabel, humanizeText, severityLabel } from "@/lib/labels";
import { usePolling } from "./use-polling";
import { Empty, SectionCard } from "./ui/card";
import { DataTable, type DataTableColumn } from "./ui/data-table";

const SEVERITY_STYLE: Record<string, string> = {
  CRITICAL: "bg-down/10 text-down ring-down/20",
  WARNING: "bg-warn/10 text-warn ring-warn/20",
  INFO: "bg-muted/10 text-muted ring-muted/20",
};

const COLUMNS: DataTableColumn<SystemEventRow>[] = [
  {
    key: "time",
    header: "Horodatage",
    render: (row) => <span className="tnum">{dateTime(row.time)}</span>,
    value: (row) => row.time,
  },
  {
    key: "severity",
    header: "Gravité",
    render: (row) => (
      <span
        className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
          SEVERITY_STYLE[row.severity] ?? SEVERITY_STYLE.INFO
        }`}
      >
        {severityLabel(row.severity)}
      </span>
    ),
    value: (row) => severityLabel(row.severity),
  },
  {
    key: "event_type",
    header: "Événement",
    render: (row) => <span>{eventTypeLabel(row.event_type)}</span>,
    value: (row) => eventTypeLabel(row.event_type),
  },
  {
    key: "message",
    header: "Détail",
    render: (row) => (
      <span className="text-muted">{humanizeText(row.message)}</span>
    ),
    value: (row) => humanizeText(row.message),
    className: "min-w-[20rem]",
  },
];

export default function SystemEventsTable({ limit = 50 }: { limit?: number }) {
  const fetcher = useCallback(() => getSystemEvents(limit), [limit]);
  const { data, error } = usePolling(fetcher, 30000);
  const columns = useMemo(() => COLUMNS, []);

  return (
    <SectionCard
      title="Événements système"
      subtitle="Verrouillages du kill switch et anomalies durables"
      bodyClassName="p-0"
    >
      {error ? (
        <div className="p-5">
          <Empty>API injoignable — événements indisponibles.</Empty>
        </div>
      ) : !data || data.length === 0 ? (
        <div className="p-5">
          <Empty>Aucun événement système enregistré.</Empty>
        </div>
      ) : (
        <DataTable
          title="Événements système"
          rows={data}
          columns={columns}
          initialPageSize={10}
          searchPlaceholder="Filtrer les événements..."
        />
      )}
    </SectionCard>
  );
}
