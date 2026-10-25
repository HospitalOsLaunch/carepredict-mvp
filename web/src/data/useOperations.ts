import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import {
  operationsApi,
  type Workplace,
  type WorkCommand,
  type SubmittedCommand,
} from "../api/operations";
export interface OperationsWorkspace {
  data: Workplace | null;
  actorId: string;
  setActor: (id: string) => void;
  busy: boolean;
  error: string | null;
  submit: (command: WorkCommand) => void;
  refresh: () => void;
  retry: (() => void) | null;
}
export function useOperations(
  enabled: boolean,
  onChange: () => void,
): OperationsWorkspace {
  const [data, setData] = useState<Workplace | null>(null);
  const [actorId, setActor] = useState("bm-camille");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uncertain, setUncertain] = useState<SubmittedCommand | null>(null);
  const generation = useRef(0),
    mutating = useRef(false),
    reading = useRef(false),
    current = useRef<Workplace | null>(null);
  const uncertainRequest = useRef<SubmittedCommand | null>(null);
  const callback = useRef(onChange);
  callback.current = onChange;
  const refresh = useCallback(async () => {
    if (!enabled || mutating.current || reading.current) return;
    const token = ++generation.current;
    reading.current = true;
    try {
      const next = await operationsApi.read();
      if (token === generation.current) {
        current.current = next;
        setData(next);
        if (!uncertainRequest.current) setError(null);
      }
    } catch {
      if (token === generation.current)
        setError(
          "Le poste ne peut pas être actualisé. Aucune nouvelle opération ne sera envoyée.",
        );
    } finally {
      reading.current = false;
    }
  }, [enabled]);
  useEffect(() => {
    if (!enabled) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      window.clearInterval(timer);
      ++generation.current;
    };
  }, [enabled, refresh]);
  const send = useCallback(
    async (command: SubmittedCommand) => {
      if (!enabled || mutating.current) return;
      mutating.current = true;
      setBusy(true);
      ++generation.current;
      try {
        const next = await operationsApi.submit(command);
        current.current = next;
        setData(next);
        setError(null);
        setUncertain(null);
        uncertainRequest.current = null;
        callback.current();
      } catch (e) {
        if (e instanceof ApiError && [409, 404, 422].includes(e.status)) {
          uncertainRequest.current = null;
          setUncertain(null);
          setError(
            "Cette opération n’est plus applicable ou ne correspond pas à votre rôle. Actualisez et vérifiez le destinataire, le lit et la capacité.",
          );
        } else {
          uncertainRequest.current = command;
          setUncertain(command);
          setError(
            "Réponse non reçue. Vérifiez le journal ou réessayez la même demande : elle ne sera pas doublée.",
          );
        }
      } finally {
        mutating.current = false;
        setBusy(false);
      }
    },
    [enabled],
  );
  const submit = useCallback(
    (command: WorkCommand) => {
      const state = current.current;
      if (!state || busy || error || uncertain) return;
      void send({
        ...command,
        actor_id: actorId,
        revision: state.revision,
        tokens: state.tokens,
        request_id: crypto.randomUUID(),
      });
    },
    [actorId, busy, error, uncertain, send],
  );
  return {
    data,
    actorId,
    setActor,
    busy,
    error,
    submit,
    refresh: () => void refresh(),
    retry: uncertain ? () => void send(uncertain) : null,
  };
}
