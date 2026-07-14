"use client";

import { getDecisions } from "@/lib/api";
import { humanizeText, strategyLabel } from "@/lib/labels";
import { dateTime } from "@/lib/format";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { ActionBadge } from "./ui/badge";

const fetcher = () => getDecisions(1);

export default function AiActivity() {
  const { data } = usePolling(fetcher, 10000);
  const last = data?.[0] ?? null;

  return (
    <SectionCard
      title="Dernière analyse IA"
      subtitle={last ? `Stratégie ${strategyLabel(last.strategy)}` : "En attente de décision"}
    >
      {!last ? (
        <Empty>Aucune décision pour l&apos;instant.</Empty>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <ActionBadge action={last.action} />
            <span className="tnum text-xs text-faint">
              {dateTime(last.time)}
            </span>
          </div>

          <div>
            <p className="text-[11px] font-medium uppercase tracking-wider text-faint">
              Confiance
            </p>
            <div className="mt-2 flex items-center gap-3">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full bg-gold"
                  style={{ width: `${Math.round(last.confidence * 100)}%` }}
                />
              </div>
              <span className="tnum text-lg font-semibold text-gold">
                {Math.round(last.confidence * 100)} %
              </span>
            </div>
          </div>

          <div>
            <p className="text-[11px] font-medium uppercase tracking-wider text-faint">
              Raison
            </p>
            <p className="mt-1.5 text-sm text-muted">{humanizeText(last.reason)}</p>
          </div>

          <div className="flex items-center gap-2 border-t border-line-soft pt-3 text-xs">
            <span className="text-faint">Décision</span>
            {last.executed ? (
              <span className="text-up">exécutée</span>
            ) : (
              <span className="text-muted">non exécutée (paper / kill switch)</span>
            )}
          </div>
        </div>
      )}
    </SectionCard>
  );
}
