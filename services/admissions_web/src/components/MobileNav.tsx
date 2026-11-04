import { LayoutGrid } from "lucide-react";
import { useEffect, useState, type ComponentType } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

export interface NavItem {
  to: string;
  label: string;
  /** Shorter name for the bottom bar (four tabs on 390 px). */
  short?: string;
  icon: ComponentType<{ className?: string }>;
  admin?: boolean;
}

/**
 * The four screens each persona opens every day, under the thumb on a phone or a tablet:
 * the bed manager and the cadre live on the bed board and the emergency tension; the
 * direction follows tension, the group and the forecast; the administrator also runs the
 * agent. Everything else stays one tap away behind « Plus ».
 */
const PRIMARY: Record<string, string[]> = {
  coordination: ["/plan-des-lits", "/urgences", "/demandes", "/lits"],
  direction: ["/urgences", "/groupe", "/prevision", "/indicateurs"],
  admin_groupe: ["/plan-des-lits", "/urgences", "/demandes", "/agents"]
};

export function primaryFor(role: string | undefined): string[] {
  return PRIMARY[role ?? ""] ?? PRIMARY.coordination;
}

const tab = (active: boolean) =>
  `relative flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 rounded-xl px-1 text-[12px] font-bold transition-colors ${
    active ? "text-violet-dark" : "text-ink-soft hover:text-ink"
  }`;

/** Bottom tab bar for small screens (below lg); the sidebar takes over on a desk. */
export function MobileNav({
  items,
  primary,
  onIntent
}: {
  items: NavItem[];
  primary: string[];
  /** Called when a tab is about to be opened (touch down, focus): its screen can be fetched ahead. */
  onIntent?: (to: string) => void;
}) {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const main = primary.map((to) => items.find((i) => i.to === to)).filter((i): i is NavItem => Boolean(i));
  const rest = items.filter((i) => !primary.includes(i.to));
  const inRest = rest.some((i) => pathname.startsWith(i.to));

  useEffect(() => setOpen(false), [pathname]);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <nav
        aria-label="Navigation principale"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-paper/95 px-2 pb-[max(env(safe-area-inset-bottom),6px)] pt-1.5 backdrop-blur lg:hidden"
      >
        <ul className="flex gap-1">
          {main.map(({ to, label, short, icon: Icon }) => (
            <li key={to} className="flex flex-1">
              <NavLink to={to} onPointerDown={() => onIntent?.(to)} onFocus={() => onIntent?.(to)} className={({ isActive }) => tab(isActive)}>
                {({ isActive }) => (
                  <>
                    <span
                      aria-hidden
                      className={`grid h-7 w-12 place-items-center rounded-full transition-all duration-200 ${
                        isActive ? "bg-violet-soft" : ""
                      }`}
                    >
                      <Icon className="h-5 w-5" />
                    </span>
                    <span className="max-w-full truncate">{short ?? label}</span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
          <li className="flex flex-1">
            <SheetTrigger asChild>
              <button type="button" className={tab(inRest)} data-active={inRest}>
                <span
                  aria-hidden
                  className={`grid h-7 w-12 place-items-center rounded-full transition-all duration-200 ${inRest ? "bg-violet-soft" : ""}`}
                >
                  <LayoutGrid className="h-5 w-5" />
                </span>
                Plus
              </button>
            </SheetTrigger>
          </li>
        </ul>
      </nav>
      <MoreSheet items={rest} onIntent={onIntent} onClose={() => setOpen(false)} />
    </Sheet>
  );
}

/** Every other screen, in a sheet that comes up from the bar (shadcn/ui Sheet on Radix). */
function MoreSheet({ items, onIntent, onClose }: { items: NavItem[]; onIntent?: (to: string) => void; onClose: () => void }) {
  return (
    <SheetContent side="bottom" className="px-4 pb-[max(env(safe-area-inset-bottom),16px)] pt-2 lg:hidden" aria-describedby={undefined}>
      <div aria-hidden className="mx-auto mb-2 h-1.5 w-10 rounded-full bg-line" />
      <SheetTitle className="flex min-h-[44px] items-center font-display text-[17px] font-semibold">Tous les écrans</SheetTitle>
      <ul className="mt-2 grid grid-cols-2 gap-2">
        {items.map(({ to, label, icon: Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              onPointerDown={() => onIntent?.(to)}
              onClick={onClose}
              className={({ isActive }) =>
                `flex min-h-[56px] items-center gap-3 rounded-2xl px-3 py-2 text-[15px] font-bold transition-colors ${
                  isActive ? "bg-violet text-white" : "bg-sky text-ink hover:bg-sky-deep"
                }`
              }
            >
              <Icon className="h-5 w-5 shrink-0" aria-hidden />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </SheetContent>
  );
}
