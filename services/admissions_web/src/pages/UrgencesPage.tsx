import { AlertTriangle, CheckCircle2, CircleDashed, Info, Siren } from "lucide-react";
import { lazy, Suspense, useState, type FormEvent } from "react";

import type { EdCensus, HetCriterion, HetLevel, TensionDeclaration, TensionStatus } from "../api/types_liscop";
import { useAuth } from "../auth";
import { LiveNumber } from "../components/live";
import { ErrorNote, Modal, PageHeader } from "../components/common";
import { fmtDateTime, fmtHours, fmtNum, fmtPct } from "../lib/format";
import { useDeclarations, useEdCensus, useEdWrite, useSnapshots, useTensionStatus } from "../lib/liscop";
import { TensionChip } from "./RorPage";
import { ChartSkeleton, KpiRowSkeleton, Loading, PanelSkeleton } from "../components/skeletons";

// recharts is heavy: loaded with the chart only, as for the other chart pages.
const BoardingChart = lazy(() => import("./UrgencesChart").then((m) => ({ default: m.BoardingChart })));

const AID_STYLE: Record<HetLevel, { panel: string; icon: typeof Siren }> = {
  aucun: { panel: "bg-lagoon-soft text-lagoon-dark", icon: CheckCircle2 },
  vigilance: { panel: "bg-sun-soft text-ink", icon: AlertTriangle },
  het_suggere: { panel: "bg-coral-soft text-coral-dark", icon: Siren }
};
const KINDS = { het: "Hôpital en tension", plan_blanc: "Plan blanc" } as const;
const LEVELS: Record<keyof typeof KINDS, Record<string, string>> = {
  het: { niveau_1: "Niveau 1", niveau_2: "Niveau 2" },
  plan_blanc: { alerte: "Mise en alerte", declenche: "Déclenché" }
};

const LEAD =
  "Le recensement des urgences calculé à partir des mouvements patients, l'indicateur « lits brancards à 10 h » et l'aide à la déclaration d'hôpital en tension.";

