import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Trash2, Users } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api/client";
import type { PoolWorkload, StaffPool, Workload, WorkloadBacktest, WorkloadDay } from "../api/types";
import { useAuth } from "../auth";
import { Empty, ErrorNote, Modal, PageHeader, Spinner } from "../components/ui";
import { fmtDay, fmtNum, fmtPct, fmtShort, parseDay } from "../lib/format";
import { label, useVocabulary } from "../lib/queries";

const WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
const DOW = new Intl.DateTimeFormat("fr-FR", { weekday: "narrow" });

const TENSION: Record<WorkloadDay["tension"], { cell: string; text: string }> = {
  normale: { cell: "bg-lagoon-soft text-lagoon-dark", text: "normale" },
  vigilance: { cell: "bg-sun text-ink", text: "vigilance" },
  tension: { cell: "bg-coral text-white", text: "tension" },
  inconnue: { cell: "bg-sky text-ink-faint", text: "effectif non renseigné" }
};

const poolKey = (p: { site_id: number; mention: string }) => `${p.site_id}:${p.mention}`;
const hours = (minutes: number | null | undefined) => (minutes == null ? null : minutes / 60);

export function useWorkload() {
  return useQuery({ queryKey: ["workload"], queryFn: () => api<Workload>("/forecast/workload") });
}

export function ChargePage() {
  const vocab = useVocabulary();
  const workload = useWorkload();
  const [selected, setSelected] = useState<string | null>(null);
  const w = workload.data;

  const firstTense = useMemo(() => {
    if (!w) return null;
    const ranked = [...w.pools].sort((a, b) => worst(b.days.slice(0, 7)) - worst(a.days.slice(0, 7)));
    return ranked[0] ? poolKey(ranked[0]) : null;
  }, [w]);

  useEffect(() => {
    if (selected === null && firstTense) setSelected(firstTense);
  }, [firstTense, selected]);

  const pool = w?.pools.find((p) => poolKey(p) === selected) ?? null;
  const week = w?.pools.flatMap((p) => p.days.slice(0, 7).map((d) => d.tension)) ?? [];
  const tenseDays = week.filter((t) => t === "tension").length;
  const watchDays = week.filter((t) => t === "vigilance").length;
  const unstaffed = w?.pools.filter((p) => !p.staffing_configured) ?? [];

  return (
    <>
      <PageHeader
        title="Charge en soins"
        lead="Les minutes de soins attendues sur quatorze jours, unité par unité, face aux heures soignantes prévues. Les journées en tension apparaissent avant d'arriver, quand il est encore temps de renforcer ou de lisser les entrées."
      />
      {workload.isLoading && <Spinner />}
      {workload.error && <ErrorNote error={workload.error} />}
      {w && w.pools.length === 0 && (
        <Empty title="Aucune unité">Déclarez les sites et leurs lits dans les paramètres.</Empty>
      )}
      {w && w.pools.length > 0 && (
        <div className="space-y-8">
          <section aria-label="Sept prochains jours" className="grid gap-4 sm:grid-cols-3">
            <Stat
              value={tenseDays}
              tone={tenseDays ? "coral" : "lagoon"}
              text="journées-unités en tension sur 7 jours"
            />
            <Stat
              value={watchDays}
              tone={watchDays ? "sun" : "lagoon"}
              text="en vigilance (90 à 100 % de l'effectif)"
            />
            <Stat
              value={unstaffed.length}
              tone={unstaffed.length ? "ink" : "lagoon"}
              text={
                unstaffed.length
                  ? "unités sans effectif renseigné : charge sans comparaison"
                  : "unités toutes renseignées"
              }
            />
          </section>

          <TensionGrid workload={w} selected={selected} onSelect={setSelected} mentions={vocab.data?.mentions} />

          {pool && <PoolDetail key={poolKey(pool)} pool={pool} mention={label(vocab.data?.mentions, pool.mention)} />}

          <Basis workload={w} />
          <BacktestPanel />
        </div>
      )}
    </>
  );
}

