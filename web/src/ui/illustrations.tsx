import type { ReactNode } from "react";
import type { Plan } from "../api/types";

/*
  Spot illustrations « Lumière » — emotional design, kept fine and light.
  One grammar for all of them, on a 64 grid:
  - a soft blob in a wash tone behind (sun, mint, lavender or apricot);
  - objects drawn with a single 1.5 px ink line that never scales with size;
  - flat fills from the palette, one or two per drawing, plus a sparkle of sun.
  Purely decorative: aria-hidden, never carry meaning on their own, and every colour
  comes from the tokens so the night theme follows.
*/

type Tone = "sun" | "mint" | "lav" | "apri";

const BLOBS = [
  "M33 7c12 0 23 8 24 20s-5 24-16 28-25 2-31-7S5 26 11 17s10-10 22-10Z",
  "M30 8c11-1 23 4 26 15s0 23-10 29-24 5-31-4-7-22-1-30 5-9 16-10Z",
  "M35 9c10 2 19 10 20 21s-6 21-17 24-24 0-29-9-3-22 4-29 11-9 22-7Z",
] as const;

/** Four-point sparkle centred on (x, y). */
const sp = (x: number, y: number, s: number) =>
  `M${x} ${y - s}Q${x} ${y} ${x + s} ${y}Q${x} ${y} ${x} ${y + s}Q${x} ${y} ${x - s} ${y}Q${x} ${y} ${x} ${y - s}Z`;

const Sparkle = ({ x, y, s = 3 }: { x: number; y: number; s?: number }) => (
  <path className="sun spark" d={sp(x, y, s)} />
);

const Window = ({ children }: { children: ReactNode }) => (
  <>
    <rect className="p l" x="14" y="12" width="36" height="40" rx="5" />
    {children}
    <path className="l" d="M14 42h36" />
    <path className="l" d="M11 17h42" />
    <path className="lav l" d="M14 17h8c-1 9-4 15-8 19Z" />
    <path className="lav l" d="M50 17h-8c1 9 4 15 8 19Z" />
    <path className="l" d="M9 52h46" />
  </>
);

