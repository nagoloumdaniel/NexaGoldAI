"use client";

import { getStructuredSignal } from "@/lib/api";
import {
  agreementLabel,
  executionModeLabel,
  gateStatusLabel,
  humanizeText,
  regimeLabel,
} from "@/lib/labels";
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
  const gateStatus = data?.regime_gate?.status;
  const gateTone =
    gateStatus === "ALLOWED"
      ? "text-up"
      : gateStatus === "BLOCKED"
        ? "text-down"
        : "text-muted";

  return (
    <SectionCard
      title="Signal structuré"
      subtitle="Prévisualisation read-only du moteur de décision"
      action={
        data?.execution_mode ? (
          <span className="rounded-md bg-surface-2 px-2 py-1 text-[11px] font-medium text-muted">
            {executionModeLabel(data.execution_mode)}
          </span>
        ) : null
      }
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
              label={data.expected_move == null ? "Confiance brute" : "Score d'edge"}
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
              label="Qualité des données"
              value={ratioPct(data.data_quality_score)}
            />
            <Row label="Régime" value={regimeLabel(data.market_regime)} />
            <Row
              label="Confiance régime"
              value={ratioPct(data.regime_details?.confidence)}
            />
            <Row
              label="Filtre régime"
              value={<span className={gateTone}>{gateStatusLabel(gateStatus)}</span>}
            />
            <Row
              label="Accord modèle / régime"
              value={agreementLabel(data.regime_gate?.agreement)}
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
              label="Volatilité 20"
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
              label="Entrée / SL / TP"
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
              {[...data.reasons, ...(data.regime_details?.reasons ?? [])].map(
                (reason) => (
                  <li key={reason}>{humanizeText(reason)}</li>
                ),
              )}
            </ul>
          </div>

          {data.warnings.length > 0 ? (
            <div className="rounded-lg border border-warn/20 bg-warn/5 px-3 py-2 text-xs text-warn">
              {data.warnings.map(humanizeText).join(" / ")}
            </div>
          ) : null}
        </div>
      )}
    </SectionCard>
  );
}
