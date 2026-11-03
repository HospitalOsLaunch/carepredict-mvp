import {
  ArrowDownUp,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Compass,
  Hourglass,
  ImageOff,
  Info,
  Keyboard,
  ListChecks,
  Loader2,
  LogIn,
  Maximize,
  Minimize,
  MousePointer2,
  MousePointerClick,
  Pause,
  Play,
  Send,
  ShieldCheck,
  SkipBack,
  SkipForward,
  Sparkles,
  TextCursorInput,
  TriangleAlert,
  type LucideIcon
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import type { MaskReason, ReplayOut, ReplayStep, StepKind, StepMask, StepOutcome, StepRect } from "../api/types_agent";
import { engineLabel, useFrames, type FrameState } from "../lib/agent";
import { fmtNum } from "../lib/format";

const SPEEDS = [1, 2, 4] as const;
/** At 1×, a step stays on screen for its real duration, between these bounds. */
const MIN_STEP_MS = 350;
const MAX_STEP_MS = 2_500;

const KIND_ICON: Record<StepKind, LucideIcon> = {
  login: LogIn,
  navigate: Compass,
  click: MousePointerClick,
  fill: TextCursorInput,
  select: ListChecks,
  read: BookOpen,
  wait: Hourglass,
  scroll: ArrowDownUp,
  key: Keyboard,
  verify: ShieldCheck,
  model_action: Sparkles,
  info: Info,
  error: TriangleAlert
};

export const MASK_LABEL: Record<MaskReason, string> = {
  identite: "Masqué : identité patient",
  secret: "Masqué : mot de passe",
  autre: "Masqué"
};

const OUTCOME: Record<StepOutcome, { text: string; chip: string; mark: string }> = {
  ok: { text: "réussi", chip: "bg-lagoon-soft text-lagoon-dark", mark: "bg-lagoon" },
  fail: { text: "échec", chip: "bg-coral-soft text-coral-dark", mark: "bg-coral" },
  info: { text: "info", chip: "bg-sky-deep text-ink-soft", mark: "bg-ink-faint" }
};

const ENGINE_CHIP: Record<string, string> = {
  script: "bg-sun-soft text-ink",
  "modèle ouvert": "bg-lagoon-soft text-lagoon-dark",
  Claude: "bg-violet-soft text-violet-dark"
};

export function fmtDuration(ms: number | null): string {
  if (ms === null) return "";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${fmtNum(ms / 1000, 1)} s`;
}

function fmtClock(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function transmittedText(t: NonNullable<ReplayStep["transmitted"]>): string {
  const s = t.count > 1 ? "s" : "";
  // A reading step carries no API result yet (null): what was read, sent at the end.
  if (t.applied == null && t.duplicates == null && t.rejected == null) return `${t.count} élément${s} relevé${s}`;
  const parts = [`appliqués ${t.applied ?? 0}`, `doublons ${t.duplicates ?? 0}`];
  if (t.rejected) parts.push(`refusés ${t.rejected}`);
  return `transmis : ${t.count} élément${s} (${parts.join(", ")})`;
}

/** Why the worker kept the image (the label ends with « (capture retenue : …) »), or null. */
export function withheldReason(label: string): string | null {
  const found = /\(capture retenue : ([^)]+)\)\s*$/.exec(label);
  return found ? found[1] : null;
}

const time = (s: ReplayStep) => new Date(s.at).getTime();
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

export function AgentPlayer({ replay }: { replay: ReplayOut }) {
  const { steps, live } = replay;
  const last = steps.length - 1;
  const [index, setIndex] = useState(live ? Math.max(0, last) : 0);
  const [playing, setPlaying] = useState(false);
  const [follow, setFollow] = useState(live);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [fullscreen, setFullscreen] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const i = clamp(index, 0, Math.max(0, last));
  const step = steps[i] as ReplayStep | undefined;
  const frameOf = useFrames(steps, i);
  const anyFrame = steps.some((s) => s.has_frame);

  // Live head: follow the newest step as it arrives.
  useEffect(() => {
    if (follow) setIndex(last);
  }, [follow, last]);
  useEffect(() => {
    if (!live) setFollow(false);
  }, [live]);

  // Playback: wait the real time between two steps, capped, divided by the speed.
  useEffect(() => {
    if (!playing || follow) return;
    if (i >= last) {
      if (!live) setPlaying(false);
      return;
    }
    const gap = clamp(time(steps[i + 1]) - time(steps[i]), MIN_STEP_MS, MAX_STEP_MS) / speed;
    const timer = window.setTimeout(() => setIndex(i + 1), gap);
    return () => window.clearTimeout(timer);
  }, [playing, follow, i, last, live, speed, steps]);

  const seek = useCallback(
    (to: number) => {
      setFollow(false);
      setIndex(clamp(to, 0, Math.max(0, last)));
    },
    [last]
  );
  const seekFrame = useCallback(
    (dir: 1 | -1) => {
      for (let j = i + dir; j >= 0 && j <= last; j += dir) {
        if (steps[j].has_frame) return seek(j);
      }
      seek(i + dir); // no image that way: move one step anyway
    },
    [i, last, steps, seek]
  );
  const togglePlay = useCallback(() => {
    if (playing || follow) {
      setPlaying(false);
      setFollow(false);
      return;
    }
    if (i >= last && !live) setIndex(0);
    setPlaying(true);
  }, [playing, follow, i, last, live]);
  const goLive = () => {
    setPlaying(false);
    setFollow(true);
  };

  // Keyboard: space plays / pauses, ← → image by image, shift + ← → step by step.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName ?? "";
      if (["INPUT", "SELECT", "TEXTAREA"].includes(tag) || el?.isContentEditable || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === " " && !["BUTTON", "A"].includes(tag)) {
        e.preventDefault();
        togglePlay();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const dir = e.key === "ArrowLeft" ? -1 : 1;
        if (e.shiftKey) seek(i + dir);
        else seekFrame(dir);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [togglePlay, seek, seekFrame, i]);

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void rootRef.current?.requestFullscreen();
  };

  const start = steps.length ? time(steps[0]) : 0;
  const total = steps.length ? time(steps[last]) - start : 0;
  const elapsed = step ? time(step) - start : 0;

  return (
    <section
      ref={rootRef}
      aria-label="Player du passage"
      className={`grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)] ${fullscreen ? "h-full overflow-auto bg-sky p-4 sm:p-6" : ""}`}
    >
      <div className="min-w-0 space-y-3">
        <Screen step={step} frame={step ? frameOf(step.id) : { failed: false }} anyFrame={anyFrame} live={live} index={i} count={steps.length} />

        <div className="panel px-3 py-3 sm:px-4">
          <Scrubber steps={steps} index={i} onSeek={seek} elapsed={elapsed} total={total} />
          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-2">
            <div className="flex items-center gap-0.5">
              <IconButton label="Étape précédente" onClick={() => seek(i - 1)} disabled={i <= 0}>
                <SkipBack className="h-4 w-4" aria-hidden />
              </IconButton>
              <IconButton label="Image précédente" onClick={() => seekFrame(-1)} disabled={i <= 0}>
                <ChevronLeft className="h-5 w-5" aria-hidden />
              </IconButton>
              <button
                type="button"
                onClick={togglePlay}
                disabled={!steps.length}
                aria-label={playing || follow ? "Pause" : "Lecture"}
                title={`${playing || follow ? "Pause" : "Lecture"} (espace)`}
                className="mx-1 grid h-12 w-12 place-items-center rounded-full bg-violet text-white shadow-lift transition-colors hover:bg-violet-dark disabled:opacity-50"
              >
                {playing || follow ? <Pause className="h-5 w-5" aria-hidden /> : <Play className="ml-0.5 h-5 w-5" aria-hidden />}
              </button>
              <IconButton label="Image suivante" onClick={() => seekFrame(1)} disabled={i >= last}>
                <ChevronRight className="h-5 w-5" aria-hidden />
              </IconButton>
              <IconButton label="Étape suivante" onClick={() => seek(i + 1)} disabled={i >= last}>
                <SkipForward className="h-4 w-4" aria-hidden />
              </IconButton>
            </div>

            <div role="group" aria-label="Vitesse" className="flex rounded-chip bg-sky p-0.5">
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={speed === s}
                  onClick={() => setSpeed(s)}
                  className={`num rounded-chip px-2.5 py-1 text-[14px] font-bold transition-colors ${speed === s ? "bg-ink text-white" : "text-ink-soft hover:text-ink"}`}
                >
                  {s}×
                </button>
              ))}
            </div>

            <div className="ml-auto flex items-center gap-1">
              {live && (
                <button
                  type="button"
                  onClick={goLive}
                  aria-pressed={follow}
                  className={`btn px-3 py-1.5 text-[14px] ${follow ? "bg-coral text-white" : "bg-coral-soft text-coral-dark hover:bg-coral hover:text-white"}`}
                >
                  <LiveDot pulse={follow} light={follow} /> En direct
                </button>
              )}
              {document.fullscreenEnabled && (
                <IconButton label={fullscreen ? "Quitter le plein écran" : "Plein écran"} onClick={toggleFullscreen}>
                  {fullscreen ? <Minimize className="h-4 w-4" aria-hidden /> : <Maximize className="h-4 w-4" aria-hidden />}
                </IconButton>
              )}
            </div>
          </div>
          <p className="mt-2 hidden text-[12px] text-ink-faint sm:block">
            Raccourcis : espace lecture / pause · ← → image par image · Maj + ← → étape par étape
          </p>
        </div>
      </div>

      <Transcript steps={steps} index={i} live={live} onSeek={seek} fullscreen={fullscreen} />
    </section>
  );
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className="grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-sky disabled:cursor-not-allowed disabled:opacity-35"
    >
      {children}
    </button>
  );
}

export function LiveDot({ pulse = true, light = false }: { pulse?: boolean; light?: boolean }) {
  const tone = light ? "bg-white" : "bg-coral";
  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden>
      {pulse && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${tone}`} />}
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${tone}`} />
    </span>
  );
}

const pct = (v: number, of: number) => `${(v / of) * 100}%`;
const rectStyle = (r: StepRect, vw: number, vh: number) => ({
  left: pct(r.x, vw),
  top: pct(r.y, vh),
  width: pct(r.w, vw),
  height: pct(r.h, vh)
});

function Screen({
  step,
  frame,
  anyFrame,
  live,
  index,
  count
}: {
  step?: ReplayStep;
  frame: FrameState;
  anyFrame: boolean;
  live: boolean;
  index: number;
  count: number;
}) {
  // While the next image loads, keep the previous one rather than flashing a placeholder.
  const lastUrl = useRef<string>();
  const screenRef = useRef<HTMLDivElement>(null);
  const width = useWidth(screenRef);
  if (frame.url) lastUrl.current = frame.url;
  const vw = step?.viewport?.w ?? 1280;
  const vh = step?.viewport?.h ?? 800;
  const shown = step?.has_frame ? (frame.url ?? (frame.failed ? undefined : lastUrl.current)) : undefined;
  const fresh = Boolean(frame.url);

  let empty: ReactNode = null;
  if (!step) empty = live ? <Placeholder icon={<Loader2 className="h-6 w-6 animate-spin" aria-hidden />} text="L'agent démarre : la première étape arrive…" /> : <Placeholder text="Aucune étape enregistrée pour ce passage." />;
  else if (!step.has_frame)
    empty = (
      <Placeholder
        icon={<ImageOff className="h-6 w-6" aria-hidden />}
        text={
          withheldReason(step.label)
            ? `Image retenue sur le poste : ${withheldReason(step.label)}`
            : anyFrame
              ? "Pas d'image pour cette étape"
              : "Ce script ne capture pas d'écran"
        }
      />
    );
  else if (frame.failed && !frame.url) empty = <Placeholder icon={<ImageOff className="h-6 w-6" aria-hidden />} text="Image indisponible : elle a peut-être été purgée." />;
  else if (!shown) empty = <Placeholder icon={<Loader2 className="h-6 w-6 animate-spin" aria-hidden />} text="Chargement de l'image…" />;

  return (
    <figure className="m-0 rounded-[22px] bg-ink p-2 shadow-[0_24px_60px_-28px_rgba(91,61,245,0.55)] ring-1 ring-ink/10 sm:p-2.5">
      <div className="flex items-center gap-2 px-2 pb-2 pt-0.5">
        <span className="flex gap-1.5" aria-hidden>
          <span className="h-2.5 w-2.5 rounded-full bg-coral" />
          <span className="h-2.5 w-2.5 rounded-full bg-sun" />
          <span className="h-2.5 w-2.5 rounded-full bg-lagoon" />
        </span>
        <span className="min-w-0 flex-1 truncate rounded-chip bg-white/10 px-3 py-0.5 text-center text-[12px] text-white/75">
          {step?.target ?? "Écran du logiciel"}
        </span>
        <span className="num shrink-0 text-[12px] text-white/60">{count ? `${index + 1} / ${count}` : "—"}</span>
      </div>
      <div ref={screenRef} className="relative overflow-hidden rounded-[14px] bg-sky-deep" style={{ aspectRatio: `${vw} / ${vh}` }}>
        {shown && step && (
          <>
            <img
              src={shown}
              alt={`Écran à l'étape ${index + 1} : ${step.label}${step.masks.length ? ` (${step.masks.length} zone${step.masks.length > 1 ? "s" : ""} masquée${step.masks.length > 1 ? "s" : ""})` : ""}`}
              className="absolute inset-0 h-full w-full object-fill"
              draggable={false}
            />
            {fresh && (
              <div className="absolute inset-0" aria-hidden data-testid="overlays">
                {step.masks.map((m, k) => {
                  // A label inside the zone only when it is readable there; the legend covers the others.
                  const fits = !width || (m.h * width) / vw >= 15 && (m.w * width) / vw >= 120;
                  return (
                    <div key={k} className="mask-hatch absolute grid place-items-center overflow-hidden rounded-[3px]" style={rectStyle(m, vw, vh)} title={MASK_LABEL[m.reason]}>
                      {fits && <span className="max-w-full truncate rounded bg-ink/85 px-1.5 text-[11px] font-bold leading-4 text-sun-glow">{MASK_LABEL[m.reason] ?? "Masqué"}</span>}
                    </div>
                  );
                })}
                <MaskLegend masks={step.masks} />
                {step.box && <div className="absolute rounded-md border-2 border-sun shadow-[0_0_0_4px_rgba(255,178,30,0.25)]" style={rectStyle(step.box, vw, vh)} data-testid="box" />}
                {step.pointer && (
                  <div className="absolute" style={{ left: pct(step.pointer.x, vw), top: pct(step.pointer.y, vh) }} data-testid="pointer">
                    {step.kind === "click" || step.kind === "model_action" ? (
                      <span key={step.id} className="click-ripple absolute left-0 top-0 h-14 w-14 rounded-full border-[3px] border-coral bg-coral/20" />
                    ) : null}
                    <MousePointer2 className="relative h-6 w-6 -translate-x-[3px] -translate-y-[2px] fill-white text-ink drop-shadow" aria-hidden />
                  </div>
                )}
                {step.kind === "scroll" && (
                  <span className="absolute bottom-3 right-3 inline-flex items-center gap-1 rounded-chip bg-ink/80 px-2.5 py-1 text-[12px] font-bold text-white">
                    <ArrowDownUp className="h-3.5 w-3.5" aria-hidden /> Défilement
                  </span>
                )}
              </div>
            )}
          </>
        )}
        {empty}
      </div>
      {step && (
        <figcaption className="flex items-start gap-2 px-2 pb-1 pt-2.5 text-[15px] font-bold text-white">
          <StepIcon kind={step.kind} className="mt-0.5 text-sun-glow" />
          <span className="min-w-0">{step.label}</span>
        </figcaption>
      )}
    </figure>
  );
}

