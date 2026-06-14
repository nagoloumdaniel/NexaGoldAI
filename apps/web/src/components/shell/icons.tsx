import type { SVGProps } from "react";

/* Jeu d'icônes minimal (stroke) — pas de dépendance externe. */

const base = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} satisfies SVGProps<SVGSVGElement>;

export type IconName =
  | "dashboard"
  | "market"
  | "positions"
  | "ai"
  | "models"
  | "analytics"
  | "settings";

export function Icon({ name }: { name: IconName }) {
  switch (name) {
    case "dashboard":
      return (
        <svg {...base}>
          <rect x="3" y="3" width="7" height="9" rx="1.5" />
          <rect x="14" y="3" width="7" height="5" rx="1.5" />
          <rect x="14" y="12" width="7" height="9" rx="1.5" />
          <rect x="3" y="16" width="7" height="5" rx="1.5" />
        </svg>
      );
    case "market":
      return (
        <svg {...base}>
          <path d="M3 17l5-5 4 3 8-9" />
          <path d="M21 6h-4M21 6v4" />
        </svg>
      );
    case "positions":
      return (
        <svg {...base}>
          <path d="M3 6h18M3 12h18M3 18h18" />
          <circle cx="8" cy="6" r="1.4" fill="currentColor" stroke="none" />
          <circle cx="15" cy="12" r="1.4" fill="currentColor" stroke="none" />
          <circle cx="11" cy="18" r="1.4" fill="currentColor" stroke="none" />
        </svg>
      );
    case "ai":
      return (
        <svg {...base}>
          <rect x="5" y="7" width="14" height="12" rx="2.5" />
          <path d="M12 7V4M9 3h6M9 12h.01M15 12h.01M9 16h6" />
        </svg>
      );
    case "models":
      return (
        <svg {...base}>
          <circle cx="6" cy="6" r="2.5" />
          <circle cx="18" cy="6" r="2.5" />
          <circle cx="12" cy="18" r="2.5" />
          <path d="M8 7.5l3 8M16 7.5l-3 8M8 6h8" />
        </svg>
      );
    case "analytics":
      return (
        <svg {...base}>
          <path d="M4 4v16h16" />
          <rect x="7" y="11" width="3" height="6" rx="0.5" />
          <rect x="13" y="7" width="3" height="10" rx="0.5" />
        </svg>
      );
    case "settings":
      return (
        <svg {...base}>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" />
        </svg>
      );
  }
}
