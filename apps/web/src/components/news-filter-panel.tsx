"use client";

import { getNewsStatus, type NewsEvent } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { newsImpactLabel } from "@/lib/labels";
import { usePolling } from "./use-polling";
import { Empty, SectionCard } from "./ui/card";

function EventRow({ event }: { event: NewsEvent }) {
  const high = event.impact === "HIGH";
  return (
    <li className="flex items-start justify-between gap-3 border-b border-line-soft py-2 last:border-0">
      <div className="min-w-0">
        <p className="truncate text-sm text-ink">{event.title}</p>
        <p className="text-xs text-faint">
          {event.currency} — {newsImpactLabel(event.impact)}
        </p>
      </div>
      <span className="tnum shrink-0 text-xs text-muted">
        {dateTime(event.time)}
      </span>
      <span
        className={`shrink-0 rounded-md px-1.5 py-0.5 text-[11px] ring-1 ring-inset ${
          high
            ? "bg-down/10 text-down ring-down/20"
            : "bg-warn/10 text-warn ring-warn/20"
        }`}
      >
        {high ? "Bloquant" : "Surveillé"}
      </span>
    </li>
  );
}

export default function NewsFilterPanel() {
  const { data, error } = usePolling(getNewsStatus, 60000);
  const unreachable = Boolean(error) || data?.engineReachable === false;
  const verdict = data?.verdict ?? null;
  const upcoming = data?.upcoming_24h ?? [];

  return (
    <SectionCard
      title="Filtre d'annonces"
      subtitle="Blocage préventif autour des publications économiques"
      action={
        verdict ? (
          <span
            className={`rounded-md px-2 py-1 text-xs font-semibold ring-1 ring-inset ${
              verdict.blocked
                ? "bg-warn/10 text-warn ring-warn/20"
                : "bg-up/10 text-up ring-up/20"
            }`}
          >
            {verdict.blocked ? "Entrées bloquées" : "Entrées permises"}
          </span>
        ) : undefined
      }
    >
      {unreachable ? (
        <Empty>Moteur injoignable — état du filtre inconnu.</Empty>
      ) : (
        <>
          <p className="text-sm text-muted">{verdict?.reason ?? "—"}</p>
          <p className="mt-1 text-xs text-faint">
            Source : {data?.provider ?? "—"} — {data?.events_cached ?? 0} événements
            en cache, mis à jour le {dateTime(data?.fetched_at)}
            {data?.last_error ? " (dernier rafraîchissement en échec)" : ""}
          </p>

          <div className="mt-4">
            <p className="text-[11px] uppercase text-faint">
              Prochaines annonces (24 h)
            </p>
            {upcoming.length === 0 ? (
              <Empty>Aucune annonce suivie dans les 24 prochaines heures.</Empty>
            ) : (
              <ul className="mt-1">
                {upcoming.slice(0, 8).map((event) => (
                  <EventRow key={`${event.time}-${event.title}`} event={event} />
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </SectionCard>
  );
}
