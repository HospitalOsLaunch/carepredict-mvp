import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { Empty, ErrorNote } from "../components/common";
import { Loading, TableSkeleton } from "../components/skeletons";
import { plural } from "../lib/format";
import { Badge, type BadgeProps } from "@/components/ui/badge";

type Rating = "bon" | "a_ameliorer" | "mauvais";
interface VitalRow {
  page: string;
  metric: string;
  p75: number;
  samples: number;
  rating: Rating;
}
interface VitalsSummary {
  days: number;
  samples: number;
  rows: VitalRow[];
}

const SCREEN: Record<string, string> = {
  "/": "Connexion",
  "/demandes": "Demandes",
  "/demandes/:id": "Détail d'une demande",
  "/lits": "Lits et sorties",
  "/plan-des-lits": "Plan des lits",
  "/urgences": "Urgences et tension",
  "/prevision": "Prévision",
  "/charge": "Charge en soins",
  "/groupe": "Vue groupe",
  "/indicateurs": "Indicateurs pilote",
  "/ror": "Remontée ROR",
  "/agents": "Agents",
  "/agents/passages/:id": "Player d'un passage",
  "/imports": "Imports",
  "/parametres": "Paramètres",
  autre: "Autre"
};

/** The three Core Web Vitals, in the words of the people who live them. */
const METRICS: Array<{ id: string; name: string; what: string; show: (v: number) => string }> = [
  { id: "LCP", name: "Affichage", what: "le contenu principal est là (LCP)", show: (v) => `${(v / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s` },
  { id: "INP", name: "Réaction", what: "réponse à un clic ou à une frappe (INP)", show: (v) => `${Math.round(v)} ms` },
  { id: "CLS", name: "Stabilité", what: "la page ne saute pas (CLS)", show: (v) => v.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) }
];

const TONE: Record<Rating, { tone: BadgeProps["tone"]; text: string }> = {
  bon: { tone: "lagoon", text: "bon" },
  a_ameliorer: { tone: "sun", text: "à améliorer" },
  mauvais: { tone: "coral", text: "mauvais" }
};

const DEVICES = [
  { value: "", label: "Tous les appareils" },
  { value: "mobile", label: "Téléphones" },
  { value: "tablette", label: "Tablettes" },
  { value: "bureau", label: "Postes de bureau" }
];

/**
 * How fast HospitalOS felt to the teams, measured in their browsers (règle 30) and kept by
 * the group's own API: the 75th percentile of each screen over 28 days — three visits in
 * four were at least this fast.
 */
export function VitalsTab() {
  const [device, setDevice] = useState("");
  const summary = useQuery({
    queryKey: ["web-vitals", device],
    queryFn: () => api<VitalsSummary>(`/web-vitals?days=28${device ? `&device=${device}` : ""}`)
  });
  const rows = summary.data?.rows ?? [];
  const pages = [...new Set(rows.map((r) => r.page))].sort((a, b) => (SCREEN[a] ?? a).localeCompare(SCREEN[b] ?? b, "fr"));
  const cell = (page: string, metric: string) => rows.find((r) => r.page === page && r.metric === metric);

  return (
    <section className="space-y-4" aria-labelledby="vitesse">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-3xl">
          <h2 id="vitesse">Vitesse ressentie par les équipes</h2>
          <p className="mt-1 text-[15px] text-ink-soft">
            Mesurée dans les navigateurs des équipes, gardée par HospitalOS seulement : ni nom, ni poste, ni adresse. Pour chaque
            écran, la valeur que trois visites sur quatre ne dépassent pas, sur les 28 derniers jours.
          </p>
        </div>
        <label className="field">
          <span className="sr-only">Appareils</span>
          <select className="input mt-0" value={device} onChange={(e) => setDevice(e.target.value)}>
            {DEVICES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {summary.isLoading ? (
        <Loading label="Chargement des mesures">
          <TableSkeleton rows={5} rowHeight="h-[52px]" />
        </Loading>
      ) : summary.error ? (
        <ErrorNote error={summary.error} />
      ) : pages.length === 0 ? (
        <Empty title="Pas encore de mesure">Elles arrivent au fil des visites, quand un onglet est fermé ou mis de côté.</Empty>
      ) : (
        <div className="panel relative overflow-x-auto">
          <table className="w-full min-w-[640px] text-[15px]">
            <caption className="sr-only">Vitesse ressentie par écran, 75e centile sur 28 jours</caption>
            <thead>
              <tr className="border-b border-line text-left text-[13px] text-ink-faint">
                <th className="px-5 py-3 font-normal">Écran</th>
                {METRICS.map((m) => (
                  <th key={m.id} className="px-3 py-3 font-normal">
                    <span className="font-bold text-ink-soft">{m.name}</span>
                    <span className="block">{m.what}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pages.map((page) => (
                <tr key={page} className="border-b border-line last:border-0">
                  <th scope="row" className="px-5 py-3 text-left font-bold">
                    {SCREEN[page] ?? page}
                  </th>
                  {METRICS.map((m) => {
                    const c = cell(page, m.id);
                    return (
                      <td key={m.id} className="px-3 py-3">
                        {c ? (
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="num font-bold">{m.show(c.p75)}</span>
                            <Badge tone={TONE[c.rating].tone}>{TONE[c.rating].text}</Badge>
                            <span className="text-[13px] text-ink-faint">{plural(c.samples, "visite", "visites")}</span>
                          </span>
                        ) : (
                          <span className="text-ink-faint">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
