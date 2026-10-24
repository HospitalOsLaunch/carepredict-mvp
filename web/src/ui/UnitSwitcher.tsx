import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { UnitSummary } from "../domain/view";
import { duration } from "../domain/view";
import { plural } from "./common";

const DECISION: Record<UnitSummary["decision"], { label: string; tone: string }> = {
  recommend: { label: "Proposition", tone: "go" },
  no_change: { label: "Rien à changer", tone: "calm" },
  abstain: { label: "Abstention", tone: "warn" },
  pending: { label: "À évaluer", tone: "calm" },
};

function Status({ s }: { s: UnitSummary }) {
  return (
    <span className="unit-status">
      <span
        className={`unit-status__dot unit-status__dot--${DECISION[s.decision].tone}`}
        aria-hidden="true"
      />
      {DECISION[s.decision].label}
    </span>
  );
}

function Line({ s }: { s: UnitSummary }) {
  return (
    <span className="unit-line num">
      {s.waiting ? plural(s.waiting, "à placer", "à placer") : "Personne à placer"}
      {s.longestWaitMinutes != null ? `, jusqu'à ${duration(s.longestWaitMinutes)}` : ""}
      {" · "}
      {s.usable ? plural(s.usable, "lit utilisable", "lits utilisables") : "aucun lit utilisable"}
    </span>
  );
}

/**
 * Unit switcher: an ARIA listbox popup. Keyboard: Enter/Space/↓ opens, ↑↓ Home End move,
 * Enter selects, Escape closes and returns focus. Digits 1–9 switch directly (global shortcut).
 */
export function UnitSwitcher({
  summaries,
  unitId,
  onSelect,
  openSignal,
}: {
  summaries: UnitSummary[];
  unitId: string;
  onSelect: (id: string) => void;
  openSignal: number;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const id = useId();
  const current = summaries.find((s) => s.id === unitId) ?? summaries[0];
  const single = summaries.length < 2;

  const show = useCallback(() => {
    if (single) return;
    setActive(
      Math.max(
        0,
        summaries.findIndex((s) => s.id === unitId),
      ),
    );
    setOpen(true);
  }, [single, summaries, unitId]);

  const close = useCallback((focus = true) => {
    setOpen(false);
    if (focus) button.current?.focus();
  }, []);

  useEffect(() => {
    if (openSignal) show();
  }, [openSignal, show]);

  useEffect(() => {
    if (open) list.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open, close]);

  if (!current) return null;

  const choose = (i: number) => {
    const s = summaries[i];
    if (s) onSelect(s.id);
    close();
  };

  const onKey = (e: React.KeyboardEvent) => {
    const last = summaries.length - 1;
    const moves: Record<string, () => void> = {
      ArrowDown: () => setActive((i) => Math.min(last, i + 1)),
      ArrowUp: () => setActive((i) => Math.max(0, i - 1)),
      Home: () => setActive(0),
      End: () => setActive(last),
      Enter: () => choose(active),
      " ": () => choose(active),
      Escape: () => close(),
      Tab: () => close(false),
    };
    const digit = Number(e.key);
    if (digit >= 1 && digit <= summaries.length) {
      e.preventDefault();
      choose(digit - 1);
      return;
    }
    const move = moves[e.key];
    if (move) {
      if (e.key !== "Tab") e.preventDefault();
      move();
    }
  };

  return (
    <div className="switcher" ref={root}>
      <button
        ref={button}
        type="button"
        className="switcher__button"
        aria-haspopup={single ? undefined : "listbox"}
        aria-expanded={single ? undefined : open}
        aria-controls={single ? undefined : `${id}-list`}
        onClick={() => (open ? close() : show())}
        onKeyDown={(e) => {
          if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
            e.preventDefault();
            show();
          }
        }}
      >
        <span className="switcher__name">{current.name}</span>
        <span className="switcher__meta">
          <Status s={current} />
        </span>
        {single ? null : (
          <svg className="switcher__chevron" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
            <path
              d="M3 4.5 6 7.5 9 4.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          </svg>
        )}
        {single ? null : <kbd className="kbd switcher__kbd">U</kbd>}
      </button>
      {open ? (
        <ul
          ref={list}
          id={`${id}-list`}
          className="switcher__list"
          role="listbox"
          tabIndex={-1}
          aria-label="Changer d'unité"
          aria-activedescendant={`${id}-opt-${active}`}
          onKeyDown={onKey}
        >
          {summaries.map((s, i) => (
            <li
              key={s.id}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={s.id === unitId}
              className={`switcher__option${i === active ? " is-active" : ""}`}
              onPointerEnter={() => setActive(i)}
              onClick={() => choose(i)}
            >
              <kbd className="kbd" aria-hidden="true">
                {i + 1}
              </kbd>
              <span className="switcher__option-main">
                <span className="switcher__option-name">{s.name}</span>
                <Line s={s} />
              </span>
              <Status s={s} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
