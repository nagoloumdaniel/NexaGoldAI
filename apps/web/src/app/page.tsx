import PageHeader from "@/components/shell/page-header";
import StatsCards from "@/components/stats-cards";
import DecisionsTable from "@/components/decisions-table";
import TradesTable from "@/components/trades-table";
import AiActivity from "@/components/ai-activity";
import { EquityChart } from "@/components/charts";
import { SectionCard } from "@/components/ui/card";

export default function Home() {
  return (
    <>
      <PageHeader
        title="Tableau de bord"
        subtitle="Vue d'ensemble de votre robot de trading IA"
        action={
          <span className="rounded-md bg-gold/10 px-3 py-1 text-xs font-medium text-gold ring-1 ring-inset ring-gold/20">
            Paper trading · XAU/USD
          </span>
        }
      />

      <div className="space-y-6">
        <StatsCards />

        <div className="grid gap-6 lg:grid-cols-3">
          <SectionCard
            title="Évolution de l'équité"
            subtitle="NAV du compte dans le temps"
            className="lg:col-span-2"
          >
            <EquityChart height={300} />
          </SectionCard>
          <AiActivity />
        </div>

        <div className="grid gap-6 xl:grid-cols-2">
          <DecisionsTable limit={8} showReason={false} />
          <TradesTable limit={8} subtitle="8 trades les plus récents" />
        </div>
      </div>
    </>
  );
}
