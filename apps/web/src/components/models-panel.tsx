"use client";

import { getModels, type ModelVersion } from "@/lib/api";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { num, ratioPct } from "@/lib/format";
import { DataTable, type DataTableColumn } from "./ui/data-table";

type ModelRow = ModelVersion & { champion: boolean };

export default function ModelsPanel() {
  const { data } = usePolling(getModels, 30000);
  const rows: ModelRow[] = (data?.versions ?? [])
    .slice()
    .reverse()
    .map((version) => ({ ...version, champion: version.id === data?.champion }));

  return (
    <SectionCard
      title="Modèles & apprentissage"
      subtitle="Les configurations candidates sont comparées avant promotion"
      bodyClassName="p-0"
      action={
        data?.granularity ? (
          <span className="rounded-md bg-surface-2 px-2 py-1 text-[11px] font-medium text-muted">
            {data.granularity}
          </span>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <div className="p-5">
          <Empty>Aucun modèle entraîné.</Empty>
        </div>
      ) : (
        <DataTable
          title="Modèles & apprentissage"
          rows={rows}
          columns={columns}
          initialPageSize={5}
          searchPlaceholder="Filtrer les modèles..."
        />
      )}
    </SectionCard>
  );
}

const columns: DataTableColumn<ModelRow>[] = [
  {
    key: "id",
    header: "Version",
    value: (v) => `${v.champion ? "champion " : ""}${v.id}`,
    render: (v) => (
      <>
        {v.champion ? (
          <span className="mr-2 rounded-md bg-gold/10 px-2 py-0.5 text-[11px] font-semibold text-gold ring-1 ring-inset ring-gold/20">
            champion
          </span>
        ) : null}
        <span className="tnum text-ink">{v.id}</span>
      </>
    ),
    className: "px-5 py-3 text-ink",
  },
  {
    key: "horizon",
    header: "Horizon",
    value: (v) => v.config.horizon,
    render: (v) => <span className="tnum text-muted">{v.config.horizon}</span>,
    className: "tnum px-5 py-3 text-muted",
  },
  {
    key: "threshold",
    header: "Seuil",
    value: (v) => v.config.threshold,
    render: (v) => <span className="tnum text-muted">{v.config.threshold}</span>,
    className: "tnum px-5 py-3 text-muted",
  },
  {
    key: "sharpe",
    header: "Sharpe",
    value: (v) => v.metrics.sharpe,
    pdfValue: (v) => num(v.metrics.sharpe),
    render: (v) => <span className="tnum text-muted">{num(v.metrics.sharpe)}</span>,
    className: "tnum px-5 py-3 text-muted",
  },
  {
    key: "accuracy",
    header: "Accuracy",
    value: (v) => v.metrics.accuracy,
    pdfValue: (v) => ratioPct(v.metrics.accuracy),
    render: (v) => (
      <span className="tnum text-muted">{ratioPct(v.metrics.accuracy)}</span>
    ),
    className: "tnum px-5 py-3 text-muted",
  },
  {
    key: "samples",
    header: "Échantillons",
    value: (v) => v.metrics.samples,
    render: (v) => <span className="tnum text-muted">{v.metrics.samples}</span>,
    className: "tnum px-5 py-3 text-muted",
  },
];
