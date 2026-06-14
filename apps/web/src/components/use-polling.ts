"use client";

import { useEffect, useState } from "react";

/** Fetch on mount and re-fetch on an interval. `fetcher` must be a stable
 * reference (declare it at module scope, not inline). */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs = 15000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const tick = () =>
      fetcher()
        .then((d) => {
          if (active) {
            setData(d);
            setError(null);
          }
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [fetcher, intervalMs]);

  return { data, error };
}
