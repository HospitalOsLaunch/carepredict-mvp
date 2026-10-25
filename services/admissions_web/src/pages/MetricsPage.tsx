import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import { api } from "../api/client";
import type { Backtest, NorthStar, PilotMetrics } from "../api/types";
import { ErrorNote, Meter, PageHeader, Spinner } from "../components/ui";
import { fmtDate, fmtEur, fmtHours, fmtNum, fmtPct, fmtShort, isoDay } from "../lib/format";
import { label, useSites, useVocabulary } from "../lib/queries";

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDay(d);
}

const PRESETS = [
  { label: "4 semaines", start: 28 },
  { label: "12 semaines", start: 84 },
  { label: "6 mois", start: 182 }
];

export function MetricsPage() {
  const sites = useSites();
  const vocab = useVocabulary();
  const [start, setStart] = useState(daysAgo(28));
  const [end, setEnd] = useState(daysAgo(1));
  const [siteId, setSiteId] = useState("");

  const params = new URLSearchParams({ start, end });
  if (siteId) params.set("site_id", siteId);
  const metrics = useQuery({
    queryKey: ["metrics", start, end, siteId],
    queryFn: () => api<PilotMetrics>(`/metrics/pilot?${params.toString()}`)
  });
  const backtest = useQuery({
    queryKey: ["backtest", siteId],
    queryFn: () => api<Backtest>(`/metrics/backtest${siteId ? `?site_id=${siteId}` : ""}`)
  });
  const m = metrics.data;

  return (
    <>
      <PageHeader
        title="Indicateurs pilote"
        lead="Ce que le pilote change, mesuré contre une période de référence fixée à l'avance. Un résultat dont l'intervalle contient zéro n'est pas un effet démontré."
      />
      <form className="mb-8 flex flex-wrap items-end gap-3" onSubmit={(e) => e.preventDefault()}>
        <div>
          <label className="field" htmlFor="m-start">
            Du
          </label>
          <input id="m-start" type="date" className="input" value={start} max={end} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div>
          <label className="field" htmlFor="m-end">
            Au
          </label>
          <input id="m-end" type="date" className="input" value={end} min={start} max={daysAgo(1)} onChange={(e) => setEnd(e.target.value)} />
        </div>
        <div>
          <label className="field" htmlFor="m-site">
            Périmètre
          </label>
          <select id="m-site" className="input" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            <option value="">Tout le groupe</option>
            {sites.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-1">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              className="btn-quiet"
              onClick={() => {
                setStart(daysAgo(p.start));
                setEnd(daysAgo(1));
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </form>

      {metrics.isLoading && <Spinner />}
      {metrics.error && <ErrorNote error={metrics.error} />}
      {m && (
        <div className="space-y-10">
          <NorthStarSection metrics={m} />

          <section aria-labelledby="speed">
            <h2 id="speed">
              {m.requests.response_hours_median === null
                ? "Pas encore de réponse sur la période"
                : `La moitié des demandes reçoivent une réponse en moins de ${fmtHours(m.requests.response_hours_median)}`}
            </h2>
            <p className="mt-1 text-ink-soft">
              Un SMR qui répond le premier a plus de chances d'accueillir le patient. {fmtPct(m.requests.responded_within_24h)}{" "}
              des réponses en moins de 24 h ; neuf sur dix en moins de {fmtHours(m.requests.response_hours_p90)}.
            </p>
            <div className="panel mt-4 h-64 px-2 py-4">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={m.weekly.map((w) => ({ ...w, label: fmtShort(w.week_start) }))}>
                  <CartesianGrid stroke="#D9E0F5" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#7D7BA3" }} />
                  <YAxis tick={{ fontSize: 12, fill: "#7D7BA3" }} unit=" h" width={48} />
                  <Tooltip formatter={(v) => [`${v} h`, "Délai médian"]} />
                  <Line type="monotone" dataKey="response_hours_median" stroke="#5B3DF5" strokeWidth={3} dot={{ r: 3 }} connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section aria-labelledby="funnel">
            <h2 id="funnel">
              {m.requests.received} demandes reçues, {m.requests.by_status.admise ?? 0} patients admis
            </h2>
            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <div className="panel px-5 py-4">
                <h3>Parcours des demandes</h3>
                <Funnel
                  rows={[
                    ["Accords donnés", m.requests.accord_rate],
                    ["Admissions", m.requests.conversion_rate],
                    ["Perdues après accord", m.requests.lost_after_accord_rate]
                  ]}
                />
              </div>
              <Reasons
                title="Motifs de refus"
                counts={m.requests.refusal_reasons}
                labels={vocab.data?.refusal_reasons}
              />
              <Reasons title="Motifs de perte" counts={m.requests.loss_reasons} labels={vocab.data?.loss_reasons} />
            </div>
          </section>

          <section aria-labelledby="occupancy">
            <h2 id="occupancy">
              Occupation de {fmtPct(m.occupancy.rate_on_open, 1)} des lits ouverts, {fmtPct(m.occupancy.rate_on_installed, 1)} des
              lits installés
            </h2>
            <ClosedReasons metrics={m} labels={vocab.data?.capacity_reasons} />
          </section>

          <BacktestSection backtest={backtest.data} loading={backtest.isLoading} error={backtest.error} />
        </div>
      )}
    </>
  );
}

function NorthStarSection({ metrics: m }: { metrics: PilotMetrics }) {
  const ns = m.north_star;
  const baseline = m.baseline;
  const baselineText = baseline.start
    ? `Référence du ${fmtDate(baseline.start)} au ${fmtDate(baseline.end)}, ${baseline.frozen_at ? `gelée le ${fmtDate(baseline.frozen_at.slice(0, 10))}` : "non gelée"}.`
    : "Aucune période de référence définie.";
  return (
    <section aria-labelledby="ns" className="panel overflow-hidden">
      <div className="bg-ink px-6 py-6 text-white">
        <p className="text-[15px] text-white/70">Journées-lits récupérées par rapport à la référence</p>
        {ns ? (
          <h2 id="ns" className="mt-1 text-[34px] leading-tight">
            {verdict(ns)}
          </h2>
        ) : (
          <h2 id="ns" className="mt-1 text-[28px]">
            Pas encore mesurable
          </h2>
        )}
        <p className="mt-2 text-white/70">{baselineText}</p>
      </div>
      <div className="px-6 py-5">
        {ns ? (
          <>
            <IntervalLine ns={ns} />
            <dl className="mt-5 grid grid-cols-2 gap-4 text-[15px] md:grid-cols-4">
              <Stat term="Occupation de référence" value={fmtPct(ns.baseline_rate, 1)} />
              <Stat term="Occupation sur la période" value={fmtPct(ns.period_rate, 1)} />
              <Stat
                term="Valeur estimée"
                value={fmtEur(ns.value_eur)}
                sub={ns.value_low_eur !== null ? `entre ${fmtEur(ns.value_low_eur)} et ${fmtEur(ns.value_high_eur)}` : undefined}
              />
              <Stat
                term="Intéressement dû"
                value={fmtEur(ns.success_fee_eur)}
                sub={ns.success_fee_eur > 0 ? "intervalle entièrement positif" : "dû seulement si l'intervalle est positif"}
              />
            </dl>
            <p className="mt-4 text-[14px] text-ink-soft">{ns.interval_note}</p>
            {m.north_star_unavailable_reason && (
              <p className="mt-2 rounded-xl bg-sun-soft px-3 py-2 text-[14px]">{m.north_star_unavailable_reason}</p>
            )}
            <details className="mt-4 text-[14px]">
              <summary className="cursor-pointer font-bold">
                Unités comparées ({ns.included_pools.length}) et unités exclues ({Object.keys(ns.excluded_pools).length})
              </summary>
              <p className="mt-2 text-ink-soft">
                Une unité dont la capacité ouverte a changé entre la référence et la période est exclue : fermer des lits
                augmente mécaniquement le taux d'occupation, ce qui serait compté à tort comme un gain.
              </p>
              <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                {ns.included_pools.map((p) => (
                  <li key={p} className="text-ink">
                    Comparée : {p}
                  </li>
                ))}
                {Object.entries(ns.excluded_pools).map(([p, why]) => (
                  <li key={p} className="text-ink-faint">
                    Exclue : {p} ({why})
                  </li>
                ))}
              </ul>
            </details>
          </>
        ) : (
          <p className="text-ink-soft">{m.north_star_unavailable_reason}</p>
        )}
      </div>
    </section>
  );
}

function verdict(ns: NorthStar): string {
  const n = Math.round(ns.recovered_bed_days);
  const sign = n > 0 ? "+" : "";
  if (ns.recovered_low === null || ns.recovered_high === null) return `${sign}${fmtNum(n)} journées-lits, incertitude non estimée`;
  if (ns.recovered_low > 0) return `${sign}${fmtNum(n)} journées-lits récupérées`;
  if (ns.recovered_high < 0) return `${fmtNum(n)} journées-lits, sous la référence`;
  return `Aucun effet démontré (${sign}${fmtNum(n)} journées-lits)`;
}

/** Number line with zero, the 80 % interval and the estimate: the honest picture of the result. */
function IntervalLine({ ns }: { ns: NorthStar }) {
  const lo = ns.recovered_low;
  const hi = ns.recovered_high;
  const values = [0, ns.recovered_bed_days, lo ?? 0, hi ?? 0];
  const span = Math.max(...values.map(Math.abs)) * 1.15 || 1;
  const x = (v: number) => `${((v + span) / (2 * span)) * 100}%`;
  return (
    <figure>
      <div className="relative h-14" role="img" aria-label={`Estimation ${fmtNum(ns.recovered_bed_days)} journées-lits, intervalle à 80 % de ${fmtNum(lo)} à ${fmtNum(hi)}`}>
        <div className="absolute inset-x-0 top-7 h-px bg-line" />
        <div className="absolute top-3 h-8 w-px bg-ink-faint" style={{ left: x(0) }} />
        <span className="absolute top-11 -translate-x-1/2 text-[12px] text-ink-faint" style={{ left: x(0) }}>
          0
        </span>
        {lo !== null && hi !== null && (
          <div
            className={`absolute top-5 h-4 rounded-full ${lo > 0 ? "bg-sun" : "bg-violet-soft ring-1 ring-violet/40"}`}
            style={{ left: x(lo), width: `calc(${x(hi)} - ${x(lo)})` }}
          />
        )}
        <div className="absolute top-3.5 h-7 w-7 -translate-x-1/2 rounded-full border-4 border-paper bg-violet shadow" style={{ left: x(ns.recovered_bed_days) }} />
      </div>
      <figcaption className="mt-2 text-[13px] text-ink-faint">
        Point : estimation. Bande : intervalle à 80 %{lo === null ? " (non calculé)" : ` de ${fmtNum(lo)} à ${fmtNum(hi)} journées-lits`}.
      </figcaption>
    </figure>
  );
}

function Stat({ term, value, sub }: { term: string; value: string; sub?: string }) {
  return (
    <div>
      <dt className="text-[13px] text-ink-faint">{term}</dt>
      <dd className="num text-[22px] font-bold">{value}</dd>
      {sub && <dd className="text-[13px] text-ink-faint">{sub}</dd>}
    </div>
  );
}

function Funnel({ rows }: { rows: Array<[string, number | null]> }) {
  return (
    <dl className="mt-3 space-y-3">
      {rows.map(([name, value]) => (
        <div key={name}>
          <div className="flex justify-between text-[15px]">
            <dt>{name}</dt>
            <dd className="num font-bold">{fmtPct(value)}</dd>
          </div>
          <Meter value={(value ?? 0) * 100} tone={name.startsWith("Perdues") ? "coral" : "lagoon"} />
        </div>
      ))}
    </dl>
  );
}

function Reasons({ title, counts, labels }: { title: string; counts: Record<string, number>; labels?: Record<string, string> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return (
    <div className="panel px-5 py-4">
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p className="mt-3 text-ink-soft">Aucun sur la période.</p>
      ) : (
        <dl className="mt-3 space-y-2.5">
          {rows.map(([code, n]) => (
            <div key={code}>
              <div className="flex justify-between gap-3 text-[14px]">
                <dt>{label(labels, code)}</dt>
                <dd className="num font-bold">{n}</dd>
              </div>
              <Meter value={(n / total) * 100} tone="violet" />
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function ClosedReasons({ metrics: m, labels }: { metrics: PilotMetrics; labels?: Record<string, string> }) {
  const reasons = Object.entries(m.occupancy.closed_bed_days_by_reason).sort((a, b) => b[1] - a[1]);
  const total = reasons.reduce((a, [, n]) => a + n, 0);
  const staffing = m.occupancy.closed_bed_days_by_reason.personnel ?? 0;
  return (
    <div className="mt-3 max-w-3xl">
      <p className="text-ink-soft">
        En moyenne {fmtNum(m.occupancy.avg_closed_beds, 1)} lits fermés par jour sur la période.
        {total > 0 &&
          ` Le manque de personnel représente ${fmtPct(staffing / total)} des journées de lits fermés : si c'est la contrainte principale, trier les demandes ne remplira pas ces lits.`}
      </p>
      {reasons.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {reasons.map(([code, n]) => (
            <li key={code} className="chip bg-paper text-ink">
              {label(labels, code)} : <span className="num">{fmtNum(n)}</span> journées
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BacktestSection({ backtest: b, loading, error }: { backtest?: Backtest; loading: boolean; error: unknown }) {
  return (
    <section aria-labelledby="bt">
      <h2 id="bt">Fiabilité de la prévision des sorties</h2>
      {loading && <Spinner />}
      {error !== null && error !== undefined && <ErrorNote error={error} />}
      {b && (
        <>
          <p className="mt-1 max-w-3xl text-ink-soft">
            La prévision à 7 jours est rejouée chaque semaine passée avec les seules données connues à ce moment.
            {b.coverage_80 !== null &&
              ` Les sorties réelles sont tombées dans la fourchette annoncée ${fmtPct(b.coverage_80)} du temps (objectif : 80 %), avec un écart moyen de ${fmtNum(b.mae, 1)} sorties.`}
          </p>
          <div className="panel mt-4 h-64 px-2 py-4">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={b.points.map((p) => ({ ...p, band: [p.p10, p.p90], label: fmtShort(p.as_of) }))}>
                <CartesianGrid stroke="#D9E0F5" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#7D7BA3" }} />
                <YAxis tick={{ fontSize: 12, fill: "#7D7BA3" }} width={40} />
                <Tooltip />
                <Area dataKey="band" name="Fourchette à 80 %" fill="#FFF1CC" stroke="#FFB21E" />
                <Line dataKey="predicted" name="Prévu" stroke="#5B3DF5" strokeWidth={2} dot={false} />
                <Line dataKey="actual" name="Réel" stroke="#1C1946" strokeWidth={0} dot={{ r: 4, fill: "#1C1946" }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-[13px] text-ink-faint">{b.note}</p>
        </>
      )}
    </section>
  );
}
