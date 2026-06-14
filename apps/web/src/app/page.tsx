"use client";

import dynamic from "next/dynamic";
import DecisionsTable from "@/components/decisions-table";
import StatsCards from "@/components/stats-cards";
import TradesTable from "@/components/trades-table";

// lightweight-charts touches the DOM, so load it client-side only.
const PriceChart = dynamic(() => import("@/components/price-chart"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[360px] items-center justify-center text-sm text-zinc-400">
      Chargement du graphique…
    </div>
  ),
});

export default function Home() {
  return (
    <div className="flex flex-1 flex-col bg-zinc-50 font-sans dark:bg-zinc-950">
      <header className="border-b border-zinc-200 bg-white px-8 py-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            <span className="text-amber-500">Nexa</span>Gold
          </h1>
          <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-600 dark:text-amber-400">
            Paper trading · XAU/USD
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 space-y-6 px-8 py-8">
        <StatsCards />

        <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="mb-4 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
            Or (XAU/USD) · M5
          </h2>
          <PriceChart />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <DecisionsTable />
          <TradesTable />
        </div>
      </main>
    </div>
  );
}
