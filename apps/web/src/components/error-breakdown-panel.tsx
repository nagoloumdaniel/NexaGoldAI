"use client";

import { useCallback } from "react";
import { getAnalysisStats, getTradeResults } from "@/lib/api";
import { num, ratioPct, signed } from "@/lib/format";
import { classificationLabel, errorCategoryLabel } from "@/lib/labels";
import { usePolling } from "./use-polling";
import { Empty, SectionCard } from "./ui/card";

function Bar({
  label,
  count,
  total,
  tone,
}: {
  label: string;
  count: number;
  total: number;
  tone: string;
}) {
  const share = total > 0 ? count / total : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="truncate text-muted">{label}</span>
        <span className="tnum shrink-0 text-ink">
          {count} ({ratioPct(share)})
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div
          className={`h-full ${tone}`}
          style={{ width: `${share * 100}%` }}
        />
      </div>
    </div>
  );
}

const CLASSIFICATION_TONE: Record<string, string> = {
  GOOD_DECISION_GOOD_RESULT: "bg-up",
  GOOD_DECISION_BAD_RESULT: "bg-warn",
  BAD_DECISION_GOOD_RESULT: "bg-ai",
  BAD_DECISION_BAD_RESULT: "bg-down",
  INCONCLUSIVE: "bg-line",
};

export default function ErrorBreakdownPanel({ limit = 200 }: { limit?: number }) {
  const resultsFetcher = useCallback(() => getTradeResults(limit), [limit]);
  const { data: results, error } = usePolling(resultsFetcher, 30000);
  const { data: stats } = usePolling(getAnalysisStats, 30000);

  const rows = results ?? [];
  const total = rows.length;
  const byClassification = new Map<string, number>();
  const byCategory = new Map<string, number>();
  for (const row of rows) {
    const cls = row.classification ?? "INCONCLUSIVE";
    byClassification.set(cls, (byClassification.get(cls) ?? 0) + 1);
    const cat = row.error_category ?? "UNKNOWN";
    if (cat !== "NONE") {
      byCategory.set(cat, (byCategory.get(cat) ?? 0) + 1);
    }
  }
  const classifications = [...byClassification.entries()].sort(
    (a, b) => b[1] - a[1],
  );
  const categories = [...byCategory.entries()].sort((a, b) => b[1] - a[1]);

  return (
    <SectionCard
      title="Répartition des décisions"
      subtitle="Une perte dans les règles n'est pas une erreur ; un gain chanceux n'est pas un succès"
    >
      {error ? (
        <Empty>API injoignable — répartition indisponible.</Empty>
      ) : total === 0 ? (
        <Empty>
          Aucun trade analysé. Cette vue se remplit à mesure que les positions
          se clôturent.
        </Empty>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <div className="rounded-lg border border-line-soft bg-surface-2/45 px-3 py-2">
              <div className="text-[11px] uppercase text-faint">Trades analysés</div>
              <div className="tnum mt-1 text-lg font-semibold text-ink">
                {stats?.results ?? total}
              </div>
            </div>
            <div className="rounded-lg border border-line-soft bg-surface-2/45 px-3 py-2">
              <div className="text-[11px] uppercase text-faint">Résultat moyen</div>
              <div
                className={`tnum mt-1 text-lg font-semibold ${
                  (stats?.avg_result_r ?? 0) > 0 ? "text-up" : "text-down"
                }`}
              >
                {stats?.avg_result_r == null
                  ? "—"
                  : `${signed(stats.avg_result_r, 2)} R`}
              </div>
            </div>
            <div className="rounded-lg border border-line-soft bg-surface-2/45 px-3 py-2">
              <div className="text-[11px] uppercase text-faint">MFE moyen</div>
              <div className="tnum mt-1 text-lg font-semibold text-ink">
                {stats?.avg_mfe_r == null ? "—" : `${num(stats.avg_mfe_r, 2)} R`}
              </div>
            </div>
            <div className="rounded-lg border border-line-soft bg-surface-2/45 px-3 py-2">
              <div className="text-[11px] uppercase text-faint">MAE moyen</div>
              <div className="tnum mt-1 text-lg font-semibold text-ink">
                {stats?.avg_mae_r == null ? "—" : `${num(stats.avg_mae_r, 2)} R`}
              </div>
            </div>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <div className="space-y-3">
              <p className="text-[11px] uppercase text-faint">
                Qualité des décisions
              </p>
              {classifications.map(([key, count]) => (
                <Bar
                  key={key}
                  label={classificationLabel(key)}
                  count={count}
                  total={total}
                  tone={CLASSIFICATION_TONE[key] ?? "bg-line"}
                />
              ))}
            </div>
            <div className="space-y-3">
              <p className="text-[11px] uppercase text-faint">Causes identifiées</p>
              {categories.length === 0 ? (
                <Empty>Aucune cause d&apos;erreur relevée.</Empty>
              ) : (
                categories.map(([key, count]) => (
                  <Bar
                    key={key}
                    label={errorCategoryLabel(key)}
                    count={count}
                    total={total}
                    tone="bg-gold"
                  />
                ))
              )}
            </div>
          </div>
        </>
      )}
    </SectionCard>
  );
}
