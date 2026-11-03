import {
  BedDouble,
  ChevronDown,
  Clapperboard,
  Eye,
  Globe,
  Monitor,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  SlidersHorizontal,
  TriangleAlert
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import type { ConnectionAction, ConnectionOut, WorkerOut } from "../api/types_agent";
import { useAuth } from "../auth";
import { LiveDot } from "../components/AgentPlayer";
import { ConnectionForm, WEEKDAYS } from "../components/ConnectionForm";
import { Empty, ErrorNote, Modal, PageHeader, Spinner } from "../components/ui";
import {
  KIND_LABEL,
  TASK_LABEL,
  TASK_STATUS,
  useAgentStatus,
  useConnectionAction,
  useConnectionRuns,
  useConnections,
  useGroupPause,
  useTaskAction,
  useWorkers
} from "../lib/agent";
import { fmtDateTime, fmtRelative } from "../lib/format";

const DONE: Record<ConnectionAction, (name: string) => string> = {
  start: (n) => `« ${n} » est démarrée : première relève au prochain signal du poste.`,
  pause: (n) => `« ${n} » est en pause : plus aucune relève jusqu'à la reprise.`,
  resume: (n) => `« ${n} » reprend : prochaine relève au prochain signal du poste.`,
  sync: (n) => `Relève demandée pour « ${n} » : le poste s'en charge à son prochain signal.`
};

const OUTCOME: Record<string, string> = {
  success: "réussi",
  done: "réussi",
  manual: "fait à la main",
  failure: "en échec",
  failed: "en échec",
  needs_human: "à reprendre",
  refused: "refusé"
};

export function ComputerUsePage() {
  const { isAdmin, canWrite } = useAuth();
  const status = useAgentStatus();
  const workers = useWorkers();
  const connections = useConnections();
  const action = useConnectionAction();
  const groupPause = useGroupPause();
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<ConnectionOut | "new" | null>(null);
  const [confirm, setConfirm] = useState<ConnectionOut | "group" | null>(null);

  const paused = status.data?.paused ?? false;
  const list = workers.data ?? [];
  const online = list.filter((w) => w.online).length;

  const run = (c: ConnectionOut, act: ConnectionAction) => {
    setNotice("");
    action.mutate({ id: c.id, action: act }, { onSuccess: () => setNotice(DONE[act](c.name)) });
  };
  const toggleGroup = (pause: boolean) =>
    groupPause.mutate(pause, {
      onSuccess: () =>
        setNotice(pause ? "Pause générale : toutes les connexions sont arrêtées." : "Pause générale levée : les connexions actives reprennent.")
    });

  return (
    <>
      <PageHeader
        title="Computer use"
        lead="L'agent lit vos logiciels comme le ferait une personne, établissement par établissement. Démarrez, mettez en pause ou relevez à la demande."
        actions={
          isAdmin && (
            <>
              <Link to="/parametres?rubrique=agent" className="btn-ghost">
                <SlidersHorizontal className="h-4 w-4" aria-hidden /> Routage, moteurs et budgets
              </Link>
              {paused ? (
                <button className="btn-primary" disabled={groupPause.isPending} onClick={() => toggleGroup(false)}>
                  <Play className="h-4 w-4" aria-hidden /> Lever la pause générale
                </button>
              ) : (
                <button className="btn bg-paper text-ink shadow-lift hover:bg-sun-soft" disabled={groupPause.isPending || !status.data} onClick={() => setConfirm("group")}>
                  <Pause className="h-4 w-4" aria-hidden /> Pause générale
                </button>
              )}
            </>
          )
        }
      />

      <AgentState loading={workers.isLoading} online={online} total={list.length} paused={paused} />

      {paused && (
        <div className="mb-6 flex items-start gap-3 rounded-panel bg-sun-soft px-5 py-4">
          <Pause className="mt-0.5 h-5 w-5 shrink-0 text-ink" aria-hidden />
          <div>
            <p className="font-bold">Pause générale en cours</p>
            <p className="text-[15px] text-ink-soft">
              Aucune connexion ne tourne et les commandes sont suspendues. {isAdmin ? "Levez la pause pour reprendre." : "Seul l'administrateur du groupe peut la lever."}
            </p>
          </div>
        </div>
      )}

      <p role="status" className={notice ? "mb-4 rounded-xl bg-lagoon-soft px-4 py-2 text-[15px] font-bold text-lagoon-dark" : "sr-only"}>
        {notice}
      </p>
      {(action.error || groupPause.error) && (
        <div className="mb-4">
          <ErrorNote error={action.error ?? groupPause.error} />
        </div>
      )}

      <section aria-labelledby="postes" className="mb-8">
        <h2 id="postes">Postes</h2>
        <p className="mt-1 text-[15px] text-ink-soft">Les machines de l'établissement qui exécutent l'agent.</p>
        <div className="mt-4">
          {workers.isLoading ? (
            <Spinner />
          ) : workers.error ? (
            <ErrorNote error={workers.error} />
          ) : list.length === 0 ? (
            <Empty title="Aucun poste n'a encore donné signe de vie">
              Installez l'agent sur une machine du réseau avec l'adresse de l'API, un compte de service « ingestion » et un nom de poste : il
              apparaîtra ici dès son premier signal.
            </Empty>
          ) : (
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {list.map((w) => (
                <WorkerCard key={w.agent_id} worker={w} />
              ))}
            </ul>
          )}
        </div>
      </section>

      <section aria-labelledby="connexions">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="connexions">Connexions</h2>
            <p className="mt-1 text-[15px] text-ink-soft">Un logiciel à lire pour un établissement, avec son script et son planning.</p>
          </div>
          {isAdmin && (
            <button className="btn-primary" onClick={() => setEditing("new")}>
              <Plus className="h-4 w-4" aria-hidden /> Nouvelle connexion
            </button>
          )}
        </div>
        <div className="mt-4 space-y-4">
          {connections.isLoading ? (
            <Spinner />
          ) : connections.error ? (
            <ErrorNote error={connections.error} />
          ) : (connections.data ?? []).length === 0 ? (
            <Empty title="Aucune connexion pour l'instant">
              {isAdmin
                ? "Créez la première : choisissez le logiciel, l'établissement, le script et le planning."
                : "L'administrateur du groupe crée les connexions ; vous pourrez ensuite les piloter ici."}
            </Empty>
          ) : (
            connections.data?.map((c) => (
              <ConnectionCard
                key={c.id}
                c={c}
                groupPaused={paused}
                canAct={canWrite && c.can_control}
                canWatch={canWrite}
                busy={action.isPending && action.variables?.id === c.id}
                onAction={(act) => (act === "pause" ? setConfirm(c) : run(c, act))}
                onEdit={isAdmin && c.can_edit ? () => setEditing(c) : undefined}
              />
            ))
          )}
        </div>
      </section>

      {editing && (
        <ConnectionForm
          connection={editing === "new" ? undefined : editing}
          workers={list}
          onClose={() => setEditing(null)}
          onDone={setNotice}
        />
      )}
      {confirm && (
        <Modal title={confirm === "group" ? "Pause générale ?" : `Mettre en pause « ${confirm.name} » ?`} onClose={() => setConfirm(null)}>
          <p className="text-ink-soft">
            {confirm === "group"
              ? "Toutes les connexions du groupe s'arrêtent, quel que soit leur état. Les demandes déjà reçues restent dans HospitalOS."
              : "L'agent ne relève plus ce logiciel et ne reporte plus de réponse jusqu'à la reprise. Les tâches en file attendent."}
          </p>
          <div className="mt-6 flex flex-wrap justify-end gap-2">
            <button className="btn-ghost" onClick={() => setConfirm(null)}>
              Annuler
            </button>
            <button
              className="btn-sun"
              onClick={() => {
                if (confirm === "group") toggleGroup(true);
                else run(confirm, "pause");
                setConfirm(null);
              }}
            >
              <Pause className="h-4 w-4" aria-hidden /> Mettre en pause
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function Dot({ tone, pulse = false }: { tone: string; pulse?: boolean }) {
  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden>
      {pulse && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${tone}`} />}
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${tone}`} />
    </span>
  );
}

function AgentState({ loading, online, total, paused }: { loading: boolean; online: number; total: number; paused: boolean }) {
  if (loading) return null;
  const up = online > 0 && !paused;
  return (
    <p className="mb-6 inline-flex items-center gap-2 rounded-chip bg-paper px-4 py-2 text-[15px] font-bold shadow-lift">
      <Dot tone={paused ? "bg-sun" : up ? "bg-lagoon" : "bg-ink-faint"} pulse={up} />
      {paused ? "Agent en pause" : up ? "Agent en ligne" : "Agent hors ligne"}
      <span className="font-normal text-ink-soft">
        · {total === 0 ? "aucun poste" : `${online} poste${online > 1 ? "s" : ""} en ligne sur ${total}`}
      </span>
    </p>
  );
}

function WorkerCard({ worker: w }: { worker: WorkerOut }) {
  const ready = w.engines.filter((e) => e.configured);
  return (
    <li className="panel px-5 py-4">
      <div className="flex items-start gap-3">
        <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${w.online ? "bg-lagoon-soft text-lagoon-dark" : "bg-sky-deep text-ink-faint"}`}>
          <Monitor className="h-5 w-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate">{w.agent_id}</h3>
          <p className="flex flex-wrap items-center gap-x-2 text-[14px] text-ink-soft">
            <span className={`inline-flex items-center gap-1.5 font-bold ${w.online ? "text-lagoon-dark" : "text-ink-faint"}`}>
              <Dot tone={w.online ? "bg-lagoon" : "bg-ink-faint"} />
              {w.online ? "En ligne" : "Hors ligne"}
            </span>
            {w.version && <span>v{w.version}</span>}
          </p>
          <p className="text-[13px] text-ink-faint" title={fmtDateTime(w.last_heartbeat_at)}>
            {w.last_heartbeat_at ? `Dernier signal ${fmtRelative(w.last_heartbeat_at)}` : "Jamais connecté"}
          </p>
        </div>
      </div>
      <dl className="mt-3 space-y-2 text-[14px]">
        <div>
          <dt className="text-[12px] font-bold uppercase tracking-wide text-ink-faint">Moteurs prêts</dt>
          <dd className="mt-1 flex flex-wrap gap-1">
            {w.engines.length === 0 && <span className="text-ink-faint">Aucun signalé</span>}
            {w.engines.map((e) => (
              <span
                key={e.name}
                title={e.detail ?? undefined}
                className={`chip ${e.configured ? "bg-violet-soft text-violet-dark" : "bg-sky text-ink-faint line-through"}`}
              >
                {e.name}
                <span className="sr-only">{e.configured ? " (configuré)" : " (non configuré)"}</span>
              </span>
            ))}
          </dd>
          {w.engines.length > 0 && <span className="sr-only">{`${ready.length} sur ${w.engines.length} configurés`}</span>}
        </div>
        <div>
          <dt className="text-[12px] font-bold uppercase tracking-wide text-ink-faint">Scripts</dt>
          <dd className="mt-1 flex flex-wrap gap-1">
            {w.playbooks.length === 0 && <span className="text-ink-faint">Aucun signalé</span>}
            {w.playbooks.map((p) => (
              <span key={p.name} className="chip bg-sun-soft text-ink" title={KIND_LABEL[p.kind]}>
                {p.label}
              </span>
            ))}
          </dd>
        </div>
      </dl>
    </li>
  );
}

const STATUS_CHIP = {
  active: { text: "Active", tone: "bg-lagoon-soft text-lagoon-dark", dot: "bg-lagoon", stripe: "bg-lagoon" },
  en_pause: { text: "En pause", tone: "bg-sun-soft text-ink", dot: "bg-sun", stripe: "bg-sun" },
  arretee: { text: "Arrêtée", tone: "bg-sky-deep text-ink-soft", dot: "bg-ink-faint", stripe: "bg-sky-deep" }
} as const;

function schedule(c: ConnectionOut): string {
  const hours = c.active_from || c.active_to ? `de ${c.active_from ?? "00:00"} à ${c.active_to ?? "24:00"}` : "toute la journée";
  const days =
    !c.days || c.days.length === 7
      ? "tous les jours"
      : WEEKDAYS.filter(([n]) => c.days?.includes(n))
          .map(([, short]) => short)
          .join(" ");
  return `Toutes les ${c.interval_minutes} min, ${hours}, ${days}`;
}

function ConnectionCard({
  c,
  groupPaused,
  canAct,
  canWatch,
  busy,
  onAction,
  onEdit
}: {
  c: ConnectionOut;
  groupPaused: boolean;
  canAct: boolean;
  /** Administrator and coordination watch the agent; the direction does not (PLAYER_SPEC). */
  canWatch: boolean;
  busy: boolean;
  onAction: (action: ConnectionAction) => void;
  onEdit?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const st = STATUS_CHIP[c.status];
  const halted = groupPaused && c.status !== "arretee";
  const chip = halted ? { text: "En pause générale", tone: "bg-sun text-ink", dot: "bg-ink" } : st;
  const Icon = c.kind === "gestion_lits" ? BedDouble : Globe;
  const titleId = `cx-${c.id}`;
  const blocked = groupPaused || busy;
  return (
    <article aria-labelledby={titleId} className="panel relative overflow-hidden">
      <span className={`absolute inset-y-0 left-0 w-1.5 ${halted ? "bg-sun" : st.stripe}`} aria-hidden />
      <div className="px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-start gap-3">
          <span
            className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${c.kind === "gestion_lits" ? "bg-lagoon-soft text-lagoon-dark" : "bg-violet-soft text-violet-dark"}`}
          >
            <Icon className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <h3 id={titleId} className="break-words text-[19px]">
              {c.name}
            </h3>
            <p className="text-[14px] text-ink-soft">
              {c.site_name ?? "Tout le groupe"} · {KIND_LABEL[c.kind]}
            </p>
          </div>
          <span className={`chip ${chip.tone}`}>
            <Dot tone={chip.dot} pulse={c.status === "active" && !groupPaused} />
            {chip.text}
          </span>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Fact label="Dernier passage" title={fmtDateTime(c.last_run_at)}>
            {c.last_run_at ? fmtRelative(c.last_run_at) : "Jamais"}
            {c.last_outcome && (
              <span className={`block text-[13px] font-normal ${/fail|échec|needs|refus/.test(c.last_outcome) ? "text-coral-dark" : "text-ink-soft"}`}>
                {OUTCOME[c.last_outcome] ?? c.last_outcome}
              </span>
            )}
          </Fact>
          <Fact label="Prochain passage" title={fmtDateTime(c.next_run_at)}>
            {c.status !== "active" || groupPaused ? "—" : c.next_run_at ? fmtRelative(c.next_run_at) : "Au prochain signal"}
          </Fact>
          <Fact label="En file">{c.pending_tasks}</Fact>
          <Fact label="À reprendre" alert={c.needs_human > 0}>
            {c.needs_human}
          </Fact>
        </dl>
        <p className="mt-3 text-[13px] text-ink-faint">
          {schedule(c)} · script {c.playbook} · {c.tasks.map((t) => TASK_LABEL[t] ?? t).join(", ")}
          {c.agent_id ? ` · poste ${c.agent_id}` : ""}
        </p>

        {c.last_error && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-coral-soft px-3 py-2 text-[14px] text-coral-dark">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span>
              <span className="font-bold">Dernière erreur : </span>
              {c.last_error}
            </span>
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {canWatch && c.running_task_id != null && (
            <Link to={`/computer-use/passages/${c.running_task_id}`} className="btn bg-ink text-white hover:bg-ink-soft">
              <Eye className="h-4 w-4" aria-hidden /> Regarder en direct
              <span className="chip bg-coral px-2 py-0 text-[12px] text-white">
                <LiveDot light /> En direct
              </span>
            </Link>
          )}
          {canAct && c.status === "arretee" && (
            <button className="btn-primary" disabled={blocked} onClick={() => onAction("start")}>
              <Play className="h-4 w-4" aria-hidden /> Démarrer
            </button>
          )}
          {canAct && c.status === "active" && (
            <>
              <button className="btn-primary" disabled={blocked} onClick={() => onAction("sync")}>
                <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} aria-hidden /> Relever maintenant
              </button>
              <button className="btn-quiet" disabled={blocked} onClick={() => onAction("pause")}>
                <Pause className="h-4 w-4" aria-hidden /> Mettre en pause
              </button>
            </>
          )}
          {canAct && c.status === "en_pause" && (
            <button className="btn-primary" disabled={blocked} onClick={() => onAction("resume")}>
              <Play className="h-4 w-4" aria-hidden /> Reprendre
            </button>
          )}
          {onEdit && (
            <button className="btn-ghost" onClick={onEdit}>
              <Pencil className="h-4 w-4" aria-hidden /> Modifier
            </button>
          )}
          <button
            className="btn-ghost ml-auto"
            aria-expanded={open}
            aria-controls={`${titleId}-runs`}
            onClick={() => setOpen(!open)}
          >
            Passages
            {c.needs_human > 0 && <span className="chip bg-coral-dark text-white">{c.needs_human} à reprendre</span>}
            <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
          </button>
        </div>
        {canAct && groupPaused && <p className="mt-2 text-[13px] text-ink-faint">Commandes suspendues pendant la pause générale.</p>}
      </div>
      {open && (
        <div id={`${titleId}-runs`} className="border-t border-line bg-sky/50 px-5 py-4 sm:px-6">
          <Runs id={c.id} canAct={canAct} canWatch={canWatch} />
        </div>
      )}
    </article>
  );
}

function Fact({ label, title, alert = false, children }: { label: string; title?: string; alert?: boolean; children: ReactNode }) {
  return (
    <div className={`rounded-xl px-3 py-2 ${alert ? "bg-coral-soft" : "bg-sky"}`} title={title}>
      <dt className="text-[12px] text-ink-faint">{label}</dt>
      <dd className={`num text-[17px] font-bold ${alert ? "text-coral-dark" : ""}`}>{children}</dd>
    </div>
  );
}

function Runs({ id, canAct, canWatch }: { id: number; canAct: boolean; canWatch: boolean }) {
  const runs = useConnectionRuns(id, true);
  const act = useTaskAction();
  if (runs.isLoading) return <Spinner />;
  if (runs.error) return <ErrorNote error={runs.error} />;
  if (!runs.data?.length) return <p className="text-[14px] text-ink-soft">Aucun passage pour l'instant.</p>;
  return (
    <>
      {act.error && (
        <div className="mb-3">
          <ErrorNote error={act.error} />
        </div>
      )}
      <ul aria-label="Derniers passages" className="divide-y divide-line">
        {runs.data.map((r) => {
          const st = TASK_STATUS[r.status] ?? { text: r.status, tone: "bg-sky-deep text-ink-soft" };
          const stuck = r.status === "needs_human" || r.status === "failed";
          return (
            <li key={r.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-bold">
                  {TASK_LABEL[r.kind] ?? r.kind}
                  {r.request_id ? <span className="font-normal text-ink-soft">, demande n° {r.request_id}</span> : null}
                </p>
                <p className="text-[13px] text-ink-faint" title={fmtDateTime(r.updated_at)}>
                  {fmtRelative(r.updated_at)}
                  {r.engine_used ? ` · ${r.engine_used}` : ""}
                  {r.attempts > 1 ? ` · ${r.attempts} essais` : ""}
                </p>
                {r.error && stuck && <p className="mt-1 text-[13px] text-ink-soft">{r.error}</p>}
              </div>
              <span className={`chip ${st.tone}`}>{st.text}</span>
              {canWatch && r.has_replay && (
                <Link
                  to={`/computer-use/passages/${r.id}`}
                  className="btn-quiet px-3 py-1.5 text-[13px]"
                  aria-label={`Revoir ce passage (${r.steps_count} étape${r.steps_count > 1 ? "s" : ""})`}
                >
                  <Clapperboard className="h-3.5 w-3.5" aria-hidden /> Revoir
                  <span className="num font-normal text-ink-soft">· {r.steps_count}</span>
                </Link>
              )}
              {canAct && stuck && (
                <div className="flex w-full justify-end gap-2 sm:w-auto">
                  <button
                    className="btn-quiet px-3 py-1.5 text-[13px]"
                    disabled={act.isPending}
                    onClick={() => act.mutate({ id: r.id, what: "retry" })}
                  >
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Relancer
                  </button>
                  <button
                    className="btn-quiet px-3 py-1.5 text-[13px]"
                    disabled={act.isPending}
                    onClick={() => act.mutate({ id: r.id, what: "manual" })}
                  >
                    Fait à la main
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

