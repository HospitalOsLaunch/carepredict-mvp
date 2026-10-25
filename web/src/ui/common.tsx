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

export interface ToastState {
  message: string;
  /** Offered for a few seconds after a decision: one tap puts things back. */
  undo?: () => void;
}

export function Toast({ toast, onDone }: { toast: ToastState | null; onDone: () => void }) {
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(onDone, toast.undo ? 6000 : 3200);
    return () => window.clearTimeout(id);
  }, [toast, onDone]);
  return (
    <div aria-live="polite" role="status">
      {toast ? (
        <div className="toast">
          <span>{toast.message}</span>
          {toast.undo ? (
            <button
              type="button"
              className="toast__undo"
              onClick={() => {
                toast.undo?.();
                onDone();
              }}
            >
              Annuler
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n > 1 ? many : one}`;
}

/** Keep scoped backend identity, display the local identifier inside a selected unit. */
export function displayId(id: string): string {
  return id.replace(/^(geriatrie|medecine|pneumologie|chirurgie)-/, "");
}
