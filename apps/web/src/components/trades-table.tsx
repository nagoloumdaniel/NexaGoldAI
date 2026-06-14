"use client";

import { getTrades } from "@/lib/api";
import { usePolling } from "./use-polling";

const fmt = (n?: number | null) =>
  n == null ? "—" : n.toLocaleString("fr-FR", { maximumFractionDigits: 3 });

export default function TradesTable() {
  const { data } = usePolling(() => getTrades(15), 15000);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <h3 className="mb-4 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        Historique des trades
      </h3>
      {!data || data.length === 0 ? (
        <p className="text-sm text-zinc-400">
          Aucun trade — le kill switch (TRADING_ENABLED) est actif.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-400">
              <tr>
                <th className="pb-2 font-medium">Ouvert</th>
                <th className="pb-2 font-medium">Sens</th>
                <th className="pb-2 font-medium">Taille</th>
                <th className="pb-2 font-medium">Entrée</th>
                <th className="pb-2 font-medium">P&L</th>
                <th className="pb-2 font-medium">Statut</th>
              </tr>
            </thead>
            <tbody>
              {data.map((t) => (
                <tr
                  key={t.id}
                  className="border-t border-zinc-100 dark:border-zinc-800"
                >
                  <td className="py-2 text-zinc-500 dark:text-zinc-400">
                    {new Date(t.openedAt).toLocaleString("fr-FR")}
                  </td>
                  <td className="py-2 text-zinc-700 dark:text-zinc-300">
                    {t.side}
                  </td>
                  <td className="py-2 text-zinc-700 dark:text-zinc-300">
                    {fmt(t.units)}
                  </td>
                  <td className="py-2 text-zinc-700 dark:text-zinc-300">
                    {fmt(t.entryPrice)}
                  </td>
                  <td
                    className={
                      t.pnl == null
                        ? "py-2 text-zinc-400"
                        : t.pnl >= 0
                          ? "py-2 text-green-600 dark:text-green-400"
                          : "py-2 text-red-600 dark:text-red-400"
                    }
                  >
                    {fmt(t.pnl)}
                  </td>
                  <td className="py-2 text-zinc-500 dark:text-zinc-400">
                    {t.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
