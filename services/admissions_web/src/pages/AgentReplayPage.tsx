import { ArrowLeft, Lock } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import type { ReplayOut } from "../api/types_agent";
import { useAuth } from "../auth";
import { AgentPlayer, LiveDot } from "../components/AgentPlayer";
import { ErrorNote, Spinner } from "../components/ui";
import { TASK_LABEL, TASK_STATUS, engineLabel, useReplay } from "../lib/agent";
import { fmtDateTime } from "../lib/format";

const KEPT = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long" });

function Back() {
  return (
    <Link to="/computer-use" className="btn-ghost -ml-3 mb-3 px-3 py-1.5 text-[14px]">
      <ArrowLeft className="h-4 w-4" aria-hidden /> Computer use
    </Link>
  );
}

export function AgentReplayPage() {
  const { canWrite } = useAuth();
  const taskId = Number(useParams().taskId);
  // Watching is for the administrator and the coordination (PLAYER_SPEC « Qui regarde »).
  if (!canWrite) return <Restricted />;
  return <Replay taskId={taskId} />;
}

function Restricted() {
  return (
    <>
      <Back />
      <div className="panel flex max-w-xl items-start gap-4 p-6">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-sun-soft text-ink">
          <Lock className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <h1 className="text-[24px]">Player réservé</h1>
          <p className="mt-2 text-ink-soft">
            Regarder les passages de l'agent est réservé à l'administrateur du groupe et à la coordination de l'établissement. Les résultats
            de chaque passage restent visibles dans la page Computer use.
          </p>
        </div>
      </div>
    </>
  );
}

function Replay({ taskId }: { taskId: number }) {
  const replay = useReplay(taskId);
  if (replay.isLoading) return <Spinner label="Chargement du passage" />;
  if (replay.error) {
    const status = (replay.error as { status?: number }).status;
    if (status === 403) return <Restricted />;
    return (
      <>
        <Back />
        {status === 404 ? (
          <ErrorNote error={new Error("Ce passage est introuvable : il a peut-être dépassé la durée de conservation et été purgé.")} />
        ) : (
          <ErrorNote error={replay.error} />
        )}
      </>
    );
  }
  if (!replay.data) return null;
  return (
    <>
      <Back />
      <ReplayHeader replay={replay.data} />
      <AgentPlayer replay={replay.data} />
    </>
  );
}

function ReplayHeader({ replay }: { replay: ReplayOut }) {
  const { task, live, retention_until } = replay;
  const st = TASK_STATUS[task.status] ?? { text: task.status, tone: "bg-sky-deep text-ink-soft" };
  return (
    <header className="mb-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="break-words">{task.connection_name ?? `Passage n° ${task.id}`}</h1>
        {live ? (
          <span className="chip bg-coral-dark text-white">
            <LiveDot light /> En direct
          </span>
        ) : (
          <span className={`chip ${st.tone}`}>{st.text}</span>
        )}
      </div>
      <dl className="mt-3 flex flex-wrap gap-2 text-[14px]">
        <Meta label="Établissement">{task.site_name ?? "Tout le groupe"}</Meta>
        <Meta label="Tâche">{TASK_LABEL[task.kind] ?? task.kind}</Meta>
        <Meta label="Moteur">{engineLabel(task.engine_used)}</Meta>
        <Meta label="Commencé">{fmtDateTime(task.created_at)}</Meta>
        {task.finished_at && <Meta label="Terminé">{fmtDateTime(task.finished_at)}</Meta>}
        {retention_until && <Meta label="Conservé jusqu'au">{KEPT.format(new Date(retention_until))}</Meta>}
      </dl>
    </header>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-chip bg-paper px-3 py-1 shadow-lift">
      <dt className="inline text-ink-faint">{label} </dt>
      <dd className="inline font-bold">{children}</dd>
    </div>
  );
}
