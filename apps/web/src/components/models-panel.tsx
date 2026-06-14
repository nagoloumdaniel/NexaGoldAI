"use client";

import { getModels } from "@/lib/api";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { num, ratioPct } from "@/lib/format";

export default function ModelsPanel() {
  const { data } = usePolling(getModels, 30000);
  const versions = data?.versions ?? [];

  return (
    <SectionCard
      title="Modèles & apprentissage"
      subtitle="À chaque réentraînement, plusieurs configurations s'affrontent ; la meilleure devient le champion actif"
      bodyClassName="p-0"
      action={
        data?.granularity ? (
          <span className="rounded-md bg-surface-2 px-2 py-1 text-[11px] font-medium text-muted">
            {data.granularity}
          </span>
        ) : null
      }
    >
      {versions.length === 0 ? (
        <div className="p-5">
          <Empty>
            Aucun modèle entraîné — lancez{" "}
            <code className="rounded bg-surface-2 px-1.5 py-0.5 text-gold">
              POST /learning/retrain
            </code>
            .
          </Empty>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-[11px] uppercase tracking-wider text-faint">
                <th className="px-5 py-2.5 font-medium">Version</th>
                <th className="px-5 py-2.5 font-medium">Horizon</th>
                <th className="px-5 py-2.5 font-medium">Seuil</th>
                <th className="px-5 py-2.5 font-medium">Sharpe</th>
                <th className="px-5 py-2.5 font-medium">Accuracy</th>
                <th className="px-5 py-2.5 font-medium">Échantillons</th>
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
                      className={`border-b border-line-soft last:border-0 hover:bg-surface-2/40 ${
                        isChampion ? "bg-gold/4" : ""
                      }`}
                    >
                      <td className="px-5 py-3 text-ink">
                        {isChampion ? (
                          <span className="mr-2 rounded-md bg-gold/10 px-2 py-0.5 text-[11px] font-semibold text-gold ring-1 ring-inset ring-gold/20">
                            champion
                          </span>
                        ) : null}
                        <span className="tnum">{v.id}</span>
                      </td>
                      <td className="tnum px-5 py-3 text-muted">
                        {v.config.horizon}
                      </td>
                      <td className="tnum px-5 py-3 text-muted">
                        {v.config.threshold}
                      </td>
                      <td className="tnum px-5 py-3 text-muted">
                        {num(v.metrics.sharpe)}
                      </td>
                      <td className="tnum px-5 py-3 text-muted">
                        {ratioPct(v.metrics.accuracy)}
                      </td>
                      <td className="tnum px-5 py-3 text-muted">
                        {v.metrics.samples}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
