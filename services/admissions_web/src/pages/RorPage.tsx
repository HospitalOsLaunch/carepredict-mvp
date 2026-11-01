import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Download, FlaskConical, XCircle } from "lucide-react";

import { api } from "../api/client";
import type { RorExport, RorTensionLevel, RorUnite } from "../api/types";
import { ErrorNote, PageHeader, Spinner } from "../components/ui";
import { fmtDateTime, fmtHours, fmtNum, fmtPct, fmtShort, plural } from "../lib/format";

const TENSION: Record<RorTensionLevel, { label: string; chip: string; icon: typeof CheckCircle2 }> = {
  normal: { label: "Normal", chip: "bg-lagoon-soft text-lagoon-dark", icon: CheckCircle2 },
  tension: { label: "Tension", chip: "bg-sun-soft text-ink", icon: AlertCircle },
  critique: { label: "Critique", chip: "bg-coral-soft text-coral-dark", icon: XCircle }
};

function useRorExport() {
  return useQuery({ queryKey: ["ror-export"], queryFn: () => api<RorExport>("/ror/export") });
}

function count(unit: RorUnite, code: string): number | null {
  return unit.capacites.find((c) => c.statut.code === code)?.nombre ?? null;
}

function hoursBetween(later: string, earlier: string | null): number | null {
  if (!earlier) return null;
  return Math.max(0, (new Date(later).getTime() - new Date(earlier).getTime()) / 3_600_000);
}