export function UrgencesPage() {
  const [siteId, setSiteId] = useState<number | null>(null);
  const census = useEdCensus(siteId);
  const status = useTensionStatus(siteId);

  if (census.isLoading)
    return (
      <>
        <PageHeader title="Urgences et tension" lead={LEAD} />
        <Loading label="Chargement du recensement des urgences">
          <KpiRowSkeleton height="h-[164px]" />
          <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <ChartSkeleton />
            <PanelSkeleton lines={6} height="h-[449px]" />
          </div>
        </Loading>
      </>
    );
  if (census.error) return <ErrorNote error={census.error} />;
  const c = census.data;
  if (!c) return null;

  return (
    <>
      <PageHeader
        title="Urgences et tension"
        lead={LEAD}
        actions={
          c.ed_sites.length > 1 ? (
            <label className="field">
              <span className="sr-only">Service d'urgences</span>
              <select className="input mt-0" value={c.site_id} onChange={(e) => setSiteId(Number(e.target.value))}>
                {c.ed_sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          ) : undefined
        }
      />
      <CensusCards census={c} />
      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Suspense fallback={<ChartSkeleton />}>
          <BoardingChart siteId={c.site_id} />
        </Suspense>
        {status.data ? <AidCard status={status.data} boardingIsYesterday={!c.today_10h.reached} /> : status.error ? (
          <ErrorNote error={status.error} />
        ) : (
          <Loading label="Chargement de l'aide à la déclaration">
            <PanelSkeleton lines={6} height="h-[449px]" />
          </Loading>
        )}
      </div>
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Declarations status={status.data} siteId={c.site_id} siteName={c.site_name} />
        <ManualSnapshot census={c} />
      </div>
      {status.data && <UnitsTension status={status.data} />}
      <details className="panel mt-6 px-6 py-5">
        <summary className="cursor-pointer font-display text-lg font-semibold">D'où viennent ces nombres</summary>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-ink-soft">
          {c.definitions.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      </details>
    </>
  );
}

function Card({ value, label, note, tone, scope }: { value: number; label: string; note?: string; tone: string; scope: number }) {
  return (
    <div className={`panel relative overflow-hidden px-5 py-4 before:absolute before:inset-x-0 before:top-0 before:h-1 ${tone}`}>
      <p className="num font-display text-4xl font-bold">
        <LiveNumber value={value} scope={String(scope)} />
      </p>
      <p className="mt-1 text-[15px] font-bold">{label}</p>
      {note && <p className="mt-1 text-[13px] text-ink-faint">{note}</p>}
    </div>
  );
}

function CensusCards({ census }: { census: EdCensus }) {
  const { now, today_10h: t } = census;
  const boardingNote = t.source === "declaration"
    ? `Déclaré à la main (calcul : ${t.computed_boarding})`
    : t.reached
      ? "Calculé à 10:00 à partir des mouvements"
      : "Provisoire : 10:00 n'est pas encore passé";
  return (
    <section aria-label={`Recensement, ${census.site_name}`} className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      <Card scope={census.site_id} value={now.present} label="présents aux urgences" note={`Au ${fmtDateTime(now.at)}`} tone="before:bg-violet" />
      <Card
        scope={census.site_id}
        value={now.waiting_bed}
        label="en attente de lit"
        note={now.longest_wait_hours === null ? "Personne n'attend de lit" : `Attente la plus longue : ${fmtHours(now.longest_wait_hours)}`}
        tone="before:bg-sun"
      />
      <Card scope={census.site_id} value={t.boarding} label="lits brancards à 10 h aujourd'hui" note={boardingNote} tone="before:bg-coral" />
      <Card
        scope={census.site_id}
        value={now.hosted_elsewhere}
        label="hébergés hors de leur discipline"
        note="Hospitalisés depuis les urgences, encore présents"
        tone="before:bg-lagoon"
      />
    </section>
  );
}

function criterionValue(c: HetCriterion): string {
  if (c.value === null) return "inconnu";
  if (c.code === "critical_units_share") return `${fmtPct(c.value)} (seuil ${fmtPct(c.threshold)})`;
  if (c.code === "longest_wait_hours") return `${fmtNum(c.value, 1)} h (seuil ${fmtNum(c.threshold)} h)`;
  return `${fmtNum(c.value)} (seuil ${fmtNum(c.threshold)})`;
}

function AidCard({ status, boardingIsYesterday }: { status: TensionStatus; boardingIsYesterday: boolean }) {
  const aid = status.aid;
  if (!aid) return null;
  const style = AID_STYLE[aid.level];
  const Icon = style.icon;
  return (
    <section className="panel overflow-hidden" aria-labelledby="aid-title">
      <div className={`flex items-center gap-3 px-5 py-4 ${style.panel}`}>
        <Icon className="h-7 w-7 shrink-0" aria-hidden />
        <div>
          <h2 id="aid-title" className="text-[15px] font-bold uppercase tracking-wide opacity-80">
            Aide à la décision HET
          </h2>
          <p className="font-display text-2xl font-bold">{aid.label}</p>
        </div>
      </div>
      <ul className="divide-y divide-line px-5">
        {aid.criteria.map((c) => (
          <li key={c.code} className="flex items-start gap-3 py-3">
            {c.triggered ? (
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-coral" aria-label="critère atteint" />
            ) : (
              <CircleDashed className="mt-0.5 h-5 w-5 shrink-0 text-ink-faint" aria-label="critère non atteint" />
            )}
            <div>
              <p className={c.triggered ? "font-bold" : ""}>{c.label}</p>
              <p className="text-[14px] text-ink-soft">{criterionValue(c)}</p>
              {c.code === "boarding_10h" && boardingIsYesterday && (
                <p className="text-[13px] text-ink-faint">relevé d'hier : 10 h n'est pas encore passé</p>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p role="note" className="flex items-start gap-2 border-t border-line bg-sky px-5 py-3 text-[14px] text-ink-soft">
        <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        {aid.notice}
      </p>
    </section>
  );
}

function declarationLabel(d: TensionDeclaration): string {
  return `${KINDS[d.kind]} · ${LEVELS[d.kind][d.level] ?? d.level}`;
}

function Declarations({ status, siteId, siteName }: { status?: TensionStatus; siteId: number; siteName: string }) {
  const { canWrite, user } = useAuth();
  const history = useDeclarations();
  const end = useEdWrite<{ ended_at: string }>("/tension/declarations", "PATCH");
  const [open, setOpen] = useState(false);
  const [ending, setEnding] = useState<TensionDeclaration | null>(null);
  const active = status?.active_declarations ?? [];
  const past = (history.data ?? []).filter((d) => d.ended_at !== null).slice(0, 5);
  return (
    <section className="panel px-5 py-4" aria-labelledby="decl-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="decl-title">Déclarations HET et Plan blanc</h2>
        {canWrite && (
          <button type="button" className="btn-primary" onClick={() => setOpen(true)}>
            Enregistrer une déclaration
          </button>
        )}
      </div>
      <p className="mt-1 text-[14px] text-ink-soft">
        Décidées par la direction, enregistrées par la cellule de gestion des lits ou un administrateur.
      </p>
      <h3 className="mt-4">En cours</h3>
      {active.length === 0 ? (
        <p className="mt-1 text-ink-faint">Aucune déclaration en cours.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {active.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-coral-soft px-3 py-2">
              <span>
                <strong>{declarationLabel(d)}</strong>
                <span className="text-[14px] text-ink-soft">
                  {" "}
                  · depuis le {fmtDateTime(d.started_at)} · {d.site_id === null ? "établissement" : siteName} · {d.declared_by}
                </span>
              </span>
              {canWrite && (
                <button type="button" className="btn-quiet py-1" onClick={() => setEnding(d)}>
                  Clôturer
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {past.length > 0 && (
        <>
          <h3 className="mt-4">Historique récent</h3>
          <ul className="mt-2 space-y-1 text-[14px] text-ink-soft">
            {past.map((d) => (
              <li key={d.id}>
                {declarationLabel(d)} · du {fmtDateTime(d.started_at)} au {fmtDateTime(d.ended_at)}
              </li>
            ))}
          </ul>
        </>
      )}
      {open && (
        <DeclarationForm
          siteId={siteId}
          siteName={siteName}
          establishmentAllowed={user?.site_id == null}
          onClose={() => setOpen(false)}
        />
      )}
      {ending && (
        <Modal title="Clôturer la déclaration" onClose={() => setEnding(null)}>
          <p>
            Clôturer « {declarationLabel(ending)} » maintenant ? La fin est enregistrée à l'heure actuelle, avec votre nom.
          </p>
          {end.error && <ErrorNote error={end.error} />}
          <div className="mt-5 flex gap-2">
            <button
              type="button"
              className="btn-danger"
              disabled={end.isPending}
              onClick={() =>
                end.mutate({ id: ending.id, body: { ended_at: new Date().toISOString() } }, { onSuccess: () => setEnding(null) })
              }
            >
              Confirmer la clôture
            </button>
            <button type="button" className="btn-quiet" onClick={() => setEnding(null)}>
              Annuler
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}

function DeclarationForm({
  siteId,
  siteName,
  establishmentAllowed,
  onClose
}: {
  siteId: number;
  siteName: string;
  establishmentAllowed: boolean;
  onClose: () => void;
}) {
  const create = useEdWrite<{ site_id: number | null; kind: string; level: string; comment?: string }>(
    "/tension/declarations"
  );
  const [kind, setKind] = useState<keyof typeof KINDS>("het");
  const [level, setLevel] = useState("niveau_1");
  const [scope, setScope] = useState<"site" | "etablissement">("site");
  const [comment, setComment] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      {
        body: {
          site_id: scope === "site" ? siteId : null,
          kind,
          level,
          ...(comment.trim() ? { comment: comment.trim() } : {})
        }
      },
      { onSuccess: onClose }
    );
  };
  return (
    <Modal title="Enregistrer une déclaration" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <p className="rounded-xl bg-sun-soft px-3 py-2 text-[14px]">
          Vous enregistrez une décision prise par la direction. HospitalOS ne déclare jamais à sa place.
        </p>
        <label className="field">
          Type
          <select
            className="input"
            value={kind}
            onChange={(e) => {
              const k = e.target.value as keyof typeof KINDS;
              setKind(k);
              setLevel(Object.keys(LEVELS[k])[0]);
            }}
          >
            {Object.entries(KINDS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Niveau
          <select className="input" value={level} onChange={(e) => setLevel(e.target.value)}>
            {Object.entries(LEVELS[kind]).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Portée
          <select className="input" value={scope} onChange={(e) => setScope(e.target.value as "site" | "etablissement")}>
            <option value="site">{siteName}</option>
            {establishmentAllowed && <option value="etablissement">Tout l'établissement</option>}
          </select>
        </label>
        <label className="field">
          Commentaire (facultatif)
          <textarea className="input" rows={3} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} />
        </label>
        {create.error && <ErrorNote error={create.error} />}
        <div className="flex gap-2">
          <button type="submit" className="btn-primary" disabled={create.isPending}>
            Enregistrer
          </button>
          <button type="button" className="btn-quiet" onClick={onClose}>
            Annuler
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ManualSnapshot({ census }: { census: EdCensus }) {
  const { canWrite } = useAuth();
  const snapshots = useSnapshots(census.site_id);
  const create = useEdWrite<Record<string, unknown>>("/ed/snapshots");
  const [values, setValues] = useState({ present: "", waiting_bed: "", boarding: "", hosted_elsewhere: "" });
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState(false);
  const fields: [keyof typeof values, string][] = [
    ["present", "Présents"],
    ["waiting_bed", "En attente de lit"],
    ["boarding", "Lits brancards"],
    ["hosted_elsewhere", "Hébergés"]
  ];
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    create.mutate(
      {
        body: {
          site_id: census.site_id,
          present: Number(values.present),
          waiting_bed: Number(values.waiting_bed),
          boarding: Number(values.boarding),
          hosted_elsewhere: Number(values.hosted_elsewhere || 0),
          ...(comment.trim() ? { comment: comment.trim() } : {})
        }
      },
      {
        onSuccess: () => {
          setSaved(true);
          setValues({ present: "", waiting_bed: "", boarding: "", hosted_elsewhere: "" });
          setComment("");
        }
      }
    );
  };
  return (
    <section className="panel px-5 py-4" aria-labelledby="snapshot-title">
      <h2 id="snapshot-title">Déclaration manuelle du recensement</h2>
      <p className="mt-1 text-[14px] text-ink-soft">
        En repli, quand le flux des urgences manque ou se trompe : la déclaration du jour remplace le calcul pour ce jour,
        qui reste affiché à côté.
      </p>
      {canWrite ? (
        <form onSubmit={submit} className="mt-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {fields.map(([key, label]) => (
              <label key={key} className="field">
                {label}
                <input
                  className="input num"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={2000}
                  required={key !== "hosted_elsewhere"}
                  value={values[key]}
                  onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                />
              </label>
            ))}
          </div>
          <label className="field mt-3">
            Commentaire (facultatif)
            <input className="input" maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button type="submit" className="btn-sun" disabled={create.isPending}>
              Déclarer maintenant
            </button>
            {saved && (
              <span role="status" className="text-[14px] font-bold text-lagoon-dark">
                Déclaration enregistrée.
              </span>
            )}
          </div>
          {create.error && (
            <div className="mt-3">
              <ErrorNote error={create.error} />
            </div>
          )}
        </form>
      ) : (
        <p className="mt-3 text-ink-faint">Lecture seule pour votre rôle.</p>
      )}
      {(snapshots.data?.length ?? 0) > 0 && (
        <>
          <h3 className="mt-5">Dernières déclarations</h3>
          <ul className="mt-2 space-y-1 text-[14px] text-ink-soft">
            {snapshots.data?.slice(0, 5).map((s) => (
              <li key={s.id}>
                {fmtDateTime(s.at)} · {s.present} présents, {s.waiting_bed} en attente, {s.boarding} brancards
                {s.comment && <> · « {s.comment} »</>}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function UnitsTension({ status }: { status: TensionStatus }) {
  const order = { critique: 0, tension: 1, normal: 2 };
  const units = [...status.units].sort((a, b) => order[a.tension.level] - order[b.tension.level] || a.label.localeCompare(b.label));
  return (
    <section className="panel mt-6 overflow-x-auto px-2 py-3 sm:px-4" aria-labelledby="units-title">
      <h2 id="units-title" className="px-2 pb-3">
        Tension des unités
      </h2>
      <table className="w-full min-w-[560px] text-[14px]">
        <caption className="sr-only">Niveau de tension de chaque unité, du plus critique au plus calme.</caption>
        <thead>
          <tr className="border-b border-line text-[12px] text-ink-faint">
            <th scope="col" className="px-2 py-2 text-left font-normal">Unité</th>
            <th scope="col" className="px-2 py-2 text-left font-normal">Site</th>
            <th scope="col" className="px-2 py-2 text-right font-normal">Utilisables / installés</th>
            <th scope="col" className="px-2 py-2 text-right font-normal">Taux</th>
            <th scope="col" className="px-2 py-2 text-left font-normal">Niveau</th>
          </tr>
        </thead>
        <tbody>
          {units.map((u) => (
            <tr key={u.pool_id} className="border-b border-line last:border-0">
              <th scope="row" className="px-2 py-2 text-left font-bold">{u.label}</th>
              <td className="px-2 py-2 text-ink-soft">{u.site_name}</td>
              <td className="num px-2 py-2 text-right">
                {u.usable} / {u.installed}
              </td>
              <td className="num px-2 py-2 text-right">{fmtPct(u.tension.availability_rate)}</td>
              <td className="px-2 py-2">
                <TensionChip level={u.tension.level} rate={u.tension.availability_rate} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-2 pt-3 text-[13px] text-ink-faint">
        Légende LISCOP : normal si au moins 20 % des lits installés sont utilisables, critique à 0, tension entre les deux.
      </p>
    </section>
  );
}
