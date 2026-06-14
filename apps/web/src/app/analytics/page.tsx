import PageHeader from "@/components/shell/page-header";
import AnalyticsCards from "@/components/analytics-cards";
import TradesTable from "@/components/trades-table";
import { EquityChart } from "@/components/charts";
import { SectionCard } from "@/components/ui/card";

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader
        title="Analytics"
        subtitle="Performance calculée sur les trades clôturés"
      />

      <div className="space-y-6">
        <AnalyticsCards />
        <SectionCard
          title="Courbe d'équité"
          subtitle="NAV — jusqu'à 500 derniers snapshots"
        >
          <EquityChart height={360} />
        </SectionCard>
        <TradesTable
          title="Trades clôturés récents"
          subtitle="50 trades les plus récents"
          limit={50}
        />
      </div>
    </>
  );
}
