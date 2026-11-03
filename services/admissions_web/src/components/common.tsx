import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import type { RequestStatus } from "../api/types";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

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

const STATUS_TONE: Record<RequestStatus, BadgeProps["tone"]> = {
  nouvelle: "coral",
  en_etude: "violet",
  accord: "lagoon",
  confirmee: "lagoon-solid",
  admise: "ink",
  refusee: "neutral",
  perdue: "neutral"
};

export function StatusChip({ status, label }: { status: RequestStatus; label: string }) {
  return <Badge tone={STATUS_TONE[status]}>{label}</Badge>;
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

/**
 * The app's dialog, on the shadcn/ui Dialog (Radix): focus trapped then restored to the
 * button that opened it, Escape and the backdrop close it, the page behind is hidden from
 * screen readers. Same props as before: every screen keeps its call.
 */
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
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={cn("p-0", wide ? "max-w-3xl" : "max-w-lg")} aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="max-h-[75vh] overflow-y-auto px-6 py-5">{children}</div>
      </DialogContent>
    </Dialog>
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
