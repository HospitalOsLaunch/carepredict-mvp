import { LayoutGrid, X } from "lucide-react";
import { useEffect, useRef, useState, type ComponentType } from "react";
import { NavLink, useLocation } from "react-router-dom";

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
  admin_groupe: ["/plan-des-lits", "/urgences", "/demandes", "/computer-use"]
};

export function primaryFor(role: string | undefined): string[] {
  return PRIMARY[role ?? ""] ?? PRIMARY.coordination;
}

const tab = (active: boolean) =>
  `relative flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 rounded-xl px-1 text-[12px] font-bold transition-colors ${
    active ? "text-violet-dark" : "text-ink-soft hover:text-ink"
  }`;

/** Bottom tab bar for small screens (below lg); the sidebar takes over on a desk. */
export function MobileNav({ items, primary }: { items: NavItem[]; primary: string[] }) {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const main = primary.map((to) => items.find((i) => i.to === to)).filter((i): i is NavItem => Boolean(i));
  const rest = items.filter((i) => !primary.includes(i.to));
  const inRest = rest.some((i) => pathname.startsWith(i.to));

  useEffect(() => setOpen(false), [pathname]);

  return (
    <>
      <nav
        aria-label="Navigation principale"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-paper/95 px-2 pb-[max(env(safe-area-inset-bottom),6px)] pt-1.5 backdrop-blur lg:hidden"
      >
        <ul className="flex gap-1">
          {main.map(({ to, label, short, icon: Icon }) => (
            <li key={to} className="flex flex-1">
              <NavLink to={to} className={({ isActive }) => tab(isActive)}>
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
            <button
              type="button"
              className={tab(inRest)}
              data-active={inRest}
              aria-expanded={open}
              aria-haspopup="dialog"
              onClick={() => setOpen(true)}
            >
              <span
                aria-hidden
                className={`grid h-7 w-12 place-items-center rounded-full transition-all duration-200 ${inRest ? "bg-violet-soft" : ""}`}
              >
                <LayoutGrid className="h-5 w-5" />
              </span>
              Plus
            </button>
          </li>
        </ul>
      </nav>
      {open && <MoreSheet items={rest} onClose={() => setOpen(false)} />}
    </>
  );
}

function MoreSheet({ items, onClose }: { items: NavItem[]; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    close.current?.focus(); // keyboard and screen reader start inside the sheet
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby="more-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // tap on the backdrop
      }}
      className="sheet-up m-0 mt-auto w-full max-w-none rounded-t-[24px] bg-paper p-0 text-ink shadow-2xl backdrop:bg-ink/40 lg:hidden"
    >
      <div className="px-4 pb-[max(env(safe-area-inset-bottom),16px)] pt-2">
        <div aria-hidden className="mx-auto mb-2 h-1.5 w-10 rounded-full bg-line" />
        <div className="flex items-center justify-between">
          <h2 id="more-title" className="text-[17px]">
            Tous les écrans
          </h2>
          <button ref={close} type="button" className="btn-ghost h-11 w-11 p-0" onClick={onClose} aria-label="Fermer">
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>
        <ul className="mt-2 grid grid-cols-2 gap-2">
          {items.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
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
      </div>
    </dialog>
  );
}
