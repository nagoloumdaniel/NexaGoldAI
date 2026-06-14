"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./icons";
import RobotStatus from "./robot-status";

type NavItem = { href: string; label: string; icon: IconName };
type NavGroup = { title: string; items: NavItem[] };

const NAV: NavGroup[] = [
  {
    title: "Principal",
    items: [{ href: "/", label: "Tableau de bord", icon: "dashboard" }],
  },
  {
    title: "Trading",
    items: [
      { href: "/marche", label: "Marché", icon: "market" },
      { href: "/positions", label: "Positions", icon: "positions" },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { href: "/ia", label: "Centre IA", icon: "ai" },
      { href: "/modeles", label: "Modèles", icon: "models" },
    ],
  },
  {
    title: "Analyse",
    items: [{ href: "/analytics", label: "Analytics", icon: "analytics" }],
  },
  {
    title: "Système",
    items: [{ href: "/parametres", label: "Système", icon: "settings" }],
  },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-surface lg:flex">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <Image
          src="/nexagold.png"
          alt="NexaGold"
          width={400}
          height={533}
          priority
          className="h-8 w-auto"
        />
        <span className="text-lg font-semibold tracking-tight">
          <span className="text-gold">Nexa</span>
          <span className="text-ink">Gold</span>
        </span>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-2">
        {NAV.map((group) => (
          <div key={group.title}>
            <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-faint">
              {group.title}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActive(pathname, item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                        active
                          ? "bg-surface-2 font-medium text-ink"
                          : "text-muted hover:bg-surface-2/60 hover:text-ink"
                      }`}
                    >
                      <span
                        className={
                          active
                            ? "text-gold"
                            : "text-faint group-hover:text-muted"
                        }
                      >
                        <Icon name={item.icon} />
                      </span>
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-line-soft p-3">
        <RobotStatus />
      </div>
    </aside>
  );
}
