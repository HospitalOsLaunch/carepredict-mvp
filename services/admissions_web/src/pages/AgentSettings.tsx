import { EngineJourney } from "../components/EngineJourney";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, Lock, Pause, Play, RefreshCw, RotateCcw, ShieldAlert, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { AgentPolicy, AgentStatus, AgentTask, EnginePolicy } from "../api/types";
import { useAuth } from "../auth";
import { ErrorNote, Meter, Spinner } from "../components/ui";
import { fmtDateTime, fmtNum, fmtPct, plural } from "../lib/format";

const TASKS: Record<string, { title: string; lead: string }> = {
  sync_inbox: {
    title: "Relever les demandes du portail",
    lead: "Lecture seule : l'agent lit la liste des dossiers et les dépose ici."
  },
  reply_portal: {
    title: "Reporter la réponse sur le portail",
    lead: "Écriture : chaque saisie est relue indépendamment avant d'être déclarée faite."
  }
};

const KIND_BADGE: Record<EnginePolicy["kind"], { text: string; tone: string }> = {
  playbook: { text: "Script", tone: "bg-ink text-white" },
  openai_compatible: { text: "Open source", tone: "bg-lagoon-soft text-lagoon-dark" },
  anthropic: { text: "Propriétaire", tone: "bg-violet-soft text-violet-dark" }
};

type Preset = "economie" | "souverain" | "qualite";

const PRESETS: Record<Preset, { title: string; lead: string; routes: Record<string, string[]> }> = {
  economie: {
    title: "Économie",
    lead: "Script, puis open source, puis propriétaire en dernier recours.",
    routes: {
      sync_inbox: ["playbook", "open_light", "closed_fast"],
      reply_portal: ["playbook", "open_heavy", "closed_best"]
    }
  },
  souverain: {
    title: "Souveraineté",
    lead: "Aucun écran ne sort de votre infrastructure : script et modèles auto-hébergés seulement.",
    routes: {
      sync_inbox: ["playbook", "open_light", "open_heavy"],
      reply_portal: ["playbook", "open_heavy"]
    }
  },
  qualite: {
    title: "Fiabilité",
    lead: "Script, puis directement les meilleurs modèles du marché.",
    routes: {
      sync_inbox: ["playbook", "closed_fast", "closed_best"],
      reply_portal: ["playbook", "closed_best"]
    }
  }
};

const TASK_STATUS: Record<string, { text: string; tone: string }> = {
  pending: { text: "En file", tone: "bg-violet-soft text-violet-dark" },
  running: { text: "En cours", tone: "bg-violet text-white" },
  done: { text: "Faite", tone: "bg-lagoon-soft text-lagoon-dark" },
  manual: { text: "Faite à la main", tone: "bg-sky-deep text-ink-soft" },
  needs_human: { text: "À reprendre", tone: "bg-coral text-white" },
  failed: { text: "Échec", tone: "bg-coral-soft text-coral-dark" },
  cancelled: { text: "Annulée", tone: "bg-sky-deep text-ink-soft" }
};

function useAgentStatus() {
  return useQuery({
    queryKey: ["agent", "status"],
    queryFn: () => api<AgentStatus>("/agent/status"),
    refetchInterval: 30_000
  });
}

export function AgentTab() {
  const status = useAgentStatus();
  if (status.isLoading) return <Spinner />;
  if (status.error) return <ErrorNote error={status.error} />;
  if (!status.data) return null;
  return (
    <div className="space-y-6">
      <StatusPanel status={status.data} />
      <PolicyEditor status={status.data} />
      <RecentTasks tasks={status.data.recent} />
    </div>
  );
}

