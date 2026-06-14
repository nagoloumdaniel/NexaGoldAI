import PageHeader from "@/components/shell/page-header";
import ModelsPanel from "@/components/models-panel";

export default function ModelesPage() {
  return (
    <>
      <PageHeader
        title="Modèles & apprentissage"
        subtitle="Registre des versions et champion actif"
      />
      <ModelsPanel />
    </>
  );
}
