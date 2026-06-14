import PageHeader from "@/components/shell/page-header";
import MarketStats from "@/components/market-stats";
import { PriceChart } from "@/components/charts";
import { SectionCard } from "@/components/ui/card";

export default function MarchePage() {
  return (
    <>
      <PageHeader
        title="Marché"
        subtitle="Or — XAU/USD (GOLD · Capital.com)"
      />

      <div className="space-y-6">
        <MarketStats />
        <SectionCard
          title="Graphique"
          subtitle="Bougies OHLC ingérées en base de données"
        >
          <PriceChart selectable height={460} />
        </SectionCard>
      </div>
    </>
  );
}