function StatusPanel({ status: s }: { status: AgentStatus }) {
  const { user, isAdmin, canWrite } = useAuth();
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["agent"] });
  const toggle = useMutation({
    mutationFn: () => api<AgentStatus>(s.paused ? "/agent/resume" : "/agent/pause", { method: "POST" }),
    onSuccess: refresh
  });
  const sync = useMutation({
    mutationFn: () => api<AgentTask>("/agent/sync", { method: "POST" }),
    onSuccess: refresh
  });
  const budget = s.policy.daily_budget_usd;
  const share = budget > 0 ? s.spent_today_usd / budget : 0;
  const waiting = (s.counts.needs_human ?? 0) + (s.counts.failed ?? 0);
  return (
    <section className="panel px-6 py-5" aria-labelledby="agent-state">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 id="agent-state" className="flex items-center gap-3">
            <span className="relative flex h-3.5 w-3.5" aria-hidden>
              {s.online && !s.paused && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-lagoon opacity-60" />
              )}
              <span
                className={`relative inline-flex h-3.5 w-3.5 rounded-full ${s.paused ? "bg-sun" : s.online ? "bg-lagoon" : "bg-ink-faint"}`}
              />
            </span>
            {s.paused
              ? "Agent en pause"
              : s.online
                ? "Agent en ligne"
                : s.last_heartbeat_at
                  ? "Agent hors ligne"
                  : "Agent jamais connecté"}
          </h2>
          <p className="mt-1 text-[14px] text-ink-soft">
            {s.last_heartbeat_at
              ? `Dernier signal le ${fmtDateTime(s.last_heartbeat_at)}${s.agent_id ? `, poste ${s.agent_id}` : ""}${s.agent_version ? ` (v${s.agent_version})` : ""}.`
              : "Installez l'agent sur un poste ou un serveur de l'établissement avec un compte de service « ingestion »."}
          </p>
          {waiting > 0 && (
            <p className="mt-2 text-[14px] font-bold text-coral-dark">
              {waiting} tâche{waiting > 1 ? "s" : ""} à reprendre à la main (voir plus bas).
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {canWrite && !(user?.role === "coordination" && user.site_id !== null) && <button className="btn-quiet" onClick={() => sync.mutate()} disabled={sync.isPending || s.paused}>
            <RefreshCw className="h-4 w-4" aria-hidden /> Relever le portail maintenant
          </button>}
          {isAdmin && <button
            className={s.paused ? "btn-primary" : "btn-quiet"}
            onClick={() => toggle.mutate()}
            disabled={toggle.isPending}
          >
            {s.paused ? <Play className="h-4 w-4" aria-hidden /> : <Pause className="h-4 w-4" aria-hidden />}
            {s.paused ? "Reprendre" : "Mettre en pause"}
          </button>}
        </div>
      </div>
      {(toggle.error || sync.error) && (
        <div className="mt-3">
          <ErrorNote error={toggle.error ?? sync.error} />
        </div>
      )}
      <div className="mt-5 grid gap-4 sm:grid-cols-[2fr_1fr_1fr]">
        <div>
          <div className="flex justify-between text-[14px]">
            <span className="font-bold">Dépense du jour</span>
            <span className="num">
              {fmtUsd(s.spent_today_usd)} / {fmtUsd(budget)}
            </span>
          </div>
          <div className="mt-2">
            <Meter value={share * 100} tone={share >= 1 ? "coral" : share >= 0.8 ? "sun" : "lagoon"} />
          </div>
          <p className="mt-1 text-[12px] text-ink-faint">Au-delà du plafond, seuls les scripts tournent encore.</p>
        </div>
        <Count label="En file" value={(s.counts.pending ?? 0) + (s.counts.running ?? 0)} />
        <Count label="Faites (total)" value={(s.counts.done ?? 0) + (s.counts.manual ?? 0)} />
      </div>
    </section>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl bg-sky px-4 py-3">
      <p className="text-[13px] text-ink-faint">{label}</p>
      <p className="num text-[24px] font-bold">{value}</p>
    </div>
  );
}

