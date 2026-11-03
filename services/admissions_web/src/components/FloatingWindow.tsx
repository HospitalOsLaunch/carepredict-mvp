import { GripHorizontal, Maximize2, Minimize2, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Where the window sits, in viewport pixels (its top-left corner), and its size. */
interface Frame {
  x: number;
  y: number;
  w: number;
  h: number;
}

const MARGIN = 12;
/** The header stays reachable: at least this much of the window remains on screen. */
const KEEP = 140;
const HEADER = 56;
const STEP = 32;

function viewport() {
  return { vw: window.innerWidth || 1280, vh: window.innerHeight || 800 };
}

/** Where a window opens: centred, or in the bottom-right corner like a picture-in-picture player. */
export type Placement = "center" | "bottom-right";

export function placed(placement: Placement, w: number, h: number): Frame {
  if (placement === "center") return centered(w, h);
  const { vw, vh } = viewport();
  const width = Math.min(w, vw - 2 * MARGIN);
  const height = Math.min(h, vh - 2 * MARGIN);
  return { x: vw - width - 2 * MARGIN, y: vh - height - 2 * MARGIN, w: width, h: height };
}

export function centered(w: number, h: number): Frame {
  const { vw, vh } = viewport();
  const width = Math.min(w, vw - 2 * MARGIN);
  const height = Math.min(h, vh - 2 * MARGIN);
  return { x: Math.round((vw - width) / 2), y: Math.round((vh - height) / 2), w: width, h: height };
}

/**
 * Keeps the window reachable: sideways it may be pushed partly off screen to see the page
 * (its header stays grabbable), but never below the bottom edge when it fits, so the player
 * controls at its foot stay visible.
 */
export function clampFrame(f: Frame): Frame {
  const { vw, vh } = viewport();
  const h = Math.min(f.h, vh);
  const lowest = h + MARGIN <= vh ? vh - h - MARGIN : vh - HEADER;
  return {
    ...f,
    h,
    x: Math.round(Math.min(Math.max(f.x, KEEP - f.w), vw - KEEP)),
    y: Math.round(Math.min(Math.max(f.y, 0), Math.max(0, lowest)))
  };
}

function load(key: string | undefined): Frame | null {
  if (!key) return null;
  try {
    const f = JSON.parse(localStorage.getItem(key) ?? "null") as Frame | null;
    return f && [f.x, f.y, f.w, f.h].every((n) => typeof n === "number" && Number.isFinite(n)) ? f : null;
  } catch {
    return null;
  }
}

function save(key: string | undefined, f: Frame) {
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify(f));
  } catch {
    /* storage unavailable: the window opens centred next time */
  }
}

