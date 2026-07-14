"use client";

import { getStructuredSignal } from "@/lib/api";
import { num, ratioPct } from "@/lib/format";
import { usePolling } from "./use-polling";
import { ActionBadge } from "./ui/badge";
import { Empty, SectionCard } from "./ui/card";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line-soft py-2.5 last:border-0">
      <span className="text-sm text-muted">{label}</span>
      <span className="text-right text-sm text-ink">{value}</span>
    </div>
  );
}

export default function StructuredSignalPanel() {
  const { data } = usePolling(getStructuredSignal, 15000);
  const gateBlocked = data?.regime_gate?.status === "BLOCKED";
  const gateLabel =
    data?.regime_gate?.status === "ALLOWED"
      ? "AUTORISE"
      : gateBlocked
        ? "BLOQUE"
        : "N/A";
  const gateTone =
    data?.regime_gate?.status === "ALLOWED"
      ? "text-up"
      : gateBlocked
        ? "text-down"
        : "text-muted";

  return (
    <SectionCard
      title="Signal structure"
      subtitle="Preview read-only du moteur de decision"
      action={data?.execution_mode ? (
        <span className="rounded-md bg-surface-2 px-2 py-1 text-[11px] font-medium text-muted">
          {data.execution_mode}
        </span>
      ) : null}
    >
      {!data ? (
        <Empty>Signal indisponible.</Empty>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <ActionBadge action={data.direction} />
            <span className="tnum text-xs text-faint">
              {data.timeframe ?? "-"} / {data.model_version ?? "-"}
            </span>
          </div>

          <div className="-my-1">
            <Row
              label="Confiance brute"
              value={ratioPct(data.calibrated_confidence)}
            />
            <Row
              label="Rendement attendu"
              value={ratioPct(data.expected_move, 3)}
            />
            <Row
              label="Espérance après coûts"
              value={ratioPct(data.expected_value_after_costs, 3)}
            />
            <Row
              label="Exposition recommandée"
              value={ratioPct(data.recommended_exposure, 1)}
            />
            <Row label="Incertitude" value={ratioPct(data.uncertainty)} />
            <Row
              label="Qualite donnees"
              value={ratioPct(data.data_quality_score)}
            />
            <Row label="Regime" value={data.market_regime ?? "-"} />
            <Row
              label="Confiance regime"
              value={ratioPct(data.regime_details?.confidence)}
            />
            <Row
              label="Filtre regime"
              value={
                <span className={gateTone}>{gateLabel}</span>
              }
            />
            <Row
              label="Accord modele / regime"
              value={data.regime_gate?.agreement ?? "-"}
            />
            <Row
              label="Momentum 12"
              value={
                data.math_summary?.momentum_12 == null
                  ? "-"
                  : ratioPct(data.math_summary.momentum_12, 2)
              }
            />
            <Row
              label="Volatilite 20"
              value={
                data.math_summary?.realised_volatility_20 == null
                  ? "-"
                  : ratioPct(data.math_summary.realised_volatility_20, 2)
              }
            />
            <Row
              label="Z-score 20"
              value={
                data.math_summary?.zscore_20 == null
                  ? "-"
                  : num(data.math_summary.zscore_20, 2)
              }
            />
            <Row
              label="ATR 14"
              value={
                data.math_summary?.atr_14 == null
                  ? "-"
                  : num(data.math_summary.atr_14, 3)
              }
            />
            <Row
              label="Spread"
              value={data.spread == null ? "-" : num(data.spread, 3)}
            />
            <Row
              label="Entree / SL / TP"
              value={
                data.recommended_entry == null
                  ? "-"
                  : `${num(data.recommended_entry)} / ${num(data.recommended_sl)} / ${num(data.recommended_tp)}`
              }
            />
          </div>

          <div>
            <p className="text-[11px] font-medium uppercase tracking-wider text-faint">
              Raisons
            </p>
            <ul className="mt-2 space-y-1 text-sm text-muted">
              {[...data.reasons, ...(data.regime_details?.reasons ?? [])].map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>

          {data.warnings.length > 0 ? (
            <div className="rounded-lg border border-warn/20 bg-warn/5 px-3 py-2 text-xs text-warn">
              {data.warnings.join(" / ")}
            </div>
          ) : null}
        </div>
      )}
    </SectionCard>
  );
}
