"use client";

import { getRiskStatus } from "@/lib/api";
import { dateTime, num, pct, signed } from "@/lib/format";
import { humanizeText } from "@/lib/labels";
import { usePolling } from "./use-polling";
import { Empty, SectionCard } from "./ui/card";

/** Jauge de consommation d'une limite de perte (0 = intacte, 1 = atteinte). */
function LimitGauge({
  label,
  loss,
  limit,
  hint,
}: {
  label: string;
  loss: number | null;
  limit: number | null;
  hint: string;
}) {
  const consumed =
    loss == null || limit == null || limit <= 0
      ? null
      : Math.max(0, Math.min(-loss / limit, 1));
  const critical = consumed != null && consumed >= 0.75;

  return (
    <div className="rounded-lg border border-line-soft bg-surface-2/45 px-3 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] uppercase text-faint">{label}</span>
        <span
          className={`tnum text-sm font-semibold ${
            consumed == null ? "text-muted" : critical ? "text-down" : "text-ink"
          }`}
        >
          {consumed == null ? "—" : `${num(consumed * 100, 0)} %`}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div
          className={`h-full transition-[width] duration-500 ${
            critical ? "bg-down" : "bg-gold"
          }`}
          style={{ width: `${(consumed ?? 0) * 100}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-muted">{hint}</p>
    </div>
  );
}

export default function RiskPanel() {
  const { data, error } = usePolling(getRiskStatus, 15000);
  const unreachable = Boolean(error) || data?.engineReachable === false;

  const kill = data?.kill_switch ?? null;
  const limits = data?.limits ?? null;
  const stats = data?.risk_stats ?? null;
  // Les limites sont en % du solde ; sans solde côté moteur on raisonne en
  // proportion du budget de perte, ce qui suffit à la jauge.
  const dailyLimitRatio = limits?.max_daily_loss_pct ?? null;
  const weeklyLimitRatio = limits?.max_weekly_loss_pct ?? null;

  return (
    <SectionCard
      title="Moteur de risque"
      subtitle="Kill switch, limites et consommation en cours"
      action={
        kill ? (
          <span
            className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold ring-1 ring-inset ${
              kill.locked
                ? "bg-down/10 text-down ring-down/20"
                : "bg-up/10 text-up ring-up/20"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                kill.locked ? "bg-down" : "bg-up"
              }`}
            />
            {kill.locked ? "Verrouillé" : "Actif"}
          </span>
        ) : undefined
      }
    >
      {unreachable ? (
        <Empty>
          Moteur injoignable — l&apos;état du risque ne peut pas être vérifié.
        </Empty>
      ) : (
        <>
          {kill?.locked ? (
            <div className="mb-4 rounded-lg border border-down/25 bg-down/5 px-3 py-3">
              <p className="text-sm font-semibold text-down">
                Trading verrouillé — aucun nouvel ordre
              </p>
              <p className="mt-1 text-sm text-muted">
                {humanizeText(kill.reason)}
              </p>
              <p className="mt-1 text-xs text-faint">
                Depuis le {dateTime(kill.locked_at)} — réactivation manuelle
                explicite requise.
              </p>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <LimitGauge
              label="Perte du jour"
              loss={stats?.realized_pnl_today ?? null}
              limit={dailyLimitRatio}
              hint={`Réalisé : ${signed(stats?.realized_pnl_today)} — limite ${pct(
                limits?.max_daily_loss_pct,
              )} du solde`}
            />
            <LimitGauge
              label="Perte de la semaine"
              loss={stats?.realized_pnl_week ?? null}
              limit={weeklyLimitRatio}
              hint={`Réalisé : ${signed(stats?.realized_pnl_week)} — limite ${pct(
                limits?.max_weekly_loss_pct,
              )} du solde`}
            />
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 text-sm xl:grid-cols-4">
            <div>
              <p className="text-[11px] uppercase text-faint">Pertes consécutives</p>
              <p
                className={`tnum mt-1 font-semibold ${
                  (stats?.consecutive_losses ?? 0) >=
                  (limits?.max_consecutive_losses ?? 99)
                    ? "text-down"
                    : "text-ink"
                }`}
              >
                {stats?.consecutive_losses ?? 0} / {limits?.max_consecutive_losses ?? "—"}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase text-faint">Risque par trade</p>
              <p className="tnum mt-1 font-semibold text-ink">
                {pct(limits?.max_risk_per_trade_pct)}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase text-faint">Positions max</p>
              <p className="tnum mt-1 font-semibold text-ink">
                {limits?.max_open_positions ?? "—"}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase text-faint">Ordres</p>
              <p
                className={`mt-1 font-semibold ${
                  data?.trading_enabled ? "text-up" : "text-warn"
                }`}
              >
                {data?.trading_enabled ? "Autorisés" : "Bloqués"}
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 border-t border-line-soft pt-3 text-sm sm:grid-cols-2">
            <div>
              <p className="text-[11px] uppercase text-faint">Dernière perte</p>
              <p className="tnum mt-1 text-muted">{dateTime(stats?.last_loss_at)}</p>
            </div>
            <div>
              <p className="text-[11px] uppercase text-faint">Pause après perte</p>
              <p className="tnum mt-1 text-muted">
                {limits?.cooldown_after_loss_minutes ?? "—"} min (
                {limits?.cooldown_after_consecutive_losses_minutes ?? "—"} min en série)
              </p>
            </div>
          </div>
        </>
      )}
    </SectionCard>
  );
}
