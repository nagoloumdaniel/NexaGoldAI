"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./icons";

const ITEMS: { href: string; label: string; icon: IconName }[] = [
  { href: "/", label: "Tableau de bord", icon: "dashboard" },
  { href: "/marche", label: "Marché", icon: "market" },
  { href: "/positions", label: "Positions", icon: "positions" },
  { href: "/ia", label: "Centre IA", icon: "ai" },
  { href: "/modeles", label: "Modèles", icon: "models" },
  { href: "/analytics", label: "Analytics", icon: "analytics" },
  { href: "/parametres", label: "Système", icon: "settings" },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

/** En-tête + onglets horizontaux, affichés sous lg en remplacement de la sidebar. */
export default function MobileNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur lg:hidden">
      <div className="flex items-center gap-2 px-4 py-3">
        <Image
          src="/nexagold.png"
          alt="NexaGold"
          width={400}
          height={533}
          priority
          className="h-7 w-auto"
        />
        <span className="text-base font-semibold tracking-tight">
          <span className="text-gold">Nexa</span>
          <span className="text-ink">Gold</span>
        </span>
      </div>
      <nav className="flex gap-1 overflow-x-auto px-2 pb-2">
        {ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-colors ${
                active
                  ? "bg-surface-2 font-medium text-gold"
                  : "text-muted hover:text-ink"
              }`}
            >
              <Icon name={item.icon} />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
