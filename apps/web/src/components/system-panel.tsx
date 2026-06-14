"use client";

import { getSummary, getModels } from "@/lib/api";
import { usePolling } from "./use-polling";
import { SectionCard } from "./ui/card";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3001";

function Dot({ ok }: { ok: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span
        className={`h-2 w-2 rounded-full ${ok ? "bg-up" : "bg-down"}`}
      />
      {ok ? "Connecté" : "Injoignable"}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-line-soft py-3 last:border-0">
      <span className="text-sm text-muted">{label}</span>
      <span className="text-sm text-ink">{children}</span>
    </div>
  );
}

export default function SystemPanel() {
  const { data: summary, error } = usePolling(getSummary, 10000);
  const { data: models } = usePolling(getModels, 30000);

  const apiOk = !error;
  const engineOk = !error && summary?.account != null;

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
          <Row label="URL de l'API">
            <code className="tnum text-xs text-faint">{API_URL}</code>
          </Row>
        </div>
      </SectionCard>

      <SectionCard title="Configuration" subtitle="Paramètres en lecture seule">
        <div className="-my-1">
          <Row label="Instrument">XAU/USD (GOLD)</Row>
          <Row label="Courtier">Capital.com</Row>
          <Row label="Environnement">Démo · paper trading</Row>
          <Row label="Modèle champion">
            <span className="tnum text-xs">
              {models?.champion ?? "—"}
              {models?.granularity ? ` · ${models.granularity}` : ""}
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
          NexaGold fonctionne en local sans compte utilisateur. Les modules de
          gestion de capital (dépôts / retraits), les alertes externes et
          l&apos;authentification 2FA ne sont pas activés car ils ne sont pas
          nécessaires à un usage personnel — ils pourront être ajoutés si le bot
          est un jour hébergé et multi-utilisateurs.
        </p>
      </SectionCard>
    </div>
  );
}
