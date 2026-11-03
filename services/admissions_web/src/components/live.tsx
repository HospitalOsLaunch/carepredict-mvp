import { useEffect, useRef, useState } from "react";

import { fmtDateTime, fmtNum, fmtRelative } from "../lib/format";

/** How long a change stays visible: long enough to be seen after an interruption. One neutral
 * colour whatever the sign: a fall can be good news (fewer patients waiting) or bad (fewer free
 * beds), so the sign says what moved and the figure says what it means. */
const DELTA_MS = 2 * 60_000;

/**
 * A live count (beds, patients): when a refresh changes it, the figure glows once and a
 * signed delta stays beside it for two minutes, so whoever looks back after a phone call
 * sees at a glance what moved. Never on the first display.
 */
export function LiveNumber({
  value,
  scope = "",
  format = fmtNum
}: {
  value: number;
  /** What the figure counts (site, unit…): a new scope is a new figure, not a change. */
  scope?: string;
  format?: (n: number) => string;
}) {
  const previous = useRef({ value, scope });
  const [delta, setDelta] = useState<{ by: number; key: number } | null>(null);

  useEffect(() => {
    const before = previous.current;
    previous.current = { value, scope };
    if (scope !== before.scope) {
      setDelta(null);
      return;
    }
    if (value === before.value) return;
    const by = value - before.value;
    setDelta((d) => ({ by, key: (d?.key ?? 0) + 1 }));
    const timer = setTimeout(() => setDelta(null), DELTA_MS);
    return () => clearTimeout(timer);
  }, [value, scope]);

  const up = (delta?.by ?? 0) > 0;
  return (
    <span className="inline-flex items-baseline gap-2" data-changed={delta ? "true" : undefined}>
      <span key={delta?.key} className={delta ? "live-changed rounded-md" : undefined}>
        {format(value)}
      </span>
      {delta && (
        <span
          data-testid="delta"
          title={`En ${up ? "hausse" : "baisse"} de ${Math.abs(delta.by)} depuis la dernière mise à jour`}
          className="chip num align-middle bg-violet-soft text-[13px] text-violet-dark"
        >
          {up ? "+" : "−"}
          {fmtNum(Math.abs(delta.by))}
        </span>
      )}
    </span>
  );
}

/** True for a moment after `value` changes (never on first display): to flag a live update. */
export function useChanged(value: unknown, ms = 4000): boolean {
  const previous = useRef(value);
  const [changed, setChanged] = useState(false);
  useEffect(() => {
    if (Object.is(value, previous.current)) return;
    previous.current = value;
    setChanged(true);
    const timer = setTimeout(() => setChanged(false), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return changed;
}

/** Re-renders every `ms` so relative times keep moving. */
export function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [ms]);
  return now;
}

/**
 * When the data on screen was computed, in words people use (« il y a 3 minutes »), with a
 * clear warning when it no longer follows the refresh (network cut, API down): a bed board
 * that silently freezes is worse than none.
 */
export function Freshness({ at, staleAfterMs, now }: { at: string | null | undefined; staleAfterMs: number; now?: number }) {
  const ticking = useNow();
  const current = now ?? ticking;
  if (!at) return null;
  const stale = current - new Date(at).getTime() > staleAfterMs;
  return (
    <p
      className={`inline-flex items-center gap-2 rounded-chip px-3 py-1 text-[13px] ${
        stale ? "bg-sun-soft font-bold text-ink" : "text-ink-faint"
      }`}
      title={`Calculé le ${fmtDateTime(at)}`}
    >
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${stale ? "bg-sun" : "bg-lagoon"}`}
      />
      <span className="font-bold">{stale ? "Données en retard" : "À jour"}</span>
      <span>· {fmtRelative(at, current)}</span>
    </p>
  );
}