function worst(days: WorkloadDay[]): number {
  return Math.max(0, ...days.map((d) => d.load_ratio ?? 0));
}

function Stat({ value, text, tone }: { value: number; text: string; tone: "coral" | "sun" | "lagoon" | "ink" }) {
  const color = { coral: "text-coral-dark", sun: "text-ink", lagoon: "text-lagoon-dark", ink: "text-ink" }[tone];
  const ring = tone === "sun" ? "ring-2 ring-sun" : tone === "coral" ? "ring-2 ring-coral" : "";
  return (
    <div className={`panel px-5 py-4 ${ring}`}>
      <p className={`num text-[40px] font-bold leading-none ${color}`}>{value}</p>
      <p className="mt-2 text-[15px] text-ink-soft">{text}</p>
    </div>
  );
}

function TensionGrid({
  workload: w,
  selected,
  onSelect,
  mentions
}: {
  workload: Workload;
  selected: string | null;
  onSelect: (key: string) => void;
  mentions: Record<string, string> | undefined;
}) {
  const days = w.pools[0]?.days.map((d) => d.day) ?? [];
  return (
    <section aria-labelledby="grid-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="grid-title">Charge rapportée à l'effectif, jour par jour</h2>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-soft">
          {(["normale", "vigilance", "tension", "inconnue"] as const).map((t) => (
            <li key={t} className="flex items-center gap-1.5">
              <span className={`h-3.5 w-3.5 rounded ${TENSION[t].cell}`} aria-hidden />
              {t === "normale"
                ? "< 90 %"
                : t === "vigilance"
                  ? "90 à 100 %"
                  : t === "tension"
                    ? "> 100 %"
                    : "effectif à saisir"}
            </li>
          ))}
        </ul>
      </div>
      <div className="panel relative mt-4 overflow-x-auto">
        <table className="w-full min-w-[860px] border-separate border-spacing-0 text-[14px]">
          <caption className="sr-only">
            Pour chaque unité et chaque jour, la charge en soins attendue en pourcentage des heures soignantes prévues.
            Choisissez une unité pour voir le détail.
          </caption>
          <thead>
            <tr className="text-[12px] text-ink-faint">
              <th className="sticky left-0 z-10 bg-paper px-4 py-2 text-left font-normal">Unité</th>
              {days.map((d) => (
                <th key={d} className="px-0.5 py-2 text-center font-normal">
                  <span className="block uppercase">{DOW.format(parseDay(d))}</span>
                  <span className="num block text-[13px] text-ink-soft">{parseDay(d).getDate()}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {w.pools.map((p) => {
              const key = poolKey(p);
              const active = key === selected;
              const name = `${p.site_name}, ${label(mentions, p.mention)}`;
              return (
                <tr key={key} className={active ? "bg-violet-soft/60" : ""}>
                  <th
                    scope="row"
                    className={`sticky left-0 z-10 px-4 py-1.5 text-left font-normal ${active ? "bg-violet-soft" : "bg-paper"}`}
                  >
                    <button
                      className="text-left hover:text-violet-dark"
                      onClick={() => onSelect(key)}
                      aria-pressed={active}
                    >
                      <span className="block font-bold leading-tight">{label(mentions, p.mention)}</span>
                      <span className="block text-[12px] text-ink-faint">{p.site_name}</span>
                    </button>
                  </th>
                  {p.days.map((d) => (
                    <td key={d.day} className="px-0.5 py-1.5">
                      <button
                        onClick={() => onSelect(key)}
                        className={`num grid h-9 w-full min-w-[42px] place-items-center rounded-lg text-[13px] font-bold transition-transform hover:scale-105 ${TENSION[d.tension].cell}`}
                        aria-label={`${name}, ${fmtDay(d.day)} : ${
                          d.load_ratio == null
                            ? `${fmtNum(hours(d.care_minutes_expected))} heures de soins attendues, effectif non renseigné`
                            : `charge à ${fmtPct(d.load_ratio)} de l'effectif, ${TENSION[d.tension].text}`
                        }`}
                      >
                        {d.load_ratio == null
                          ? fmtNum(hours(d.care_minutes_expected)) + "h"
                          : Math.round(d.load_ratio * 100)}
                      </button>
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[13px] text-ink-faint">
        Chiffre = charge attendue en % des heures soignantes prévues. Sans effectif saisi, la case donne les heures de
        soins attendues.
      </p>
    </section>
  );
}

function PoolDetail({ pool, mention }: { pool: PoolWorkload; mention: string }) {
  const { canWrite } = useAuth();
  const [editing, setEditing] = useState(false);
  const data = pool.days.map((d) => ({
    label: fmtShort(d.day),
    band: [round1(hours(d.care_minutes_p10)), round1(hours(d.care_minutes_p90))],
    expected: round1(hours(d.care_minutes_expected)),
    staff: d.staff_minutes == null ? null : round1(hours(d.staff_minutes))
  }));
  const tense = pool.days.filter((d) => d.tension === "tension");
  return (
    <section className="panel px-6 py-5" aria-labelledby="pool-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="pool-title">
            {mention}, {pool.site_name}
          </h2>
          <p className="mt-1 text-ink-soft">
            {pool.occupied_now} patients présents pour {pool.beds_open} lits ouverts.{" "}
            {tense.length
              ? tense.length === 1
                ? `Tension attendue le ${fmtDay(tense[0].day)}.`
                : `${tense.length} jours en tension sur ${pool.days.length}, le premier ${fmtDay(tense[0].day)}.`
              : pool.staffing_configured
                ? "Pas de tension attendue sur la période."
                : "Saisissez l'effectif pour comparer."}
          </p>
        </div>
        {canWrite && (
          <button className="btn-quiet" onClick={() => setEditing(true)}>
            <Users className="h-4 w-4" aria-hidden /> Effectif soignant
          </button>
        )}
      </div>

      <div
        className="mt-5 h-64"
        role="img"
        aria-label={`Heures de soins attendues et heures soignantes prévues, ${mention}`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid stroke="#D9E0F5" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#7D7BA3" }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 12, fill: "#7D7BA3" }} unit=" h" width={52} />
            <Tooltip
              formatter={(value, name) => {
                const v = Array.isArray(value) ? `${value[0]} à ${value[1]} h` : `${value} h`;
                return [v, name];
              }}
            />
            <Area dataKey="band" name="Fourchette à 80 %" fill="#ECE8FF" stroke="none" isAnimationActive={false} />
            <Line
              dataKey="expected"
              name="Soins attendus"
              stroke="#5B3DF5"
              strokeWidth={3}
              dot={{ r: 3 }}
              isAnimationActive={false}
            />
            <Line
              dataKey="staff"
              name="Heures soignantes"
              type="stepAfter"
              stroke="#1C1946"
              strokeDasharray="6 4"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-ink-soft">
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-5 rounded bg-violet" aria-hidden /> soins attendus
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-5 rounded bg-violet-soft" aria-hidden /> fourchette à 80 %
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-5 border-t-2 border-dashed border-ink" aria-hidden /> heures soignantes prévues
        </span>
      </p>

      <div className="relative mt-5 overflow-x-auto">
        <table className="w-full min-w-[720px] text-[14px]">
          <caption className="sr-only">Détail par jour</caption>
          <thead>
            <tr className="border-b border-line text-left text-[12px] text-ink-faint">
              <th className="py-2 pr-3 font-normal">Jour</th>
              <th className="px-2 py-2 text-right font-normal">Présents attendus</th>
              <th className="px-2 py-2 text-right font-normal">Entrées promises</th>
              <th className="px-2 py-2 text-right font-normal">Entrées probables</th>
              <th className="px-2 py-2 text-right font-normal">Soins (h)</th>
              <th className="px-2 py-2 text-right font-normal">Effectif (h)</th>
              <th className="px-2 py-2 text-right font-normal">Risque de dépassement</th>
            </tr>
          </thead>
          <tbody>
            {pool.days.map((d) => (
              <tr key={d.day} className="border-b border-line last:border-0">
                <td className="py-2 pr-3">
                  <span
                    className={`mr-2 inline-block h-2.5 w-2.5 rounded-full ${TENSION[d.tension].cell}`}
                    aria-hidden
                  />
                  {fmtDay(d.day)}
                </td>
                <td className="num px-2 py-2 text-right">{fmtNum(d.census_expected, 1)}</td>
                <td className="num px-2 py-2 text-right">{d.known_admissions || "—"}</td>
                <td className="num px-2 py-2 text-right">{fmtNum(d.expected_new_admissions, 1)}</td>
                <td className="num px-2 py-2 text-right font-bold">
                  {fmtNum(hours(d.care_minutes_expected))}
                  <span className="font-normal text-ink-faint">
                    {" "}
                    ({fmtNum(hours(d.care_minutes_p10))}–{fmtNum(hours(d.care_minutes_p90))})
                  </span>
                </td>
                <td className="num px-2 py-2 text-right">{fmtNum(hours(d.staff_minutes))}</td>
                <td
                  className={`num px-2 py-2 text-right ${d.tension === "tension" ? "font-bold text-coral-dark" : ""}`}
                >
                  {fmtPct(d.prob_over_capacity)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <StaffModal pool={pool} mention={mention} onClose={() => setEditing(false)} />}
    </section>
  );
}

function round1(v: number | null): number | null {
  return v == null ? null : Math.round(v * 10) / 10;
}

function StaffModal({ pool, mention, onClose }: { pool: PoolWorkload; mention: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const staffing = useQuery({
    queryKey: ["staffing", pool.site_id],
    queryFn: () => api<StaffPool[]>(`/staffing?site_id=${pool.site_id}`)
  });
  const current = staffing.data?.find((s) => s.mention === pool.mention);
  const [weekly, setWeekly] = useState<string[]>(Array(7).fill(""));
  const [day, setDay] = useState("");
  const [dayHours, setDayHours] = useState("");
  const [comment, setComment] = useState("");

  useEffect(() => {
    if (current) setWeekly(current.weekly_hours.map((h) => (h == null ? "" : String(h))));
  }, [current]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["staffing"] });
    void queryClient.invalidateQueries({ queryKey: ["workload"] });
  };
  const path = `/staffing/${pool.site_id}/${pool.mention}`;
  const saveWeekly = useMutation({
    mutationFn: () =>
      api<StaffPool[]>(`${path}/weekly`, {
        method: "PUT",
        json: { hours: weekly.map((h) => (h.trim() === "" ? null : Number(h))), comment: comment.trim() || null }
      }),
    onSuccess: refresh
  });
  const saveDay = useMutation({
    mutationFn: (body: { day: string; care_hours: number | null }) =>
      api<StaffPool[]>(`${path}/days/${body.day}`, {
        method: "PUT",
        json: { care_hours: body.care_hours, comment: comment.trim() || null }
      }),
    onSuccess: () => {
      refresh();
      setDay("");
      setDayHours("");
    }
  });

  return (
    <Modal title={`Effectif soignant, ${mention}`} onClose={onClose} wide>
      <p className="text-ink-soft">
        Heures de soins disponibles par jour (IDE et aides-soignants, hors encadrement). Ce sont elles que la charge
        attendue vient remplir.
      </p>
      {staffing.isLoading && <Spinner />}
      {staffing.error && <ErrorNote error={staffing.error} />}
      <form
        className="mt-5"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          saveWeekly.mutate();
        }}
      >
        <h3>Semaine type</h3>
        <div className="mt-3 grid grid-cols-4 gap-3 sm:grid-cols-7">
          {WEEKDAYS.map((name, i) => (
            <div key={name}>
              <label className="field" htmlFor={`wk-${i}`}>
                {name.slice(0, 3)}.
              </label>
              <input
                id={`wk-${i}`}
                type="number"
                min={0}
                max={2000}
                step="0.5"
                inputMode="decimal"
                className="input num"
                value={weekly[i]}
                onChange={(e) => setWeekly(weekly.map((v, j) => (j === i ? e.target.value : v)))}
                aria-label={`${name}, heures soignantes`}
              />
            </div>
          ))}
        </div>
        <label className="field mt-4" htmlFor="st-comment">
          Commentaire (facultatif, tracé dans le journal)
        </label>
        <input
          id="st-comment"
          className="input"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          maxLength={300}
        />
        {saveWeekly.error && (
          <div className="mt-3">
            <ErrorNote error={saveWeekly.error} />
          </div>
        )}
        <div className="mt-4 flex items-center gap-3">
          <button type="submit" className="btn-primary" disabled={saveWeekly.isPending}>
            Enregistrer la semaine type
          </button>
          {saveWeekly.isSuccess && (
            <span className="text-[14px] text-lagoon-dark" role="status">
              Enregistrée.
            </span>
          )}
        </div>
      </form>

      <div className="mt-8 border-t border-line pt-5">
        <h3 className="flex items-center gap-2">
          <CalendarClock className="h-5 w-5 text-violet" aria-hidden /> Jours particuliers
        </h3>
        <p className="mt-1 text-[14px] text-ink-soft">
          Absences, intérim, renfort : la valeur du jour remplace la semaine type pour cette date.
        </p>
        {current && Object.keys(current.overrides).length > 0 ? (
          <ul className="mt-3 divide-y divide-line">
            {Object.entries(current.overrides).map(([d, h]) => (
              <li key={d} className="flex items-center justify-between py-2">
                <span>
                  {fmtDay(d)} : <span className="num font-bold">{fmtNum(h, 1)} h</span>
                  <span className="text-ink-faint">
                    {" "}
                    au lieu de {fmtNum(current.weekly_hours[(parseDay(d).getDay() + 6) % 7], 1)} h
                  </span>
                </span>
                <button
                  className="btn-ghost h-9 w-9 p-0"
                  onClick={() => saveDay.mutate({ day: d, care_hours: null })}
                  aria-label={`Retirer l'exception du ${fmtDay(d)}`}
                  disabled={saveDay.isPending}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-[14px] text-ink-faint">Aucune exception à venir.</p>
        )}
        <form
          className="mt-3 grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            saveDay.mutate({ day, care_hours: Number(dayHours) });
          }}
        >
          <div>
            <label className="field" htmlFor="ov-day">
              Date
            </label>
            <input
              id="ov-day"
              type="date"
              required
              className="input"
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
          </div>
          <div>
            <label className="field" htmlFor="ov-hours">
              Heures soignantes ce jour-là
            </label>
            <input
              id="ov-hours"
              type="number"
              min={0}
              max={2000}
              step="0.5"
              required
              className="input num"
              value={dayHours}
              onChange={(e) => setDayHours(e.target.value)}
            />
          </div>
          <button type="submit" className="btn-quiet" disabled={!day || dayHours === "" || saveDay.isPending}>
            Ajouter l'exception
          </button>
        </form>
        {saveDay.error && (
          <div className="mt-3">
            <ErrorNote error={saveDay.error} />
          </div>
        )}
      </div>
    </Modal>
  );
}

function Basis({ workload: w }: { workload: Workload }) {
  const m = w.care_minutes;
  return (
    <section className="panel px-6 py-5" aria-labelledby="basis">
      <h2 id="basis">Comment la charge est calculée</h2>
      <p className="mt-2 text-ink-soft">
        Pour chaque jour : la probabilité que chaque patient soit encore là, multipliée par les minutes de son niveau de
        soins, plus le surcroît des sorties et des entrées, plus les entrées promises, plus les entrées habituelles de
        ce jour de la semaine dans la limite des lits libres.
      </p>
      <dl className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-6">
        {(["1", "2", "3", "4", "entree", "sortie"] as const).map((k) => (
          <div key={k} className="rounded-xl bg-sky px-3 py-2">
            <dt className="text-[12px] text-ink-faint">
              {k === "entree" ? "Entrée" : k === "sortie" ? "Sortie" : `Niveau ${k}`}
            </dt>
            <dd className="num text-[18px] font-bold">{m[k] ?? "—"} min</dd>
          </div>
        ))}
      </dl>
      <ul className="mt-4 list-disc space-y-1 pl-5 text-[14px] text-ink-soft">
        <li>
          {w.care_level_known_share == null
            ? "Aucun patient présent."
            : `${fmtPct(w.care_level_known_share)} des patients présents ont un niveau de soins coté ; les autres comptent au niveau 2 en attendant d'être cotés (page Lits et sorties).`}
        </li>
        <li>
          {w.plan_slip_is_prior
            ? `L'écart entre date de sortie prévue et sortie réelle suit une hypothèse prudente : seulement ${w.plan_slip_samples} sorties avec une date prévue historisée, il en faut 30 pour le mesurer.`
            : `L'écart entre date prévue et sortie réelle est mesuré sur ${w.plan_slip_samples} sorties du groupe.`}
        </li>
        <li>
          Les minutes par niveau sont des hypothèses de départ, à caler avec l'outil de charge de vos unités
          (paramètres, onglet « Charge en soins »).
        </li>
      </ul>
    </section>
  );
}

function BacktestPanel() {
  const [open, setOpen] = useState(false);
  const backtest = useQuery({
    queryKey: ["workload-backtest"],
    queryFn: () => api<WorkloadBacktest>("/metrics/backtest/workload"),
    enabled: open
  });
  const b = backtest.data;
  const byHorizon = (k: number) =>
    b?.points.filter((p) => p.k === k).map((p) => ({ ...p, label: fmtShort(p.as_of) })) ?? [];
  return (
    <details className="panel px-6 py-5" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer font-display text-[19px] font-semibold">
        Fiabilité : la prévision rejouée sur les semaines passées
      </summary>
      {backtest.isLoading && (
        <div className="mt-4">
          <Spinner label="Rejeu en cours" />
        </div>
      )}
      {backtest.error && <ErrorNote error={backtest.error} />}
      {b && (
        <>
          <dl className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl bg-sky px-4 py-3">
              <dt className="text-[13px] text-ink-faint">Erreur moyenne par unité et par jour</dt>
              <dd className="num text-[26px] font-bold">{fmtPct(b.mape, 1)}</dd>
            </div>
            <div className="rounded-xl bg-sky px-4 py-3">
              <dt className="text-[13px] text-ink-faint">Biais (positif = surestime)</dt>
              <dd className="num text-[26px] font-bold">{fmtPct(b.bias_pct, 1)}</dd>
            </div>
            <div className="rounded-xl bg-sky px-4 py-3">
              <dt className="text-[13px] text-ink-faint">Réel dans la fourchette à 80 %</dt>
              <dd className="num text-[26px] font-bold">{fmtPct(b.coverage_80)}</dd>
            </div>
          </dl>
          <div className="mt-5 h-56" role="img" aria-label="Heures de soins prévues à J+3 et réalisées, groupe entier">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={byHorizon(3)}>
                <CartesianGrid stroke="#D9E0F5" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#7D7BA3" }} />
                <YAxis tick={{ fontSize: 12, fill: "#7D7BA3" }} unit=" h" width={60} domain={["auto", "auto"]} />
                <Tooltip formatter={(v, n) => [`${v} h`, n]} />
                <Line
                  dataKey="predicted_hours"
                  name="Prévu à J+3"
                  stroke="#5B3DF5"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  dataKey="actual_hours"
                  name="Réalisé"
                  stroke="#1C1946"
                  strokeWidth={0}
                  dot={{ r: 4, fill: "#1C1946" }}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-[13px] text-ink-faint">{b.note}</p>
        </>
      )}
    </details>
  );
}