const ART = {
  // ---- moments of the day (greeting)
  morning: {
    tone: "sun",
    blob: 0,
    body: (
      <Window>
        <g className="rise">
          <path className="sun" d="M22 42a10 10 0 0 1 20 0Z" />
          <path className="l" d="M32 27v-3M24 31l-2-2M40 31l2-2" />
        </g>
      </Window>
    ),
  },
  evening: {
    tone: "apri",
    blob: 1,
    body: (
      <Window>
        <path className="apri" d="M25 42a7 7 0 0 1 14 0Z" />
        <Sparkle x={38} y={26} s={2.5} />
      </Window>
    ),
  },
  night: {
    tone: "lav",
    blob: 2,
    body: (
      <>
        <path className="sun l" d="M40 10A12 12 0 1 0 52 28A10 10 0 0 1 40 10Z" />
        <Sparkle x={20} y={16} />
        <Sparkle x={28} y={26} s={2} />
        <path className="l" d="M21 34c-2-2 2-3 0-6M27 34c-2-2 2-3 0-6" />
        <path className="p l" d="M14 38h20v6a8 8 0 0 1-8 8h-4a8 8 0 0 1-8-8Z" />
        <path className="l" d="M34 41h2a3.5 3.5 0 0 1 0 7h-2" />
        <path className="l" d="M10 55h30" />
      </>
    ),
  },

  // ---- the three flow zones
  door: {
    tone: "sun",
    blob: 0,
    body: (
      <>
        <path className="sun o" d="M30 54h14l8 6H24Z" />
        <rect className="sun l" x="20" y="10" width="24" height="44" rx="2" />
        <path className="p l" d="M20 10l12 4v36l-12 4Z" />
        <circle className="ink" cx="29" cy="33" r="1.3" />
        <path className="l" d="M6 54h52" />
        <path className="l" d="M50 42v-3h5v3" />
        <rect className="mint l" x="46" y="42" width="13" height="12" rx="2" />
        <Sparkle x={11} y={20} />
      </>
    ),
  },
  bed: {
    tone: "lav",
    blob: 1,
    body: (
      <>
        <circle className="sun" cx="46" cy="17" r="6" />
        <Sparkle x={22} y={16} />
        <path className="l" d="M10 24v30M54 36v18" />
        <rect className="p l" x="10" y="40" width="44" height="8" rx="2" />
        <rect className="mint l" x="24" y="32" width="30" height="8" rx="3" />
        <rect className="p l" x="13" y="31" width="11" height="9" rx="4" />
      </>
    ),
  },
  key: {
    tone: "mint",
    blob: 2,
    body: (
      <>
        <path className="l" d="M32 36h22M48 36v6M53 36v5" />
        <circle className="sun l" cx="22" cy="36" r="10" />
        <circle className="p l" cx="19" cy="36" r="3" />
        <path className="apri l" d="M44 26c-4-3-6-5-6-7.5a3 3 0 0 1 6-1a3 3 0 0 1 6 1c0 2.5-2 4.5-6 7.5Z" />
        <Sparkle x={14} y={17} />
      </>
    ),
  },

  // ---- the proposal, by what it asks
  plane: {
    tone: "lav",
    blob: 0,
    body: (
      <>
        <path className="l dash" d="M5 49c6 0 10-4 16-4" />
        <path className="p l" d="M12 32L54 14L31 39Z" />
        <path className="lav l" d="M31 39L54 14L42 50Z" />
        <path className="brand l" d="M31 39l2 9 5-4Z" />
        <Sparkle x={16} y={16} />
        <Sparkle x={52} y={40} s={2} />
      </>
    ),
  },
  transport: {
    tone: "sun",
    blob: 1,
    body: (
      <>
        <circle className="sun" cx="50" cy="14" r="5" />
        <path className="l" d="M2 31h4M1 36h5" />
        <path className="p l" d="M8 45V30a6 6 0 0 1 6-6h26l10 8h4a2 2 0 0 1 2 2v11Z" />
        <path className="lav l" d="M14 29h10v6H14Z" />
        <path className="lav l" d="M28 29h9l6 6H28Z" />
        <path className="mint" d="M9 39h46v2.5H9Z" />
        <path className="l" d="M4 50h56" />
        <circle className="p l" cx="18" cy="45" r="5" />
        <circle className="p l" cx="44" cy="45" r="5" />
        <circle className="ink" cx="18" cy="45" r="1.3" />
        <circle className="ink" cx="44" cy="45" r="1.3" />
      </>
    ),
  },
  spray: {
    tone: "mint",
    blob: 2,
    body: (
      <>
        <path className="l" d="M24 30v-5h8v5" />
        <path className="mint l" d="M21 19h15l5 3h-5v3H21Z" />
        <path className="p l" d="M20 30h16v20a4 4 0 0 1-4 4h-8a4 4 0 0 1-4-4Z" />
        <rect className="lav" x="23" y="37" width="10" height="9" rx="2" />
        <circle className="ink" cx="45" cy="21" r="0.9" />
        <circle className="ink" cx="48" cy="24" r="0.9" />
        <circle className="ink" cx="45" cy="26" r="0.9" />
        <Sparkle x={50} y={14} s={4} />
        <Sparkle x={55} y={29} s={2.5} />
      </>
    ),
  },
  coffee: {
    tone: "mint",
    blob: 0,
    body: (
      <>
        <path className="l" d="M23 25c-2-2.5 2-4 0-7M29 25c-2-2.5 2-4 0-7M35 25c-2-2.5 2-4 0-7" />
        <path className="p l" d="M16 30h24v9a11 11 0 0 1-11 11h-2a11 11 0 0 1-11-11Z" />
        <path className="l" d="M40 33h3a4.5 4.5 0 0 1 0 9h-3" />
        <path
          className="apri"
          d="M28 44c-3-2-4.5-3.5-4.5-5.2a2.2 2.2 0 0 1 4.5-.6a2.2 2.2 0 0 1 4.5.6c0 1.7-1.5 3.2-4.5 5.2Z"
        />
        <path className="l" d="M11 54h34" />
        <Sparkle x={49} y={17} />
      </>
    ),
  },
  cloud: {
    tone: "apri",
    blob: 1,
    body: (
      <>
        <circle className="sun" cx="40" cy="24" r="10" />
        <path className="l" d="M40 9V6M51 13l2-2M55 24h3" />
        <path className="p l" d="M18 48a7 7 0 0 1-1-14a10 10 0 0 1 19-4a8 8 0 0 1 12 7a6 6 0 0 1-1 11Z" />
      </>
    ),
  },

  // ---- pages, empty states, help
  magnifier: {
    tone: "lav",
    blob: 2,
    body: (
      <>
        <rect className="p l" x="12" y="10" width="28" height="38" rx="3" />
        <path className="l" d="M18 19h16M18 25h16M18 31h9" />
        <path className="l thick" d="M46.5 44.5l7 7" />
        <circle className="glass l" cx="40" cy="38" r="9" />
        <path className="l ok" d="M36 38l3 3 5-6" />
      </>
    ),
  },
  suitcase: {
    tone: "mint",
    blob: 0,
    body: (
      <>
        <path className="l" d="M26 24v-4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v4" />
        <rect className="p l" x="14" y="24" width="36" height="28" rx="4" />
        <rect className="mint o" x="22.8" y="24.8" width="18.4" height="26.4" />
        <path className="l" d="M22 24v28M42 24v28" />
        <path className="l" d="M8 52h48" />
        <path className="l" d="M38 21c2 0 4-1 6-1" />
        <path className="apri l" d="M44 20l6-2 2 6-6 2Z" />
        <Sparkle x={54} y={13} />
      </>
    ),
  },
  boat: {
    tone: "lav",
    blob: 1,
    body: (
      <>
        <circle className="sun" cx="47" cy="17" r="6" />
        <path className="p l" d="M31 12v30H17Z" />
        <path className="apri l" d="M34 18v24h10Z" />
        <path className="brand l" d="M14 44h36l-5 7H19Z" />
        <path className="l" d="M6 57c3-2 6-2 9 0s6 2 9 0 6-2 9 0 6 2 9 0 6-2 9 0" />
      </>
    ),
  },
  keys: {
    tone: "sun",
    blob: 2,
    body: (
      <>
        <rect className="p l" x="8" y="30" width="15" height="15" rx="3" />
        <rect className="p l" x="25" y="22" width="15" height="15" rx="3" />
        <rect className="p l" x="42" y="30" width="15" height="15" rx="3" />
        <path className="l" d="M10 48h11M27 40h11M44 48h11" />
        <path className="l" d="M12 37.5h7M16 34.5l3 3-3 3" />
        <path className="l" d="M34 25l-3 5h4l-3 5" />
        <circle className="apri" cx="49.5" cy="37.5" r="3" />
        <Sparkle x={14} y={17} />
        <Sparkle x={52} y={18} s={2} />
      </>
    ),
  },

  // ---- small section marks (data quality, proposal detail)
  puzzle: {
    tone: "mint",
    blob: 0,
    body: (
      <>
        <path className="mint l" d="M14 20h12a4 4 0 1 1 8 0h12v12a4 4 0 1 0 0 8v12H14Z" />
        <Sparkle x={52} y={14} />
      </>
    ),
  },
  hourglass: {
    tone: "apri",
    blob: 1,
    body: (
      <>
        <path className="p l" d="M21 12c0 10 11 14 11 20s-11 10-11 20h22c0-10-11-14-11-20s11-10 11-20Z" />
        <path className="apri" d="M25 18h14c-1 4-4 7-7 9-3-2-6-5-7-9Z" />
        <path className="apri" d="M24 50c1-5 5-8 8-9 3 1 7 4 8 9Z" />
        <path className="l" d="M17 12h30M17 52h30" />
      </>
    ),
  },
  envelope: {
    tone: "lav",
    blob: 2,
    body: (
      <>
        <rect className="p l" x="10" y="18" width="44" height="30" rx="3" />
        <path className="l" d="M11 20l21 15 21-15" />
        <circle className="sun l" cx="52" cy="18" r="5" />
      </>
    ),
  },
  clipboard: {
    tone: "mint",
    blob: 1,
    body: (
      <>
        <rect className="p l" x="14" y="12" width="32" height="42" rx="3" />
        <rect className="lav l" x="23" y="9" width="14" height="7" rx="2" />
        <path className="l ok" d="M20 26l2.5 2.5 4.5-5M20 37l2.5 2.5 4.5-5" />
        <path className="l" d="M31 26h9M31 37h9M20 47h20" />
      </>
    ),
  },
  box: {
    tone: "apri",
    blob: 0,
    body: (
      <>
        <path className="p l" d="M12 24l20-10 20 10v22l-20 10-20-10Z" />
        <path className="apri o" d="M20 20l20 10 4-2-20-10Z" />
        <path className="l" d="M12 24l20 10 20-10M32 34v22" />
        <Sparkle x={53} y={12} />
      </>
    ),
  },
  notebook: {
    tone: "lav",
    blob: 2,
    body: (
      <>
        <rect className="p l" x="16" y="10" width="32" height="44" rx="3" />
        <path className="sun" d="M40 10.8v12l3-2.5 3 2.5v-12Z" />
        <path className="l" d="M22 10v44" />
        <path className="l" d="M13 18h6M13 28h6M13 38h6M13 48h6" />
        <path className="l" d="M27 20h10M27 27h15M27 34h10" />
      </>
    ),
  },
  signpost: {
    tone: "sun",
    blob: 1,
    body: (
      <>
        <path className="l" d="M32 14v42M24 56h16" />
        <path className="p l" d="M18 18h22l5 5-5 5H18Z" />
        <path className="mint l" d="M46 32H24l-5 5 5 5h22Z" />
      </>
    ),
  },
  balance: {
    tone: "lav",
    blob: 0,
    body: (
      <>
        <path className="l" d="M32 12v40M22 52h20M14 20h36" />
        <path className="l" d="M14 20l-6 14M14 20l6 14M50 20l-6 14M50 20l6 14" />
        <circle className="sun" cx="32" cy="12" r="3.5" />
        <path className="mint l" d="M7 34h14a7 7 0 0 1-14 0Z" />
        <path className="apri l" d="M43 34h14a7 7 0 0 1-14 0Z" />
      </>
    ),
  },
  path: {
    tone: "mint",
    blob: 2,
    body: (
      <>
        <path className="l dash" d="M12 52c10 0 14-6 20-12s8-12 18-12" />
        <circle className="lav l" cx="12" cy="52" r="4" />
        <path className="l" d="M50 28V11" />
        <path className="sun l" d="M50 11h10l-3 4 3 4H50Z" />
        <Sparkle x={24} y={24} />
      </>
    ),
  },
  bulb: {
    tone: "sun",
    blob: 1,
    body: (
      <>
        <path className="l" d="M32 4v2M15 11l2 2M49 11l-2 2M10 24h3M51 24h3" />
        <path className="p l" d="M32 10a14 14 0 0 1 8 25.5V42H24v-6.5A14 14 0 0 1 32 10Z" />
        <circle className="sun" cx="32" cy="24" r="6" />
        <path className="l" d="M25 46h14M27 50h10" />
      </>
    ),
  },
  tag: {
    tone: "lav",
    blob: 0,
    body: (
      <>
        <path className="l" d="M22 19c-2-6-8-8-12-6" />
        <path className="p l" d="M14 14h18l20 20-18 18-20-20Z" />
        <path className="mint o" d="M33 36l6-6 6 6-6 6Z" />
        <circle className="l" cx="22" cy="22" r="3" />
      </>
    ),
  },
} satisfies Record<string, { tone: Tone; blob: 0 | 1 | 2; body: JSX.Element }>;

