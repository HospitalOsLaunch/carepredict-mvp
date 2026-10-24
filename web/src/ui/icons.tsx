// Minimal stroke icon set, 16px grid. Decorative unless a title is given.
import type { ReactNode } from "react";

function Svg({ children, size = 16, title }: { children: ReactNode; size?: number; title?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

export const Check = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M3.5 8.5l3 3 6-7" />
  </Svg>
);
export const Clock = (p: { size?: number }) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="5.5" />
    <path d="M8 5v3.2l2 1.3" />
  </Svg>
);
export const Cross = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
  </Svg>
);
export const Question = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M6 6.2a2 2 0 1 1 2.8 1.8c-.5.3-.8.7-.8 1.3v.3" />
    <circle cx="8" cy="11.8" r=".4" fill="currentColor" />
  </Svg>
);
export const Dash = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M5 8h6" />
  </Svg>
);
export const Alert = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M8 2.5l6 10.5H2z" />
    <path d="M8 7v2.5" />
    <circle cx="8" cy="11.3" r=".4" fill="currentColor" />
  </Svg>
);
export const Info = (p: { size?: number }) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="5.5" />
    <path d="M8 7.3V11" />
    <circle cx="8" cy="5.2" r=".4" fill="currentColor" />
  </Svg>
);
export const Back = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M9.5 3.5L5 8l4.5 4.5" />
  </Svg>
);
export const Refresh = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M12.5 5.5A5 5 0 1 0 13 9" />
    <path d="M12.8 2.6v3h-3" />
  </Svg>
);
export const Ban = (p: { size?: number }) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="5.5" />
    <path d="M4.2 11.8l7.6-7.6" />
  </Svg>
);
export const BoardIcon = (p: { size?: number }) => (
  <Svg {...p}>
    <rect x="2" y="3" width="12" height="10" rx="1.5" />
    <path d="M2 7h12M6 7v6M10 7v6" />
  </Svg>
);
export const ScalesIcon = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M8 2.5v11M4.5 13.5h7M3 5h10" />
    <path d="M3 5l-1.5 4a1.8 1.8 0 0 0 3 0zM13 5l-1.5 4a1.8 1.8 0 0 0 3 0z" />
  </Svg>
);
export const PulseIcon = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M1.5 8.5h3l1.5-4 3 7 1.5-3h4" />
  </Svg>
);

/** The mark: a bed outline whose headboard is an arrow handing over. */
export const Mark = () => (
  <svg className="brand__mark" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="1" y="1" width="22" height="22" rx="5" fill="var(--ink)" />
    <path
      d="M5.5 16.5v-6m0 3h13v3m-9.5-3v-2.2a1.3 1.3 0 0 1 1.3-1.3h6.9a1.3 1.3 0 0 1 1.3 1.3v2.2"
      stroke="var(--board)"
      strokeWidth="1.6"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <circle cx="7.6" cy="10.4" r="1.3" fill="var(--bloc)" />
  </svg>
);
