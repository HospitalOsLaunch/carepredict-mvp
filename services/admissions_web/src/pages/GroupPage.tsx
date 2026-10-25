import { Link } from "react-router-dom";

import type { PoolForecast, Site } from "../api/types";
import { LampLegend, LampStrip, type LampDay } from "../components/LampStrip";
import { ErrorNote, Meter, PageHeader, Spinner } from "../components/ui";
import { fmtHours, fmtNum, fmtPct, plural } from "../lib/format";
import { label, useDashboard, useSites, useVocabulary } from "../lib/queries";
import { useForecast } from "../lib/requests";

/** Site-level lamps: a bed is free somewhere on the site if any mention has one. */
function siteDays(pools: PoolForecast[]): LampDay[] {
  if (!pools.length) return [];
  return pools[0].days.map((_, k) => {
    const days = pools.map((p) => p.days[k]);
    const none = days.reduce((acc, d) => acc * (1 - d.prob_at_least_one_free), 1);
    return {
      day: days[0].day,
      free_expected: days.reduce((acc, d) => acc + Math.max(0, d.free_expected), 0),
      prob_at_least_one_free: 1 - none
    };
  });
}

export function GroupPage() {
  const dashboard = useDashboard();
  const forecast = useForecast();
  const sites = useSites();
  const vocab = useVocabulary();
  const d = dashboard.data;

  if (dashboard.isLoading) return <Spinner />;
  if (dashboard.error) return <ErrorNote error={dashboard.error} />;
  if (!d) return null;

  return (
    <>
      <PageHeader
        title={`${d.occupied} patients pour ${d.beds_open} lits ouverts`}
        lead={
          <>
            Taux d'occupation de {fmtPct(d.occupancy_on_open)} sur {plural(d.sites.length, "site", "sites")}.{" "}
            {d.awaiting_response > 0
              ? `${plural(d.awaiting_response, "demande attend", "demandes attendent")} une réponse. `
              : "Aucune demande n'attend de réponse. "}
            Sur trente jours, la moitié des demandes ont reçu une réponse en moins de{" "}
            {fmtHours(d.responses_median_hours_30d)}.
          </>
        }
      />
      <div className="mb-3 flex justify-end">
        <LampLegend />
      </div>
      <ul className="space-y-4">
        {d.sites.map((s) => {
          const pools = forecast.data?.pools.filter((p) => p.site_id === s.site_id) ?? [];
          const occ = s.occupancy_on_open ?? 0;
          return (
            <li key={s.site_id} className="panel grid gap-5 px-6 py-5 lg:grid-cols-[minmax(220px,1fr)_auto]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <h2>{s.site_name}</h2>
                  {s.city && <span className="text-ink-faint">{s.city}</span>}
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <span className="w-40">
                    <Meter value={occ * 100} tone={occ >= 0.95 ? "coral" : "violet"} />
                  </span>
                  <span className="text-[15px]">
                    <strong className="num">{s.occupied}</strong> / {s.beds_open} lits ouverts
                    {s.beds_installed > s.beds_open && (
                      <span className="text-ink-faint">, {s.beds_installed - s.beds_open} fermés</span>
                    )}
                  </span>
                </div>
                <dl className="mt-4 grid grid-cols-3 gap-4 text-[14px]">
                  <div>
                    <dt className="text-ink-faint">À répondre</dt>
                    <dd className={`num text-xl font-bold ${s.awaiting_response ? "text-coral-dark" : ""}`}>
                      {s.awaiting_response}
                    </dd>
                    {s.oldest_waiting_hours !== null && (
                      <dd className="text-ink-faint">depuis {fmtHours(s.oldest_waiting_hours)}</dd>
                    )}
                  </div>
                  <div>
                    <dt className="text-ink-faint">Sorties sous 7 j</dt>
                    <dd className="num text-xl font-bold">{fmtNum(s.discharges_next_7_days)}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-faint">Libres à J+7</dt>
                    <dd className="num text-xl font-bold">{fmtNum(Math.max(0, s.free_beds_in_7_days))}</dd>
                    {s.reserved_next_7_days > 0 && (
                      <dd className="text-ink-faint">après {plural(s.reserved_next_7_days, "promesse", "promesses")}</dd>
                    )}
                  </div>
                </dl>
              </div>
              <div className="min-w-0 overflow-x-auto lg:self-center">
                {pools.length ? <LampStrip days={siteDays(pools)} animate /> : <Spinner label="Prévision" />}
                <Link to="/lits" className="mt-2 inline-block text-[14px] font-bold text-violet hover:underline">
                  Voir les lits du site
                </Link>
              </div>
            </li>
          );
        })}
      </ul>

      <ClosedBeds sites={sites.data ?? []} mentionLabel={(m) => label(vocab.data?.mentions, m)} />
    </>
  );
}

function ClosedBeds({ sites, mentionLabel }: { sites: Site[]; mentionLabel: (m: string) => string }) {
  const rows = sites.flatMap((s) =>
    s.pools.filter((p) => p.beds_installed > p.beds_open).map((p) => ({ site: s.name, ...p }))
  );
  if (!rows.length) return null;
  return (
    <section className="mt-10" aria-labelledby="closed">
      <h2 id="closed">Lits fermés aujourd'hui</h2>
      <p className="mt-1 max-w-2xl text-ink-soft">
        Si les lits sont fermés faute de personnel, mieux trier les demandes ne suffit pas à remplir le site. Les motifs
        sont suivis dans les indicateurs pilote.
      </p>
      <ul className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {rows.map((r) => (
          <li key={`${r.site}-${r.mention}`} className="flex items-center justify-between rounded-xl bg-paper px-4 py-3">
            <span>
              {r.site}, {mentionLabel(r.mention)}
            </span>
            <span className="num font-bold text-coral-dark">{r.beds_installed - r.beds_open} fermés</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
