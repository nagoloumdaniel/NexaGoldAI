"use client";

import { useState } from "react";
import {
  getReconciliation,
  resolveTrade,
  runReconciliation,
  type ReconciliationStatus,
} from "@/lib/api";
import { signed } from "@/lib/format";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { ActionBadge } from "./ui/badge";

function Metric({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-lg border border-line-soft bg-surface-2 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wider text-faint">
        {label}
      </p>
      <p className="tnum mt-1 text-lg font-semibold text-ink">
        {value == null ? "-" : value}
      </p>
    </div>
  );
}

export default function ReconciliationPanel() {
  const { data } = usePolling(getReconciliation, 15000);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<ReconciliationStatus | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [exitPrices, setExitPrices] = useState<Record<string, string>>({});
  const [manualResult, setManualResult] = useState<string | null>(null);
  const view = syncResult ?? data;
  const offline = view?.engineReachable === false;
  const rows = view?.rows ?? [];
  const untracked = view?.untracked ?? [];

  async function handleSync() {
    setSyncing(true);
    setSyncError(null);
    try {
      setSyncResult(await runReconciliation());
    } catch (error) {
      setSyncError(String(error));
    } finally {
      setSyncing(false);
    }
  }

  async function handleCancel(tradeId: string) {
    setResolvingId(tradeId);
    setSyncError(null);
    setManualResult(null);
    try {
      const result = await resolveTrade(tradeId, { status: "CANCELLED" });
      setManualResult(
        result.updated
          ? `${tradeId} marque CANCELLED.`
          : result.reason ?? "Resolution refusee.",
      );
      setSyncResult(await getReconciliation());
    } catch (error) {
      setSyncError(String(error));
    } finally {
      setResolvingId(null);
    }
  }

  async function handleClose(tradeId: string) {
    const raw = exitPrices[tradeId];
    const exitPrice = Number(raw);
    if (!raw || Number.isNaN(exitPrice) || exitPrice <= 0) {
      setSyncError("Prix de sortie requis pour cloturer manuellement.");
      return;
    }
    setResolvingId(tradeId);
    setSyncError(null);
    setManualResult(null);
    try {
      const result = await resolveTrade(tradeId, {
        status: "CLOSED",
        exit_price: exitPrice,
      });
      setManualResult(
        result.updated
          ? `${tradeId} cloture: P&L ${signed(result.pnl ?? 0)}.`
          : result.reason ?? "Resolution refusee.",
      );
      setSyncResult(await getReconciliation());
    } catch (error) {
      setSyncError(String(error));
    } finally {
      setResolvingId(null);
    }
  }

  return (
    <SectionCard
      title="Reconciliation broker"
      subtitle="Comparaison des trades ouverts en base avec les positions Capital.com"
      bodyClassName="p-0"
      action={
        <button
          type="button"
          onClick={handleSync}
          disabled={syncing || offline}
          className="rounded-md bg-gold/10 px-3 py-1.5 text-xs font-medium text-gold ring-1 ring-inset ring-gold/20 transition-colors hover:bg-gold/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {syncing ? "Synchronisation..." : "Synchroniser"}
        </button>
      }
    >
      <div className="space-y-4 p-5">
        {offline ? (
          <p className="rounded-lg border border-warn/20 bg-warn/5 px-4 py-2.5 text-sm text-warn">
            Moteur injoignable - reconciliation indisponible.
          </p>
        ) : null}
        {syncError ? (
          <p className="rounded-lg border border-down/20 bg-down/5 px-4 py-2.5 text-sm text-down">
            Synchronisation echouee: {syncError}
          </p>
        ) : null}
        {syncResult && !offline ? (
          <p className="rounded-lg border border-ai/20 bg-ai/5 px-4 py-2.5 text-sm text-ai">
            Sync terminee: {syncResult.closed ?? 0} cloturee(s),{" "}
            {syncResult.unresolved_closures.length} non resolue(s),{" "}
            {syncResult.untracked_broker_positions ?? 0} hors DB.
          </p>
        ) : null}
        {manualResult ? (
          <p className="rounded-lg border border-up/20 bg-up/5 px-4 py-2.5 text-sm text-up">
            {manualResult}
          </p>
        ) : null}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Metric label="DB ouvertes" value={view?.db_open_trades ?? null} />
          <Metric
            label="Broker ouvertes"
            value={view?.broker_open_positions ?? null}
          />
          <Metric label="Matchees" value={view?.matched ?? null} />
          <Metric label="Cloturees" value={view?.closed ?? null} />
          <Metric label="Manquantes" value={view?.missing_on_broker ?? null} />
          <Metric
            label="Hors DB"
            value={view?.untracked_broker_positions ?? null}
          />
        </div>
      </div>

      {rows.length === 0 && untracked.length === 0 ? (
        <div className="px-5 pb-5">
          <Empty>Aucun ecart de reconciliation a afficher.</Empty>
        </div>
      ) : (
        <div className="overflow-x-auto border-t border-line-soft">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-[11px] uppercase tracking-wider text-faint">
                <th className="px-5 py-2.5 font-medium">Trade</th>
                <th className="px-5 py-2.5 font-medium">Sens</th>
                <th className="px-5 py-2.5 font-medium">Taille</th>
                <th className="px-5 py-2.5 font-medium">Statut</th>
                <th className="px-5 py-2.5 font-medium">P&L broker</th>
                <th className="px-5 py-2.5 font-medium">Resolution</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.trade_id}
                  className="border-b border-line-soft last:border-0 hover:bg-surface-2/40"
                >
                  <td className="px-5 py-3">
                    <p className="tnum text-xs text-ink">{row.trade_id}</p>
                    <p className="tnum mt-1 text-[11px] text-faint">
                      {row.broker_deal_id ?? row.broker_trade_id ?? "-"}
                    </p>
                  </td>
                  <td className="px-5 py-3">
                    <ActionBadge action={row.side} />
                  </td>
                  <td className="tnum px-5 py-3 text-muted">{row.units}</td>
                  <td
                    className={`px-5 py-3 ${
                      row.status === "matched"
                        ? "text-up"
                        : row.status === "closed_from_broker"
                          ? "text-ai"
                          : "text-warn"
                    }`}
                  >
                    {row.status === "matched"
                      ? "Matchee"
                      : row.status === "closed_from_broker"
                        ? "Cloturee broker"
                        : "Absente broker"}
                  </td>
                  <td className="tnum px-5 py-3 text-muted">
                    {row.broker_pnl == null ? "-" : signed(row.broker_pnl)}
                  </td>
                  <td className="px-5 py-3">
                    {row.status === "missing_on_broker" ? (
                      <div className="flex min-w-72 items-center gap-2">
                        <input
                          type="number"
                          inputMode="decimal"
                          step="0.01"
                          placeholder="Prix sortie"
                          value={exitPrices[row.trade_id] ?? ""}
                          onChange={(event) =>
                            setExitPrices((current) => ({
                              ...current,
                              [row.trade_id]: event.target.value,
                            }))
                          }
                          className="h-8 w-28 rounded-md border border-line bg-surface-2 px-2 text-xs text-ink outline-none transition-colors placeholder:text-faint focus:border-gold"
                        />
                        <button
                          type="button"
                          onClick={() => handleClose(row.trade_id)}
                          disabled={resolvingId === row.trade_id}
                          className="h-8 rounded-md bg-ai/10 px-2.5 text-xs font-medium text-ai ring-1 ring-inset ring-ai/20 transition-colors hover:bg-ai/15 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Cloturer
                        </button>
                        <button
                          type="button"
                          onClick={() => handleCancel(row.trade_id)}
                          disabled={resolvingId === row.trade_id}
                          className="h-8 rounded-md bg-warn/10 px-2.5 text-xs font-medium text-warn ring-1 ring-inset ring-warn/20 transition-colors hover:bg-warn/15 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Annuler DB
                        </button>
                      </div>
                    ) : (
                      <span className="text-faint">-</span>
                    )}
                  </td>
                </tr>
              ))}
              {untracked.map((position, index) => (
                <tr
                  key={`${position.deal_id ?? position.deal_reference ?? index}`}
                  className="border-b border-line-soft last:border-0 bg-warn/5"
                >
                  <td className="px-5 py-3">
                    <p className="tnum text-xs text-warn">
                      Position broker hors DB
                    </p>
                    <p className="tnum mt-1 text-[11px] text-faint">
                      {position.deal_id ?? position.deal_reference ?? "-"}
                    </p>
                  </td>
                  <td className="px-5 py-3">
                    <ActionBadge action={position.direction ?? "HOLD"} />
                  </td>
                  <td className="tnum px-5 py-3 text-muted">{position.size}</td>
                  <td className="px-5 py-3 text-warn">Non suivie</td>
                  <td className="tnum px-5 py-3 text-muted">
                    {signed(position.pnl)}
                  </td>
                  <td className="px-5 py-3 text-faint">-</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