function useCompact(): boolean {
  const query = "(max-width: 639px)";
  const [compact, setCompact] = useState(() => typeof window.matchMedia === "function" && window.matchMedia(query).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(query);
    const on = () => setCompact(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return compact;
}

/**
 * A window over the page it was opened from: the page stays usable behind it (non-modal).
 * Dragged by its header (mouse, finger or pen), or moved with the arrow keys on its handle
 * (WCAG 2.5.7: dragging is never the only way); resized from its corner; enlarged to the
 * screen and back; closed by its button or Escape. It remembers where it was on this device.
 * On a phone it takes the whole screen: there is no room to move it.
 */
export function FloatingWindow({
  title,
  titleId,
  badge,
  subtitle,
  tools,
  onClose,
  children,
  storageKey,
  initialSize = { w: 1120, h: 820 },
  placement = "center"
}: {
  title: ReactNode;
  titleId: string;
  /** A short state shown beside the title (« En direct »…). */
  badge?: ReactNode;
  subtitle?: ReactNode;
  /** Controls placed in the header before the window buttons (a view switch…). */
  tools?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  storageKey?: string;
  initialSize?: { w: number; h: number };
  placement?: Placement;
}) {
  const compact = useCompact();
  const [frame, setFrame] = useState<Frame>(() => clampFrame(load(storageKey) ?? placed(placement, initialSize.w, initialSize.h)));
  const [maximized, setMaximized] = useState(false);
  const [dragging, setDragging] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ dx: number; dy: number; id: number } | null>(null);
  const opener = useRef<Element | null>(null);

  // Focus moves into the window when it opens, and back to what opened it when it closes.
  useLayoutEffect(() => {
    opener.current = document.activeElement;
    rootRef.current?.focus();
    return () => {
      const back = opener.current as HTMLElement | null;
      if (back && back.isConnected && typeof back.focus === "function") back.focus();
    };
  }, []);

  useEffect(() => {
    const onResize = () => setFrame((f) => clampFrame({ ...f, w: Math.min(f.w, window.innerWidth - 2 * MARGIN) }));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // The size the person gives the window with its corner is kept as well.
  useEffect(() => {
    const el = rootRef.current;
    if (!el || compact || maximized || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      const w = Math.round(el.offsetWidth);
      const h = Math.round(el.offsetHeight);
      setFrame((f) => (Math.abs(f.w - w) > 1 || Math.abs(f.h - h) > 1 ? { ...f, w, h } : f));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [compact, maximized]);

  useEffect(() => {
    if (!dragging) save(storageKey, frame);
  }, [frame, dragging, storageKey]);

  const recenter = useCallback(() => setFrame((f) => clampFrame(placed(placement, f.w, f.h))), [placement]);
  const movable = !compact && !maximized;
  // A small window (the 420 px player) lays its header out tighter, whatever the screen.
  const tight = !compact && !maximized && frame.w < 640;

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!movable || e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button, a, input, select, textarea, [data-no-drag]")) return;
    drag.current = { dx: e.clientX - frame.x, dy: e.clientY - frame.y, id: e.pointerId };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDragging(true);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    setFrame((f) => clampFrame({ ...f, x: e.clientX - d.dx, y: e.clientY - d.dy }));
  };
  const endDrag = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    drag.current = null;
    setDragging(false);
  };

  const onHandleKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const by = e.shiftKey ? STEP * 3 : STEP;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-by, 0], ArrowRight: [by, 0], ArrowUp: [0, -by], ArrowDown: [0, by] };
    if (e.key === "Home") {
      e.preventDefault();
      recenter();
    } else if (moves[e.key]) {
      e.preventDefault();
      e.stopPropagation(); // the arrows move the window here, not the player
      const [dx, dy] = moves[e.key];
      setFrame((f) => clampFrame({ ...f, x: f.x + dx, y: f.y + dy }));
    }
  };

  const style = compact || maximized ? undefined : { left: frame.x, top: frame.y, width: frame.w, height: frame.h };

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      tabIndex={-1}
      data-player-host
      data-tight={tight || undefined}
      data-testid="floating-window"
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        const tag = (e.target as HTMLElement).tagName;
        if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
        e.stopPropagation();
        onClose();
      }}
      style={style}
      className={cn(
        "window-in group fixed z-40 flex flex-col overflow-hidden bg-sky text-ink outline-none",
        compact || maximized
          ? "inset-0 sm:inset-3 sm:rounded-[20px] sm:shadow-2xl sm:ring-1 sm:ring-ink/10"
          : "min-h-[22rem] min-w-[20rem] max-w-[calc(100vw-24px)] resize rounded-[20px] shadow-[0_30px_80px_-24px_rgba(28,25,70,0.55)] ring-1 ring-ink/10",
        dragging && "select-none"
      )}
    >
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={(e) => {
          if (!(e.target as HTMLElement).closest("button, a")) setMaximized((m) => !m);
        }}
        data-testid="window-handle"
        className={cn(
          "flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-paper px-3 py-2 sm:px-4",
          movable && (dragging ? "cursor-grabbing" : "cursor-grab")
        )}
      >
        {movable && (
          <button
            type="button"
            onKeyDown={onHandleKey}
            onClick={recenter}
            aria-label={`Déplacer la fenêtre : flèches pour la déplacer, Début pour la replacer ${placement === "center" ? "au centre" : "en bas à droite"}`}
            title="Glisser l'en-tête pour déplacer · flèches au clavier · double-clic pour agrandir"
            className="touch-target -ml-1 grid h-9 w-9 shrink-0 cursor-grab place-items-center rounded-xl text-ink-faint transition-colors hover:bg-sky hover:text-ink"
          >
            <GripHorizontal className="h-5 w-5" aria-hidden />
          </button>
        )}
        <div className={cn("min-w-0 flex-1", tight ? "basis-0" : "basis-[12rem]")}>
          <div className={cn("flex min-w-0 items-center gap-x-2 gap-y-1", tight ? "flex-nowrap" : "flex-wrap")}>
            <h2 id={titleId} className={cn("min-w-0 leading-tight", tight ? "line-clamp-2 text-[15px]" : "truncate text-[18px] sm:text-[20px]")}>
              {title}
            </h2>
            {badge}
          </div>
          {subtitle && <div className="mt-0.5 min-w-0 text-[13px] text-ink-soft">{subtitle}</div>}
        </div>
        {/* In a tight window the tools stay on the title row (icons only); on a phone, their own row. */}
        {tools && <div className={cn("flex justify-start", tight ? "shrink-0" : "order-last w-full md:order-none md:w-auto")}>{tools}</div>}
        <div className="flex shrink-0 items-center gap-1 self-start md:self-center">
          {!compact && (
            <button
              type="button"
              onClick={() => setMaximized((m) => !m)}
              aria-label={maximized ? "Restaurer la taille de la fenêtre" : "Agrandir la fenêtre"}
              title={maximized ? "Restaurer" : "Agrandir"}
              className="touch-target grid h-9 w-9 place-items-center rounded-xl text-ink transition-colors hover:bg-sky"
            >
              {maximized ? <Minimize2 className="h-4 w-4" aria-hidden /> : <Maximize2 className="h-4 w-4" aria-hidden />}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer le player"
            title="Fermer (Échap)"
            className="touch-target grid h-9 w-9 place-items-center rounded-xl text-ink transition-colors hover:bg-coral-soft hover:text-coral-dark"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </div>
  );
}
