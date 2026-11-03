import { ListChecks, Lock, MonitorPlay, PanelsLeftRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { ReplayOut } from "../api/types_agent";
import { useAuth } from "../auth";
import { AgentPlayer, LiveDot, type PlayerView } from "../components/AgentPlayer";
import { ErrorNote, Spinner } from "../components/common";
import { FloatingWindow } from "../components/FloatingWindow";
import { TASK_STATUS, useReplay } from "../lib/agent";
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
  const title = status === 403 ? "Player réservé" : data ? passageTitle(data) : "Chargement du passage";

  return (
    <FloatingWindow
      title={title}
      titleId="player-title"
      badge={data ? <StateBadge replay={data} /> : undefined}
      tools={data && <ViewSwitch view={shown} narrow={narrow} onChange={choose} />}
      onClose={onClose}
      storageKey="hospitalos.player.window.v2"
      placement="bottom-right"
      initialSize={{ w: 420, h: 420 }}
    >
      <div ref={bodyRef} className="h-full p-2 sm:p-3">
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
          className={`touch-target inline-flex items-center justify-center gap-1.5 rounded-chip px-3 py-1.5 text-[14px] font-bold transition-colors group-data-[tight]:px-2.5 ${
            view === id ? "bg-ink text-white shadow-lift" : "text-ink-soft hover:text-ink"
          }`}
        >
          <Icon className="h-4 w-4" aria-hidden />
          {/* Icons only in a small window; the name stays the button's accessible name. */}
          <span aria-hidden className={`group-data-[tight]:hidden ${id === "both" ? "hidden md:inline" : ""}`}>
            {label}
          </span>
        </button>
      ))}
    </div>
  );
}

/** What the agent does, for the window title: live (a verb) and afterwards (a noun). */
const ACTION: Record<string, { live: string; noun: string }> = {
  sync_movements: { live: "relève les mouvements", noun: "la relève des mouvements" },
  sync_inbox: { live: "relève les demandes du portail", noun: "la relève des demandes" },
  reply_portal: { live: "reporte une réponse sur le portail", noun: "le report de la réponse" }
};
const HOUR = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const DAY = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });

/**
 * The window title says what the agent does, in the words of the button that opened it:
 * « Regarder en direct » → « L'agent relève les mouvements » ; « Revoir » → « Revoir la relève
 * des mouvements de 18:00 » (« du 3 nov. à 18:00 » another day).
 */
export function passageTitle({ task, live }: ReplayOut, now = new Date()): string {
  const action = ACTION[task.kind];
  if (live) return `L'agent ${action?.live ?? "travaille"}`;
  const at = new Date(task.created_at);
  const sameDay = at.toDateString() === now.toDateString();
  const when = sameDay ? `de ${HOUR.format(at)}` : `du ${DAY.format(at)} à ${HOUR.format(at)}`;
  return `Revoir ${action?.noun ?? "le passage"} ${when}`;
}

/** Only what changes how to read the window: live, or a passage that did not go well. */
function StateBadge({ replay }: { replay: ReplayOut }) {
  if (replay.live)
    return (
      // In a small window, only the dot: the controls already say « En direct », and the title needs the room.
      <span className="chip shrink-0 bg-coral-dark text-white group-data-[tight]:px-1.5 group-data-[tight]:py-1.5" title="En direct">
        <LiveDot light /> <span className="group-data-[tight]:sr-only">En direct</span>
      </span>
    );
  if (replay.task.status === "done") return null;
  const st = TASK_STATUS[replay.task.status] ?? { text: replay.task.status, tone: "bg-sky-deep text-ink-soft" };
  return <span className={`chip shrink-0 ${st.tone}`}>{st.text}</span>;
}
