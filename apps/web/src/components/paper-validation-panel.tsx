"use client";

import { getPaperValidation } from "@/lib/api";
import { strategyLabel } from "@/lib/labels";
import { dateTime, num, ratioPct } from "@/lib/format";
import { usePolling } from "./use-polling";
import { SectionCard } from "./ui/card";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-line-soft bg-surface-2/45 px-3 py-2">
      <div className="text-[11px] uppercase text-faint">{label}</div>
      <div className="tnum mt-1 text-lg font-semibold text-ink">{value}</div>
    </div>
  );
}

export default function PaperValidationPanel() {
  const { data } = usePolling(getPaperValidation, 30000);
  const closed = data?.closed_trades ?? 0;
  const target = data?.target_closed_trades ?? 100;
  const progress = Math.max(0, Math.min(data?.progress ?? 0, 1));
  const remaining = Math.max(target - closed, 0);

  return (
    <SectionCard
      title="Validation paper"
      subtitle="Suivi prospectif avant revue quantitative"
      action={
        <span className="tnum rounded-md bg-surface-2 px-2 py-1 text-xs text-muted ring-1 ring-inset ring-line-soft">
          {closed} / {target} clôturés
        </span>
      }
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="text-muted">
          Stratégie : {strategyLabel(data?.strategy)}
        </span>
        <span className={data?.eligible_for_review ? "text-up" : "text-warn"}>
          {data?.eligible_for_review
            ? "Revue quantitative éligible"
            : `${remaining} clôture(s) restante(s)`}
        </span>
      </div>

      <div className="h-2 overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full bg-gold transition-[width] duration-500"
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Metric label="P&L clôturé" value={num(data?.total_pnl ?? 0, 2)} />
        <Metric label="Win rate" value={ratioPct(data?.win_rate ?? 0)} />
        <Metric
          label="Profit factor"
          value={data?.profit_factor == null ? "-" : num(data.profit_factor, 2)}
        />
        <Metric label="Positions ouvertes" value={String(data?.open_trades ?? 0)} />
        <Metric label="Trades totaux" value={String(data?.total_trades ?? 0)} />
        <Metric label="Gagnants" value={String(data?.wins ?? 0)} />
        <Metric label="Perdants" value={String(data?.losses ?? 0)} />
        <Metric label="Progression" value={ratioPct(progress)} />
      </div>

      <div className="mt-4 grid gap-3 border-t border-line-soft pt-3 text-sm sm:grid-cols-2">
        <div>
          <p className="text-[11px] uppercase text-faint">Début collecte</p>
          <p className="tnum mt-1 text-muted">{dateTime(data?.started_at)}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase text-faint">Dernière clôture</p>
          <p className="tnum mt-1 text-muted">{dateTime(data?.last_closed_at)}</p>
        </div>
      </div>
    </SectionCard>
  );
}
