import PageHeader from "@/components/shell/page-header";
import ModelsPanel from "@/components/models-panel";
import PaperValidationPanel from "@/components/paper-validation-panel";
import RegimeShadowPanel from "@/components/regime-shadow-panel";
import PromotionGuardPanel from "@/components/promotion-guard-panel";

export default function ModelesPage() {
  return (
    <>
      <PageHeader
        title="Modèles & apprentissage"
        subtitle="Registre des versions et champion actif"
      />
      <div className="space-y-6">
        <PromotionGuardPanel />
        <div className="grid gap-6 lg:grid-cols-2">
          <PaperValidationPanel />
          <RegimeShadowPanel />
        </div>
        <ModelsPanel />
      </div>
    </>
  );
}
