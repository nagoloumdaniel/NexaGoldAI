"use client";

import { useMemo } from "react";
import { getTrades, type Trade } from "@/lib/api";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { ActionBadge, StatusBadge } from "./ui/badge";
import { num, signed, dateTime, tone } from "@/lib/format";
import { DataTable, type DataTableColumn } from "./ui/data-table";

export default function TradesTable({
  title = "Historique des trades",
  subtitle,
  limit = 50,
  onlyOpen = false,
}: {
  title?: string;
  subtitle?: string;
  limit?: number;
  onlyOpen?: boolean;
}) {
  const fetcher = useMemo(() => () => getTrades(limit), [limit]);
  const { data } = usePolling(fetcher, 15000);
  const rows = useMemo(
    () => (data ?? []).filter((t) => (onlyOpen ? t.status === "OPEN" : true)),
    [data, onlyOpen],
  );
  const columns = useMemo(() => buildColumns(), []);

  return (
    <SectionCard title={title} subtitle={subtitle} bodyClassName="p-0">
      {rows.length === 0 ? (
        <div className="p-5">
          <Empty>
            {onlyOpen
              ? "Aucune position ouverte."
              : "Aucun trade - le kill switch est actif."}
          </Empty>
        </div>
      ) : (
        <DataTable
          title={title}
          rows={rows}
          columns={columns}
          initialPageSize={10}
          searchPlaceholder="Filtrer les trades..."
        />
      )}
    </SectionCard>
  );
}

function buildColumns(): DataTableColumn<Trade>[] {
  return [
    {
      key: "openedAt",
      header: "Ouvert",
      value: (t) => dateTime(t.openedAt),
      sortValue: (t) => new Date(t.openedAt).getTime(),
      render: (t) => <span className="tnum text-muted">{dateTime(t.openedAt)}</span>,
      className: "tnum px-5 py-3 text-muted",
    },
    {
      key: "side",
      header: "Sens",
      value: (t) => t.side,
      render: (t) => <ActionBadge action={t.side} />,
      className: "px-5 py-3",
    },
    {
      key: "units",
      header: "Taille",
      value: (t) => t.units,
      pdfValue: (t) => num(t.units, 3),
      render: (t) => <span className="tnum text-ink">{num(t.units, 3)}</span>,
      className: "tnum px-5 py-3 text-ink",
    },
    {
      key: "entryPrice",
      header: "Entree",
      value: (t) => t.entryPrice,
      pdfValue: (t) => num(t.entryPrice),
      render: (t) => <span className="tnum text-ink">{num(t.entryPrice)}</span>,
      className: "tnum px-5 py-3 text-ink",
    },
    {
      key: "exitPrice",
      header: "Sortie",
      value: (t) => t.exitPrice,
      pdfValue: (t) => num(t.exitPrice),
      render: (t) => (
        <span className="tnum text-muted">
          {t.exitPrice == null ? "-" : num(t.exitPrice)}
        </span>
      ),
      className: "tnum px-5 py-3 text-muted",
    },
    {
      key: "pnl",
      header: "P&L",
      value: (t) => t.pnl,
      pdfValue: (t) => signed(t.pnl),
      render: (t) => (
        <span
          className={`tnum ${
            t.pnl == null
              ? "text-faint"
              : tone(t.pnl) === "up"
                ? "text-up"
                : tone(t.pnl) === "down"
                  ? "text-down"
                  : "text-ink"
          }`}
        >
          {t.pnl == null ? "-" : signed(t.pnl)}
        </span>
      ),
      className: "tnum px-5 py-3",
    },
    {
      key: "status",
      header: "Statut",
      value: (t) => t.status,
      render: (t) => <StatusBadge status={t.status} />,
      className: "px-5 py-3",
    },
    {
      key: "strategy",
      header: "Strategie",
      value: (t) => t.strategy,
      render: (t) => <span className="text-muted">{t.strategy}</span>,
      className: "px-5 py-3",
    },
  ];
}
