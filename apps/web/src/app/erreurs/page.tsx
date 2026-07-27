import PageHeader from "@/components/shell/page-header";
import ErrorBreakdownPanel from "@/components/error-breakdown-panel";
import TradeResultsTable from "@/components/trade-results-table";

export default function ErreursPage() {
  return (
    <>
      <PageHeader
        title="Erreurs & post-trade"
        subtitle="Qualité des décisions, excursions et causes des pertes"
      />
      <div className="space-y-6">
        <ErrorBreakdownPanel />
        <TradeResultsTable />
      </div>
    </>
  );
}
