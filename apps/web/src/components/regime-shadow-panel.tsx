"use client";

import { getRegimeShadow } from "@/lib/api";
import { ratioPct, time } from "@/lib/format";
import { usePolling } from "./use-polling";
import { SectionCard } from "./ui/card";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 py-3">
      <div className="text-[11px] uppercase text-faint">{label}</div>
      <div className="tnum mt-1 text-lg font-semibold text-ink">{value}</div>
    </div>
  );
}

export default function RegimeShadowPanel() {
  const { data } = usePolling(getRegimeShadow, 30000);
  const total = data?.total_decisions ?? 0;
  const filtered = data?.filtered_decisions ?? 0;
  const kept = data?.kept_decisions ?? 0;
  const active = total > 0;

  return (
    <SectionCard
      title="Shadow régime"
      subtitle="Filtre candidat observé sans exécution"
      action={
        <span className={active ? "tnum text-xs text-muted" : "text-xs text-faint"}>
          {active ? `${filtered} bloquées` : "En attente"}
        </span>
      }
    >
      <div className="grid grid-cols-2 gap-x-6 border-b border-line-soft sm:grid-cols-4">
        <Metric label="Décisions" value={String(total)} />
        <Metric label="Conservées" value={String(kept)} />
        <Metric label="Bloquées" value={String(filtered)} />
        <Metric label="Taux filtre" value={ratioPct(data?.filter_rate ?? 0)} />
      </div>

      <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <div className="min-w-0">
          <div className="text-[11px] uppercase text-faint">Filtre</div>
          <div className="mt-1 truncate text-muted">{data?.filter ?? "-"}</div>
        </div>
        <div className="min-w-0">
          <div className="text-[11px] uppercase text-faint">Dernière observation</div>
          <div className="tnum mt-1 text-muted">
            {data?.last_seen_at ? time(data.last_seen_at) : "-"}
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
        <span className={data?.execution_enabled ? "text-down" : "text-up"}>
          {data?.execution_enabled ? "Exécution active" : "Aucune exécution"}
        </span>
        <span className="text-muted">
          {active ? "Comparaison prospective en cours" : "Actif après redémarrage moteur"}
        </span>
      </div>
    </SectionCard>
  );
}
