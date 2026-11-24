// Demonstration clock. Bundled planner outputs were computed at a fixed instant (a morning in
// October for the unit, an evening in November for the 24-hour plan). Shown as is, they make
// the cockpit read as an archive and the journal mix two calendars. On load, every instant of
// a demonstration bundle is moved by one offset so that it happens today, now: relative
// durations, orderings and every figure stay exactly what the engine computed.
//
// Never applied to an API (live or local engine): real data keeps its real time.
// `?horloge=fixe` keeps the recorded instants (reproducible captures); tests keep them too.

const ISO = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(:\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;
/** Engine messages quote local times as « 2026-11-17 14:00 CET ». */
const QUOTED = /(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}) (CET|CEST)/g;
const MINUTE = 60_000;

export function demoClockOn(): boolean {
  if (import.meta.env.MODE === "test") return false;
  try {
    return new URLSearchParams(window.location.search).get("horloge") !== "fixe";
  } catch {
    return true;
  }
}

/** Offset that brings `anchor` to `now`, floored to a whole step (minutes). */
export function offsetTo(anchor: string, now: number, stepMinutes: number): number {
  const step = stepMinutes * MINUTE;
  return Math.floor(now / step) * step - Date.parse(anchor);
}

function shiftIso(value: string, offset: number): string {
  const m = ISO.exec(value);
  if (!m) return value;
  let out = new Date(Date.parse(value) + offset).toISOString(); // …T…:SS.sssZ
  if (!m[3]?.includes(".")) out = out.replace(/\.\d{3}Z$/, "Z");
  if (!m[3]) out = out.replace(/:\d{2}Z$/, "Z");
  return m[4] === "Z" ? out : out.replace(/Z$/, "+00:00");
}

const parisParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Paris",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZoneName: "shortOffset",
});

function paris(ms: number): { day: string; hm: string; zone: string } {
  const p = Object.fromEntries(parisParts.formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, hm: `${p.hour}:${p.minute}`, zone: p.timeZoneName === "GMT+2" ? "CEST" : "CET" };
}

function shiftQuoted(text: string, offset: number): string {
  return text.replace(QUOTED, (_, day: string, h: string, min: string, zone: string) => {
    const utc = Date.parse(`${day}T${h}:${min}:00${zone === "CEST" ? "+02:00" : "+01:00"}`);
    const p = paris(utc + offset);
    return `${p.day} ${p.hm} ${p.zone}`;
  });
}

/** A deep copy of `value` with every instant moved by `offset` milliseconds. */
export function rebase<T>(value: T, offset: number): T {
  if (!offset) return value;
  const walk = (v: unknown): unknown => {
    if (typeof v === "string") return ISO.test(v) ? shiftIso(v, offset) : shiftQuoted(v, offset);
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") {
      return Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, walk(x)]));
    }
    return v;
  };
  return walk(value) as T;
}

/** « 10:00 » in a label, moved by a whole number of hours (the plan bundle moves by hours). */
export function shiftClockText(text: string, offset: number): string {
  const hours = Math.round(offset / 3_600_000);
  if (!hours || offset % 3_600_000) return text;
  return text.replace(/\b(\d{1,2}):(\d{2})\b/g, (_, h: string, m: string) => {
    const next = (((Number(h) + hours) % 24) + 24) % 24;
    return `${String(next).padStart(2, "0")}:${m}`;
  });
}

/** « Matinée ordinaire » at 16:00 reads « Après-midi ordinaire ». */
export function momentLabel(label: string, at: string): string {
  const hour = Number(paris(Date.parse(at)).hm.slice(0, 2));
  const word =
    hour >= 5 && hour < 12 ? "Matinée" : hour < 18 && hour >= 12 ? "Après-midi" : hour >= 18 && hour < 22 ? "Soirée" : "Nuit";
  return label.replace(/^Matinée\b/, word);
}

/** Local « HH:MM » of an instant, Paris time (trajectory labels). */
export function parisClock(iso: string): string {
  return paris(Date.parse(iso)).hm;
}
