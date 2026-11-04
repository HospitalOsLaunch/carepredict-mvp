import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Loading placeholders that take the shape and the size of what is coming (règle 1 de
 * l'audit): the page no longer jumps when the data arrives, and the eye already knows where
 * to look. Sizes come from the loaded screens measured at 1440 px. The pulse stops under
 * `prefers-reduced-motion` (global rule in index.css).
 */
export function Skeleton({ className, as: Tag = "div" }: { className?: string; as?: "div" | "span" }) {
  return <Tag aria-hidden className={cn("block animate-pulse rounded-xl bg-sky-deep", className)} />;
}

/** Announces the wait once to screen readers; what is inside is hidden from them. */
export function Loading({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div role="status" aria-busy="true" aria-live="polite" className={className} data-testid="skeleton">
      <span className="sr-only">{label}…</span>
      {children}
    </div>
  );
}

/** A page title and its lead, while they depend on the data (Vue groupe). */
export function HeaderSkeleton() {
  return (
    <div className="mb-6 space-y-3 lg:mb-8">
      <Skeleton className="h-9 w-[min(28rem,80%)]" />
      <Skeleton className="h-4 w-[min(40rem,95%)]" />
      <Skeleton className="h-4 w-[min(30rem,70%)]" />
    </div>
  );
}

/** The row of key numbers at the top of a screen. */
export function KpiRowSkeleton({ count = 4, height = "h-[93px]", className }: { count?: number; height?: string; className?: string }) {
  return (
    <div className={cn("grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4", className)}>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={cn("panel flex flex-col justify-end gap-2 px-5 py-4", height)}>
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3.5 w-3/4" />
        </div>
      ))}
    </div>
  );
}

/** A panel with a title and a few lines (a card, a section of settings…). */
export function PanelSkeleton({ lines = 3, height, className }: { lines?: number; height?: string; className?: string }) {
  return (
    <div className={cn("panel space-y-3 px-5 py-5", height, className)}>
      <Skeleton className="h-6 w-48" />
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-4", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/** A chart: its title, then the plot area at the height it will take. */
export function ChartSkeleton({ height = "h-[449px]", className }: { height?: string; className?: string }) {
  return (
    <div className={cn("panel flex flex-col gap-4 px-5 py-5", height, className)}>
      <Skeleton className="h-6 w-56" />
      <Skeleton className="min-h-0 flex-1 rounded-2xl" />
    </div>
  );
}

/** A list of rows (requests, passages, machines). */
export function ListSkeleton({ rows = 5, rowHeight = "h-[76px]", className }: { rows?: number; rowHeight?: string; className?: string }) {
  return (
    <ul className={cn("space-y-2", className)} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className={cn("panel flex items-center gap-4 px-4", rowHeight)}>
          <Skeleton className="h-10 w-10 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3.5 w-3/4" />
          </div>
          <Skeleton className="h-6 w-20 shrink-0 rounded-chip" />
        </li>
      ))}
    </ul>
  );
}

/** A table: a header line and rows at the height of the real ones. */
export function TableSkeleton({ rows = 6, rowHeight = "h-[87px]" }: { rows?: number; rowHeight?: string }) {
  return (
    <div className="panel overflow-hidden" aria-hidden>
      <div className="flex gap-6 border-b border-line px-5 py-3">
        {["w-24", "w-16", "w-20", "w-14", "w-[4.5rem]"].map((w) => (
          <Skeleton key={w} className={cn("h-3.5", w)} />
        ))}
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={cn("flex items-center gap-6 border-b border-line px-5 last:border-0", rowHeight)}>
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="hidden h-4 w-32 sm:block" />
          <Skeleton className="ml-auto h-6 w-20 rounded-chip" />
        </div>
      ))}
    </div>
  );
}

/** Units of the bed board: a title, then rooms as tiles. */
export function BedGridSkeleton({ units = 2 }: { units?: number }) {
  return (
    <div className="space-y-6" aria-hidden>
      {Array.from({ length: units }, (_, u) => (
        <section key={u} className="panel h-[415px] overflow-hidden px-5 py-5">
          <Skeleton className="h-6 w-56" />
          <div className="mt-5 grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
            {Array.from({ length: 16 }, (_, i) => (
              <Skeleton key={i} className="h-[72px] rounded-2xl" />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** The fourteen forecast lamps (Vue groupe, Lits et sorties, a request's detail). */
export function LampStripSkeleton() {
  return (
    <div className="flex gap-1.5" aria-hidden>
      {Array.from({ length: 14 }, (_, i) => (
        <Skeleton key={i} className="h-[51px] w-7 rounded-lg" />
      ))}
    </div>
  );
}

/** While a screen's own file downloads: the shape every screen shares. */
export function PageSkeleton() {
  return (
    <Loading label="Chargement de l'écran">
      <HeaderSkeleton />
      <KpiRowSkeleton />
      <PanelSkeleton lines={4} className="mt-6" />
    </Loading>
  );
}
