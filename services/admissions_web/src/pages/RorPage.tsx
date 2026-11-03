import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Download, FlaskConical, Send, XCircle } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import type { RorExport, RorOutboxEntry, RorPrevision, RorUnite, TensionLevel } from "../api/types_liscop";
import { useAuth } from "../auth";
import { ErrorNote, PageHeader, Spinner } from "../components/common";
import { fmtDateTime, fmtHours, fmtNum, fmtPct, fmtShort, isoDay, plural } from "../lib/format";

const TENSION: Record<TensionLevel, { label: string; chip: string; icon: typeof CheckCircle2 }> = {
  normal: { label: "Normal", chip: "bg-lagoon-soft text-lagoon-dark", icon: CheckCircle2 },
  tension: { label: "Tension", chip: "bg-sun-soft text-ink", icon: AlertCircle },
  critique: { label: "Critique", chip: "bg-coral-soft text-coral-dark", icon: XCircle }
};

const HORIZONS = ["J+1", "J+2", "J+7"];

export function TensionChip({ level, rate }: { level: TensionLevel; rate: number | null }) {
  const t = TENSION[level];
  const Icon = t.icon;
  return (
    <span className={`chip ${t.chip}`} title={rate === null ? undefined : `${fmtPct(rate)} de lits disponibles`}>
      <Icon className="h-3.5 w-3.5" aria-hidden /> {t.label}
    </span>
  );
}

/** Signal bars like LISCOP: 4 within the hour, 3 within 3 h, 2 within 12 h, 1 within 24 h. */
export function freshnessBars(hours: number | null): number {
  if (hours === null) return 0;
  if (hours <= 1) return 4;
  if (hours <= 3) return 3;
  if (hours <= 12) return 2;
  if (hours <= 24) return 1;
  return 0;
}

/** Most likely LISCOP level of a forecast day, from the scenario shares. */
export function forecastLevel(p: RorPrevision): TensionLevel {
  if ((p.p_critique ?? 0) >= 0.5) return "critique";
  if ((p.p_tension ?? 0) >= 0.5) return "tension";
  return "normal";
}

