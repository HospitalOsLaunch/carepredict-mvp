import { DeltaText } from "./DeltaText";
import { MiniBar } from "./MiniBar";
import { PressureBadge } from "./PressureBadge";
import { Sparkline } from "./Sparkline";
import type { SparklinePoint, StatusVariant } from "./types";

export type DataTableCell =
  | { type: "text"; value: string; muted?: string }
  | { type: "status"; status: StatusVariant; label?: string; score?: number }
  | { type: "miniBar"; value: number; label?: string }
  | { type: "sparkline"; data: SparklinePoint[]; variant?: StatusVariant }
  | { type: "delta"; value: number; unit?: string; inverted?: boolean }
  | { type: "action"; label: string };

export interface DataTableColumn {
  key: string;
  header: string;
  align?: "left" | "right";
}

export interface DataTableRow {
  id: string;
  cells: Record<string, DataTableCell>;
}

interface DataTableProps {
  columns: DataTableColumn[];
  rows: DataTableRow[];
  footerLink?: string;
}

export function DataTable({ columns, rows, footerLink }: DataTableProps) {
  return (
    <div className="overflow-hidden rounded-card border border-border-subtle bg-bg-card shadow-card">
      <table className="w-full border-collapse text-body-copy">
        <thead className="bg-bg-app">
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={`text-card-label px-4 py-3 ${column.align === "right" ? "text-right" : "text-left"}`}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-border-subtle transition hover:bg-bg-app/70">
              {columns.map((column) => (
                <td key={column.key} className={`px-4 py-3 ${column.align === "right" ? "text-right" : "text-left"}`}>
                  <CellRenderer cell={row.cells[column.key]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {footerLink ? (
        <a href="#view-all" className="block border-t border-border-subtle px-4 py-3 text-control text-brand-primary hover:bg-bg-app">
          {footerLink} →
        </a>
      ) : null}
    </div>
  );
}

function CellRenderer({ cell }: { cell?: DataTableCell }) {
  if (!cell) return <span className="text-text-muted">—</span>;
  if (cell.type === "text") {
    return (
      <span>
        <span className="text-body-strong block">{cell.value}</span>
        {cell.muted ? <span className="text-caption">{cell.muted}</span> : null}
      </span>
    );
  }
  if (cell.type === "status") return <PressureBadge status={cell.status} label={cell.label} score={cell.score} />;
  if (cell.type === "miniBar") return <MiniBar value={cell.value} label={cell.label} />;
  if (cell.type === "sparkline") {
    return (
      <div className="max-w-[150px] overflow-hidden rounded-lg px-3 py-1.5">
        <Sparkline data={cell.data} variant={cell.variant} height={28} />
      </div>
    );
  }
  if (cell.type === "delta") return <DeltaText value={cell.value} unit={cell.unit} inverted={cell.inverted} />;
  return <button className="text-control text-brand-primary hover:underline">{cell.label}</button>;
}
