"use client";

import {
  AreaData,
  ColorType,
  createChart,
  UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { getAnalytics } from "@/lib/api";

/**
 * Courbe d'équité (NAV dans le temps) à partir des snapshots d'équité.
 * Vide tant qu'aucun EquitySnapshot n'a été enregistré par le moteur.
 */
export default function EquityChart({ height = 320 }: { height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [empty, setEmpty] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8b8b95",
        fontFamily: "var(--font-geist-sans)",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: 0 },
      timeScale: { timeVisible: true, borderColor: "rgba(255,255,255,0.08)" },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
    });

    const series = chart.addAreaSeries({
      lineColor: "#d4af37",
      topColor: "rgba(212,175,55,0.28)",
      bottomColor: "rgba(212,175,55,0.01)",
      lineWidth: 2,
    });

    let active = true;
    const load = () =>
      getAnalytics()
        .then((a) => {
          if (!active) return;
          const data: AreaData[] = a.equityCurve.map((p) => ({
            time: (new Date(p.time).getTime() / 1000) as UTCTimestamp,
            value: p.nav,
          }));
          setEmpty(data.length === 0);
          series.setData(data);
          chart.timeScale().fitContent();
        })
        .catch(() => undefined);

    load();
    const interval = setInterval(load, 30000);
    const onResize = () => chart.applyOptions({ width: container.clientWidth });
    window.addEventListener("resize", onResize);

    return () => {
      active = false;
      clearInterval(interval);
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [height]);

  return (
    <div className="relative">
      {empty ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-muted">
          Aucun historique d&apos;équité enregistré pour l&apos;instant.
        </div>
      ) : null}
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
