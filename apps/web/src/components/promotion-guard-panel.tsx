"use client";

import { getPromotionEligibility } from "@/lib/api";
import { humanizeText, strategyLabel } from "@/lib/labels";
import { dateTime } from "@/lib/format";
import { usePolling } from "./use-polling";
import { SectionCard } from "./ui/card";

type GuardTone = "blocked" | "ok";

const TONE = {
  blocked: {
    label: "Bloquant",
    chip: "bg-down/10 text-down ring-down/20",
    dot: "bg-down",
  },
  ok: {
    label: "OK",
    chip: "bg-up/10 text-up ring-up/20",
    dot: "bg-up",
  },
} as const;

function GuardItem({
  title,
  detail,
  tone,
}: {
  title: string;
  detail: string;
  tone: GuardTone;
}) {
  const style = TONE[tone];
  return (
    <div className="rounded-lg border border-line-soft bg-surface-2/45 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 shrink-0 rounded-full ${style.dot}`} />
            <p className="text-sm font-medium text-ink">{title}</p>
          </div>
          <p className="mt-1 text-sm leading-relaxed text-muted">{detail}</p>
        </div>
        <span
          className={`shrink-0 rounded-md px-2 py-1 text-[11px] font-medium ring-1 ring-inset ${style.chip}`}
        >
          {style.label}
        </span>
      </div>
    </div>
  );
}

export default function PromotionGuardPanel() {
  const { data } = usePolling(getPromotionEligibility, 30000);
  const eligible = Boolean(data?.promotion_eligible);
  const checkedAt = data?.checked_at ? dateTime(data.checked_at) : "-";

  return (
    <SectionCard
      title="Verrous de promotion"
      subtitle="Contrat officiel du moteur avant toute activation live"
      action={
        <span
          className={`rounded-md px-2 py-1 text-[11px] font-medium ring-1 ring-inset ${
            eligible
              ? "bg-up/10 text-up ring-up/20"
              : "bg-down/10 text-down ring-down/20"
          }`}
        >
          {eligible ? "Promotion possible" : "Live interdit"}
        </span>
      }
    >
      <div className="mb-4 grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <p className="text-[11px] uppercase text-faint">Stratégie</p>
          <p className="mt-1 text-ink">{strategyLabel(data?.strategy)}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase text-faint">Environnement</p>
          <p className="mt-1 text-ink">{data?.capital_env ?? "demo"}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase text-faint">Dernier contrôle</p>
          <p className="tnum mt-1 text-ink">{checkedAt}</p>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        {(data?.requirements ?? []).map((item) => (
          <GuardItem
            key={item.code}
            tone={item.passed ? "ok" : "blocked"}
            title={item.label}
            detail={humanizeText(item.detail)}
          />
        ))}
      </div>
    </SectionCard>
  );
}
