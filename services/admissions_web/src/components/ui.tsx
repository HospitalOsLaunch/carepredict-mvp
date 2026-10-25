import { AlertTriangle, Loader2, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import type { RequestStatus } from "../api/types";

export function Spinner({ label = "Chargement" }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-ink-soft">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}…
    </span>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Une erreur est survenue.";
  return (
    <p role="alert" className="flex items-start gap-2 rounded-xl bg-coral-soft px-3 py-2 text-[15px] text-coral-dark">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> {message}
    </p>
  );
}

const STATUS_STYLE: Record<RequestStatus, string> = {
  nouvelle: "bg-coral-soft text-coral-dark",
  en_etude: "bg-violet-soft text-violet-dark",
  accord: "bg-lagoon-soft text-lagoon-dark",
  confirmee: "bg-lagoon text-white",
  admise: "bg-ink text-white",
  refusee: "bg-sky-deep text-ink-soft",
  perdue: "bg-sky-deep text-ink-soft"
};

export function StatusChip({ status, label }: { status: RequestStatus; label: string }) {
  return <span className={`chip ${STATUS_STYLE[status]}`}>{label}</span>;
}

export function PageHeader({ title, lead, actions }: { title: ReactNode; lead?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1>{title}</h1>
        {lead && <p className="mt-2 text-[17px] text-ink-soft">{lead}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide = false
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className={`w-[calc(100%-2rem)] ${wide ? "max-w-3xl" : "max-w-lg"} rounded-panel bg-paper p-0 text-ink shadow-2xl backdrop:bg-ink/40`}
      aria-labelledby="modal-title"
    >
      <div className="flex items-center justify-between border-b border-line px-6 py-4">
        <h2 id="modal-title">{title}</h2>
        <button type="button" className="btn-ghost h-9 w-9 p-0" onClick={onClose} aria-label="Fermer">
          <X className="h-5 w-5" aria-hidden />
        </button>
      </div>
      <div className="max-h-[75vh] overflow-y-auto px-6 py-5">{children}</div>
    </dialog>
  );
}

export function Meter({ value, tone = "violet" }: { value: number; tone?: "violet" | "sun" | "coral" | "lagoon" }) {
  const color = { violet: "bg-violet", sun: "bg-sun", coral: "bg-coral", lagoon: "bg-lagoon" }[tone];
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-sky-deep" aria-hidden>
      <span className={`block h-full rounded-full ${color}`} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-panel border-2 border-dashed border-line px-6 py-10 text-center">
      <p className="font-display text-lg font-semibold">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-md text-ink-soft">{children}</div>}
    </div>
  );
}
