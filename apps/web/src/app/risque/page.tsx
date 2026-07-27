import PageHeader from "@/components/shell/page-header";
import RiskPanel from "@/components/risk-panel";
import NewsFilterPanel from "@/components/news-filter-panel";
import RiskDecisionsTable from "@/components/risk-decisions-table";
import SystemEventsTable from "@/components/system-events-table";

export default function RisquePage() {
  return (
    <>
      <PageHeader
        title="Risque & protections"
        subtitle="Limites, kill switch, filtre d'annonces et journal des blocages"
      />
      <div className="space-y-6">
        <RiskPanel />
        <NewsFilterPanel />
        <RiskDecisionsTable />
        <SystemEventsTable />
      </div>
    </>
  );
}
