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
export const BookIcon = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M3 2.5h8.5a1 1 0 0 1 1 1v10H4.5A1.5 1.5 0 0 1 3 12V2.5Z" />
    <path d="M3 12a1.5 1.5 0 0 1 1.5-1.5h8M6 5.5h4" />
  </Svg>
);
export const Search = (p: { size?: number }) => (
  <Svg {...p}>
    <circle cx="7" cy="7" r="4.5" />
    <path d="M10.5 10.5l3 3" />
  </Svg>
);
export const Download = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M8 2.5v8M4.5 7.5 8 11l3.5-3.5M3 13.5h10" />
  </Svg>
);
export const Copy = (p: { size?: number }) => (
  <Svg {...p}>
    <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
    <path d="M3.5 10.5h-1v-8h8v1" />
  </Svg>
);
export const LinkIcon = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M7 9a3 3 0 0 0 4.2 0l2-2A3 3 0 0 0 9 2.8l-1 1M9 7a3 3 0 0 0-4.2 0l-2 2A3 3 0 0 0 7 13.2l1-1" />
  </Svg>
);
export const PulseIcon = (p: { size?: number }) => (
  <Svg {...p}>
    <path d="M1.5 8.5h3l1.5-4 3 7 1.5-3h4" />
  </Svg>
);

/**
 * The HospitalOS symbol: two beds and, between them, a sun rising — the place that
 * frees up lets the light in. Pills take the brand blue, the sun the light.
 */
export const Mark = ({ size = 24 }: { size?: number }) => (
  <svg className="brand__mark" width={size} height={size} viewBox="0 0 256 256" aria-hidden="true">
    <rect x="36" y="32" width="52" height="192" rx="26" fill="var(--brand)" />
    <rect x="168" y="32" width="52" height="192" rx="26" fill="var(--brand)" />
    <circle className="brand__sun" cx="128" cy="108" r="30" fill="var(--sun)" />
  </svg>
);
