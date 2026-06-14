import type { ReactNode } from "react";

/** Surface de base : carte sobre, bord fin, coins arrondis. */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-line bg-surface ${className}`}
    >
      {children}
    </div>
  );
}

/** Carte avec en-tête de section (titre + sous-titre + action optionnelle). */
export function SectionCard({
  title,
  subtitle,
  action,
  children,
  className = "",
  bodyClassName = "p-5",
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <Card className={className}>
      <div className="flex items-start justify-between gap-4 border-b border-line-soft px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {subtitle ? (
            <p className="mt-0.5 text-xs text-faint">{subtitle}</p>
          ) : null}
        </div>
        {action}
      </div>
      <div className={bodyClassName}>{children}</div>
    </Card>
  );
}

const TONE_CLASS = {
  up: "text-up",
  down: "text-down",
  gold: "text-gold",
  ink: "text-ink",
} as const;

/** Indicateur clé : libellé discret en capitales + grande valeur chiffrée. */
export function Stat({
  label,
  value,
  hint,
  tone = "ink",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: keyof typeof TONE_CLASS;
}) {
  return (
    <Card className="p-5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-faint">
        {label}
      </p>
      <p className={`tnum mt-2 text-2xl font-semibold ${TONE_CLASS[tone]}`}>
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </Card>
  );
}

/** Bloc vide cohérent quand aucune donnée n'est disponible. */
export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-2 text-sm text-muted">{children}</p>;
}
