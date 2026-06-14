const ACTION_STYLE: Record<string, string> = {
  BUY: "bg-up/10 text-up ring-up/20",
  SELL: "bg-down/10 text-down ring-down/20",
  HOLD: "bg-muted/10 text-muted ring-muted/20",
};

/** Pastille d'action IA / sens de trade (BUY / SELL / HOLD). */
export function ActionBadge({ action }: { action: string }) {
  const style = ACTION_STYLE[action] ?? ACTION_STYLE.HOLD;
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${style}`}
    >
      {action}
    </span>
  );
}

const STATUS_STYLE: Record<string, string> = {
  OPEN: "bg-ai/10 text-ai ring-ai/20",
  CLOSED: "bg-muted/10 text-muted ring-muted/20",
  CANCELLED: "bg-warn/10 text-warn ring-warn/20",
};

const STATUS_LABEL: Record<string, string> = {
  OPEN: "Ouverte",
  CLOSED: "Fermée",
  CANCELLED: "Annulée",
};

/** Pastille de statut de trade. */
export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLE[status] ?? STATUS_STYLE.CLOSED;
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${style}`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** Barre de confiance IA (0–1) avec valeur en pourcentage. */
export function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
        <div
          className="h-full rounded-full bg-gold"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="tnum text-xs text-muted">{pct} %</span>
    </div>
  );
}
