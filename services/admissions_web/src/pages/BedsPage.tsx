import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DoorOpen } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { Pool, Site, Stay } from "../api/types";
import { useAuth } from "../auth";
import { LampLegend, LampStrip } from "../components/LampStrip";
import { Empty, ErrorNote, Meter, Modal, PageHeader, Spinner } from "../components/ui";
import { fmtDate, fmtDay, fmtNum, fmtPct, isoDay, plural } from "../lib/format";
import { label, useSites, useVocabulary } from "../lib/queries";
import { useForecast } from "../lib/requests";

export function BedsPage() {
  const sites = useSites();
  const [siteId, setSiteId] = useState<number | null>(null);
  const activeSites = (sites.data ?? []).filter((s) => s.active);

  useEffect(() => {
    if (siteId === null && activeSites.length) setSiteId(activeSites[0].id);
  }, [activeSites, siteId]);

  const site = activeSites.find((s) => s.id === siteId) ?? null;
  return (
    <>
      <PageHeader
        title="Lits et sorties"
        lead="Les sorties attendues sur quatorze jours, calculées à partir des durées de séjour observées et des dates de sortie prévues par les équipes."
      />
      {sites.isLoading && <Spinner />}
      {sites.error && <ErrorNote error={sites.error} />}
      {activeSites.length > 1 && (
        <div role="tablist" aria-label="Sites" className="mb-6 flex flex-wrap gap-2">
          {activeSites.map((s) => (
            <button
              key={s.id}
              role="tab"
              aria-selected={s.id === siteId}
              onClick={() => setSiteId(s.id)}
              className={`rounded-chip px-4 py-2 text-[15px] font-bold ${
                s.id === siteId ? "bg-ink text-white" : "bg-paper text-ink-soft shadow-lift hover:text-ink"
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
      {site && <SiteBeds key={site.id} site={site} />}
    </>
  );
}

function SiteBeds({ site }: { site: Site }) {
  const vocab = useVocabulary();
  const forecast = useForecast();
  const { canWrite } = useAuth();
  const [editing, setEditing] = useState<Pool | null>(null);
  const stays = useQuery({
    queryKey: ["stays", site.id],
    queryFn: () => api<Stay[]>(`/stays?scope=presents&site_id=${site.id}`)
  });

  const pools = useMemo(
    () => forecast.data?.pools.filter((p) => p.site_id === site.id) ?? [],
    [forecast.data, site.id]
  );

  return (
    <div className="space-y-8">
      <section aria-labelledby="pools">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="pools">{site.name}</h2>
          <LampLegend />
        </div>
        <div className="grid gap-4 2xl:grid-cols-2">
          {site.pools.map((pool) => {
            const pf = pools.find((p) => p.mention === pool.mention);
            const week = pf?.days[Math.min(6, pf.days.length - 1)];
            const closed = pool.beds_installed - pool.beds_open;
            return (
              <article key={pool.mention} className="panel min-w-0 px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3>{label(vocab.data?.mentions, pool.mention)}</h3>
                    <p className="text-[14px] text-ink-soft">
                      {pool.occupied} patients pour {plural(pool.beds_open, "lit ouvert", "lits ouverts")}
                      {closed > 0 ? `, ${plural(closed, "lit fermé", "lits fermés")}` : ""}
                    </p>
                  </div>
                  {canWrite && (
                    <button className="btn-quiet" onClick={() => setEditing(pool)}>
                      Lits ouverts
                    </button>
                  )}
                </div>
                {pf ? (
                  <>
                    <div className="mt-3 overflow-x-auto">
                      <LampStrip days={pf.days} animate />
                    </div>
                    <p className="mt-2 text-[14px] text-ink-soft">
                      Sous 7 jours : <strong className="text-ink">{fmtNum(week?.cumulative_expected, 1)}</strong> sorties
                      attendues (entre {week?.cumulative_p10} et {week?.cumulative_p90}),{" "}
                      {plural(week?.reserved ?? 0, "lit déjà promis", "lits déjà promis")}.
                    </p>
                  </>
                ) : (
                  <Spinner label="Prévision" />
                )}
              </article>
            );
          })}
        </div>
        {forecast.data && forecast.data.basis.low_data_mentions.length > 0 && (
          <p className="mt-3 text-[14px] text-ink-soft">
            Historique encore court pour :{" "}
            {forecast.data.basis.low_data_mentions.map((m) => label(vocab.data?.mentions, m)).join(", ")}. La prévision
            s'appuie alors sur l'ensemble des mentions du groupe.
          </p>
        )}
      </section>

      <section aria-labelledby="present">
        <h2 id="present">Patients présents</h2>
        <p className="mt-1 text-ink-soft">
          Renseigner une date de sortie prévue rend la prévision plus précise que la seule durée de séjour habituelle.
        </p>
        <div className="mt-4">
          {stays.isLoading && <Spinner />}
          {stays.error && <ErrorNote error={stays.error} />}
          {stays.data && stays.data.length === 0 && <Empty title="Aucun patient présent" />}
          {stays.data && stays.data.length > 0 && <StaysTable stays={stays.data} canWrite={canWrite} />}
        </div>
      </section>

      {editing && <PoolModal site={site} pool={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function StaysTable({ stays, canWrite }: { stays: Stay[]; canWrite: boolean }) {
  const vocab = useVocabulary();
  const [sort, setSort] = useState<"sortie" | "duree">("sortie");
  const rows = [...stays].sort((a, b) =>
    sort === "duree" ? b.length_of_stay - a.length_of_stay : (b.prob_within_7_days ?? 0) - (a.prob_within_7_days ?? 0)
  );
  return (
    <div className="panel relative overflow-x-auto">
      <table className="w-full min-w-[760px] text-[15px]">
        <caption className="sr-only">Patients présents et sortie attendue</caption>
        <thead>
          <tr className="border-b border-line text-left text-[13px] text-ink-faint">
            <th className="px-5 py-3 font-normal">Patient</th>
            <th className="px-3 py-3 font-normal">Mention</th>
            <th className="px-3 py-3 font-normal">
              <button className="font-bold hover:text-ink" onClick={() => setSort("duree")} aria-pressed={sort === "duree"}>
                Durée
              </button>
            </th>
            <th className="px-3 py-3 font-normal">
              <button className="font-bold hover:text-ink" onClick={() => setSort("sortie")} aria-pressed={sort === "sortie"}>
                Sortie sous 7 jours
              </button>
            </th>
            <th className="px-3 py-3 font-normal">Sortie prévue</th>
            <th className="px-5 py-3 font-normal">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <StayRow key={s.id} stay={s} mention={label(vocab.data?.mentions, s.mention)} canWrite={canWrite} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StayRow({ stay, mention, canWrite }: { stay: Stay; mention: string; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const [planned, setPlanned] = useState(stay.planned_discharge_date ?? "");
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<Stay>(`/stays/${stay.id}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["stays"] });
      void queryClient.invalidateQueries({ queryKey: ["forecast"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
    }
  });
  const today = isoDay(new Date());
  const p = stay.prob_within_7_days ?? 0;
  const dirty = planned !== (stay.planned_discharge_date ?? "");
  return (
    <tr className="border-b border-line last:border-0">
      <td className="px-5 py-3">
        <p className="font-bold">{stay.patient_ref}</p>
        <p className="text-[13px] text-ink-faint">Entré le {fmtDate(stay.admission_date)}</p>
      </td>
      <td className="px-3 py-3">{mention}</td>
      <td className="num px-3 py-3">{stay.length_of_stay} j</td>
      <td className="px-3 py-3">
        <div className="flex items-center gap-2">
          <span className="w-24">
            <Meter value={p * 100} tone={p >= 0.5 ? "sun" : "violet"} />
          </span>
          <span className="num text-[14px]">{fmtPct(p)}</span>
        </div>
        <p className="text-[13px] text-ink-faint">
          {stay.median_discharge_day ? `Médiane : ${fmtDay(stay.median_discharge_day)}` : "Au-delà de 4 semaines"}
        </p>
      </td>
      <td className="px-3 py-3">
        {canWrite ? (
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              update.mutate(planned ? { planned_discharge_date: planned } : { clear_planned: true });
            }}
          >
            <label className="sr-only" htmlFor={`planned-${stay.id}`}>
              Sortie prévue de {stay.patient_ref}
            </label>
            <input
              id={`planned-${stay.id}`}
              type="date"
              className="input mt-0 w-[150px] py-1.5"
              min={stay.admission_date}
              value={planned}
              onChange={(e) => setPlanned(e.target.value)}
            />
            {dirty && (
              <button className="btn-primary px-3 py-1.5 text-[14px]" type="submit" disabled={update.isPending}>
                Enregistrer
              </button>
            )}
          </form>
        ) : (
          fmtDate(stay.planned_discharge_date)
        )}
        {update.error && <p className="mt-1 text-[13px] text-coral-dark">{(update.error as Error).message}</p>}
      </td>
      <td className="px-5 py-3 text-right">
        {canWrite && (
          <button
            className="btn-quiet px-3 py-1.5 text-[14px]"
            disabled={update.isPending}
            onClick={() => update.mutate({ discharge_date: today })}
            title="Enregistrer la sortie aujourd'hui"
          >
            <DoorOpen className="h-4 w-4" aria-hidden /> Sorti aujourd'hui
          </button>
        )}
      </td>
    </tr>
  );
}

function PoolModal({ site, pool, onClose }: { site: Site; pool: Pool; onClose: () => void }) {
  const vocab = useVocabulary();
  const { isAdmin } = useAuth();
  const queryClient = useQueryClient();
  const [installed, setInstalled] = useState(String(pool.beds_installed));
  const [opened, setOpened] = useState(String(pool.beds_open));
  const [isolation, setIsolation] = useState(String(pool.isolation_rooms));
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const save = useMutation({
    mutationFn: () =>
      api<Site>(`/sites/${site.id}/pools/${pool.mention}`, {
        method: "PUT",
        json: {
          beds_installed: Number(installed),
          beds_open: Number(opened),
          isolation_rooms: Number(isolation),
          reason,
          comment: comment.trim() || null
        }
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      onClose();
    }
  });
  const closing = Number(opened) < Number(installed);
  return (
    <Modal title={`Lits ouverts, ${label(vocab.data?.mentions, pool.mention)}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <p className="text-ink-soft">
          Chaque changement est daté et motivé. Le motif « manque de personnel » sert à mesurer ce qui limite
          réellement les admissions.
        </p>
        <div className="mt-4 grid grid-cols-3 gap-3">
          <div>
            <label className="field" htmlFor="p-inst">
              Installés
            </label>
            <input id="p-inst" type="number" min={0} className="input" disabled={!isAdmin} value={installed} onChange={(e) => setInstalled(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="p-open">
              Ouverts
            </label>
            <input id="p-open" type="number" min={0} max={Number(installed)} className="input" value={opened} onChange={(e) => setOpened(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="p-iso">
              Isolement
            </label>
            <input id="p-iso" type="number" min={0} className="input" value={isolation} onChange={(e) => setIsolation(e.target.value)} />
          </div>
        </div>
        <label className="field mt-4" htmlFor="p-reason">
          Motif {closing ? "de la fermeture" : "du changement"}
        </label>
        <select id="p-reason" required className="input" value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="" disabled>
            Choisir
          </option>
          {Object.entries(vocab.data?.capacity_reasons ?? {}).map(([code, text]) => (
            <option key={code} value={code}>
              {text}
            </option>
          ))}
        </select>
        <label className="field mt-4" htmlFor="p-comment">
          Précision (facultatif)
        </label>
        <input id="p-comment" className="input" value={comment} onChange={(e) => setComment(e.target.value)} />
        {save.error && (
          <div className="mt-3">
            <ErrorNote error={save.error} />
          </div>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn-primary" disabled={!reason || save.isPending}>
            Enregistrer les lits
          </button>
        </div>
      </form>
    </Modal>
  );
}
