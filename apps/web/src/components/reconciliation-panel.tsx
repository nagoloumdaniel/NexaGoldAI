"use client";

import {
  useCallback,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  getReconciliation,
  resolveTrade,
  runReconciliation,
  type ReconciliationRow,
  type ReconciliationStatus,
  type UntrackedBrokerPosition,
} from "@/lib/api";
import { humanizeText, reconciliationStatusLabel } from "@/lib/labels";
import { signed } from "@/lib/format";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { ActionBadge } from "./ui/badge";
import { DataTable, type DataTableColumn } from "./ui/data-table";

type DisplayRow =
  | { kind: "db"; row: ReconciliationRow }
  | { kind: "broker"; row: UntrackedBrokerPosition; index: number };

function Metric({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-lg border border-line-soft bg-surface-2 px-3 py-2">
      <p className="text-[10px] font-medium uppercase text-faint">{label}</p>
      <p className="tnum mt-1 text-lg font-semibold text-ink">
        {value == null ? "-" : value}
      </p>
    </div>
  );
}

function rowId(item: DisplayRow) {
  if (item.kind === "db") return item.row.trade_id;
  return item.row.deal_id ?? item.row.deal_reference ?? `broker-${item.index}`;
}

function statusTone(status: string) {
  if (status === "matched") return "text-up";
  if (status === "closed_from_broker") return "text-ai";
  return "text-warn";
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
  const tableRows: DisplayRow[] = useMemo(
    () => [
      ...(view?.rows ?? []).map((row) => ({ kind: "db" as const, row })),
      ...(view?.untracked ?? []).map((row, index) => ({
        kind: "broker" as const,
        row,
        index,
      })),
    ],
    [view?.rows, view?.untracked],
  );

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

  const handleCancel = useCallback(async (tradeId: string) => {
    setResolvingId(tradeId);
    setSyncError(null);
    setManualResult(null);
    try {
      const result = await resolveTrade(tradeId, { status: "CANCELLED" });
      setManualResult(
        result.updated
          ? `${tradeId} marqué annulé.`
          : result.reason
            ? humanizeText(result.reason)
            : "Résolution refusée.",
      );
      setSyncResult(await getReconciliation());
    } catch (error) {
      setSyncError(String(error));
    } finally {
      setResolvingId(null);
    }
  }, []);

  const handleClose = useCallback(async (tradeId: string) => {
    const raw = exitPrices[tradeId];
    const exitPrice = Number(raw);
    if (!raw || Number.isNaN(exitPrice) || exitPrice <= 0) {
      setSyncError("Prix de sortie requis pour clôturer manuellement.");
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
          ? `${tradeId} clôturé : P&L ${signed(result.pnl ?? 0)}.`
          : result.reason
            ? humanizeText(result.reason)
            : "Résolution refusée.",
      );
      setSyncResult(await getReconciliation());
    } catch (error) {
      setSyncError(String(error));
    } finally {
      setResolvingId(null);
    }
  }, [exitPrices]);

  const columns = useMemo(
    () =>
      buildColumns({
        exitPrices,
        resolvingId,
        setExitPrices,
        handleClose,
        handleCancel,
      }),
    [exitPrices, resolvingId, handleClose, handleCancel],
  );

  return (
    <SectionCard
      title="Réconciliation broker"
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
            Moteur injoignable. Réconciliation indisponible.
          </p>
        ) : null}
        {syncError ? (
          <p className="rounded-lg border border-down/20 bg-down/5 px-4 py-2.5 text-sm text-down">
            Synchronisation échouée : {humanizeText(syncError)}
          </p>
        ) : null}
        {syncResult && !offline ? (
          <p className="rounded-lg border border-ai/20 bg-ai/5 px-4 py-2.5 text-sm text-ai">
            Synchronisation terminée : {syncResult.closed ?? 0} clôturée(s),{" "}
            {syncResult.unresolved_closures.length} non résolue(s),{" "}
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
          <Metric label="Broker ouvertes" value={view?.broker_open_positions ?? null} />
          <Metric label="Matchées" value={view?.matched ?? null} />
          <Metric label="Clôturées" value={view?.closed ?? null} />
          <Metric label="Manquantes" value={view?.missing_on_broker ?? null} />
          <Metric label="Hors DB" value={view?.untracked_broker_positions ?? null} />
        </div>
      </div>

      {tableRows.length === 0 ? (
        <div className="px-5 pb-5">
          <Empty>Aucun écart de réconciliation à afficher.</Empty>
        </div>
      ) : (
        <div className="border-t border-line-soft">
          <DataTable
            title="Réconciliation broker"
            rows={tableRows}
            columns={columns}
            initialPageSize={5}
            searchPlaceholder="Filtrer la réconciliation..."
          />
        </div>
      )}
    </SectionCard>
  );
}

