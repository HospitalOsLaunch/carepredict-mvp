import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FlaskConical, RefreshCw, XCircle } from "lucide-react";
import { lazy, Suspense, useState } from "react";

import { api } from "../api/client";
import type { ForecastDay, ForecastScope, ForecastSeries, LiscopForecast } from "../api/types_liscop";
import { Empty, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { fmtDateTime, fmtDay, fmtHours, fmtNum, fmtPct, fmtShort } from "../lib/format";

// recharts stays out of the main bundle (as for the other chart pages).
const BoardingChart = lazy(() => import("./PrevisionChart").then((m) => ({ default: m.BoardingChart })));

const SCOPES: { value: ForecastScope; label: string; noun: string }[] = [
  { value: "unit", label: "Unité", noun: "Unité" },
  { value: "site", label: "Établissement", noun: "Établissement" },
  { value: "ght", label: "GHT", noun: "GHT" },
  { value: "departement", label: "Département", noun: "Département" }
];
const SHOWN = ["J+1", "J+2", "J+7"];
const STRIP = ["J+1", "J+2", "J+3", "J+4", "J+5", "J+6", "J+7"];

const GATES: Record<string, string> = {
  a_arrivals_mae_ratio: "(a) précision des arrivées",
  b_coverage_80: "(b) couverture à 80 %",
  c_regime_shift: "(c) rupture de régime",
  d_boarding_mae_ratio: "(d) brancards"
};

type Level = "normal" | "tension" | "critique";
const LEVEL: Record<Level, { label: string; cell: string; dot: string; icon: typeof CheckCircle2 }> = {
  normal: { label: "Normal", cell: "bg-lagoon-soft", dot: "bg-lagoon", icon: CheckCircle2 },
  tension: { label: "Tension", cell: "bg-sun-soft", dot: "bg-sun", icon: AlertCircle },
  critique: { label: "Critique", cell: "bg-coral-soft", dot: "bg-coral", icon: XCircle }
};

/** The most likely LISCOP level: critique, tension or normal, from the scenario shares. */
export function levelOf(day: ForecastDay): Level {
  if ((day.p_critique ?? 0) >= 0.5) return "critique";
  if ((day.p_tension ?? 0) >= 0.5) return "tension";
  return "normal";
}

function useForecast(scope: ForecastScope, target?: string) {
  const params = new URLSearchParams({ scope });
  if (target) params.set("target", target);
  return useQuery({
    queryKey: ["forecast-liscop", scope, target ?? "all"],
    queryFn: () => api<LiscopForecast>(`/forecast/liscop?${params.toString()}`)
  });
}

export function byHorizon(series: ForecastSeries | undefined, horizon: string): ForecastDay | undefined {
  return series?.values.find((v) => v.horizon === horizon);
}

export function range(day: ForecastDay): string {
  return `${fmtNum(day.q10)} à ${fmtNum(day.q90)}`;
}

function BedsCell({ day }: { day: ForecastDay | undefined }) {
  if (!day) return <td className="px-2 py-2 text-center text-ink-faint">—</td>;
  const level = LEVEL[levelOf(day)];
  const Icon = level.icon;
  return (
    <td className={`px-2 py-2 ${level.cell}`}>
      <span className="num block text-right text-[18px] font-bold">{fmtNum(day.mean)}</span>
      <span className="block text-right text-[12px] text-ink-soft">{range(day)}</span>
      <span className="mt-0.5 flex items-center justify-end gap-1 text-[12px] font-bold">
        <Icon className="h-3 w-3" aria-hidden /> {level.label} · risque {fmtPct(day.p_tension)}
      </span>
    </td>
  );
}

function Strip({ series }: { series: ForecastSeries }) {
  return (
    <ol className="flex gap-1" aria-label={`Sept jours, ${series.label}`}>
      {STRIP.map((h) => {
        const day = byHorizon(series, h);
        if (!day) return null;
        const level = levelOf(day);
        const text = `${h} (${fmtDay(day.day)}) : ${fmtNum(day.mean)} lits, ${LEVEL[level].label.toLowerCase()}, tension ${fmtPct(day.p_tension)}`;
        return (
          <li key={h} title={text} className={`h-7 w-4 rounded-[4px] ${LEVEL[level].dot}`}>
            <span className="sr-only">{text}</span>
          </li>
        );
      })}
    </ol>
  );
}

function BedsTable({ data }: { data: LiscopForecast }) {
  const beds = data.series.filter((s) => s.target === "available_beds");
  const arrivals = new Map(data.series.filter((s) => s.target === "arrivals").map((s) => [s.scope_key, s]));
  const noun = SCOPES.find((s) => s.value === data.scope)?.noun ?? "Unité";
  if (!beds.length) {
    return (
      <Empty title="Rien à afficher à cette échelle">
        {data.restricted_to_site
          ? "Votre compte est limité à un établissement : les vues GHT et département ne sont pas ouvertes."
          : "Le dernier calcul ne contient pas cette échelle."}
      </Empty>
    );
  }
  return (
    <>
      <ul className="space-y-3 sm:hidden" aria-label={`Lits disponibles attendus par ${noun.toLowerCase()}`}>
        {beds.map((s) => (
          <UnitCard key={s.scope_key} series={s} arrivals={byHorizon(arrivals.get(s.scope_key), "J+1")} />
        ))}
      </ul>
      <div className="relative hidden max-w-full overflow-x-auto sm:block">
        <table className="w-full min-w-[860px] text-[14px]">
          <caption className="sr-only">
            Lits disponibles attendus par {noun.toLowerCase()} à J+1, J+2 et J+7, avec la fourchette à 80 % et la
            probabilité de tension, arrivées attendues demain et tendance sur sept jours.
          </caption>
          <thead>
            <tr className="border-b border-line text-[12px] text-ink-faint">
              <th scope="col" className="px-2 py-2 text-left font-normal">
                {noun}
              </th>
              <th scope="col" className="px-2 py-2 text-right font-normal">
                Lits installés
              </th>
              <th scope="col" className="px-2 py-2 text-right font-normal">
                Arrivées attendues J+1
              </th>
              {SHOWN.map((h) => (
                <th key={h} scope="col" className="px-2 py-2 text-right font-normal">
                  Disponibles {h}
                </th>
              ))}
              <th scope="col" className="px-2 py-2 text-left font-normal">
                J+1 à J+7
              </th>
            </tr>
          </thead>
          <tbody>
            {beds.map((s) => {
              const arr = byHorizon(arrivals.get(s.scope_key), "J+1");
              return (
                <tr key={s.scope_key} className="border-b border-line/60 align-middle">
                  <th scope="row" className="px-2 py-2 text-left font-bold">
                    {s.label}
                  </th>
                  <td className="num px-2 py-2 text-right">{fmtNum(s.beds_installed)}</td>
                  <td className="px-2 py-2 text-right">
                    <span className="num">{arr ? fmtNum(arr.mean, 1) : "—"}</span>
                    {arr && <span className="block text-[12px] text-ink-faint">{range(arr)}</span>}
                  </td>
                  {SHOWN.map((h) => (
                    <BedsCell key={h} day={byHorizon(s, h)} />
                  ))}
                  <td className="px-2 py-2">
                    <Strip series={s} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function UnitCard({ series, arrivals }: { series: ForecastSeries; arrivals: ForecastDay | undefined }) {
  return (
    <li className="rounded-xl border border-line px-3 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[15px]">{series.label}</h3>
        <span className="text-[12px] text-ink-faint">{fmtNum(series.beds_installed)} lits installés</span>
      </div>
      {arrivals && (
        <p className="mt-1 text-[13px] text-ink-soft">
          Arrivées attendues demain : <b className="num">{fmtNum(arrivals.mean, 1)}</b> ({range(arrivals)})
        </p>
      )}
      <dl className="mt-2 grid grid-cols-3 gap-1">
        {SHOWN.map((h) => {
          const day = byHorizon(series, h);
          const level = day ? LEVEL[levelOf(day)] : null;
          return (
            <div key={h} className={`rounded-lg px-2 py-1.5 ${level?.cell ?? "bg-sky"}`}>
              <dt className="text-[12px] text-ink-soft">{h}</dt>
              <dd className="num text-[18px] font-bold">{day ? fmtNum(day.mean) : "—"}</dd>
              {day && level && (
                <dd className="text-[12px]">
                  {range(day)} · {level.label.toLowerCase()} · risque {fmtPct(day.p_tension)}
                </dd>
              )}
            </div>
          );
        })}
      </dl>
      <div className="mt-2">
        <Strip series={series} />
      </div>
    </li>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-ink-soft" aria-label="Légende LISCOP">
      <li className="flex items-center gap-1.5">
        <span className={`h-3 w-3 rounded-[3px] ${LEVEL.normal.dot}`} aria-hidden /> Normal : au moins 20 % des lits
        installés disponibles
      </li>
      <li className="flex items-center gap-1.5">
        <span className={`h-3 w-3 rounded-[3px] ${LEVEL.tension.dot}`} aria-hidden /> Tension : moins de 20 %
      </li>
      <li className="flex items-center gap-1.5">
        <span className={`h-3 w-3 rounded-[3px] ${LEVEL.critique.dot}`} aria-hidden /> Critique : aucun lit
      </li>
      <li>Couleur : niveau le plus probable ; risque : probabilité d'être en tension ou critique.</li>
    </ul>
  );
}

function Freshness({ data }: { data: LiscopForecast }) {
  const run = data.run;
  if (!run) return null;
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[14px] text-ink-soft">
      <span>
        Calculée le {fmtDateTime(run.created_at)} (il y a {fmtHours(run.age_hours)}), J+0 = {fmtDay(run.as_of)}
      </span>
      {run.stale && (
        <span className="chip bg-sun-soft text-ink">
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> À rafraîchir
        </span>
      )}
      {data.last_failure_at && (
        <span className="chip bg-coral-soft text-coral-dark">
          Dernier calcul en échec le {fmtDateTime(data.last_failure_at)} : chiffres du calcul précédent
        </span>
      )}
    </p>
  );
}

function Method({ data }: { data: LiscopForecast }) {
  const models = data.series.filter((s) => s.model && (s.target === "arrivals" || s.target === "boarding_10h"));
  const bt = data.backtest;
  return (
    <section className="panel px-5 py-4" aria-labelledby="methode">
      <h2 id="methode">D'où viennent ces chiffres</h2>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-[14px] text-ink-soft">
        {data.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
      {data.run && (
        <p className="mt-3 text-[14px]">
          Modèles retenus par validation croisée :{" "}
          {Object.entries(data.run.models_chosen)
            .map(([m, n]) => `${m} (${n})`)
            .join(", ")}
          {data.run.fallback_series > 0 && ` ; ${data.run.fallback_series} série(s) gardent la référence saisonnière`}.
        </p>
      )}
      {models.length > 0 && (
        <ul className="mt-2 grid gap-x-6 text-[13px] text-ink-soft sm:grid-cols-2">
          {models.map((s) => (
            <li key={`${s.target}-${s.scope_key}`}>
              {s.target === "arrivals" ? "Arrivées" : "Brancards 10 h"} · {s.label} : <b>{s.model}</b>
              {s.fallback ? " (référence)" : ""}
            </li>
          ))}
        </ul>
      )}
      {bt && (
        <p className="mt-3 text-[14px]">
          Backtest du {fmtShort(bt.last_full_day)} ({bt.origins} origines) : arrivées MAE / référence{" "}
          {fmtNum(bt.arrivals_mae_ratio, 2)}, couverture à 80 % {fmtPct(bt.arrivals_coverage_80)} ; lits disponibles{" "}
          {fmtPct(bt.beds_coverage_80)} ; brancards MAE / référence {fmtNum(bt.boarding_mae_ratio, 2)}. Critères
          pré-enregistrés :{" "}
          {Object.entries(bt.gates)
            .map(([k, v]) => `${GATES[k] ?? k} ${v}`)
            .join(" ; ")}
          .
        </p>
      )}
    </section>
  );
}

export function PrevisionPage() {
  const [scope, setScope] = useState<ForecastScope>("unit");
  const main = useForecast(scope);
  const boarding = useForecast(scope === "unit" ? "site" : scope, "boarding_10h");
  const data = main.data;
  const boardingSeries = boarding.data?.series.filter((s) => s.target === "boarding_10h") ?? [];

  return (
    <>
      <PageHeader
        title="Prévision"
        lead="Lits disponibles attendus, probabilité de tension et lits brancards à 10 h, de demain à J+7, avec leur fourchette à 80 %."
        actions={
          <div
            role="group"
            aria-label="Échelle"
            className="flex flex-wrap gap-1 rounded-panel bg-paper p-1 shadow-lift"
          >
            {SCOPES.map((s) => (
              <button
                key={s.value}
                type="button"
                aria-pressed={scope === s.value}
                onClick={() => setScope(s.value)}
                className={`btn px-3 py-1.5 ${scope === s.value ? "bg-violet text-white" : "text-ink-soft hover:bg-sky"}`}
              >
                {s.label}
              </button>
            ))}
          </div>
        }
      />

      {main.isLoading && <Spinner />}
      {main.error && <ErrorNote error={main.error} />}
      {data && !data.run && (
        <Empty title="Aucune prévision calculée pour l'instant">
          Le moteur de prévision tourne en tâche planifiée et dépose ses résultats ici dès son premier passage.
        </Empty>
      )}
      {data?.run && (
        <div className="space-y-6">
          {data.synthetic && (
            <p role="note" className="flex max-w-4xl items-start gap-3 rounded-panel bg-sun-soft px-5 py-4 text-[15px]">
              <FlaskConical className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
              <span>
                Prévision calculée sur des données de démonstration synthétiques : elle montre le fonctionnement, pas la
                précision attendue sur un hôpital réel.
              </span>
            </p>
          )}
          <Freshness data={data} />
          <section className="panel min-w-0 px-3 py-3 sm:px-4" aria-labelledby="lits-attendus">
            <div className="flex flex-wrap items-baseline justify-between gap-3 px-2 pb-3">
              <h2 id="lits-attendus">Lits disponibles attendus</h2>
              <p className="text-[13px] text-ink-faint">
                disponibles attendus = libérés − arrivées non programmées − promesses
              </p>
            </div>
            <BedsTable data={data} />
            <div className="px-2 pt-3">
              <Legend />
            </div>
          </section>
          <section className="panel px-5 py-4" aria-labelledby="brancards">
            <h2 id="brancards">Lits brancards à 10 h</h2>
            {boarding.isLoading && <Spinner />}
            {boarding.error && <ErrorNote error={boarding.error} />}
            {boarding.data && !boardingSeries.length && (
              <p className="mt-2 text-[14px] text-ink-soft">Aucun service d'urgences à cette échelle.</p>
            )}
            <div className={`mt-3 grid gap-6 ${boardingSeries.length > 1 ? "xl:grid-cols-2" : ""}`}>
              {boardingSeries.map((s) => (
                <div key={s.scope_key}>
                  <h3 className="mb-2">{s.label}</h3>
                  <Suspense fallback={<Spinner />}>
                    <BoardingChart series={s} />
                  </Suspense>
                </div>
              ))}
            </div>
          </section>
          <Method data={data} />
        </div>
      )}
    </>
  );
}
