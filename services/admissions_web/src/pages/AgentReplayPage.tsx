import { ListChecks, Lock, MonitorPlay, PanelsLeftRight } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { ReplayOut } from "../api/types_agent";
import { useAuth } from "../auth";
import { AgentPlayer, LiveDot, type PlayerView } from "../components/AgentPlayer";
import { ErrorNote, Spinner } from "../components/common";
import { FloatingWindow } from "../components/FloatingWindow";
import { TASK_LABEL, TASK_STATUS, engineLabel, useReplay } from "../lib/agent";
import { fmtDateTime } from "../lib/format";

const KEPT = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long" });
const VIEW_KEY = "hospitalos.player.view";
const VIEWS: Array<{ id: PlayerView; label: string; icon: typeof MonitorPlay }> = [
  { id: "video", label: "Vidéo", icon: MonitorPlay },
  { id: "flow", label: "Transcription", icon: ListChecks },
  { id: "both", label: "Les deux", icon: PanelsLeftRight }
];

function rememberedView(): PlayerView {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    if (v === "video" || v === "flow" || v === "both") return v;
  } catch {
    /* storage unavailable */
  }
  return "both";
}

/**
 * The player of a passage, in a window over the Agents screen it was opened from
 * (/agents/passages/:taskId, a link that can be shared). Closing it comes back to the screen.
 */
export function AgentReplayPage() {
  const navigate = useNavigate();
  const taskId = Number(useParams().taskId);
  return <PassageWindow key={taskId} taskId={taskId} onClose={() => navigate("/agents")} />;
}

export function PassageWindow({ taskId, onClose }: { taskId: number; onClose: () => void }) {
  const { canWrite } = useAuth();
  // Watching is for the administrator and the coordination (PLAYER_SPEC « Qui regarde »).
  if (!canWrite)
    return (
      <FloatingWindow title="Player réservé" titleId="player-title" onClose={onClose} storageKey="hospitalos.player.window" initialSize={{ w: 640, h: 360 }}>
        <Restricted />
      </FloatingWindow>
    );
  return <Replay taskId={taskId} onClose={onClose} />;
}

function Restricted() {
  return (
    <div className="flex items-start gap-4 p-6">
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-sun-soft text-ink">
        <Lock className="h-5 w-5" aria-hidden />
      </span>
      <p className="text-ink-soft">
        Regarder les passages de l'agent est réservé à l'administrateur du groupe et à la coordination de l'établissement. Les résultats de
        chaque passage restent visibles dans la page Agents.
      </p>
    </div>
  );
}

function Replay({ taskId, onClose }: { taskId: number; onClose: () => void }) {
  const replay = useReplay(taskId);
  const [view, setView] = useState<PlayerView>(rememberedView);
  const bodyRef = useRef<HTMLDivElement>(null);
  const narrow = useNarrow(bodyRef);
  // Side by side needs room: in a narrow window, « Les deux » shows the screen.
  const shown: PlayerView = view === "both" && narrow ? "video" : view;
  const choose = (v: PlayerView) => {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* the choice lasts for this visit */
    }
  };

  const data = replay.data;
  const status = (replay.error as { status?: number } | null)?.status;
  const title = status === 403 ? "Player réservé" : (data?.task.connection_name ?? `Passage n° ${taskId}`);

  return (
    <FloatingWindow
      title={title}
      titleId="player-title"
      subtitle={data ? <ReplayMeta replay={data} /> : undefined}
      tools={data && <ViewSwitch view={shown} narrow={narrow} onChange={choose} />}
      onClose={onClose}
      storageKey="hospitalos.player.window"
    >
      <div ref={bodyRef} className="h-full p-3 sm:p-4">
        {replay.isLoading ? (
          <Spinner label="Chargement du passage" />
        ) : status === 403 ? (
          <Restricted />
        ) : replay.error ? (
          status === 404 ? (
            <ErrorNote error={new Error("Ce passage est introuvable : il a peut-être dépassé la durée de conservation et été purgé.")} />
          ) : (
            <ErrorNote error={replay.error} />
          )
        ) : data ? (
          <AgentPlayer replay={data} view={shown} />
        ) : null}
      </div>
    </FloatingWindow>
  );
}

/** True when the window body is too narrow to show the screen and the flow side by side. */
function useNarrow(ref: React.RefObject<HTMLElement>): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setNarrow(el.clientWidth > 0 && el.clientWidth < 860));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return narrow;
}

function ViewSwitch({ view, narrow, onChange }: { view: PlayerView; narrow: boolean; onChange: (v: PlayerView) => void }) {
  return (
    <div role="group" aria-label="Vue du player" className="flex shrink-0 rounded-chip bg-sky p-0.5" data-no-drag>
      {VIEWS.filter((v) => !(narrow && v.id === "both")).map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          aria-pressed={view === id}
          aria-label={label}
          title={label}
          onClick={() => onChange(id)}
          className={`touch-target inline-flex items-center gap-1.5 rounded-chip px-3 py-1.5 text-[14px] font-bold transition-colors ${
            view === id ? "bg-ink text-white shadow-lift" : "text-ink-soft hover:text-ink"
          }`}
        >
          <Icon className="h-4 w-4" aria-hidden />
          <span aria-hidden className={id === "both" ? "hidden md:inline" : ""}>
            {label}
          </span>
        </button>
      ))}
    </div>
  );
}

/** The task's engine once recorded (at the end); while it runs, the engines its steps used. */
export function enginesOf({ task, steps }: ReplayOut): string {
  if (task.engine_used) return engineLabel(task.engine_used);
  const seen = [...new Set(steps.map((s) => engineLabel(s.engine)))].filter((e) => e !== "—");
  return seen.length ? seen.join(" · ") : "—";
}

function ReplayMeta({ replay }: { replay: ReplayOut }) {
  const { task, live, retention_until } = replay;
  const st = TASK_STATUS[task.status] ?? { text: task.status, tone: "bg-sky-deep text-ink-soft" };
  return (
    <dl className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {live ? (
        <span className="chip bg-coral-dark text-white">
          <LiveDot light /> En direct
        </span>
      ) : (
        <span className={`chip ${st.tone}`}>{st.text}</span>
      )}
      <Meta label="Établissement" wide>
        {task.site_name ?? "Tout le groupe"}
      </Meta>
      <Meta label="Tâche">{TASK_LABEL[task.kind] ?? task.kind}</Meta>
      <Meta label="Moteur" wide>
        {enginesOf(replay)}
      </Meta>
      <Meta label="Commencé">{fmtDateTime(task.created_at)}</Meta>
      {task.finished_at && (
        <Meta label="Terminé" wide>
          {fmtDateTime(task.finished_at)}
        </Meta>
      )}
      {retention_until && (
        <Meta label="Conservé jusqu'au" wide>
          {KEPT.format(new Date(retention_until))}
        </Meta>
      )}
    </dl>
  );
}

/** `wide`: shown from tablet width up; on a phone the header keeps status, task and start. */
function Meta({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`whitespace-nowrap ${wide ? "hidden md:block" : ""}`}>
      <dt className="inline text-ink-faint">{label} </dt>
      <dd className="inline font-bold text-ink">{children}</dd>
    </div>
  );
}
