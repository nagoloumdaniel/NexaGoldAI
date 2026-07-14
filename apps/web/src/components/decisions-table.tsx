"use client";

import { useMemo } from "react";
import { getDecisions, type Decision } from "@/lib/api";
import { humanizeText, strategyLabel } from "@/lib/labels";
import { ratioPct, time } from "@/lib/format";
import { usePolling } from "./use-polling";
import { SectionCard, Empty } from "./ui/card";
import { ActionBadge, Confidence } from "./ui/badge";
import { DataTable, type DataTableColumn } from "./ui/data-table";

function featureNumber(
  features: Record<string, unknown> | null | undefined,
  key: string,
) {
  const value = features?.[key];
  return typeof value === "number" ? value : null;
}

export default function DecisionsTable({
  limit = 50,
  showReason = true,
}: {
  limit?: number;
  showReason?: boolean;
}) {
  const fetcher = useStableDecisions(limit);
  const { data } = usePolling(fetcher, 10000);
  const showsExpectedReturn = Boolean(
    data?.some((decision) => decision.features?.signal_kind === "expected_return"),
  );
  const columns = useMemo(
    () => buildColumns(showReason, showsExpectedReturn),
    [showReason, showsExpectedReturn],
  );

  return (
    <SectionCard
      title="Décisions IA récentes"
      subtitle="Chaque évaluation du modèle est journalisée, exécutée ou non"
      bodyClassName="p-0"
    >
      {!data || data.length === 0 ? (
        <div className="p-5">
          <Empty>Aucune décision pour l&apos;instant.</Empty>
        </div>
      ) : (
        <DataTable
          title="Décisions IA récentes"
          rows={data}
          columns={columns}
          initialPageSize={5}
          searchPlaceholder="Filtrer les décisions..."
        />
      )}
    </SectionCard>
  );
}

function buildColumns(
  showReason: boolean,
  showsExpectedReturn: boolean,
): DataTableColumn<Decision>[] {
  const columns: DataTableColumn<Decision>[] = [
    {
      key: "time",
      header: "Heure",
      value: (d) => time(d.time),
      sortValue: (d) => new Date(d.time).getTime(),
      render: (d) => <span className="tnum text-muted">{time(d.time)}</span>,
      className: "tnum px-5 py-3 text-muted",
    },
    {
      key: "strategy",
      header: "Stratégie",
      value: (d) => strategyLabel(d.strategy),
      render: (d) => <span className="text-muted">{strategyLabel(d.strategy)}</span>,
      className: "px-5 py-3",
    },
    {
      key: "action",
      header: "Action",
      value: (d) => d.action,
      render: (d) => <ActionBadge action={d.action} />,
      className: "px-5 py-3",
    },
    {
      key: "confidence",
      header: "Confiance",
      value: (d) => d.confidence,
      pdfValue: (d) => ratioPct(d.confidence),
      render: (d) => <Confidence value={d.confidence} />,
      className: "px-5 py-3",
    },
  ];
  if (showsExpectedReturn) {
    columns.push(
      {
        key: "expected_return",
        header: "Rendement attendu",
        value: (d) => featureNumber(d.features, "expected_return"),
        pdfValue: (d) => ratioPct(featureNumber(d.features, "expected_return"), 3),
        render: (d) => (
          <span className="tnum text-muted">
            {ratioPct(featureNumber(d.features, "expected_return"), 3)}
          </span>
        ),
        className: "tnum px-5 py-3 text-muted",
      },
      {
        key: "threshold",
        header: "Seuil",
        value: (d) => featureNumber(d.features, "expected_return_threshold"),
        pdfValue: (d) =>
          ratioPct(featureNumber(d.features, "expected_return_threshold"), 3),
        render: (d) => (
          <span className="tnum text-muted">
            {ratioPct(featureNumber(d.features, "expected_return_threshold"), 3)}
          </span>
        ),
        className: "tnum px-5 py-3 text-muted",
      },
      {
        key: "position_size",
        header: "Exposition",
        value: (d) => featureNumber(d.features, "position_size"),
        pdfValue: (d) => ratioPct(featureNumber(d.features, "position_size"), 1),
        render: (d) => (
          <span className="tnum text-muted">
            {ratioPct(featureNumber(d.features, "position_size"), 1)}
          </span>
        ),
        className: "tnum px-5 py-3 text-muted",
      },
    );
  }
  if (showReason) {
    columns.push({
      key: "reason",
      header: "Raison",
      value: (d) => humanizeText(d.reason),
      render: (d) => (
        <span className="block max-w-xs truncate text-muted">
          {humanizeText(d.reason)}
        </span>
      ),
      className: "px-5 py-3",
    });
  }
  columns.push({
    key: "executed",
    header: "Exécutée",
    value: (d) => (d.executed ? "Oui" : "Non"),
    render: (d) =>
      d.executed ? (
        <span className="text-up">Oui</span>
      ) : (
        <span className="text-faint">Non</span>
      ),
    className: "px-5 py-3",
  });
  return columns;
}

function useStableDecisions(limit: number) {
  return useMemo(() => () => getDecisions(limit), [limit]);
}