export type IlluName = keyof typeof ART;

export function Illu({ name, size = 40, className }: { name: IlluName; size?: number; className?: string }) {
  const art = ART[name];
  return (
    <svg
      className={`illu illu--${art.tone} illu--${name}${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden="true"
      focusable="false"
    >
      <path className="illu__blob" d={BLOBS[art.blob]} />
      {art.body}
    </svg>
  );
}

/** The drawing that goes with a proposal: it shows what the action asks for. */
export function proposalIllu(plan: Plan | null): IlluName {
  if (!plan) return "plane";
  if (plan.decision === "abstain") return "cloud";
  if (plan.decision === "no_change") return "coffee";
  switch (plan.selected.kind) {
    case "request_transport":
      return "transport";
    case "prioritize_cleaning":
      return "spray";
    case "reserve_bed":
      return "key";
    default:
      return "plane";
  }
}

/** Morning window, evening glow, or the night-shift moon and tea. */
export function momentIllu(hour: number): IlluName {
  if (hour >= 5 && hour < 18) return "morning";
  if (hour >= 18 && hour < 22) return "evening";
  return "night";
}

/** An empty state that breathes: a drawing, a short headline, one line of help. */
export function Empty({ illu, title, children }: { illu: IlluName; title: string; children?: ReactNode }) {
  return (
    <div className="empty empty--illu">
      <Illu name={illu} size={72} />
      <div>
        <p className="empty__title">{title}</p>
        {children ? <p>{children}</p> : null}
      </div>
    </div>
  );
}