/** One chip per reason, with the number of zones: the masks of a table are too small to carry a label. */
function MaskLegend({ masks }: { masks: StepMask[] }) {
  if (!masks.length) return null;
  const counts = new Map<MaskReason, number>();
  for (const m of masks) counts.set(m.reason, (counts.get(m.reason) ?? 0) + 1);
  return (
    <div className="absolute bottom-2 left-2 flex max-w-[calc(100%-1rem)] flex-wrap gap-1">
      {[...counts].map(([reason, n]) => (
        <span key={reason} className="inline-flex items-center gap-1.5 rounded-chip bg-ink/85 py-0.5 pl-1 pr-2 text-[11px] font-bold text-white sm:text-[12px]">
          <span className="mask-hatch h-3.5 w-3.5 rounded-full" />
          {MASK_LABEL[reason] ?? "Masqué"}
          {n > 1 && <span className="num text-sun-glow">× {n}</span>}
        </span>
      ))}
    </div>
  );
}

function useWidth(ref: RefObject<HTMLElement>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

function Placeholder({ text, icon }: { text: string; icon?: ReactNode }) {
  return (
    <div className="absolute inset-0 grid place-items-center bg-[radial-gradient(circle_at_30%_20%,#ECE8FF,transparent_55%),radial-gradient(circle_at_80%_90%,#FFF1CC,transparent_50%)] p-6 text-center">
      <div className="max-w-sm text-ink-soft">
        {icon && <span className="mx-auto mb-2 grid h-12 w-12 place-items-center rounded-full bg-paper text-violet shadow-lift">{icon}</span>}
        <p className="text-[15px] font-bold">{text}</p>
      </div>
    </div>
  );
}

function StepIcon({ kind, className = "" }: { kind: StepKind; className?: string }) {
  const Icon = KIND_ICON[kind] ?? Info;
  return <Icon className={`h-4 w-4 shrink-0 ${className}`} aria-hidden />;
}

function Scrubber({
  steps,
  index,
  onSeek,
  elapsed,
  total
}: {
  steps: ReplayStep[];
  index: number;
  onSeek: (i: number) => void;
  elapsed: number;
  total: number;
}) {
  const max = Math.max(0, steps.length - 1);
  const at = (k: number) => (max ? (k / max) * 100 : 0);
  return (
    <div className="flex items-center gap-3">
      <span className="num w-10 shrink-0 text-right text-[13px] text-ink-soft">{fmtClock(elapsed)}</span>
      <div className="relative h-8 min-w-0 flex-1">
        <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-sky-deep" aria-hidden />
        <div className="absolute left-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-violet/30" style={{ width: `${at(index)}%` }} aria-hidden />
        <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2" aria-hidden data-testid="markers">
          {steps.map((s, k) => (
            <span
              key={s.id}
              data-outcome={s.outcome}
              className={`absolute top-1/2 h-3.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full ${OUTCOME[s.outcome]?.mark ?? "bg-ink-faint"}`}
              style={{ left: `${at(k)}%` }}
            />
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={max}
          step={1}
          value={index}
          disabled={!steps.length}
          onChange={(e) => onSeek(Number(e.target.value))}
          aria-label="Barre de temps"
          aria-valuetext={steps.length ? `Étape ${index + 1} sur ${steps.length} : ${steps[index].label}` : "Aucune étape"}
          className="player-range absolute inset-0 h-full w-full cursor-pointer"
        />
      </div>
      <span className="num w-10 shrink-0 text-[13px] text-ink-faint">{fmtClock(total)}</span>
    </div>
  );
}

function Transcript({
  steps,
  index,
  live,
  onSeek,
  fullscreen
}: {
  steps: ReplayStep[];
  index: number;
  live: boolean;
  onSeek: (i: number) => void;
  fullscreen: boolean;
}) {
  const listRef = useRef<HTMLOListElement>(null);
  // Keep the current line visible inside the list without scrolling the page.
  useEffect(() => {
    const box = listRef.current;
    const el = box?.querySelector<HTMLElement>('[aria-current="step"]');
    if (!box || !el || box.scrollHeight <= box.clientHeight) return;
    if (el.offsetTop < box.scrollTop || el.offsetTop + el.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTop = el.offsetTop - box.clientHeight / 3;
    }
  }, [index]);

  return (
    <div className="panel flex min-w-0 flex-col overflow-hidden lg:self-start">
      <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <h2 id="transcription" className="text-[17px]">
          Transcription
        </h2>
        <span className="text-[13px] text-ink-faint">
          {steps.length} étape{steps.length > 1 ? "s" : ""}
        </span>
      </div>
      <ol
        ref={listRef}
        aria-labelledby="transcription"
        aria-live={live ? "polite" : "off"}
        aria-relevant="additions"
        className={`relative divide-y divide-line overflow-y-auto ${fullscreen ? "max-h-[calc(100vh-8rem)]" : "max-h-[26rem] lg:max-h-[calc(100vh-14rem)]"}`}
      >
        {steps.map((s, k) => {
          const current = k === index;
          const engine = engineLabel(s.engine);
          const out = OUTCOME[s.outcome] ?? OUTCOME.info;
          return (
            <li key={s.id} aria-current={current ? "step" : undefined} className={current ? "bg-violet-soft" : ""}>
              <button
                type="button"
                onClick={() => onSeek(k)}
                className={`relative flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors ${current ? "" : "hover:bg-sky"}`}
              >
                {current && <span className="absolute inset-y-0 left-0 w-1 bg-violet" aria-hidden />}
                <span
                  className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg ${s.outcome === "fail" ? "bg-coral-soft text-coral-dark" : current ? "bg-violet text-white" : "bg-sky text-violet-dark"}`}
                >
                  <StepIcon kind={s.kind} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-bold leading-snug">{s.label}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px]">
                    <span className={`chip px-2 py-0 text-[12px] ${ENGINE_CHIP[engine] ?? "bg-sky-deep text-ink-soft"}`}>{engine}</span>
                    {s.duration_ms !== null && <span className="num text-ink-faint">{fmtDuration(s.duration_ms)}</span>}
                    <span className={`chip px-2 py-0 text-[12px] ${out.chip}`}>{out.text}</span>
                  </span>
                  {s.transmitted && (
                    <span className="mt-1.5 flex items-start gap-1.5 rounded-lg bg-lagoon-soft px-2 py-1 text-[13px] text-lagoon-dark">
                      <Send className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                      <span>
                        {transmittedText(s.transmitted)}
                        {s.transmitted.fields.length > 0 && <span className="block text-[12px] opacity-80">champs : {s.transmitted.fields.join(", ")}</span>}
                      </span>
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {steps.length === 0 && <p className="px-4 py-6 text-[15px] text-ink-soft">{live ? "Les étapes s'afficheront ici au fil de l'eau." : "Aucune étape."}</p>}
    </div>
  );
}
