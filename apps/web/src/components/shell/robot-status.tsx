"use client";

import { getSummary } from "@/lib/api";
import { usePolling } from "@/components/use-polling";

/**
 * État du moteur de trading, affiché en pied de sidebar.
 * Le compte n'est renseigné que si l'API joint le moteur → bon signal de vie.
 */
export default function RobotStatus() {
  const { data, error } = usePolling(getSummary, 10000);
  const online = !error && data?.account != null;

  return (
    <div className="rounded-lg border border-line-soft bg-surface-2 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          {online ? (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-up/70" />
          ) : null}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${
              online ? "bg-up" : "bg-faint"
            }`}
          />
        </span>
        <span className="text-xs font-medium text-ink">
          Robot IA · {online ? "Actif" : "Hors ligne"}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-faint">
        {online ? "Moteur connecté" : "Moteur injoignable"}
      </p>
    </div>
  );
}
