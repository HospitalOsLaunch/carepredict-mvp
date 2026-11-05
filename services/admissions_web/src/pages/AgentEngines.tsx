import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, CircleSlash, Lock, ShieldCheck, ShieldQuestion, Wallet, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { api } from "../api/client";
import type { AgentPolicy, AgentStatus, EnginePolicy } from "../api/types";
import type { WorkerOut } from "../api/types_agent";
import { ErrorNote, Modal } from "../components/common";
import { Loading, PanelSkeleton } from "../components/skeletons";
import {
  availability,
  BASIS,
  changes,
  ENGINE_ORDER,
  KIND,
  pct,
  presetOf,
  PRESETS,
  readiness,
  routeSentence,
  SETUP,
  short,
  TASKS,
  usd,
  type Preset
} from "../lib/engines";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Status = Pick<AgentStatus, "policy" | "calibrations" | "spent_today_usd" | "spend_30d">;
type Basis = NonNullable<EnginePolicy["identifiable_basis"]>;

/**
 * Engines and routing, on the Agents screen where the administrator runs the agent: for each
 * task the order of the engines and what the agent will really do; for each engine where it
 * stands on the workers and what is missing; who may see identifiable screens, and on what
 * basis; what it costs. Nothing changes until « Enregistrer », which lists every change.
 */
export function EnginesSection({
  status,
  workers,
  loading,
  canEdit
}: {
  status: Status | undefined;
  workers: WorkerOut[];
  loading: boolean;
  canEdit: boolean;
}) {
  const { hash } = useLocation();
  const ready = !loading && Boolean(status?.policy);
  // Arriving from Paramètres (/agents#moteurs): once the section is drawn, bring it into view.
  useEffect(() => {
    if (ready && hash === "#moteurs") document.getElementById("moteurs")?.scrollIntoView({ block: "start" });
  }, [ready, hash]);
  return (
    <section aria-labelledby="moteurs-titre" id="moteurs" className="mt-10 scroll-mt-20 lg:scroll-mt-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-3xl">
          <h2 id="moteurs-titre">Moteurs et routage</h2>
          <p className="mt-1 text-[15px] text-ink-soft">
            Pour chaque tâche, l'agent essaie les moteurs dans l'ordre et ne passe au suivant que si le précédent échoue : le
            script d'abord, un modèle seulement quand l'écran a changé.
          </p>
        </div>
        {!canEdit && (
          <p className="inline-flex items-center gap-1.5 text-[14px] text-ink-faint">
            <Lock className="h-4 w-4" aria-hidden /> Lecture seule : réglé par l'administrateur du groupe
          </p>
        )}
      </div>
      {loading ? (
        <Loading label="Chargement des moteurs" className="mt-4 space-y-4">
          <PanelSkeleton lines={4} height="h-[260px]" />
          <PanelSkeleton lines={6} height="h-[420px]" />
        </Loading>
      ) : status?.policy ? (
        <Editor status={status} workers={workers} canEdit={canEdit} />
      ) : (
        // An answer without the policy (an older API): the rest of the screen stays usable.
        <p className="mt-3 text-ink-soft">Les réglages des moteurs ne sont pas disponibles pour l'instant.</p>
      )}
    </section>
  );
}

