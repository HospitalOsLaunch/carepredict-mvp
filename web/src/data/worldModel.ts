import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { worldApi, type WmSession } from "../api/worldModel";

const namespace = "hospitalos.world-model.v1.";
const pendingStorage = new Map<string, string>();
export function remembered(key: string): string | null {
  if (pendingStorage.has(key)) return pendingStorage.get(key)!;
  try { return window.localStorage.getItem(namespace + key); }
  catch { return null; }
}
export function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(namespace + key, value);
    pendingStorage.delete(key);
  } catch { pendingStorage.set(key, value); }
}

type Ticket = { id: string; saved: boolean };
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function newTicket(context: string): Ticket {
  let id: string;
  if (typeof crypto.randomUUID === "function") id = crypto.randomUUID();
  else {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6]! & 0x0f) | 0x40;
    bytes[8] = (bytes[8]! & 0x3f) | 0x80;
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
    id = [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
  }
  const ticket = { id, saved: false };
  remember("session." + context, JSON.stringify(ticket));
  return ticket;
}
function storedTicket(context: string): Ticket | null {
  try {
    const t: unknown = JSON.parse(remembered("session." + context) ?? "null");
    if (t && typeof t === "object" && "id" in t && typeof t.id === "string" && uuidPattern.test(t.id) &&
        "saved" in t && typeof t.saved === "boolean") return { id: t.id, saved: t.saved };
  } catch { /* an invalid local pointer cannot restore a session */ }
  return null;
}

export function hasWorldSession() {
  const context = remembered("active-context");
  return Boolean(context && storedTicket(context)?.saved);
}

export function worldError(e: unknown) {
  if (e instanceof ApiError) {
    if (e.status === 404) return "Ce parcours est introuvable. Vous pouvez ouvrir un nouveau parcours.";
    return e.detail || "Le serveur a refusé cette opération.";
  }
  if (e instanceof TypeError) return "Connexion au simulateur indisponible. Vérifiez la connexion puis réessayez.";
  if (e instanceof DOMException && e.name === "AbortError") return "Le simulateur met du temps à répondre. Actualisez le parcours.";
  return e instanceof Error ? e.message : "Impossible de joindre le simulateur.";
}

export function useWorldSession(context: string) {
  const [state, setState] = useState<WmSession | null>(null);
  const [busy, setBusy] = useState<"load" | "confirm" | "advance" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const active = useRef<AbortController | null>(null);
  const lastState = useRef<WmSession | null>(null);
  const accept = useCallback((session: WmSession) => {
    lastState.current = session;
    setState(session);
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    active.current = ctrl;
    const t = storedTicket(context) ?? newTicket(context);
    setBusy("load");
    setError(null);
    const request = t.saved ? worldApi.read(t.id, context, ctrl.signal) : worldApi.open(t.id, context, ctrl.signal);
    request.then((next) => {
      if (ctrl.signal.aborted || active.current !== ctrl) return;
      remember("session." + context, JSON.stringify({ id: next.id, saved: true }));
      remember("active-context", context);
      accept(next);
    }).catch((e: unknown) => {
      if (!ctrl.signal.aborted && active.current === ctrl) setError(worldError(e));
    }).finally(() => {
      if (active.current === ctrl) { active.current = null; setBusy(null); }
    });
    return () => {
      ctrl.abort();
      active.current?.abort();
      active.current = null;
    };
  }, [context, version, accept]);

  const reload = () => {
    if (active.current) return;
    active.current = new AbortController();
    setBusy("load");
    setVersion((v) => v + 1);
  };
  const restart = () => {
    if (active.current) return;
    active.current = new AbortController();
    newTicket(context);
    lastState.current = null;
    setState(null);
    setBusy("load");
    setVersion((v) => v + 1);
  };
  async function mutate(kind: "confirm" | "advance", optionId?: string) {
    const current = lastState.current;
    if (!current || active.current || error) return;
    if (kind === "confirm" && (current.phase !== "planning" || !current.options.some((o) => o.id === optionId))) return;
    if (kind === "advance" && current.phase !== "confirmed" && current.phase !== "awaiting_report") return;
    const ctrl = new AbortController();
    active.current = ctrl;
    setBusy(kind);
    setError(null);
    try {
      const next = kind === "confirm"
        ? await worldApi.confirm(current.id, context, optionId!, ctrl.signal)
        : await worldApi.advance(current.id, context, current.phase === "awaiting_report" ? 16 : 12, ctrl.signal);
      if (!ctrl.signal.aborted && active.current === ctrl) accept(next);
    } catch (e) {
      if (!ctrl.signal.aborted && active.current === ctrl) setError(worldError(e));
    } finally {
      if (active.current === ctrl) { active.current = null; setBusy(null); }
    }
  }
  return { state, busy, error, reload, restart, confirm: (id: string) => mutate("confirm", id), advance: () => mutate("advance") };
}