function fmtUsd(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("fr-FR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function PolicyEditor({ status }: { status: AgentStatus }) {
  const { isAdmin } = useAuth();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<AgentPolicy>(status.policy);
  const serverJson = JSON.stringify(status.policy);
  useEffect(() => setDraft(JSON.parse(serverJson) as AgentPolicy), [serverJson]);
  const dirty = JSON.stringify(draft) !== serverJson;

  const save = useMutation({
    mutationFn: () => api<AgentPolicy>("/agent/policy", { method: "PUT", json: draft }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["agent"] })
  });

  const spend = useMemo(() => new Map(status.spend_30d.map((e) => [e.engine, e])), [status.spend_30d]);
  const reported = useMemo(() => new Map(status.engines.map((e) => [e.name, e])), [status.engines]);
  const names = Object.keys(draft.engines);

  const setEngine = (name: string, patch: Partial<EnginePolicy>) =>
    setDraft({ ...draft, engines: { ...draft.engines, [name]: { ...draft.engines[name], ...patch } } });
  const setRoute = (kind: string, chain: string[]) =>
    setDraft({ ...draft, routes: { ...draft.routes, [kind]: chain } });
  const applyPreset = (preset: Preset) => {
    const routes = PRESETS[preset].routes;
    const engines = { ...draft.engines };
    const used = new Set(Object.values(routes).flat());
    for (const name of used) if (engines[name]) engines[name] = { ...engines[name], enabled: true };
    setDraft({ ...draft, routes: { ...draft.routes, ...routes }, engines });
  };

  return (
    <section aria-labelledby="routing" className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-2xl">
          <h2 id="routing">Moteurs et routage</h2>
          <p className="mt-1 text-ink-soft">
            Pour chaque tâche, l'agent essaie les moteurs dans l'ordre et passe au suivant en cas d'échec, tant que le
            budget le permet. Le moins cher et le plus contrôlable d'abord ; le plus capable en dernier recours.
          </p>
        </div>
        {!isAdmin && (
          <p className="text-[14px] text-ink-faint">Lecture seule : réservé à l'administrateur du groupe.</p>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-3" role="group" aria-label="Préréglages de routage">
        {(Object.keys(PRESETS) as Preset[]).map((p) => (
          <button
            key={p}
            className="panel px-5 py-4 text-left transition-shadow hover:ring-2 hover:ring-violet disabled:opacity-60"
            onClick={() => applyPreset(p)}
            disabled={!isAdmin}
          >
            <p className="font-display text-[17px] font-bold">{PRESETS[p].title}</p>
            <p className="mt-1 text-[14px] text-ink-soft">{PRESETS[p].lead}</p>
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {Object.keys(TASKS).map((kind) => (
          <RouteCard
            key={kind}
            kind={kind}
            chain={draft.routes[kind] ?? []}
            engines={draft.engines}
            budget={draft.task_budget_usd[kind] ?? 1}
            readOnly={!isAdmin}
            onChain={(chain) => setRoute(kind, chain)}
            onBudget={(v) => setDraft({ ...draft, task_budget_usd: { ...draft.task_budget_usd, [kind]: v } })}
          />
        ))}
      </div>

      <div className="panel relative overflow-x-auto">
        <table className="w-full min-w-[980px] text-[14px]">
          <caption className="sr-only">Moteurs disponibles, autorisations, prix et usage sur 30 jours</caption>
          <thead>
            <tr className="border-b border-line text-left text-[12px] text-ink-faint">
              <th className="px-5 py-3 font-normal">Moteur</th>
              <th className="px-2 py-3 font-normal">Activé</th>
              <th className="px-2 py-3 font-normal">Voit des données identifiantes</th>
              <th className="px-2 py-3 font-normal">Prix</th>
              <th className="px-2 py-3 font-normal">Sur l'agent</th>
              <th className="px-5 py-3 text-right font-normal">30 derniers jours</th>
            </tr>
          </thead>
          <tbody>
            {names.map((name) => {
              const e = draft.engines[name];
              const used = spend.get(name);
              const rep = reported.get(name);
              const cal = status.calibrations[name];
              const calOk = e.min_calibration == null || (cal?.hit_rate ?? 0) >= e.min_calibration;
              return (
                <tr key={name} className="border-b border-line align-top last:border-0">
                  <td className="px-5 py-3">
                    <span className={`chip ${KIND_BADGE[e.kind].tone}`}>{KIND_BADGE[e.kind].text}</span>
                    <p className="mt-1 font-bold">{e.label}</p>
                    <p className="text-[12px] text-ink-faint">{e.model ?? "Playwright, sans modèle"}</p>
                    {e.min_calibration != null && (
                      <p className={`mt-1 text-[12px] ${calOk ? "text-lagoon-dark" : "text-coral-dark"}`}>
                        Pointage : {cal ? `${fmtPct(cal.hit_rate)} sur ${cal.trials} essais` : "jamais calibré"} (seuil{" "}
                        {fmtPct(e.min_calibration)})
                      </p>
                    )}
                  </td>
                  <td className="px-2 py-3">
                    <Toggle
                      label={`Activer ${e.label}`}
                      checked={e.enabled}
                      disabled={!isAdmin}
                      onChange={(v) => setEngine(name, { enabled: v })}
                    />
                  </td>
                  <td className="px-2 py-3">
                    {e.kind === "playbook" ? (
                      <span className="flex items-center gap-1 text-[13px] text-ink-soft">
                        <Lock className="h-3.5 w-3.5" aria-hidden /> Reste sur le poste
                      </span>
                    ) : (
                      <>
                        <Toggle
                          label={`Autoriser ${e.label} à voir des écrans avec des données identifiantes`}
                          checked={e.identifiable_data_allowed}
                          disabled={!isAdmin}
                          onChange={(v) => setEngine(name, { identifiable_data_allowed: v })}
                        />
                        {e.identifiable_data_allowed && (
                          <p className="mt-1 max-w-[220px] text-[12px] text-coral-dark">
                            {e.open_weights
                              ? "Seulement si le serveur GPU est hébergé chez un hébergeur HDS ou chez vous."
                              : "Seulement si un contrat couvre ces données (HDS, accord de traitement)."}
                          </p>
                        )}
                      </>
                    )}
                  </td>
                  <td className="px-2 py-3">
                    {e.kind === "playbook" ? (
                      <span className="text-ink-soft">Gratuit</span>
                    ) : (
                      <PriceFields engine={e} disabled={!isAdmin} onChange={(patch) => setEngine(name, patch)} />
                    )}
                  </td>
                  <td className="px-2 py-3">
                    {rep ? (
                      rep.configured ? (
                        <span className="flex items-center gap-1 text-lagoon-dark">
                          <Check className="h-4 w-4" aria-hidden /> Configuré
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-ink-faint" title={rep.detail ?? undefined}>
                          <X className="h-4 w-4" aria-hidden /> Non configuré
                        </span>
                      )
                    ) : (
                      <span className="text-ink-faint">—</span>
                    )}
                  </td>
                  <td className="num px-5 py-3 text-right">
                    {used ? (
                      <>
                        <p className="font-bold">{fmtUsd(used.cost_usd)}</p>
                        <p className="text-[12px] text-ink-faint">
                          {plural(used.attempts, "essai", "essais")}, {fmtPct(used.attempts ? used.successes / used.attempts : null)}{" "}
                          réussis
                        </p>
                        {used.successes > 0 && (
                          <p className="text-[12px] text-ink-faint">
                            {fmtUsd(used.cost_usd / used.successes, 3)} par réussite
                          </p>
                        )}
                      </>
                    ) : (
                      <span className="text-ink-faint">Pas utilisé</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="panel grid gap-4 px-6 py-5 sm:grid-cols-4 sm:items-end">
        <NumberField
          id="daily"
          label="Plafond quotidien (USD)"
          value={draft.daily_budget_usd}
          step={1}
          disabled={!isAdmin}
          onChange={(v) => setDraft({ ...draft, daily_budget_usd: v })}
        />
        <NumberField
          id="interval"
          label="Relève du portail (minutes)"
          value={draft.sync_interval_minutes}
          step={1}
          min={1}
          disabled={!isAdmin}
          onChange={(v) => setDraft({ ...draft, sync_interval_minutes: Math.round(v) })}
        />
        <NumberField
          id="attempts"
          label="Tentatives avant reprise humaine"
          value={draft.max_attempts}
          step={1}
          min={1}
          disabled={!isAdmin}
          onChange={(v) => setDraft({ ...draft, max_attempts: Math.round(v) })}
        />
        <p className="flex items-start gap-2 text-[13px] text-ink-soft">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-violet" aria-hidden />
          Relecture indépendante de chaque écriture : toujours active, non désactivable.
        </p>
      </div>

      {isAdmin && (
        <div
          className={`flex flex-wrap items-center gap-3 ${
            dirty ? "sticky bottom-4 z-10 rounded-panel bg-paper px-5 py-3 shadow-lift ring-2 ring-violet" : ""
          }`}
        >
          {dirty && <span className="font-bold">Modifications non enregistrées</span>}
          <button className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            Enregistrer la politique
          </button>
          {dirty && (
            <button className="btn-ghost" onClick={() => setDraft(JSON.parse(serverJson) as AgentPolicy)}>
              Annuler les changements
            </button>
          )}
          {save.isSuccess && !dirty && (
            <span className="text-[14px] text-lagoon-dark" role="status">
              Politique enregistrée : l'agent l'applique à son prochain signal.
            </span>
          )}
          {save.error && <ErrorNote error={save.error} />}
        </div>
      )}
    </section>
  );
}

function RouteCard({
  kind,
  chain,
  engines,
  budget,
  readOnly,
  onChain,
  onBudget
}: {
  kind: string;
  chain: string[];
  engines: Record<string, EnginePolicy>;
  budget: number;
  readOnly: boolean;
  onChain: (chain: string[]) => void;
  onBudget: (v: number) => void;
}) {
  const unused = Object.keys(engines).filter((n) => !chain.includes(n));
  const move = (i: number, d: -1 | 1) => {
    const next = [...chain];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    onChain(next);
  };
  return (
    <div className="panel px-5 py-4">
      <h3>{TASKS[kind].title}</h3>
      <p className="mt-1 text-[14px] text-ink-soft">{TASKS[kind].lead}</p>
      <ol className="mt-4 space-y-2">
        {chain.map((name, i) => {
          const e = engines[name];
          const off = !e?.enabled || (e.kind !== "playbook" && !e.identifiable_data_allowed);
          return (
            <li
              key={name}
              className={`flex items-center gap-3 rounded-xl border border-line px-3 py-2 ${off ? "opacity-60" : ""}`}
            >
              <span className="num grid h-7 w-7 shrink-0 place-items-center rounded-full bg-sky text-[13px] font-bold">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-bold">{e?.label ?? name}</p>
                <p className="text-[12px] text-ink-faint">
                  {!e?.enabled
                    ? "désactivé : sera sauté"
                    : e.kind !== "playbook" && !e.identifiable_data_allowed
                      ? "pas autorisé sur des écrans identifiants : sera sauté"
                      : KIND_BADGE[e.kind].text}
                </p>
              </div>
              {!readOnly && (
                <div className="flex shrink-0 gap-1">
                  <button
                    className="btn-ghost h-8 w-8 p-0"
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                    aria-label={`Monter ${e?.label ?? name}`}
                  >
                    <ArrowUp className="h-4 w-4" aria-hidden />
                  </button>
                  <button
                    className="btn-ghost h-8 w-8 p-0"
                    disabled={i === chain.length - 1}
                    onClick={() => move(i, 1)}
                    aria-label={`Descendre ${e?.label ?? name}`}
                  >
                    <ArrowDown className="h-4 w-4" aria-hidden />
                  </button>
                  <button
                    className="btn-ghost h-8 w-8 p-0"
                    onClick={() => onChain(chain.filter((n) => n !== name))}
                    aria-label={`Retirer ${e?.label ?? name} de la route`}
                  >
                    <X className="h-4 w-4" aria-hidden />
                  </button>
                </div>
              )}
            </li>
          );
        })}
        {chain.length === 0 && (
          <li className="text-[14px] text-coral-dark">
            Aucun moteur : la tâche partira directement en reprise humaine.
          </li>
        )}
      </ol>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 sm:items-end">
        {!readOnly && unused.length > 0 && (
          <div>
            <label className="field" htmlFor={`add-${kind}`}>
              Ajouter un moteur
            </label>
            <select
              id={`add-${kind}`}
              className="input"
              value=""
              onChange={(ev) => ev.target.value && onChain([...chain, ev.target.value])}
            >
              <option value="">Choisir</option>
              {unused.map((n) => (
                <option key={n} value={n}>
                  {engines[n].label}
                </option>
              ))}
            </select>
          </div>
        )}
        <NumberField
          id={`budget-${kind}`}
          label="Budget par tâche (USD)"
          value={budget}
          step={0.1}
          disabled={readOnly}
          onChange={onBudget}
        />
      </div>
    </div>
  );
}

function PriceFields({
  engine: e,
  disabled,
  onChange
}: {
  engine: EnginePolicy;
  disabled: boolean;
  onChange: (patch: Partial<EnginePolicy>) => void;
}) {
  if (e.kind === "openai_compatible") {
    return (
      <label className="flex items-center gap-2 text-[13px]">
        <input
          type="number"
          min={0}
          step={0.1}
          className="input mt-0 w-20 py-1 num"
          value={e.usd_per_hour}
          disabled={disabled}
          onChange={(ev) => onChange({ usd_per_hour: Number(ev.target.value) })}
        />
        <span className="text-ink-soft">USD / heure GPU</span>
      </label>
    );
  }
  return (
    <div className="space-y-1 text-[13px]">
      <label className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          step={0.1}
          className="input mt-0 w-20 py-1 num"
          value={e.input_usd_per_mtok}
          disabled={disabled}
          onChange={(ev) => onChange({ input_usd_per_mtok: Number(ev.target.value) })}
        />
        <span className="text-ink-soft">USD / M jetons lus</span>
      </label>
      <label className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          step={0.1}
          className="input mt-0 w-20 py-1 num"
          value={e.output_usd_per_mtok}
          disabled={disabled}
          onChange={(ev) => onChange({ output_usd_per_mtok: Number(ev.target.value) })}
        />
        <span className="text-ink-soft">USD / M jetons écrits</span>
      </label>
    </div>
  );
}

function NumberField({
  id,
  label,
  value,
  step,
  min = 0,
  disabled,
  onChange
}: {
  id: string;
  label: string;
  value: number;
  step: number;
  min?: number;
  disabled: boolean;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="field" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={min}
        step={step}
        className="input num"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

function Toggle({
  label,
  checked,
  disabled,
  onChange
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-60 ${
        checked ? "bg-violet" : "bg-sky-deep"
      }`}
    >
      <span
        className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0.5"}`}
      />
    </button>
  );
}

function RecentTasks({ tasks }: { tasks: AgentTask[] }) {
  const { canWrite } = useAuth();
  const queryClient = useQueryClient();
  const act = useMutation({
    mutationFn: ({ id, what }: { id: number; what: "retry" | "manual" }) =>
      api<AgentTask>(`/agent/tasks/${id}/${what}`, { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["agent"] })
  });
  return (
    <section aria-labelledby="recent-tasks">
      <h2 id="recent-tasks">Dernières tâches</h2>
      {act.error && (
        <div className="mt-3">
          <ErrorNote error={act.error} />
        </div>
      )}
      {tasks.length === 0 ? (
        <p className="mt-3 text-ink-soft">
          Aucune tâche pour l'instant. Les réponses aux demandes venues d'un portail et les relèves programmées
          apparaîtront ici.
        </p>
      ) : (
        <div className="panel relative mt-4 overflow-x-auto">
          <table className="w-full min-w-[860px] text-[14px]">
            <caption className="sr-only">Dernières tâches de l'agent</caption>
            <thead>
              <tr className="border-b border-line text-left text-[12px] text-ink-faint">
                <th className="px-5 py-3 font-normal">Tâche</th>
                <th className="px-2 py-3 font-normal">État</th>
                <th className="px-2 py-3 font-normal">Parcours des moteurs</th>
                <th className="px-2 py-3 text-right font-normal">Coût</th>
                <th className="px-5 py-3 font-normal">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => {
                const st = TASK_STATUS[t.status] ?? { text: t.status, tone: "bg-sky-deep" };
                const stuck = t.status === "needs_human" || t.status === "failed";
                return (
                  <tr key={t.id} className="border-b border-line align-top last:border-0">
                    <td className="px-5 py-3">
                      <p className="font-bold">{TASKS[t.kind]?.title ?? t.kind}</p>
                      <p className="text-[12px] text-ink-faint">
                        {fmtDateTime(t.updated_at)}
                        {t.request_id ? `, demande n° ${t.request_id}` : ""}
                        {t.result?.created != null ? `, ${t.result.created} nouvelle(s)` : ""}
                      </p>
                    </td>
                    <td className="px-2 py-3">
                      <span className={`chip ${st.tone}`}>{st.text}</span>
                      {t.status === "pending" && t.available_at && <p className="mt-1 text-[12px] text-ink-soft">Nouvel essai après {fmtDateTime(t.available_at)}</p>}
                      {stuck && t.reconcile_only && <p className="mt-1 max-w-[260px] text-[12px] text-ink-soft">La reprise vérifie la réponse enregistrée, sans la renvoyer.</p>}
                      {t.summary && stuck && <p className="mt-1 max-w-[260px] text-[12px] text-ink-soft">{t.summary}</p>}
                    </td>
                    <td className="px-2 py-3">
                      <EngineJourney steps={t.route ?? []} cost={t.cost_usd} />
                    </td>
                    <td className="num px-2 py-3 text-right">{t.cost_usd ? fmtUsd(t.cost_usd, 3) : "0"}</td>
                    <td className="px-5 py-3 text-right">
                      {canWrite && stuck && (
                        <div className="flex justify-end gap-2">
                          <button
                            className="btn-quiet px-3 py-1.5 text-[13px]"
                            disabled={act.isPending}
                            onClick={() => act.mutate({ id: t.id, what: "retry" })}
                          >
                            <RotateCcw className="h-3.5 w-3.5" aria-hidden /> {t.reconcile_only ? "Vérifier le portail" : "Relancer"}
                          </button>
                          <button
                            className="btn-quiet px-3 py-1.5 text-[13px]"
                            disabled={act.isPending}
                            onClick={() => act.mutate({ id: t.id, what: "manual" })}
                          >
                            Fait à la main
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-[13px] text-ink-faint">
        {fmtNum(tasks.length)} tâches affichées, les plus récentes d'abord.
      </p>
    </section>
  );
}
