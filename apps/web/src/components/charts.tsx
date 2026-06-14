"use client";

import dynamic from "next/dynamic";

const loading = (
  <div className="flex h-80 items-center justify-center text-sm text-muted">
    Chargement du graphique…
  </div>
);

/* lightweight-charts touche le DOM : chargement client uniquement (ssr:false). */
export const PriceChart = dynamic(() => import("./price-chart"), {
  ssr: false,
  loading: () => loading,
});

export const EquityChart = dynamic(() => import("./equity-chart"), {
  ssr: false,
  loading: () => loading,
});
