"use client";

import { getDecisions } from "@/lib/api";
import { usePolling } from "./use-polling";

const ACTION_STYLE: Record<string, string> = {
  BUY: "bg-green-500/10 text-green-600 dark:text-green-400",
  SELL: "bg-red-500/10 text-red-600 dark:text-red-400",
  HOLD: "bg-zinc-500/10 text-zinc-500 dark:text-zinc-400",
};

export default function DecisionsTable() {
  const { data } = usePolling(() => getDecisions(15), 10000);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <h3 className="mb-4 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        Décisions IA récentes
      </h3>
      {!data || data.length === 0 ? (
        <p className="text-sm text-zinc-400">Aucune décision pour l&apos;instant.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-400">
              <tr>
                <th className="pb-2 font-medium">Heure</th>
                <th className="pb-2 font-medium">Action</th>
                <th className="pb-2 font-medium">Confiance</th>
                <th className="pb-2 font-medium">Raison</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d, i) => (
                <tr
                  key={i}
                  className="border-t border-zinc-100 dark:border-zinc-800"
                >
                  <td className="py-2 text-zinc-500 dark:text-zinc-400">
                    {new Date(d.time).toLocaleTimeString("fr-FR")}
                  </td>
                  <td className="py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        ACTION_STYLE[d.action] ?? ACTION_STYLE.HOLD
                      }`}
                    >
                      {d.action}
                    </span>
                  </td>
                  <td className="py-2 text-zinc-700 dark:text-zinc-300">
                    {(d.confidence * 100).toFixed(0)} %
                  </td>
                  <td className="py-2 text-zinc-500 dark:text-zinc-400">
                    {d.reason}
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