function download(data: RorExport) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `ror-export-maquette-${data.date_situation}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export function TensionChip({ level, rate }: { level: RorTensionLevel; rate: number | null }) {
  const t = TENSION[level];
  const Icon = t.icon;
  return (
    <span className={`chip ${t.chip}`} title={rate === null ? undefined : `${fmtPct(rate)} de lits disponibles`}>
      <Icon className="h-3.5 w-3.5" aria-hidden /> {t.label}
    </span>
  );
}

export function RorPage() {
  const query = useRorExport();
  const data = query.data;

  if (query.isLoading) return <Spinner />;
  if (query.error) return <ErrorNote error={query.error} />;
  if (!data) return null;

  const units = data.unites;
  const available = units.reduce((acc, u) => acc + (count(u, "02") ?? 0), 0);
  const strained = units.filter((u) => u.tension.niveau !== "normal").length;
  const toLink = units.filter((u) => !u.identifiant_unite_ror).length;
  const ages = units
    .map((u) => hoursBetween(data.genere_le, u.dernier_mouvement_saisi))
    .filter((h): h is number => h !== null);
  const freshest = ages.length ? Math.min(...ages) : null;
  const stalest = ages.length ? Math.max(...ages) : null;
  const horizons = units[0]?.previsionnel.map((p) => p.echeance) ?? [];

  return (
    <>
      <PageHeader
        title="Remontée vers le ROR"
        lead={
          <>
            Ce que HospitalOS peut transmettre, sans aucune saisie supplémentaire, au ROR national et aux outils
            régionaux qui le lisent, comme LISCOP. Les chiffres sont recalculés à chaque sortie, entrée ou fermeture de
            lits enregistrée.
          </>
        }
        actions={
          <button className="btn-primary" onClick={() => download(data)}>
            <Download className="h-4 w-4" aria-hidden /> Télécharger le JSON
          </button>
        }
      />

      <p role="note" className="mb-6 flex max-w-4xl items-start gap-3 rounded-panel bg-sun-soft px-5 py-4 text-[15px]">
        <FlaskConical className="mt-0.5 h-5 w-5 shrink-0 text-ink" aria-hidden />
        <span>{data.avertissement}</span>
      </p>

      <dl className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi value={fmtNum(available)} label="lits disponibles maintenant, au sens du ROR" />
        <Kpi
          value={fmtNum(strained)}
          label={`${strained >= 2 ? "unités" : "unité"} en tension ou critique sur ${units.length}`}
          tone={strained ? "sun" : undefined}
        />
        <Kpi
          value={freshest === null ? "—" : `il y a ${fmtHours(freshest)}`}
          label={
            stalest === null
              ? "aucun mouvement saisi"
              : `dernier mouvement saisi ; l'unité la moins récente : il y a ${fmtHours(stalest)}`
          }
        />
        <Kpi
          value={fmtNum(toLink)}
          label={`${toLink >= 2 ? "unités" : "unité"} à rattacher à leur identifiant ROR`}
          tone={toLink ? "coral" : undefined}
        />
      </dl>

      <section className="panel overflow-x-auto px-2 py-3 sm:px-4" aria-labelledby="ror-table">
        <div className="flex flex-wrap items-baseline justify-between gap-3 px-2 pb-3">
          <h2 id="ror-table">Capacité par unité, situation du {fmtShort(data.date_situation)}</h2>
          <p className="text-[13px] text-ink-faint">Calculé le {fmtDateTime(data.genere_le)}</p>
        </div>
        <table className="w-full min-w-[980px] text-[14px]">
          <caption className="sr-only">
            Pour chaque unité, les lits par statut du ROR, le niveau de tension, les lits disponibles attendus aux
            échéances suivantes et l'ancienneté du dernier mouvement saisi.
          </caption>
          <thead>
            <tr className="border-b border-line text-[12px] text-ink-faint">
              <th scope="col" className="px-2 py-2 text-left font-normal">
                Unité
              </th>
              <th scope="col" className="px-2 py-2 text-right font-normal">
                Installés
              </th>
              <th scope="col" className="px-2 py-2 text-right font-normal">
                Fermés
              </th>
              <th scope="col" className="px-2 py-2 text-right font-normal">
                Occupés
              </th>
              <th scope="col" className="px-2 py-2 text-right font-normal">
                Réservés&nbsp;24&nbsp;h
              </th>
              <th scope="col" className="px-2 py-2 text-right font-normal">
                Disponibles
              </th>
              <th scope="col" className="px-2 py-2 text-left font-normal">
                Tension
              </th>
              {horizons.map((h) => (
                <th key={h} scope="col" className="px-2 py-2 text-right font-normal">
                  Prévu {h}
                </th>
              ))}
              <th scope="col" className="px-2 py-2 text-right font-normal">
                Dernier mouvement
              </th>
            </tr>
          </thead>
          <tbody>
            {units.map((u) => (
              <UnitRow key={`${u.site_id}-${u.mention}`} unit={u} generatedAt={data.genere_le} />
            ))}
          </tbody>
        </table>
        <p className="flex flex-wrap gap-x-4 gap-y-1 px-2 pt-3 text-[13px] text-ink-faint">
          <span>Tension : normal si au moins 20 % des lits installés sont disponibles, critique à 0.</span>
          <span>Prévu : lits libres attendus, entre parenthèses la fourchette à 80 %.</span>
        </p>
      </section>

      <section className="mt-10 grid gap-6 lg:grid-cols-2" aria-label="Avant un vrai envoi">
        <div className="panel px-6 py-5">
          <h2>À compléter avant un envoi réel</h2>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-ink-soft">
            {data.non_suivi_dans_le_pilote.map((item) => (
              <li key={item}>{item}</li>
            ))}
            <li>Habilitation et raccordement au flux d'alimentation du ROR national, avec l'ANS et l'ARS.</li>
          </ul>
        </div>
        <div className="panel px-6 py-5">
          <h2>Hypothèses de calcul</h2>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-ink-soft">
            {data.hypotheses.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="mt-4 text-[13px] text-ink-faint">
            Référentiels :{" "}
            {data.referentiels.map((r, i) => (
              <span key={r.nom}>
                {i > 0 && ", "}
                <a className="font-bold text-violet hover:underline" href={r.url} target="_blank" rel="noreferrer">
                  {r.nom}
                </a>
              </span>
            ))}
            .
          </p>
        </div>
      </section>

      <details className="panel mt-6 px-6 py-5">
        <summary className="cursor-pointer font-display text-lg font-semibold">
          Aperçu du message transmis ({plural(units.length, "unité", "unités")})
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

function UnitRow({ unit, generatedAt }: { unit: RorUnite; generatedAt: string }) {
  const closed = count(unit, "05") ?? 0;
  const closure = unit.fermetures[0];
  const age = hoursBetween(generatedAt, unit.dernier_mouvement_saisi);
  return (
    <tr className="border-b border-line last:border-0">
      <th scope="row" className="px-2 py-3 text-left font-normal">
        <span className="block font-bold">{unit.libelle_unite}</span>
        <span className="block text-[13px] text-ink-faint">
          {unit.etablissement}
          {unit.finess_geographique ? ` · FINESS ${unit.finess_geographique}` : ""}
          {unit.identifiant_unite_ror ? "" : " · identifiant ROR à rattacher"}
        </span>
      </th>
      <td className="num px-2 py-3 text-right">{count(unit, "01")}</td>
      <td className="num px-2 py-3 text-right">
        {closed}
        {closure && <span className="block text-[12px] text-ink-faint">{closure.type_fermeture.libelle.toLowerCase()}</span>}
      </td>
      <td className="num px-2 py-3 text-right">{count(unit, "03")}</td>
      <td className="num px-2 py-3 text-right">{count(unit, "04")}</td>
      <td className="num px-2 py-3 text-right text-[16px] font-bold">{count(unit, "02")}</td>
      <td className="px-2 py-3">
        <TensionChip level={unit.tension.niveau} rate={unit.tension.taux_disponibilite} />
      </td>
      {unit.previsionnel.map((p) => (
        <td key={p.echeance} className="num px-2 py-3 text-right">
          <span className="font-bold">{fmtNum(p.lits_disponibles_attendus)}</span>
          <span className="block text-[12px] text-ink-faint">
            ({p.fourchette_80[0]}–{p.fourchette_80[1]})
          </span>
        </td>
      ))}
      <td className="num px-2 py-3 text-right text-ink-soft">{age === null ? "—" : `il y a ${fmtHours(age)}`}</td>
    </tr>
  );
}
