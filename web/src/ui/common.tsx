import { useEffect, useState } from "react";
import type { Assessment, Freshness } from "../domain/view";
import { age } from "../domain/view";

/** The state instant plus the time elapsed since it was received. */
export function useNow(a: Assessment | null, loadedAt: number): string | null {
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setTick(Date.now()), 15000);
    return () => window.clearInterval(id);
  }, []);
  if (!a) return null;
  // Anchor on the server's reconstruction instant: client and server clocks may differ,
  // and demonstration states are pinned in time.
  return new Date(Date.parse(a.state.at) + Math.max(0, tick - loadedAt)).toISOString();
}

/** Age of a fact. The ink fades with age; only the backend can declare it stale. */
export function Fresh({ f, prefix }: { f: Freshness | undefined; prefix?: string }) {
  if (!f) return <span className="fresh mute">âge inconnu</span>;
  if (f.stale) {
    return (
      <span className="fresh fresh--stale" title={f.key}>
        {prefix}périmée{Number.isNaN(f.minutes) ? "" : ` (${age(f.minutes)})`}
      </span>
    );
  }
  return (
    <span className={`fresh${f.ageing ? " fresh--ageing" : ""}`} title={`${f.key} · source ${f.source}`}>
      {prefix}
      {age(f.minutes)}
    </span>
  );
}

export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return;
    const id = window.setTimeout(onDone, 3200);
    return () => window.clearTimeout(id);
  }, [message, onDone]);
  return (
    <div aria-live="polite" role="status">
      {message ? <div className="toast">{message}</div> : null}
    </div>
  );
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n > 1 ? many : one}`;
}
