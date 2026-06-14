"use client";

import { getCandles } from "@/lib/api";
import { usePolling } from "./use-polling";
import { Stat } from "./ui/card";
import { num, signed, tone } from "@/lib/format";

const fetcher = () => getCandles("M5", 300);

/** Statistiques de marché dérivées de la fenêtre de bougies M5 chargée. */
export default function MarketStats() {
  const { data } = usePolling(fetcher, 30000);
  const candles = data ?? [];
  const has = candles.length > 0;

  const last = has ? candles[candles.length - 1].close : null;
  const open = has ? candles[0].open : null;
  const change = has && last != null && open != null ? last - open : null;
  const changePct =
    change != null && open ? (change / open) * 100 : null;
  const high = has ? Math.max(...candles.map((c) => c.high)) : null;
  const low = has ? Math.min(...candles.map((c) => c.low)) : null;
  const volume = has ? candles.reduce((a, c) => a + (c.volume ?? 0), 0) : null;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-5">
      <Stat
        label="Prix XAU/USD"
        value={last != null ? num(last) : "—"}
        tone="gold"
        hint="dernier close M5"
      />
      <Stat
        label="Variation"
        value={
          change != null
            ? `${signed(change)} (${signed(changePct, 2)} %)`
            : "—"
        }
        tone={tone(change) === "flat" ? "ink" : tone(change)}
        hint="sur la fenêtre"
      />
      <Stat label="Plus haut" value={high != null ? num(high) : "—"} />
      <Stat label="Plus bas" value={low != null ? num(low) : "—"} />
      <Stat
        label="Volume"
        value={volume != null ? num(volume, 0) : "—"}
        hint="cumulé (fenêtre)"
      />
    </div>
  );
}
