import { parseDay } from "../lib/format";

export interface LampDay {
  day: string;
  free_expected: number;
  prob_at_least_one_free: number;
  reserved?: number;
}

const WEEKDAY = new Intl.DateTimeFormat("fr-FR", { weekday: "narrow" });

/** A bed is "sûr" when P(at least one free bed) >= 80 %, "probable" when one is expected. */
export function lampState(d: LampDay): "sur" | "probable" | "eteint" {
  if (d.prob_at_least_one_free >= 0.8) return "sur";
  if (d.free_expected >= 1) return "probable";
  return "eteint";
}

const STATE_LABEL = { sur: "lit sûr", probable: "lit probable", eteint: "aucun lit prévu" } as const;

interface Props {
  days: LampDay[];
  size?: "sm" | "md";
  highlight?: string | null;
  onPick?: (day: string) => void;
  animate?: boolean;
}

export function LampStrip({ days, size = "md", highlight, onPick, animate = false }: Props) {
  const lamp = size === "md" ? "h-7 w-7" : "h-[18px] w-[18px]";
  const gap = size === "md" ? "gap-1.5" : "gap-1";
  return (
    <ol className={`relative flex ${gap}`} aria-label="Lits libres prévus, jour par jour">
      {days.map((d, i) => {
        const state = lampState(d);
        const free = Math.max(0, Math.round(d.free_expected));
        const date = parseDay(d.day);
        const isHighlight = highlight === d.day;
        const text = `${date.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })} : ${STATE_LABEL[state]}, ${free} lit${free > 1 ? "s" : ""} libre${free > 1 ? "s" : ""} attendu${free > 1 ? "s" : ""}`;
        const body = (
          <>
            <span
              aria-hidden
              style={animate ? { animationDelay: `${i * 45}ms` } : undefined}
              className={[
                "relative grid place-items-center rounded-full",
                lamp,
                animate && state !== "eteint" ? "lamp-on" : "",
                state === "sur" ? "bg-sun shadow-[0_0_0_4px_rgba(255,178,30,0.22),0_0_18px_rgba(255,178,30,0.55)]" : "",
                state === "probable" ? "bg-sun-soft ring-2 ring-inset ring-sun" : "",
                state === "eteint" ? "bg-sky ring-1 ring-inset ring-line" : ""
              ].join(" ")}
            >
              {size === "md" && state !== "eteint" && (
                <span className="num text-[12px] font-bold leading-none text-ink">{free}</span>
              )}
            </span>
            <span
              aria-hidden
              className={`num leading-none ${size === "md" ? "text-[11px]" : "text-[9px]"} ${
                isHighlight ? "font-bold text-violet" : "text-ink-faint"
              }`}
            >
              {size === "md" ? `${WEEKDAY.format(date)}${date.getDate()}` : date.getDate()}
            </span>
            <span className="sr-only">{text}</span>
          </>
        );
        return (
          <li key={d.day} className="relative flex">
            {onPick ? (
              <button
                type="button"
                onClick={() => onPick(d.day)}
                title={text}
                className={`flex flex-col items-center gap-1 rounded-lg px-0.5 py-1 hover:bg-sky ${
                  isHighlight ? "bg-violet-soft" : ""
                }`}
              >
                {body}
              </button>
            ) : (
              <span title={text} className="flex flex-col items-center gap-1 py-1">
                {body}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function LampLegend() {
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-ink-soft">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-3 rounded-full bg-sun shadow-[0_0_8px_rgba(255,178,30,0.7)]" /> Lit sûr (8 chances sur 10)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-3 rounded-full bg-sun-soft ring-2 ring-inset ring-sun" /> Lit probable
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-3 rounded-full bg-sky ring-1 ring-inset ring-line" /> Aucun lit prévu
      </span>
    </p>
  );
}
