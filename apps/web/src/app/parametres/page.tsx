import PageHeader from "@/components/shell/page-header";
import SystemPanel from "@/components/system-panel";

export default function SystemePage() {
  return (
    <>
      <PageHeader
        title="Système"
        subtitle="État des services et configuration"
      />
      <SystemPanel />
    </>
  );
}
