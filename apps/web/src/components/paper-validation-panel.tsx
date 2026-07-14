"use client";

import { getPaperValidation } from "@/lib/api";
import { num, ratioPct } from "@/lib/format";
import { usePolling } from "./use-polling";
import { SectionCard } from "./ui/card";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 py-3">
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

  return (
    <SectionCard
      title="Validation paper"
      subtitle="Expected-return H1 · suivi prospectif"
      action={
        <span className="tnum text-xs text-muted">
          {closed} / {target} clôturés
        </span>
      }
    >
      <div className="h-2 overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full bg-gold transition-[width] duration-500"
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-6 border-b border-line-soft sm:grid-cols-4">
        <Metric label="P&L clôturé" value={num(data?.total_pnl ?? 0, 2)} />
        <Metric label="Win rate" value={ratioPct(data?.win_rate ?? 0)} />
        <Metric
          label="Profit factor"
          value={data?.profit_factor == null ? "-" : num(data.profit_factor, 2)}
        />
        <Metric label="Positions ouvertes" value={String(data?.open_trades ?? 0)} />
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
        <span className={data?.eligible_for_review ? "text-up" : "text-muted"}>
          {data?.eligible_for_review ? "Revue quantitative éligible" : "Collecte en cours"}
        </span>
        <span className="text-muted">Promotion live automatique désactivée</span>
      </div>
    </SectionCard>
  );
}
