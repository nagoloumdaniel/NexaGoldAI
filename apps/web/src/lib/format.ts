/** Formatters partagés (locale fr-FR). Centralisés pour un rendu cohérent. */

export function num(n?: number | null, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function money(n?: number | null, currency = "", digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${num(n, digits)} ${currency}`.trim();
}

/** Valeur déjà en pourcentage (ex. 12.5 → "12,5 %"). */
export function pct(n?: number | null, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${num(n, digits)} %`;
}

/** Ratio 0–1 → pourcentage (ex. 0.62 → "62 %"). */
export function ratioPct(n?: number | null, digits = 0): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${num(n * 100, digits)} %`;
}

/** Préfixe le signe + pour les valeurs positives (P&L). */
export function signed(n?: number | null, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  const s = num(Math.abs(n), digits);
  return n >= 0 ? `+${s}` : `-${s}`;
}

export function tone(n?: number | null): "up" | "down" | "flat" {
  if (n == null || Number.isNaN(n) || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

/** Variante pour le composant Stat : "flat" et null retombent sur "ink". */
export function pnlTone(n?: number | null): "up" | "down" | "ink" {
  const t = tone(n);
  return t === "flat" ? "ink" : t;
}

export function time(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function dateTime(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
