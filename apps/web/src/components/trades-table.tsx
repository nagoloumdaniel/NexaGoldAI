"use client";

import { useMemo } from "react";
import { getTrades } from "@/lib/api";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { ActionBadge, StatusBadge } from "./ui/badge";
import { num, signed, dateTime, tone } from "@/lib/format";

export default function TradesTable({
  title = "Historique des trades",
  subtitle,
  limit = 15,
  onlyOpen = false,
}: {
  title?: string;
  subtitle?: string;
  limit?: number;
  onlyOpen?: boolean;
}) {
  const fetcher = useMemo(() => () => getTrades(limit), [limit]);
  const { data } = usePolling(fetcher, 15000);
  const rows = (data ?? []).filter((t) => (onlyOpen ? t.status === "OPEN" : true));

  return (
    <SectionCard title={title} subtitle={subtitle} bodyClassName="p-0">
      {rows.length === 0 ? (
        <div className="p-5">
          <Empty>
            {onlyOpen
              ? "Aucune position ouverte."
              : "Aucun trade — le kill switch (TRADING_ENABLED) est actif."}
          </Empty>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-[11px] uppercase tracking-wider text-faint">
                <th className="px-5 py-2.5 font-medium">Ouvert</th>
                <th className="px-5 py-2.5 font-medium">Sens</th>
                <th className="px-5 py-2.5 font-medium">Taille</th>
                <th className="px-5 py-2.5 font-medium">Entrée</th>
                <th className="px-5 py-2.5 font-medium">Sortie</th>
                <th className="px-5 py-2.5 font-medium">P&L</th>
                <th className="px-5 py-2.5 font-medium">Statut</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr
                  key={t.id}
                  className="border-b border-line-soft last:border-0 hover:bg-surface-2/40"
                >
                  <td className="tnum px-5 py-3 text-muted">
                    {dateTime(t.openedAt)}
                  </td>
                  <td className="px-5 py-3">
                    <ActionBadge action={t.side} />
                  </td>
                  <td className="tnum px-5 py-3 text-ink">{num(t.units, 3)}</td>
                  <td className="tnum px-5 py-3 text-ink">
                    {num(t.entryPrice)}
                  </td>
                  <td className="tnum px-5 py-3 text-muted">
                    {t.exitPrice == null ? "—" : num(t.exitPrice)}
                  </td>
                  <td
                    className={`tnum px-5 py-3 ${
                      t.pnl == null
                        ? "text-faint"
                        : tone(t.pnl) === "up"
                          ? "text-up"
                          : tone(t.pnl) === "down"
                            ? "text-down"
                            : "text-ink"
                    }`}
                  >
                    {t.pnl == null ? "—" : signed(t.pnl)}
                  </td>
                  <td className="px-5 py-3">
                    <StatusBadge status={t.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
