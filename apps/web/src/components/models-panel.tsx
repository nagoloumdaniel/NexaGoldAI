"use client";

import { getModels } from "@/lib/api";
import { usePolling } from "./use-polling";

const fmt = (n?: number | null) =>
  n == null ? "—" : n.toLocaleString("fr-FR", { maximumFractionDigits: 2 });

export default function ModelsPanel() {
  const { data } = usePolling(getModels, 30000);
  const versions = data?.versions ?? [];

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <h3 className="mb-1 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        Modèles &amp; apprentissage
      </h3>
      <p className="mb-4 text-xs text-zinc-400">
        À chaque réentraînement, plusieurs configurations s&apos;affrontent ; la
        meilleure devient le champion actif.
      </p>
      {versions.length === 0 ? (
        <p className="text-sm text-zinc-400">
          Aucun modèle entraîné — lancez{" "}
          <code className="text-amber-600 dark:text-amber-400">
            POST /learning/retrain
          </code>
          .
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-400">
              <tr>
                <th className="pb-2 font-medium">Version</th>
                <th className="pb-2 font-medium">Horizon</th>
                <th className="pb-2 font-medium">Seuil</th>
                <th className="pb-2 font-medium">Sharpe</th>
                <th className="pb-2 font-medium">Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {versions
                .slice()
                .reverse()
                .map((v) => {
                  const isChampion = v.id === data?.champion;
                  return (
                    <tr
                      key={v.id}
                      className="border-t border-zinc-100 dark:border-zinc-800"
                    >
                      <td className="py-2 text-zinc-700 dark:text-zinc-300">
                        {isChampion ? (
                          <span className="mr-2 rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-600 dark:text-amber-400">
                            champion
                          </span>
                        ) : null}
                        {v.id}
                      </td>
                      <td className="py-2 text-zinc-500 dark:text-zinc-400">
                        {v.config.horizon}
                      </td>
                      <td className="py-2 text-zinc-500 dark:text-zinc-400">
                        {v.config.threshold}
                      </td>
                      <td className="py-2 text-zinc-500 dark:text-zinc-400">
                        {fmt(v.metrics.sharpe)}
                      </td>
                      <td className="py-2 text-zinc-500 dark:text-zinc-400">
                        {fmt(v.metrics.accuracy * 100)} %
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