function Editor({ status, workers, canEdit }: { status: Status; workers: WorkerOut[]; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const saved = status.policy;
  const savedJson = JSON.stringify(saved);
  const [draft, setDraft] = useState<AgentPolicy>(saved);
  // A save elsewhere (another tab, another administrator) replaces the draft only if untouched.
  const [base, setBase] = useState(savedJson);
  useEffect(() => {
    if (savedJson !== base) {
      setDraft((d) => (JSON.stringify(d) === base ? (JSON.parse(savedJson) as AgentPolicy) : d));
      setBase(savedJson);
    }
  }, [savedJson, base]);
  const [authorizing, setAuthorizing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const list = useMemo(() => changes(saved, draft), [saved, draft]);
  const save = useMutation({
    mutationFn: () => api<AgentPolicy>("/agent/policy", { method: "PUT", json: draft }),
    onSuccess: (policy) => {
      setNotice(`Enregistré : ${list.length} changement${list.length > 1 ? "s" : ""}. Les postes l'appliquent à leur prochain signal.`);
      setDraft(policy);
      void queryClient.invalidateQueries({ queryKey: ["agent"] });
    }
  });

  const setEngine = (name: string, patch: Partial<EnginePolicy>) =>
    setDraft((d) => ({ ...d, engines: { ...d.engines, [name]: { ...d.engines[name], ...patch } } }));
  const setRoute = (task: string, chain: string[]) => setDraft((d) => ({ ...d, routes: { ...d.routes, [task]: chain } }));
  const preset = presetOf(draft);
  const ctx = { calibrations: status.calibrations, spent_today_usd: status.spent_today_usd };

  return (
    <div className="mt-4 space-y-6 pb-4">
      <p role="status" className={notice ? "rounded-xl bg-lagoon-soft px-4 py-2 text-[15px] font-bold text-lagoon-dark" : "sr-only"}>
        {notice}
      </p>

      {/* 1. Each task: what the agent will do, and the order of the engines. */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3>Ce que fera l'agent</h3>
          <div role="group" aria-label="Préréglages de routage" className="flex flex-wrap gap-2">
            {(Object.keys(PRESETS) as Preset[]).map((p) => (
              <button
                key={p}
                type="button"
                aria-pressed={preset === p}
                disabled={!canEdit}
                title={PRESETS[p].lead}
                onClick={() => setDraft((d) => ({ ...d, routes: { ...d.routes, ...PRESETS[p].routes } }))}
                className={cn(
                  "touch-target rounded-chip px-4 py-1.5 text-[14px] font-bold transition-colors disabled:cursor-not-allowed",
                  preset === p ? "bg-ink text-white" : "bg-paper text-ink-soft shadow-lift hover:text-ink"
                )}
              >
                {PRESETS[p].title}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-1 text-[14px] text-ink-soft">
          {preset ? PRESETS[preset].lead : "Ordre personnalisé."} Un préréglage change l'ordre seulement : activer un moteur reste un
          choix à part.
        </p>
        <div className="mt-3 grid gap-4 xl:grid-cols-3">
          {Object.keys(TASKS).map((task) => (
            <RouteCard
              key={task}
              task={task}
              policy={draft}
              workers={workers}
              ctx={ctx}
              canEdit={canEdit}
              onChain={(chain) => setRoute(task, chain)}
              onBudget={(v) => setDraft((d) => ({ ...d, task_budget_usd: { ...d.task_budget_usd, [task]: v } }))}
              onEnable={(name) => setEngine(name, { enabled: true })}
            />
          ))}
        </div>
      </div>

      {/* 2. Each engine: where it stands, what is missing, who may see what. */}
      <div>
        <h3>Les moteurs</h3>
        <ul className="mt-3 grid gap-4 lg:grid-cols-2">
          {ENGINE_ORDER.filter((n) => draft.engines[n]).map((name) => (
            <EngineCard
              key={name}
              name={name}
              engine={draft.engines[name]}
              workers={workers}
              status={status}
              canEdit={canEdit}
              onChange={(patch) => setEngine(name, patch)}
              onAuthorize={() => setAuthorizing(name)}
            />
          ))}
        </ul>
      </div>

      {/* 3. Money and limits. */}
      <Budgets policy={draft} spentToday={status.spent_today_usd} canEdit={canEdit} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} />

      {canEdit && list.length > 0 && (
        <SaveBar
          changes={list}
          saving={save.isPending}
          error={save.error}
          onCancel={() => {
            setDraft(saved);
            save.reset();
          }}
          onSave={() => {
            setNotice(null);
            save.mutate();
          }}
        />
      )}

      {authorizing && (
        <AuthorizeDialog
          engine={draft.engines[authorizing]}
          onClose={() => setAuthorizing(null)}
          onConfirm={(basis, reference) => {
            setEngine(authorizing, { identifiable_data_allowed: true, identifiable_basis: basis, identifiable_reference: reference || null });
            setAuthorizing(null);
          }}
        />
      )}
    </div>
  );
}

function RouteCard({
  task,
  policy,
  workers,
  ctx,
  canEdit,
  onChain,
  onBudget,
  onEnable
}: {
  task: string;
  policy: AgentPolicy;
  workers: WorkerOut[];
  ctx: Pick<AgentStatus, "calibrations" | "spent_today_usd">;
  canEdit: boolean;
  onChain: (chain: string[]) => void;
  onBudget: (v: number) => void;
  onEnable: (engine: string) => void;
}) {
  const t = TASKS[task];
  const chain = policy.routes[task] ?? [];
  const locked = Boolean(t.scriptOnly);
  const addable = ENGINE_ORDER.filter((n) => policy.engines[n] && !chain.includes(n) && !(locked && n !== "playbook"));
  const move = (i: number, by: number) => {
    const next = [...chain];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    onChain(next);
  };
  return (
    <article className="panel flex flex-col px-5 py-4" aria-labelledby={`route-${task}`}>
      <h4 id={`route-${task}`} className="font-display text-[17px] font-bold">
        {t.title}
      </h4>
      <p className="mt-0.5 text-[13px] text-ink-soft">{t.lead}</p>
      <p className="mt-3 rounded-xl bg-sky px-3 py-2 text-[14px] font-bold" data-testid={`route-sentence-${task}`}>
        {routeSentence(task, policy, workers, ctx)}
      </p>
      <ol className="mt-3 space-y-2" aria-label={`Ordre des moteurs : ${t.title}`}>
        {chain.map((name, i) => {
          const e = policy.engines[name];
          const r = readiness(name, task, policy, workers, ctx);
          return (
            <li key={name} className={cn("rounded-xl border px-3 py-2", r.ready ? "border-line bg-paper" : "border-dashed border-line bg-sky/50")}>
              <div className="flex items-start gap-2">
                <span className="num mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-sky-deep text-[12px] font-bold">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className={cn("truncate font-bold", !r.ready && "text-ink-soft")}>{e ? short(e) : name}</p>
                  {r.ready ? (
                    <p className="inline-flex items-center gap-1 text-[13px] font-bold text-lagoon-dark">
                      <Check className="h-3.5 w-3.5" aria-hidden /> prêt
                    </p>
                  ) : (
                    <p className="text-[13px] text-ink-soft">
                      <span className="inline-flex items-center gap-1 font-bold text-ink">
                        <CircleSlash className="h-3.5 w-3.5" aria-hidden /> sera sauté :
                      </span>{" "}
                      {r.reason}
                      {canEdit && r.reason === "désactivé" && (
                        <button type="button" className="ml-1 font-bold text-violet underline" onClick={() => onEnable(name)}>
                          Activer
                        </button>
                      )}
                    </p>
                  )}
                </div>
                {canEdit && !locked && (
                  <span className="flex shrink-0 gap-0.5">
                    <IconAction label={`Monter ${e ? short(e) : name}`} disabled={i === 0} onClick={() => move(i, -1)}>
                      <ArrowUp className="h-4 w-4" aria-hidden />
                    </IconAction>
                    <IconAction label={`Descendre ${e ? short(e) : name}`} disabled={i === chain.length - 1} onClick={() => move(i, 1)}>
                      <ArrowDown className="h-4 w-4" aria-hidden />
                    </IconAction>
                    <IconAction label={`Retirer ${e ? short(e) : name} de la route`} onClick={() => onChain(chain.filter((n) => n !== name))}>
                      <X className="h-4 w-4" aria-hidden />
                    </IconAction>
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {locked ? (
        <p className="mt-3 inline-flex items-start gap-1.5 text-[13px] text-ink-soft">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {t.scriptOnly}
        </p>
      ) : (
        <div className="mt-auto grid grid-cols-2 gap-3 pt-3">
          <label className="field" htmlFor={`add-${task}`}>
            Ajouter un moteur
            <select
              id={`add-${task}`}
              className="input"
              value=""
              disabled={!canEdit || addable.length === 0}
              onChange={(e) => e.target.value && onChain([...chain, e.target.value])}
            >
              <option value="">{addable.length ? "Choisir" : "Tous sont dans la route"}</option>
              {addable.map((n) => (
                <option key={n} value={n}>
                  {short(policy.engines[n])}
                </option>
              ))}
            </select>
          </label>
          <label className="field" htmlFor={`budget-${task}`}>
            Budget par tâche ($)
            <input
              id={`budget-${task}`}
              className="input"
              type="number"
              min={0}
              step={0.1}
              disabled={!canEdit}
              value={policy.task_budget_usd[task] ?? 0}
              onChange={(e) => onBudget(Math.max(0, Number(e.target.value) || 0))}
            />
          </label>
        </div>
      )}
    </article>
  );
}

function EngineCard({
  name,
  engine: e,
  workers,
  status,
  canEdit,
  onChange,
  onAuthorize
}: {
  name: string;
  engine: EnginePolicy;
  workers: WorkerOut[];
  status: Status;
  canEdit: boolean;
  onChange: (patch: Partial<EnginePolicy>) => void;
  onAuthorize: () => void;
}) {
  const kind = KIND[e.kind];
  const where = availability(name, workers);
  const used = status.spend_30d.find((s) => s.engine === name);
  const calibration = status.calibrations[name];
  const model = e.kind !== "playbook";
  const state = !e.enabled
    ? { text: "Désactivé", tone: "bg-sky-deep text-ink-soft" }
    : where.online > 0 && where.ready.length === 0
      ? { text: "À configurer sur les postes", tone: "bg-sun-soft text-ink" }
      : model && !e.identifiable_data_allowed
        ? { text: "En attente d'autorisation", tone: "bg-sun-soft text-ink" }
        : { text: "Actif", tone: "bg-lagoon-soft text-lagoon-dark" };

  return (
    <li className="panel flex flex-col px-5 py-4" aria-labelledby={`engine-${name}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <span className={`chip px-2 py-0.5 text-[12px] ${kind.tone}`}>{kind.text}</span>
          <h4 id={`engine-${name}`} className="mt-1.5 font-display text-[17px] font-bold">
            {e.label}
          </h4>
          {e.model && <p className="font-mono text-[12px] text-ink-faint">{e.model}</p>}
        </div>
        <span className={`chip shrink-0 ${state.tone}`}>{state.text}</span>
      </div>
      <p className="mt-2 text-[14px] text-ink-soft">{kind.where}</p>

      <div className="mt-3">
        <p className="text-[12px] font-bold uppercase tracking-wide text-ink-faint">Sur les postes en ligne</p>
        {where.online === 0 ? (
          <p className="mt-1 text-[14px] text-ink-soft">Aucun poste en ligne.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-[14px]">
            {where.ready.map((w) => (
              <li key={w} className="flex items-center gap-1.5">
                <Check className="h-4 w-4 text-lagoon-dark" aria-hidden /> <span className="font-bold">{w}</span> : prêt
              </li>
            ))}
            {where.missing.map((m) => (
              <li key={m.worker} className="flex items-start gap-1.5">
                <X className="mt-0.5 h-4 w-4 shrink-0 text-coral-dark" aria-hidden />
                <span>
                  <span className="font-bold">{m.worker}</span> : {m.detail}
                </span>
              </li>
            ))}
          </ul>
        )}
        {where.online > 0 && where.ready.length < where.online && <p className="mt-1.5 rounded-lg bg-sky px-2.5 py-1.5 text-[13px]">{SETUP[name]}</p>}
      </div>

      {e.min_calibration != null && (
        <p className={cn("mt-2 text-[14px]", calibration && calibration.hit_rate >= e.min_calibration ? "text-ink-soft" : "text-coral-dark")}>
          Pointage :{" "}
          {calibration
            ? `${pct(calibration.hit_rate)} sur ${calibration.trials} essais (seuil ${pct(e.min_calibration)})`
            : `jamais calibré (seuil ${pct(e.min_calibration)})`}
        </p>
      )}

      <div className="mt-3 space-y-2 border-t border-line pt-3">
        {name === "playbook" ? (
          <p className="inline-flex items-center gap-1.5 text-[14px] text-ink-soft">
            <Lock className="h-4 w-4" aria-hidden /> Toujours actif : il se connecte au portail pour tous les moteurs et relit chaque
            écriture.
          </p>
        ) : (
          <>
            <Switch label="Activé" checked={e.enabled} disabled={!canEdit} onChange={(v) => onChange({ enabled: v })} />
            <Switch
              label="Peut voir des écrans avec des données identifiantes"
              checked={e.identifiable_data_allowed}
              disabled={!canEdit}
              onChange={(v) => (v ? onAuthorize() : onChange({ identifiable_data_allowed: false, identifiable_basis: null, identifiable_reference: null }))}
            />
            {e.identifiable_data_allowed && e.identifiable_basis ? (
              <p className="flex items-start gap-1.5 rounded-lg bg-lagoon-soft px-2.5 py-1.5 text-[13px] text-lagoon-dark">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                <span>
                  {BASIS[e.identifiable_basis].label}
                  {e.identifiable_reference ? ` : ${e.identifiable_reference}` : ""}
                </span>
              </p>
            ) : (
              <p className="flex items-start gap-1.5 text-[13px] text-ink-soft">
                <ShieldQuestion className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                Les portails affichent des noms de patients : sans cette autorisation, le moteur est sauté.
              </p>
            )}
          </>
        )}
      </div>

      <div className="mt-auto flex flex-wrap items-end justify-between gap-3 pt-3">
        <Prices engine={e} canEdit={canEdit} onChange={onChange} />
        <p className="text-right text-[13px] text-ink-soft">
          <span className="block text-[12px] font-bold uppercase tracking-wide text-ink-faint">30 derniers jours</span>
          {used
            ? `${used.attempts} passage${used.attempts > 1 ? "s" : ""}, ${used.successes} réussi${used.successes > 1 ? "s" : ""}, ${usd(used.cost_usd)}`
            : "Pas utilisé"}
        </p>
      </div>
    </li>
  );
}

function Prices({ engine: e, canEdit, onChange }: { engine: EnginePolicy; canEdit: boolean; onChange: (patch: Partial<EnginePolicy>) => void }) {
  if (e.kind === "playbook") return <p className="text-[14px] font-bold">Gratuit</p>;
  const field = (key: "input_usd_per_mtok" | "output_usd_per_mtok" | "usd_per_hour", label: string) => (
    <label className="flex items-center gap-1.5 text-[13px] text-ink-soft">
      <input
        type="number"
        min={0}
        step={0.1}
        className="input mt-0 w-20 py-1"
        disabled={!canEdit}
        value={e[key]}
        onChange={(ev) => onChange({ [key]: Math.max(0, Number(ev.target.value) || 0) })}
        aria-label={`${e.label} : ${label}`}
      />
      {label}
    </label>
  );
  return e.kind === "anthropic" ? (
    <div className="space-y-1">
      {field("input_usd_per_mtok", "$ / M jetons lus")}
      {field("output_usd_per_mtok", "$ / M jetons écrits")}
    </div>
  ) : (
    field("usd_per_hour", "$ / heure GPU")
  );
}

function Budgets({
  policy,
  spentToday,
  canEdit,
  onChange
}: {
  policy: AgentPolicy;
  spentToday: number;
  canEdit: boolean;
  onChange: (patch: Partial<AgentPolicy>) => void;
}) {
  const share = policy.daily_budget_usd > 0 ? Math.min(1, spentToday / policy.daily_budget_usd) : 1;
  return (
    <div className="panel grid gap-5 px-5 py-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]">
      <div>
        <h3 className="inline-flex items-center gap-2">
          <Wallet className="h-5 w-5" aria-hidden /> Budget des modèles
        </h3>
        <p className="mt-1 flex items-baseline justify-between text-[14px]">
          <span>Dépensé aujourd'hui</span>
          <span className="num font-bold">
            {usd(spentToday)} / {usd(policy.daily_budget_usd)}
          </span>
        </p>
        <div className="mt-1 h-2 rounded-full bg-sky-deep" role="meter" aria-valuemin={0} aria-valuemax={policy.daily_budget_usd} aria-valuenow={spentToday} aria-label="Dépense du jour">
          <div className={cn("h-2 rounded-full", share >= 1 ? "bg-coral-dark" : share > 0.8 ? "bg-sun" : "bg-violet")} style={{ width: `${share * 100}%` }} />
        </div>
        <p className="mt-1 text-[13px] text-ink-soft">Au-delà du plafond, seuls les scripts tournent jusqu'à minuit.</p>
      </div>
      <label className="field" htmlFor="daily-budget">
        Plafond du jour ($)
        <input
          id="daily-budget"
          className="input"
          type="number"
          min={0}
          step={1}
          disabled={!canEdit}
          value={policy.daily_budget_usd}
          onChange={(e) => onChange({ daily_budget_usd: Math.max(0, Number(e.target.value) || 0) })}
        />
      </label>
      <label className="field" htmlFor="max-attempts">
        Tentatives avant reprise humaine
        <input
          id="max-attempts"
          className="input"
          type="number"
          min={1}
          max={10}
          disabled={!canEdit}
          value={policy.max_attempts}
          onChange={(e) => onChange({ max_attempts: Math.min(10, Math.max(1, Number(e.target.value) || 1)) })}
        />
      </label>
      <details className="text-[14px] md:col-span-3">
        <summary className="cursor-pointer font-bold text-ink-soft">Réglage hérité : relève sans connexion</summary>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <label className="field" htmlFor="legacy-interval">
            Toutes les (minutes)
            <input
              id="legacy-interval"
              className="input w-32"
              type="number"
              min={1}
              max={1440}
              disabled={!canEdit}
              value={policy.sync_interval_minutes}
              onChange={(e) => onChange({ sync_interval_minutes: Math.min(1440, Math.max(1, Number(e.target.value) || 1)) })}
            />
          </label>
          <p className="max-w-xl text-ink-soft">
            Seulement pour un poste installé sans connexion. Les connexions ont chacune leur planning, dans leur carte.
          </p>
        </div>
      </details>
    </div>
  );
}

function SaveBar({
  changes: list,
  saving,
  error,
  onCancel,
  onSave
}: {
  changes: string[];
  saving: boolean;
  error: unknown;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div
      role="region"
      aria-label="Changements à enregistrer"
      className="sticky bottom-24 z-20 rounded-panel bg-ink px-5 py-4 text-white shadow-[0_20px_50px_-20px_rgba(28,25,70,0.7)] lg:bottom-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-bold">
            {list.length} changement{list.length > 1 ? "s" : ""} pas encore enregistré{list.length > 1 ? "s" : ""}
          </p>
          <ul className="mt-1 list-disc pl-5 text-[14px] text-white/85">
            {list.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="quiet" onClick={onCancel} disabled={saving}>
            Annuler
          </Button>
          <Button variant="sun" onClick={onSave} disabled={saving}>
            {saving ? "Enregistrement…" : "Enregistrer"}
          </Button>
        </div>
      </div>
      {error ? (
        <div className="mt-3">
          <ErrorNote error={error} />
        </div>
      ) : null}
    </div>
  );
}

function AuthorizeDialog({
  engine,
  onClose,
  onConfirm
}: {
  engine: EnginePolicy;
  onClose: () => void;
  onConfirm: (basis: Basis, reference: string) => void;
}) {
  const [basis, setBasis] = useState<Basis | "">("");
  const [reference, setReference] = useState("");
  const needsReference = basis !== "" && BASIS[basis].reference !== null;
  const ready = basis !== "" && (!needsReference || reference.trim().length > 0);
  return (
    <Modal title={`Laisser ${short(engine)} voir des données identifiantes`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (basis) onConfirm(basis, reference.trim());
        }}
      >
        <p className="text-[15px] text-ink-soft">
          {KIND[engine.kind].where} Ces écrans montrent des noms, des dates de naissance et des numéros de dossier. L'autorisation et
          sa justification sont inscrites au journal d'audit à votre nom.
        </p>
        <fieldset className="mt-4 space-y-2">
          <legend className="field mb-1">Sur quoi repose l'autorisation ?</legend>
          {(Object.keys(BASIS) as Basis[]).map((b) => (
            <label key={b} className={cn("flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5", basis === b ? "border-violet bg-violet-soft" : "border-line")}>
              <input type="radio" name="basis" value={b} checked={basis === b} onChange={() => setBasis(b)} />
              <span className="font-bold">{BASIS[b].label}</span>
            </label>
          ))}
        </fieldset>
        {needsReference && (
          <label className="field mt-3" htmlFor="basis-reference">
            {BASIS[basis as Basis].reference}
            <input id="basis-reference" className="input" maxLength={120} value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
        )}
        {basis === "demonstration" && (
          <p className="mt-3 rounded-xl bg-sun-soft px-3 py-2 text-[14px]">À n'utiliser qu'avec un portail fictif : aucun patient réel ne doit passer par ce moteur.</p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          <Button type="submit" variant="primary" disabled={!ready}>
            Autoriser
          </Button>
          <Button type="button" variant="quiet" onClick={onClose}>
            Annuler
          </Button>
        </div>
        <p className="mt-3 text-[13px] text-ink-faint">Rien n'est appliqué avant « Enregistrer ».</p>
      </form>
    </Modal>
  );
}

function Switch({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className={cn("flex items-center justify-between gap-3 text-[14px]", disabled ? "cursor-not-allowed" : "cursor-pointer")}>
      <span>{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "touch-target relative h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-60",
          checked ? "bg-violet" : "bg-sky-deep"
        )}
      >
        <span aria-hidden className={cn("absolute left-0 top-1 h-5 w-5 rounded-full bg-white shadow transition-transform", checked ? "translate-x-6" : "translate-x-1")} />
      </button>
    </label>
  );
}

function IconAction({ label, disabled = false, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="touch-target grid h-8 w-8 place-items-center rounded-lg text-ink-soft hover:bg-sky hover:text-ink disabled:opacity-30"
    >
      {children}
    </button>
  );
}

