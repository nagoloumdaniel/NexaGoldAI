"use client";

import { getAnalytics } from "@/lib/api";
import { usePolling } from "./use-polling";
import { Stat } from "./ui/card";
import { num, ratioPct, signed, pnlTone } from "@/lib/format";

/** KPIs de performance calculés sur les trades clôturés. */
export default function AnalyticsCards() {
  const { data } = usePolling(getAnalytics, 30000);

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat
        label="Win rate"
        value={data ? ratioPct(data.winRate) : "—"}
        hint="trades gagnants"
      />
      <Stat
        label="Profit factor"
        value={data?.profitFactor != null ? num(data.profitFactor) : "—"}
        hint="gains / pertes"
      />
      <Stat
        label="P&L total"
        value={data ? signed(data.totalPnl) : "—"}
        tone={data ? pnlTone(data.totalPnl) : "ink"}
        hint="trades clôturés"
      />
      <Stat
        label="Trades clôturés"
        value={data ? String(data.tradeCount) : "—"}
      />
    </div>
  );
}
