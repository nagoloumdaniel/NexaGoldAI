"use client";

import {
  CandlestickData,
  ColorType,
  createChart,
  UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { getCandles } from "@/lib/api";

export default function PriceChart() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#a1a1aa",
      },
      grid: {
        vertLines: { color: "rgba(160,160,170,0.1)" },
        horzLines: { color: "rgba(160,160,170,0.1)" },
      },
      timeScale: { timeVisible: true, borderColor: "rgba(160,160,170,0.2)" },
      rightPriceScale: { borderColor: "rgba(160,160,170,0.2)" },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#16a34a",
      downColor: "#dc2626",
      borderUpColor: "#16a34a",
      borderDownColor: "#dc2626",
      wickUpColor: "#16a34a",
      wickDownColor: "#dc2626",
    });

    let active = true;
    const load = () =>
      getCandles("M5", 300)
        .then((candles) => {
          if (!active) return;
          const data: CandlestickData[] = candles.map((c) => ({
            time: (new Date(c.time).getTime() / 1000) as UTCTimestamp,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          }));
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
  }, []);

  return <div ref={containerRef} className="w-full" />;
}
