import PageHeader from "@/components/shell/page-header";
import ModelsPanel from "@/components/models-panel";
import PaperValidationPanel from "@/components/paper-validation-panel";

export default function ModelesPage() {
  return (
    <>
      <PageHeader
        title="Modèles & apprentissage"
        subtitle="Registre des versions et champion actif"
      />
      <div className="space-y-6">
        <PaperValidationPanel />
        <ModelsPanel />
      </div>
    </>
  );
}
