"use client";

import { getSummary } from "@/lib/api";
import { usePolling } from "./use-polling";

const fmt = (n?: number | null) =>
  n == null
    ? "—"
    : n.toLocaleString("fr-FR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });

function Card({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
        {value}
      </p>
      {hint ? (
        <p className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">{hint}</p>
      ) : null}
    </div>
  );
}

export default function StatsCards() {
  const { data, error } = usePolling(getSummary, 10000);
  const account = data?.account ?? null;
  const currency = account?.currency ?? "";

  return (
    <>
      {error ? (
        <p className="mb-3 text-sm text-amber-600 dark:text-amber-400">
          API injoignable — démarrez l&apos;API (port 3001) et le moteur.
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Card
          label="Solde"
          value={account ? `${fmt(account.balance)} ${currency}` : "—"}
          hint="Compte démo"
        />
        <Card
          label="Équité (NAV)"
          value={account ? `${fmt(account.nav)} ${currency}` : "—"}
        />
        <Card
          label="P&L latent"
          value={account ? `${fmt(account.unrealized_pl)} ${currency}` : "—"}
        />
        <Card
          label="Drawdown"
          value={data?.drawdownPct != null ? `${fmt(data.drawdownPct)} %` : "—"}
        />
        <Card
          label="Décisions IA"
          value={data ? String(data.decisions) : "—"}
          hint="journalisées"
        />
        <Card
          label="Positions"
          value={data ? String(data.openTrades) : "—"}
          hint="ouvertes"
        />
      </div>
    </>
  );
}