function saveFile(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function useRorExport() {
  return useQuery({ queryKey: ["ror-export"], queryFn: () => api<RorExport>("/ror/export") });
}

export function RorPage() {
  const query = useRorExport();
  const { isAdmin } = useAuth();
  const data = query.data;

  if (query.isLoading) return <Spinner />;
  if (query.error) return <ErrorNote error={query.error} />;
  if (!data) return null;

  const units = data.unites;
  const sum = (pick: (u: RorUnite) => number | null) => units.reduce((acc, u) => acc + (pick(u) ?? 0), 0);
  const available = sum((u) => u.disponibles_par_genre.total);
  const strained = units.filter((u) => u.tension.niveau !== "normal").length;
  const critical = units.filter((u) => u.tension.niveau === "critique").length;
  const toLink = units.filter((u) => !u.identifiant_unite_ror).length;
  const ages = units.map((u) => u.fraicheur?.age_heures).filter((h): h is number => h !== undefined);
  const stalest = ages.length ? Math.max(...ages) : null;
  const expected = units.filter((u) => u.previsionnel_nature.nature === "disponibles_attendus");
  const j1 = expected.reduce((acc, u) => acc + (u.previsionnel.find((p) => p.echeance === "J+1")?.moyenne ?? 0), 0);

  return (
    <>
      <PageHeader
        title="Remontée vers le ROR"
        lead={
          <>
            Ce que HospitalOS peut transmettre, sans saisie supplémentaire, au ROR national et aux outils régionaux qui
            le lisent, comme LISCOP : disponibilités au lit près, capacité opérationnelle, prévisionnel et indicateurs
            pour l'ORU.
          </>
        }
        actions={
          <button
            className="btn-quiet"
            onClick={() => saveFile(`ror-export-maquette-${data.date_situation}.json`, JSON.stringify(data, null, 2), "application/json")}
          >
            <Download className="h-4 w-4" aria-hidden /> Télécharger le JSON
          </button>
        }
      />

      <p role="note" className="mb-6 flex max-w-4xl items-start gap-3 rounded-panel bg-sun-soft px-5 py-4 text-[15px]">
        <FlaskConical className="mt-0.5 h-5 w-5 shrink-0 text-ink" aria-hidden />
        <span>
          {data.avertissement}
          {data.synthetique && " Données de démonstration, issues de notre simulateur."}
        </span>
      </p>

      <dl className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          value={fmtNum(available)}
          label={`lits disponibles maintenant (F ${fmtNum(sum((u) => u.disponibles_par_genre.femme))} · H ${fmtNum(
            sum((u) => u.disponibles_par_genre.homme)
          )} · indéterminé ${fmtNum(sum((u) => u.disponibles_par_genre.indetermine))})`}
        />
        <Kpi
          value={fmtNum(strained)}
          label={`${strained >= 2 ? "unités" : "unité"} en tension ou critique sur ${units.length}, dont ${critical} critique${critical >= 2 ? "s" : ""}`}
          tone={critical ? "coral" : strained ? "sun" : undefined}
        />
        <Kpi
          value={expected.length ? fmtNum(j1) : "—"}
          label={
            expected.length
              ? `lits disponibles attendus demain (${plural(expected.length, "unité prévue", "unités prévues")})`
              : "pas de prévision stockée : seules les sorties prévues sont connues"
          }
        />
        <Kpi
          value={stalest === null ? "—" : `il y a ${fmtHours(stalest)}`}
          label={`donnée la plus ancienne ; ${plural(toLink, "unité", "unités")} sans identifiant ROR`}
          tone={stalest !== null && stalest > 24 ? "coral" : toLink ? "sun" : undefined}
        />
      </dl>

      <UnitsSection data={data} />

      {isAdmin && <OutboxSection />}

      <OruSection />

      <section className="mt-10 grid gap-6 lg:grid-cols-2" aria-label="Avant un vrai envoi">
        <div className="panel px-6 py-5">
          <h2>À compléter avant un envoi réel</h2>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-ink-soft">
            {data.non_suivi_dans_le_pilote.map((item) => (
              <li key={item}>{item}</li>
            ))}
            {toLink > 0 && <li>{plural(toLink, "unité", "unités")} à rattacher à leur identifiant ROR.</li>}
          </ul>
        </div>
        <div className="panel px-6 py-5">
          <h2>Hypothèses de calcul</h2>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-ink-soft">
            {data.hypotheses.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="mt-4 text-[13px] text-ink-faint">Référentiels :</p>
          <ul className="mt-1 space-y-1 text-[13px]">
            {data.referentiels.map((r) => (
              <li key={r.nom}>
                <a className="break-words font-bold text-violet hover:underline" href={r.url} target="_blank" rel="noreferrer">
                  {r.nom}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <details className="panel mt-6 px-6 py-5">
        <summary className="cursor-pointer font-display text-lg font-semibold">
          Aperçu du message ({plural(units.length, "unité", "unités")})
        </summary>
        <pre className="mt-4 max-h-[480px] overflow-auto rounded-xl bg-sky px-4 py-3 text-[12px] leading-relaxed">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </>
  );
}

function Kpi({ value, label, tone }: { value: string; label: string; tone?: "sun" | "coral" }) {
  const border = tone === "coral" ? "border-coral" : tone === "sun" ? "border-sun" : "border-transparent";
  return (
    <div className={`panel flex flex-col-reverse justify-end border-2 px-5 py-4 ${border}`}>
      <dt className="mt-1 text-[14px] text-ink-soft">{label}</dt>
      <dd className="num font-display text-3xl font-bold">{value}</dd>
    </div>
  );
}

// --- capacity table ---------------------------------------------------------------------------

function UnitsSection({ data }: { data: RorExport }) {
  const units = data.unites;
  const run = data.prevision;
  const th = "px-2 py-1.5 font-normal";
  return (
    <section className="panel px-3 py-3 sm:px-4" aria-labelledby="ror-table">
      <div className="flex flex-wrap items-baseline justify-between gap-3 px-1 pb-3">
        <h2 id="ror-table">Capacité par unité, situation du {fmtShort(data.date_situation)}</h2>
        <p className="text-[13px] text-ink-faint">
          Calculé le {fmtDateTime(data.genere_le)}
          {run && ` · prévision du ${fmtDateTime(run.calcule_le)} (${run.modele})${run.perimee ? ", à recalculer" : ""}`}
        </p>
      </div>

      <table className="hidden w-full text-[14px] lg:table">
        <caption className="sr-only">
          Pour chaque unité : lits disponibles par genre, prévisionnel à J+1, J+2 et J+7, capacité opérationnelle, lits
          réservés en cas de crise, niveau de tension, fraîcheur de la donnée et identifiant ROR.
        </caption>
        <thead>
          <tr className="text-[12px] font-bold uppercase tracking-wide text-ink-faint">
            <td />
            <th scope="colgroup" colSpan={4} className={`${th} border-b border-line text-center font-bold`}>
              Disponibles
            </th>
            <th scope="colgroup" colSpan={3} className={`${th} border-b border-line text-center font-bold`}>
              Prévisionnel
            </th>
            <th scope="colgroup" colSpan={3} className={`${th} border-b border-line text-center font-bold`}>
              Opérationnel
            </th>
            <td colSpan={4} />
          </tr>
          <tr className="border-b border-line text-[12px] text-ink-faint">
            <th scope="col" className={`${th} text-left`}>
              Unité
            </th>
            <th scope="col" className={`${th} text-right`} title="Femme (J190 01)">
              F
            </th>
            <th scope="col" className={`${th} text-right`} title="Homme (J190 02)">
              H
            </th>
            <th scope="col" className={`${th} text-right`} title="Indéterminé (J190 04)">
              Ind.
            </th>
            <th scope="col" className={`${th} text-right`}>
              Total
            </th>
            {HORIZONS.map((h) => (
              <th key={h} scope="col" className={`${th} text-right`}>
                {h}
              </th>
            ))}
            <th scope="col" className={`${th} text-right`}>
              En service
            </th>
            <th scope="col" className={`${th} text-right`}>
              Réactivables
            </th>
            <th scope="col" className={`${th} text-right`}>
              Suppl.
            </th>
            <th scope="col" className={`${th} text-right`}>
              Crise-SSE
            </th>
            <th scope="col" className={`${th} text-left`}>
              Tension
            </th>
            <th scope="col" className={`${th} text-left`}>
              Fraîcheur
            </th>
            <th scope="col" className={`${th} text-left`}>
              ROR
            </th>
          </tr>
        </thead>
        <tbody>
          {units.map((u) => (
            <UnitRow key={u.pool_id} unit={u} />
          ))}
        </tbody>
      </table>

      <ul className="space-y-3 lg:hidden" aria-label="Capacité par unité">
        {units.map((u) => (
          <UnitCard key={u.pool_id} unit={u} />
        ))}
      </ul>

      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 px-1 text-[13px] text-ink-faint">
        <li>Tension (légende LISCOP) : normal si au moins 20 % des lits installés sont disponibles, critique à 0.</li>
        <li>
          Prévisionnel : lits disponibles attendus (moyenne, fourchette à 80 %, risque de tension). « Libérés » : sorties
          prévues seulement, faute de prévision stockée.
        </li>
        <li>Fraîcheur : dernier mouvement, changement de lit ou de capacité ; 4 barres dans l'heure, 0 au-delà de 24 h.</li>
      </ul>
    </section>
  );
}

function genderCell(n: number | null) {
  return n === null ? <span className="text-ink-faint">—</span> : fmtNum(n);
}

function UnitName({ unit }: { unit: RorUnite }) {
  return (
    <>
      <span className="block font-bold">{unit.libelle_unite}</span>
      <span className="block text-[13px] text-ink-faint">
        {unit.etablissement}
        {unit.disponibles_par_genre.niveau === "unite" && " · sans plan des lits"}
        {unit.disponibles_par_genre.isolement ? ` · ${unit.disponibles_par_genre.isolement} en isolement` : ""}
      </span>
    </>
  );
}

function ForecastValue({ unit, horizon }: { unit: RorUnite; horizon: string }) {
  const p = unit.previsionnel.find((x) => x.echeance === horizon);
  if (!p) return <span className="text-ink-faint">—</span>;
  const released = unit.previsionnel_nature.nature === "liberes_non_promis";
  const level = TENSION[forecastLevel(p)];
  return (
    <>
      <span className={`num block font-bold ${released ? "text-ink-soft" : ""}`}>{fmtNum(p.moyenne)}</span>
      <span className="block whitespace-nowrap text-[12px] text-ink-faint">
        {p.fourchette_80[0]} à {p.fourchette_80[1]}
      </span>
      {released ? (
        <span className="block text-[11px] italic text-ink-faint">libérés</span>
      ) : (
        p.p_tension !== null && (
          <span className={`chip mt-0.5 whitespace-nowrap px-1.5 text-[11px] ${level.chip}`} title={`${level.label} probable`}>
            <span className="sr-only">risque de tension </span>
            {fmtPct(p.p_tension)}
          </span>
        )
      )}
    </>
  );
}

function Freshness({ unit }: { unit: RorUnite }) {
  const f = unit.fraicheur;
  const hours = f?.age_heures ?? null;
  const bars = freshnessBars(hours);
  const label = f ? `il y a ${fmtHours(hours)}` : "inconnue";
  return (
    <span className="inline-flex items-center gap-2" title={f ? `${f.libelle}, le ${fmtDateTime(f.le)}` : undefined}>
      <span
        className="flex h-4 items-end gap-0.5"
        role="img"
        aria-label={`Fraîcheur ${bars} sur 4${f ? ` : ${f.libelle}` : ""}`}
      >
        {[1, 2, 3, 4].map((k) => (
          <span
            key={k}
            className={`w-1 rounded-sm ${k <= bars ? (bars <= 1 ? "bg-coral" : "bg-lagoon") : "bg-line"}`}
            style={{ height: `${k * 25}%` }}
          />
        ))}
      </span>
      <span className="whitespace-nowrap text-[13px] text-ink-soft">{label}</span>
    </span>
  );
}

function RorId({ unit }: { unit: RorUnite }) {
  return unit.identifiant_unite_ror ? (
    <span className="chip bg-lagoon-soft text-lagoon-dark">{unit.identifiant_unite_ror}</span>
  ) : (
    <span className="chip whitespace-nowrap bg-coral-soft text-coral-dark">à rattacher</span>
  );
}

function UnitRow({ unit }: { unit: RorUnite }) {
  const g = unit.disponibles_par_genre;
  const op = unit.operationnel;
  const td = "num px-2 py-3 text-right align-top";
  return (
    <tr className="border-b border-line last:border-0">
      <th scope="row" className="px-2 py-3 text-left align-top font-normal">
        <UnitName unit={unit} />
      </th>
      <td className={td}>{genderCell(g.femme)}</td>
      <td className={td}>{genderCell(g.homme)}</td>
      <td className={td}>{genderCell(g.indetermine)}</td>
      <td className={`${td} text-[16px] font-bold`}>{fmtNum(g.total)}</td>
      {HORIZONS.map((h) => (
        <td key={h} className={td}>
          <ForecastValue unit={unit} horizon={h} />
        </td>
      ))}
      <td className={td}>{fmtNum(op.en_service)}</td>
      <td className={td}>{fmtNum(op.reactivables)}</td>
      <td className={td}>{fmtNum(op.supplementaires)}</td>
      <td className={td}>{fmtNum(unit.reserves_crise_sse)}</td>
      <td className="px-2 py-3 align-top">
        <TensionChip level={unit.tension.niveau} rate={unit.tension.taux_disponibilite} />
      </td>
      <td className="px-2 py-3 align-top">
        <Freshness unit={unit} />
      </td>
      <td className="px-2 py-3 align-top">
        <RorId unit={unit} />
      </td>
    </tr>
  );
}

function UnitCard({ unit }: { unit: RorUnite }) {
  const g = unit.disponibles_par_genre;
  const op = unit.operationnel;
  return (
    <li className="rounded-xl border border-line px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <UnitName unit={unit} />
        </div>
        <TensionChip level={unit.tension.niveau} rate={unit.tension.taux_disponibilite} />
      </div>
      <dl className="mt-3 grid grid-cols-4 gap-2 text-center">
        {(
          [
            ["F", g.femme],
            ["H", g.homme],
            ["Ind.", g.indetermine],
            ["Total", g.total]
          ] as const
        ).map(([label, n]) => (
          <div key={label} className="rounded-lg bg-sky px-1 py-1.5">
            <dt className="text-[12px] text-ink-faint">{label}</dt>
            <dd className={`num ${label === "Total" ? "text-[18px] font-bold" : ""}`}>{genderCell(n)}</dd>
          </div>
        ))}
      </dl>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-center">
        {HORIZONS.map((h) => (
          <div key={h} className="rounded-lg border border-line px-1 py-1.5">
            <dt className="text-[12px] text-ink-faint">{h}</dt>
            <dd>
              <ForecastValue unit={unit} horizon={h} />
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[13px] text-ink-soft">
        En service {op.en_service} · réactivables {op.reactivables} · suppl. {op.supplementaires} · crise-SSE{" "}
        {unit.reserves_crise_sse}
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <Freshness unit={unit} />
        <RorId unit={unit} />
      </div>
    </li>
  );
}

// --- simulated send ---------------------------------------------------------------------------

function OutboxSection() {
  const client = useQueryClient();
  const history = useQuery({ queryKey: ["ror-outbox"], queryFn: () => api<RorOutboxEntry[]>("/ror/outbox") });
  const prepare = useMutation({
    mutationFn: () => api<RorOutboxEntry>("/ror/outbox", { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["ror-outbox"] })
  });
  const last = prepare.data;
  return (
    <section className="panel mt-8 px-6 py-5" aria-labelledby="ror-outbox">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 id="ror-outbox">Envois au ROR (simulation)</h2>
          <p className="mt-1 text-[14px] text-ink-soft">
            Fige l'export actuel avec son empreinte SHA-256, comme il partirait vers le ROR. Rien n'est transmis tant
            que le raccordement n'est pas habilité.
          </p>
        </div>
        <button className="btn-primary" onClick={() => prepare.mutate()} disabled={prepare.isPending}>
          <Send className="h-4 w-4" aria-hidden /> Préparer un envoi (simulation)
        </button>
      </div>
      {prepare.error && <ErrorNote error={prepare.error} />}
      {last && (
        <p role="status" className="mt-3 rounded-xl bg-lagoon-soft px-4 py-2 text-[14px]">
          Envoi n° {last.id} préparé ({plural(last.unites, "unité", "unités")}), non transmis. Empreinte{" "}
          <code className="break-all">{last.empreinte_sha256}</code>
        </p>
      )}
      {history.data && history.data.length > 0 ? (
        <ol className="mt-4 divide-y divide-line text-[14px]" aria-label="Historique des envois simulés">
          {history.data.map((h) => (
            <li key={h.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
              <span>
                <strong>n° {h.id}</strong> · {fmtDateTime(h.cree_le)} · {plural(h.unites, "unité", "unités")}
                {h.prepare_par && ` · ${h.prepare_par}`}
              </span>
              <span className="flex items-center gap-2">
                <code className="text-[12px] text-ink-faint" title={h.empreinte_sha256}>
                  {h.empreinte_sha256.slice(0, 12)}…
                </code>
                <span className="chip bg-sky text-ink-soft">simulé</span>
              </span>
            </li>
          ))}
        </ol>
      ) : (
        history.data && <p className="mt-4 text-[14px] text-ink-faint">Aucun envoi préparé pour l'instant.</p>
      )}
    </section>
  );
}

// --- ORU --------------------------------------------------------------------------------------

function OruSection() {
  const today = new Date();
  const [end, setEnd] = useState(isoDay(today));
  const [start, setStart] = useState(isoDay(new Date(today.getTime() - 29 * 86_400_000)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function download(format: "csv" | "json") {
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams({ start, end, format });
      const name = `oru-indicateurs-${start}-${end}.${format}`;
      if (format === "csv") {
        const text = await api<string>(`/oru/indicators?${params.toString()}`);
        saveFile(name, text, "text/csv;charset=utf-8");
      } else {
        const body = await api<unknown>(`/oru/indicators?${params.toString()}`);
        saveFile(name, JSON.stringify(body, null, 2), "application/json");
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel mt-8 px-6 py-5" aria-labelledby="oru">
      <h2 id="oru">Indicateurs pour l'ORU</h2>
      <p className="mt-1 max-w-3xl text-[14px] text-ink-soft">
        Par site et par jour : passages aux urgences, présents, en attente de lit, lits brancards à 10 h (calculés ou
        déclarés), hébergés, unités en tension, HET et Plan blanc, prévision des lits brancards. Jusqu'à 366 jours, en
        CSV (séparateur point-virgule, pour un tableur) ou en JSON.
      </p>
      <form
        className="mt-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void download("csv");
        }}
      >
        <label className="field">
          Du
          <input className="input" type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label className="field">
          Au
          <input className="input" type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} required />
        </label>
        <button className="btn-primary" type="submit" disabled={busy}>
          <Download className="h-4 w-4" aria-hidden /> CSV
        </button>
        <button className="btn-quiet" type="button" disabled={busy} onClick={() => void download("json")}>
          <Download className="h-4 w-4" aria-hidden /> JSON
        </button>
      </form>
      {error !== null && <ErrorNote error={error} />}
    </section>
  );
}
