import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, RotateCcw, SlidersHorizontal } from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { AgentStatus, AgentTask } from "../api/types";
import { useAuth } from "../auth";
import { ErrorNote, Spinner } from "../components/common";
import { TASK_STATUS } from "../lib/agent";
import { TASKS } from "../lib/engines";
import { fmtDateTime, fmtNum } from "../lib/format";

function useAgentStatus() {
  return useQuery({
    queryKey: ["agent", "status"],
    queryFn: () => api<AgentStatus>("/agent/status"),
    refetchInterval: 30_000
  });
}

/**
 * The engines and the routing are set on the Agents screen, next to the workers and the
 * connections they serve; here, the way there and the agent's last tasks (retry, by hand).
 */
export function AgentTab() {
  const status = useAgentStatus();
  return (
    <div className="space-y-6">
      <Link
        to="/agents#moteurs"
        className="panel flex items-center gap-4 px-5 py-4 transition-shadow hover:ring-2 hover:ring-violet"
      >
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-violet-soft text-violet-dark">
          <SlidersHorizontal className="h-5 w-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-display text-[17px] font-bold">Moteurs et routage</span>
          <span className="block text-[14px] text-ink-soft">
            Ont déménagé dans l'écran Agents : ordre des moteurs par tâche, autorisations, budgets, état sur chaque poste.
          </span>
        </span>
        <ArrowRight className="h-5 w-5 shrink-0" aria-hidden />
      </Link>
      {status.isLoading ? <Spinner /> : status.error ? <ErrorNote error={status.error} /> : status.data ? <RecentTasks tasks={status.data.recent} /> : null}
    </div>
  );
}

function fmtUsd(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("fr-FR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function RecentTasks({ tasks }: { tasks: AgentTask[] }) {
  const { canWrite } = useAuth();
  const queryClient = useQueryClient();
  const act = useMutation({
    mutationFn: ({ id, what }: { id: number; what: "retry" | "manual" }) =>
      api<AgentTask>(`/agent/tasks/${id}/${what}`, { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["agent"] })
  });
  return (
    <section aria-labelledby="recent-tasks">
      <h2 id="recent-tasks">Dernières tâches</h2>
      {act.error && (
        <div className="mt-3">
          <ErrorNote error={act.error} />
        </div>
      )}
      {tasks.length === 0 ? (
        <p className="mt-3 text-ink-soft">
          Aucune tâche pour l'instant. Les réponses aux demandes venues d'un portail et les relèves programmées
          apparaîtront ici.
        </p>
      ) : (
        <div className="panel relative mt-4 overflow-x-auto">
          <table className="w-full min-w-[860px] text-[14px]">
            <caption className="sr-only">Dernières tâches de l'agent</caption>
            <thead>
              <tr className="border-b border-line text-left text-[12px] text-ink-faint">
                <th className="px-5 py-3 font-normal">Tâche</th>
                <th className="px-2 py-3 font-normal">État</th>
                <th className="px-2 py-3 font-normal">Parcours des moteurs</th>
                <th className="px-2 py-3 text-right font-normal">Coût</th>
                <th className="px-5 py-3 font-normal">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => {
                const st = TASK_STATUS[t.status] ?? { text: t.status, tone: "bg-sky-deep" };
                const stuck = t.status === "needs_human" || t.status === "failed";
                return (
                  <tr key={t.id} className="border-b border-line align-top last:border-0">
                    <td className="px-5 py-3">
                      <p className="font-bold">{TASKS[t.kind]?.title ?? t.kind}</p>
                      <p className="text-[12px] text-ink-faint">
                        {fmtDateTime(t.updated_at)}
                        {t.request_id ? `, demande n° ${t.request_id}` : ""}
                        {t.result?.created != null ? `, ${t.result.created} nouvelle(s)` : ""}
                      </p>
                    </td>
                    <td className="px-2 py-3">
                      <span className={`chip ${st.tone}`}>{st.text}</span>
                      {t.status === "pending" && t.available_at && <p className="mt-1 text-[12px] text-ink-soft">Nouvel essai après {fmtDateTime(t.available_at)}</p>}
                      {stuck && t.reconcile_only && <p className="mt-1 max-w-[260px] text-[12px] text-ink-soft">La reprise vérifie la réponse enregistrée, sans la renvoyer.</p>}
                      {t.error && stuck && <p className="mt-1 max-w-[260px] text-[12px] text-ink-soft">{t.error}</p>}
                    </td>
                    <td className="px-2 py-3">
                      <ol className="flex flex-wrap items-center gap-1 text-[12px]">
                        {(t.result?.route ?? []).map((step, i) => (
                          <li
                            key={i}
                            title={step.reason ?? step.error ?? undefined}
                            className={`chip ${
                              step.decision === "success"
                                ? "bg-lagoon-soft text-lagoon-dark"
                                : step.decision === "ignoré"
                                  ? "bg-sky text-ink-faint line-through"
                                  : "bg-coral-soft text-coral-dark"
                            }`}
                          >
                            {step.engine}
                          </li>
                        ))}
                        {!t.result?.route?.length && <li className="text-ink-faint">—</li>}
                      </ol>
                    </td>
                    <td className="num px-2 py-3 text-right">{t.cost_usd ? fmtUsd(t.cost_usd, 3) : "0"}</td>
                    <td className="px-5 py-3 text-right">
                      {canWrite && stuck && (
                        <div className="flex justify-end gap-2">
                          <button
                            className="btn-quiet px-3 py-1.5 text-[13px]"
                            disabled={act.isPending}
                            onClick={() => act.mutate({ id: t.id, what: "retry" })}
                          >
                            <RotateCcw className="h-3.5 w-3.5" aria-hidden /> {t.reconcile_only ? "Vérifier le portail" : "Relancer"}
                          </button>
                          <button
                            className="btn-quiet px-3 py-1.5 text-[13px]"
                            disabled={act.isPending}
                            onClick={() => act.mutate({ id: t.id, what: "manual" })}
                          >
                            Fait à la main
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-[13px] text-ink-faint">
        {fmtNum(tasks.length)} tâches affichées, les plus récentes d'abord.
      </p>
    </section>
  );
}
