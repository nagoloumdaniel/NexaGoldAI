import PageHeader from "@/components/shell/page-header";
import AiActivity from "@/components/ai-activity";
import DecisionsTable from "@/components/decisions-table";

export default function IaPage() {
  return (
    <>
      <PageHeader
        title="Centre IA"
        subtitle="Décisions, confiance et raisonnement du modèle"
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <AiActivity />
        </div>
        <div className="lg:col-span-2">
          <DecisionsTable limit={50} />
        </div>
      </div>
    </>
  );
}
