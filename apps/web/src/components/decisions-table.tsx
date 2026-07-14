"use client";

import { useMemo } from "react";
import { getDecisions } from "@/lib/api";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { ActionBadge, Confidence } from "./ui/badge";
import { ratioPct, time } from "@/lib/format";

function featureNumber(
  features: Record<string, unknown> | null | undefined,
  key: string,
) {
  const value = features?.[key];
  return typeof value === "number" ? value : null;
}

export default function DecisionsTable({
  limit = 15,
  showReason = true,
}: {
  limit?: number;
  showReason?: boolean;
}) {
  const fetcher = useStableDecisions(limit);
  const { data } = usePolling(fetcher, 10000);
  const showsExpectedReturn = Boolean(
    data?.some((decision) => decision.features?.signal_kind === "expected_return"),
  );

  return (
    <SectionCard
      title="Décisions IA récentes"
      subtitle="Chaque évaluation du modèle est journalisée, exécutée ou non"
      bodyClassName="p-0"
    >
      {!data || data.length === 0 ? (
        <div className="p-5">
          <Empty>Aucune décision pour l&apos;instant.</Empty>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-[11px] uppercase tracking-wider text-faint">
                <th className="px-5 py-2.5 font-medium">Heure</th>
                <th className="px-5 py-2.5 font-medium">Action</th>
                <th className="px-5 py-2.5 font-medium">Confiance</th>
                {showsExpectedReturn ? (
                  <>
                    <th className="px-5 py-2.5 font-medium">Rendement attendu</th>
                    <th className="px-5 py-2.5 font-medium">Seuil</th>
                    <th className="px-5 py-2.5 font-medium">Exposition</th>
                  </>
                ) : null}
                {showReason ? (
                  <th className="px-5 py-2.5 font-medium">Raison</th>
                ) : null}
                <th className="px-5 py-2.5 font-medium">Exécutée</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d, i) => (
                <tr
                  key={i}
                  className="border-b border-line-soft last:border-0 hover:bg-surface-2/40"
                >
                  <td className="tnum px-5 py-3 text-muted">{time(d.time)}</td>
                  <td className="px-5 py-3">
                    <ActionBadge action={d.action} />
                  </td>
                  <td className="px-5 py-3">
                    <Confidence value={d.confidence} />
                  </td>
                  {showsExpectedReturn ? (
                    <>
                      <td className="tnum px-5 py-3 text-muted">
                        {ratioPct(featureNumber(d.features, "expected_return"), 3)}
                      </td>
                      <td className="tnum px-5 py-3 text-muted">
                        {ratioPct(
                          featureNumber(d.features, "expected_return_threshold"),
                          3,
                        )}
                      </td>
                      <td className="tnum px-5 py-3 text-muted">
                        {ratioPct(featureNumber(d.features, "position_size"), 1)}
                      </td>
                    </>
                  ) : null}
                  {showReason ? (
                    <td className="max-w-xs truncate px-5 py-3 text-muted">
                      {d.reason}
                    </td>
                  ) : null}
                  <td className="px-5 py-3">
                    {d.executed ? (
                      <span className="text-up">Oui</span>
                    ) : (
                      <span className="text-faint">Non</span>
                    )}
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

/** Stabilise la fonction de fetch pour usePolling (référence constante). */
function useStableDecisions(limit: number) {
  return useMemo(() => () => getDecisions(limit), [limit]);
}
