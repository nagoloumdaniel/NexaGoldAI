"use client";

import { getSummary } from "@/lib/api";
import { usePolling } from "./use-polling";
import { Stat } from "./ui/card";
import { money, pct, signed, pnlTone } from "@/lib/format";

export default function StatsCards() {
  const { data, error } = usePolling(getSummary, 10000);
  const account = data?.account ?? null;
  const currency = account?.currency ?? "";
  const upl = account?.unrealized_pl ?? null;

  return (
    <div className="space-y-3">
      {error ? (
        <p className="rounded-lg border border-warn/20 bg-warn/5 px-4 py-2.5 text-sm text-warn">
          API injoignable — démarrez l&apos;API (port 3001) et le moteur.
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Stat
          label="Solde"
          value={account ? money(account.balance, currency) : "—"}
          hint="Compte démo"
        />
        <Stat
          label="Équité (NAV)"
          value={account ? money(account.nav, currency) : "—"}
          tone="gold"
        />
        <Stat
          label="P&L latent"
          value={upl != null ? `${signed(upl)} ${currency}`.trim() : "—"}
          tone={pnlTone(upl)}
        />
        <Stat
          label="Drawdown"
          value={data?.drawdownPct != null ? pct(data.drawdownPct) : "—"}
          hint="depuis le pic"
        />
        <Stat
          label="Décisions IA"
          value={data ? String(data.decisions) : "—"}
          hint="journalisées"
        />
        <Stat
          label="Positions"
          value={data ? String(data.openTrades) : "—"}
          hint="ouvertes"
        />
      </div>
    </div>
  );
}
