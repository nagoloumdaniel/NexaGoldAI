"use client";

import { getModels, getSummary, getSystemStatus } from "@/lib/api";
import { strategyLabel } from "@/lib/labels";
import { usePolling } from "./use-polling";
import { SectionCard } from "./ui/card";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3001";

function Dot({ ok }: { ok: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-up" : "bg-down"}`} />
      {ok ? "Connecté" : "Injoignable"}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line-soft py-3 last:border-0">
      <span className="text-sm text-muted">{label}</span>
      <span className="text-right text-sm text-ink">{children}</span>
    </div>
  );
}

function BoolText({
  value,
  on,
  off,
  dangerWhenOn = false,
}: {
  value?: boolean | null;
  on: string;
  off: string;
  dangerWhenOn?: boolean;
}) {
  if (value == null) return <span className="text-faint">-</span>;
  return (
    <span className={value && dangerWhenOn ? "text-down" : "text-ink"}>
      {value ? on : off}
    </span>
  );
}

export default function SystemPanel() {
  const { error } = usePolling(getSummary, 10000);
  const { data: models } = usePolling(getModels, 30000);
  const { data: system } = usePolling(getSystemStatus, 10000);

  const apiOk = !error;
  const engineOk = Boolean(system?.engineReachable);
  const health = system?.health ?? null;
  const trade = system?.trade ?? null;
  const tradingEnabled = health?.trading_enabled ?? trade?.trading_enabled;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <SectionCard title="État des connexions" subtitle="Services locaux">
        <div className="-my-1">
          <Row label="API NestJS">
            <Dot ok={apiOk} />
          </Row>
          <Row label="Moteur de trading">
            <Dot ok={engineOk} />
          </Row>
          <Row label="Base moteur">
            <BoolText
              value={health?.database_connected}
              on="Connectée"
              off="Indisponible"
            />
          </Row>
          <Row label="Broker">
            <BoolText
              value={health?.broker_configured}
              on="Configuré"
              off="Non configuré"
            />
          </Row>
          <Row label="URL API">
            <code className="tnum text-xs text-faint">{API_URL}</code>
          </Row>
          <Row label="URL moteur">
            <code className="tnum text-xs text-faint">
              {system?.engineUrl ?? "http://localhost:8000"}
            </code>
          </Row>
        </div>
      </SectionCard>

      <SectionCard title="Configuration" subtitle="Paramètres en lecture seule">
        <div className="-my-1">
          <Row label="Instrument">{health?.symbol ?? "XAUUSD"} (XAU/USD)</Row>
          <Row label="Courtier">MetaTrader 5</Row>
          <Row label="Environnement">{health?.broker_env ?? "demo"}</Row>
          <Row label="Kill switch">
            <BoolText
              value={tradingEnabled}
              on="Ordres autorisés"
              off="Ordres bloqués"
              dangerWhenOn
            />
          </Row>
          <Row label="Ingestion">
            <BoolText
              value={health?.ingestion_running}
              on="Active"
              off="Arrêtée"
            />
          </Row>
          <Row label="Boucle trading">
            <BoolText
              value={trade?.loop_running}
              on="Active"
              off="Arrêtée"
            />
          </Row>
          <Row label="Stratégie">
            <span className="tnum text-xs">{strategyLabel(trade?.strategy)}</span>
          </Row>
          <Row label="Modèle champion">
            <span className="tnum text-xs">
              {models?.champion ?? "-"}
              {models?.granularity ? ` / ${models.granularity}` : ""}
            </span>
          </Row>
        </div>
      </SectionCard>

      <SectionCard
        title="À propos"
        subtitle="Bot personnel en local"
        className="lg:col-span-2"
      >
        <p className="text-sm leading-relaxed text-muted">
          NexaGold fonctionne actuellement comme un cockpit local de supervision.
          Les actions sensibles restent disponibles côté API, mais cette page met
          maintenant en avant l&apos;état réel du moteur et du kill switch avant toute
          décision opérationnelle.
        </p>
      </SectionCard>
    </div>
  );
}
