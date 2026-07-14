import PageHeader from "@/components/shell/page-header";
import TradesTable from "@/components/trades-table";
import ReconciliationPanel from "@/components/reconciliation-panel";

export default function PositionsPage() {
  return (
    <>
      <PageHeader
        title="Positions"
        subtitle="Positions ouvertes et historique des trades"
      />

      <div className="space-y-6">
        <ReconciliationPanel />
        <TradesTable
          title="Positions ouvertes"
          subtitle="Trades actuellement en cours"
          onlyOpen
          limit={50}
        />
        <TradesTable
          title="Historique complet"
          subtitle="50 trades les plus récents"
          limit={50}
        />
      </div>
    </>
  );
}
