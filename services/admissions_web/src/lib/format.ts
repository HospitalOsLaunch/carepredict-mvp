const DAY = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
const DATETIME = new Intl.DateTimeFormat("fr-FR", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit"
});
const SHORT = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });

/** "2026-10-25" is a calendar day: parse it at local noon to avoid timezone drift. */
export function parseDay(iso: string): Date {
  return new Date(`${iso}T12:00:00`);
}

export function isoDay(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export const fmtDay = (iso: string | null | undefined) => (iso ? DAY.format(parseDay(iso)) : "—");
export const fmtDate = (iso: string | null | undefined) => (iso ? DATE.format(parseDay(iso)) : "—");
export const fmtShort = (iso: string | null | undefined) => (iso ? SHORT.format(parseDay(iso)) : "—");
export const fmtDateTime = (iso: string | null | undefined) => (iso ? DATETIME.format(new Date(iso)) : "—");

export function fmtHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "—";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} j`;
}

export function fmtPct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits).replace(".", ",")} %`;
}

export function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtEur(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

export function relativeDay(iso: string, today: string): string {
  const diff = Math.round((parseDay(iso).getTime() - parseDay(today).getTime()) / 86_400_000);
  if (diff === 0) return "aujourd'hui";
  if (diff === 1) return "demain";
  if (diff === -1) return "hier";
  if (diff > 1) return `dans ${diff} j`;
  return `il y a ${-diff} j`;
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${Math.abs(n) >= 2 ? many : one}`;
}