function buildColumns({
  exitPrices,
  resolvingId,
  setExitPrices,
  handleClose,
  handleCancel,
}: {
  exitPrices: Record<string, string>;
  resolvingId: string | null;
  setExitPrices: Dispatch<SetStateAction<Record<string, string>>>;
  handleClose: (tradeId: string) => void;
  handleCancel: (tradeId: string) => void;
}): DataTableColumn<DisplayRow>[] {
  return [
    {
      key: "trade",
      header: "Trade",
      value: (item) =>
        item.kind === "db"
          ? `${item.row.trade_id} ${item.row.broker_deal_id ?? item.row.broker_trade_id ?? ""}`
          : `Position broker hors DB ${rowId(item)}`,
      render: (item) => (
        <>
          <p className={`tnum text-xs ${item.kind === "db" ? "text-ink" : "text-warn"}`}>
            {item.kind === "db" ? item.row.trade_id : "Position broker hors DB"}
          </p>
          <p className="tnum mt-1 text-[11px] text-faint">
            {item.kind === "db"
              ? item.row.broker_deal_id ?? item.row.broker_trade_id ?? "-"
              : rowId(item)}
          </p>
        </>
      ),
      className: "px-5 py-3",
    },
    {
      key: "side",
      header: "Sens",
      value: (item) => (item.kind === "db" ? item.row.side : item.row.direction),
      render: (item) => (
        <ActionBadge
          action={item.kind === "db" ? item.row.side : item.row.direction ?? "HOLD"}
        />
      ),
      className: "px-5 py-3",
    },
    {
      key: "units",
      header: "Taille",
      value: (item) => (item.kind === "db" ? item.row.units : item.row.size),
      render: (item) => (
        <span className="tnum text-muted">
          {item.kind === "db" ? item.row.units : item.row.size}
        </span>
      ),
      className: "tnum px-5 py-3 text-muted",
    },
    {
      key: "status",
      header: "Statut",
      value: (item) =>
        item.kind === "db"
          ? reconciliationStatusLabel(item.row.status)
          : reconciliationStatusLabel("untracked"),
      render: (item) => {
        const status = item.kind === "db" ? item.row.status : "untracked";
        return (
          <span className={statusTone(status)}>
            {reconciliationStatusLabel(status)}
          </span>
        );
      },
      className: "px-5 py-3",
    },
    {
      key: "pnl",
      header: "P&L broker",
      value: (item) => (item.kind === "db" ? item.row.broker_pnl : item.row.pnl),
      pdfValue: (item) =>
        item.kind === "db" ? signed(item.row.broker_pnl) : signed(item.row.pnl),
      render: (item) => (
        <span className="tnum text-muted">
          {item.kind === "db"
            ? item.row.broker_pnl == null
              ? "-"
              : signed(item.row.broker_pnl)
            : signed(item.row.pnl)}
        </span>
      ),
      className: "tnum px-5 py-3 text-muted",
    },
    {
      key: "resolution",
      header: "Résolution",
      value: (item) =>
        item.kind === "db" && item.row.status === "missing_on_broker"
          ? "Résolution manuelle disponible"
          : "-",
      pdfValue: () => "-",
      render: (item) => {
        if (item.kind !== "db" || item.row.status !== "missing_on_broker") {
          return <span className="text-faint">-</span>;
        }
        return (
          <div className="flex min-w-72 items-center gap-2">
            <input
              type="number"
              inputMode="decimal"
              step="0.01"
              placeholder="Prix de sortie"
              value={exitPrices[item.row.trade_id] ?? ""}
              onChange={(event) =>
                setExitPrices((current) => ({
                  ...current,
                  [item.row.trade_id]: event.target.value,
                }))
              }
              className="h-8 w-28 rounded-md border border-line bg-surface-2 px-2 text-xs text-ink outline-none transition-colors placeholder:text-faint focus:border-gold"
            />
            <button
              type="button"
              onClick={() => handleClose(item.row.trade_id)}
              disabled={resolvingId === item.row.trade_id}
              className="h-8 rounded-md bg-ai/10 px-2.5 text-xs font-medium text-ai ring-1 ring-inset ring-ai/20 transition-colors hover:bg-ai/15 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Clôturer
            </button>
            <button
              type="button"
              onClick={() => handleCancel(item.row.trade_id)}
              disabled={resolvingId === item.row.trade_id}
              className="h-8 rounded-md bg-warn/10 px-2.5 text-xs font-medium text-warn ring-1 ring-inset ring-warn/20 transition-colors hover:bg-warn/15 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Annuler DB
            </button>
          </div>
        );
      },
      className: "px-5 py-3",
    },
  ];
}
