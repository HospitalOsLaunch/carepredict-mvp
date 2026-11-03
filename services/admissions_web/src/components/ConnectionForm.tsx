import { AlertTriangle, Archive, KeyRound, Lock } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import type { ConnectionKind, ConnectionOut, ConnectionTask, WorkerOut, WorkerPlaybook } from "../api/types_agent";
import { KIND_LABEL, TASK_LABEL, TASKS_BY_KIND, useArchiveConnection, useSaveConnection } from "../lib/agent";
import { fmtDateTime } from "../lib/format";
import { useSites } from "../lib/queries";
import { ErrorNote, Modal } from "./common";

export const WEEKDAYS: Array<[number, string, string]> = [
  [1, "lun.", "lundi"],
  [2, "mar.", "mardi"],
  [3, "mer.", "mercredi"],
  [4, "jeu.", "jeudi"],
  [5, "ven.", "vendredi"],
  [6, "sam.", "samedi"],
  [7, "dim.", "dimanche"]
];

/** Scripts reported by the workers for one kind of software, once each. */
export function catalogue(workers: WorkerOut[], kind: ConnectionKind): WorkerPlaybook[] {
  const byName = new Map<string, WorkerPlaybook>();
  for (const w of workers) for (const p of w.playbooks) if (p.kind === kind && !byName.has(p.name)) byName.set(p.name, p);
  return [...byName.values()];
}

function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

export function ConnectionForm({
  connection: c,
  workers,
  onClose,
  onDone
}: {
  connection?: ConnectionOut;
  workers: WorkerOut[];
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const sites = useSites();
  const save = useSaveConnection(c?.id ?? null);
  const archive = useArchiveConnection();
  const [kind, setKind] = useState<ConnectionKind>(c?.kind ?? "portail_orientation");
  const scripts = useMemo(() => catalogue(workers, kind), [workers, kind]);
  const [f, setF] = useState(() => ({
    name: c?.name ?? "",
    site: c?.site_id == null ? "" : String(c.site_id),
    url: c?.url ?? "",
    hosts: (c?.allowed_hosts ?? []).filter((h) => h !== hostOf(c?.url ?? "")).join(", "),
    username: c?.username ?? "",
    playbook: c?.playbook ?? catalogue(workers, "portail_orientation")[0]?.name ?? "",
    source: c?.source_system ?? "",
    interval: String(c?.interval_minutes ?? 15),
    from: c?.active_from ?? "",
    to: c?.active_to ?? "",
    agent: c?.agent_id ?? ""
  }));
  const [tasks, setTasks] = useState<ConnectionTask[]>(c?.tasks ?? [...TASKS_BY_KIND.portail_orientation]);
  const [days, setDays] = useState<number[]>(c?.days ?? [1, 2, 3, 4, 5, 6, 7]);
  // The password is write-only: never pre-filled, sent only when typed.
  const [secret, setSecret] = useState("");
  const [secretMode, setSecretMode] = useState<"keep" | "replace" | "clear">(c?.secret_set ? "keep" : "replace");
  const [confirmArchive, setConfirmArchive] = useState(false);

  const set = (key: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [key]: e.target.value });
  const changeKind = (next: ConnectionKind) => {
    setKind(next);
    setTasks([...TASKS_BY_KIND[next]]);
    setF({ ...f, playbook: catalogue(workers, next)[0]?.name ?? "" });
  };
  const kindTasks: readonly ConnectionTask[] = TASKS_BY_KIND[kind];
  const missingDays = days.length === 0;
  const missingTasks = !tasks.some((t) => kindTasks.includes(t));
  const knownScript = scripts.some((p) => p.name === f.playbook);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (missingDays || missingTasks) return;
    const body = {
      name: f.name.trim(),
      site_id: f.site ? Number(f.site) : null,
      url: f.url.trim(),
      allowed_hosts: f.hosts.split(/[\s,;]+/).filter(Boolean),
      username: f.username.trim() || null,
      playbook: f.playbook.trim(),
      tasks: tasks.filter((t) => kindTasks.includes(t)),
      source_system: kind === "gestion_lits" ? f.source.trim() || null : null,
      interval_minutes: Number(f.interval),
      active_from: f.from || null,
      active_to: f.to || null,
      days: [...days].sort((a, b) => a - b),
      agent_id: f.agent || null,
      ...(secretMode === "replace" && secret ? { secret } : {}),
      ...(secretMode === "clear" ? { clear_secret: true as const } : {})
    };
    save.mutate(c ? body : { ...body, kind }, {
      onSuccess: () => {
        onDone(c ? `« ${body.name} » est enregistrée.` : `« ${body.name} » est créée, à l'arrêt : démarrez-la quand vous êtes prêt.`);
        onClose();
      }
    });
  };

  return (
    <Modal title={c ? `Modifier « ${c.name} »` : "Nouvelle connexion"} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="field" htmlFor="cx-name">
              Nom
            </label>
            <input id="cx-name" required maxLength={120} className="input" value={f.name} onChange={set("name")} placeholder="Portail régional, site Nord" />
          </div>
          <div>
            <label className="field" htmlFor="cx-kind">
              Logiciel lu
            </label>
            <select
              id="cx-kind"
              className="input"
              value={kind}
              disabled={!!c}
              aria-describedby={c ? "cx-kind-hint" : undefined}
              onChange={(e) => changeKind(e.target.value as ConnectionKind)}
            >
              {(Object.keys(KIND_LABEL) as ConnectionKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
            {c && (
              <p id="cx-kind-hint" className="mt-1 text-[13px] text-ink-faint">
                Pour un autre logiciel, créez une nouvelle connexion.
              </p>
            )}
          </div>
          <div>
            <label className="field" htmlFor="cx-site">
              Établissement
            </label>
            <select id="cx-site" className="input" value={f.site} onChange={set("site")}>
              <option value="">Tout le groupe</option>
              {sites.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <fieldset className="space-y-4">
          <legend className="font-display text-[17px] font-bold">Accès au logiciel</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="field" htmlFor="cx-url">
                Adresse
              </label>
              <input id="cx-url" type="url" required className="input" value={f.url} onChange={set("url")} placeholder="https://portail.exemple.fr" />
            </div>
            <div className="sm:col-span-2">
              <label className="field" htmlFor="cx-hosts">
                Autres adresses autorisées
              </label>
              <input id="cx-hosts" className="input" value={f.hosts} onChange={set("hosts")} aria-describedby="cx-hosts-hint" placeholder="sso.exemple.fr" />
              <p id="cx-hosts-hint" className="mt-1 text-[13px] text-ink-faint">
                Facultatif, séparées par des virgules. L'agent ne navigue jamais ailleurs que sur ces adresses et celle du logiciel.
              </p>
            </div>
            <div>
              <label className="field" htmlFor="cx-user">
                Identifiant
              </label>
              <input id="cx-user" autoComplete="off" className="input" value={f.username} onChange={set("username")} />
            </div>
            <div>
              {secretMode === "keep" ? (
                <>
                  <p className="field">Mot de passe</p>
                  <p className="mt-1 flex items-center gap-2 rounded-xl bg-lagoon-soft px-3 py-2 text-[15px] text-lagoon-dark">
                    <Lock className="h-4 w-4 shrink-0" aria-hidden /> Défini le {fmtDateTime(c?.secret_updated_at)}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button type="button" className="btn-quiet px-3 py-1.5 text-[14px]" onClick={() => setSecretMode("replace")}>
                      <KeyRound className="h-4 w-4" aria-hidden /> Remplacer
                    </button>
                    <button type="button" className="btn-danger px-3 py-1.5 text-[14px]" onClick={() => setSecretMode("clear")}>
                      Effacer le mot de passe
                    </button>
                  </div>
                </>
              ) : secretMode === "clear" ? (
                <>
                  <p className="field">Mot de passe</p>
                  <p role="status" className="mt-1 rounded-xl bg-coral-soft px-3 py-2 text-[15px] text-coral-dark">
                    Il sera effacé à l'enregistrement.
                  </p>
                  <button type="button" className="btn-ghost mt-2 px-3 py-1.5 text-[14px]" onClick={() => setSecretMode("keep")}>
                    Garder le mot de passe
                  </button>
                </>
              ) : (
                <>
                  <label className="field" htmlFor="cx-secret">
                    {c?.secret_set ? "Nouveau mot de passe" : "Mot de passe"}
                  </label>
                  <input
                    id="cx-secret"
                    type="password"
                    autoComplete="new-password"
                    className="input"
                    value={secret}
                    onChange={(e) => setSecret(e.target.value)}
                    aria-describedby="cx-secret-hint"
                  />
                  <p id="cx-secret-hint" className="mt-1 text-[13px] text-ink-faint">
                    Chiffré dès l'enregistrement : personne ne pourra le relire ici, pas même vous.
                  </p>
                  {c?.secret_set && (
                    <button
                      type="button"
                      className="btn-ghost mt-1 px-3 py-1.5 text-[14px]"
                      onClick={() => {
                        setSecret("");
                        setSecretMode("keep");
                      }}
                    >
                      Garder l'ancien
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="font-display text-[17px] font-bold">Ce que fait l'agent</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="field" htmlFor="cx-playbook">
                Script
              </label>
              {scripts.length > 0 ? (
                <select id="cx-playbook" required className="input" value={f.playbook} onChange={set("playbook")}>
                  {!knownScript && <option value={f.playbook}>{f.playbook ? `${f.playbook} (signalé par aucun poste)` : "Choisir"}</option>}
                  {scripts.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.label}
                    </option>
                  ))}
                </select>
              ) : (
                <>
                  <input id="cx-playbook" required className="input" value={f.playbook} onChange={set("playbook")} aria-describedby="cx-playbook-hint" />
                  <p id="cx-playbook-hint" className="mt-1 flex items-start gap-1.5 text-[13px] text-coral-dark">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                    Aucun poste n'a encore signalé de script pour ce logiciel : saisissez son nom exact.
                  </p>
                </>
              )}
            </div>
            {kind === "gestion_lits" && (
              <div>
                <label className="field" htmlFor="cx-source">
                  Code de la source
                </label>
                <input id="cx-source" className="input" value={f.source} onChange={set("source")} aria-describedby="cx-source-hint" placeholder="bedsoft" />
                <p id="cx-source-hint" className="mt-1 text-[13px] text-ink-faint">
                  Facultatif. Ajouté aux sources autorisées du compte du poste.
                </p>
              </div>
            )}
          </div>
          <div>
            <p className="field" id="cx-tasks">
              Tâches
            </p>
            <div role="group" aria-labelledby="cx-tasks" className="mt-1 flex flex-wrap gap-2">
              {kindTasks.map((t) => (
                <label key={t} className="flex items-center gap-2 rounded-xl border border-line px-3 py-2 hover:bg-sky">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-violet"
                    checked={tasks.includes(t)}
                    onChange={(e) => setTasks(e.target.checked ? [...tasks, t] : tasks.filter((x) => x !== t))}
                  />
                  {TASK_LABEL[t]}
                </label>
              ))}
            </div>
            {missingTasks && <p className="mt-1 text-[13px] text-coral-dark">Cochez au moins une tâche.</p>}
          </div>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="font-display text-[17px] font-bold">Planning</legend>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="col-span-2 sm:col-span-1">
              <label className="field" htmlFor="cx-interval">
                Toutes les (min)
              </label>
              <input id="cx-interval" type="number" required min={1} max={1440} className="input num" value={f.interval} onChange={set("interval")} />
            </div>
            <div>
              <label className="field" htmlFor="cx-from">
                De
              </label>
              <input id="cx-from" type="time" className="input num" value={f.from} onChange={set("from")} />
            </div>
            <div>
              <label className="field" htmlFor="cx-to">
                À
              </label>
              <input id="cx-to" type="time" className="input num" value={f.to} onChange={set("to")} />
            </div>
            <div className="col-span-2 sm:col-span-1">
              <label className="field" htmlFor="cx-agent">
                Poste
              </label>
              <select id="cx-agent" className="input" value={f.agent} onChange={set("agent")}>
                <option value="">N'importe quel poste</option>
                {workers.map((w) => (
                  <option key={w.agent_id} value={w.agent_id}>
                    {w.agent_id}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-[13px] text-ink-faint">Sans heures, l'agent relève toute la journée.</p>
          <div>
            <p className="field" id="cx-days">
              Jours
            </p>
            <div role="group" aria-labelledby="cx-days" className="mt-1 flex flex-wrap gap-2">
              {WEEKDAYS.map(([n, short, long]) => {
                const on = days.includes(n);
                return (
                  <button
                    key={n}
                    type="button"
                    aria-pressed={on}
                    aria-label={long}
                    onClick={() => setDays(on ? days.filter((d) => d !== n) : [...days, n])}
                    className={`rounded-chip px-3 py-1.5 text-[14px] font-bold transition-colors ${on ? "bg-violet text-white" : "bg-sky text-ink-soft hover:bg-sky-deep"}`}
                  >
                    {short}
                  </button>
                );
              })}
            </div>
            {missingDays && <p className="mt-1 text-[13px] text-coral-dark">Choisissez au moins un jour.</p>}
          </div>
        </fieldset>

        {(save.error || archive.error) && <ErrorNote error={save.error ?? archive.error} />}

        {confirmArchive && c ? (
          <div role="alertdialog" aria-labelledby="cx-archive-q" className="rounded-xl bg-coral-soft px-4 py-3">
            <p id="cx-archive-q" className="font-bold text-coral-dark">
              Archiver « {c.name} » ?
            </p>
            <p className="mt-1 text-[14px] text-ink-soft">Elle disparaît de la liste et ses tâches en attente sont annulées.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className="btn bg-coral-dark text-white hover:bg-coral-dark/90"
                disabled={archive.isPending}
                onClick={() =>
                  archive.mutate(c.id, {
                    onSuccess: () => {
                      onDone(`« ${c.name} » est archivée.`);
                      onClose();
                    }
                  })
                }
              >
                Oui, archiver
              </button>
              <button type="button" className="btn-ghost" onClick={() => setConfirmArchive(false)}>
                Non, la garder
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap justify-end gap-2">
            {c && (
              <button type="button" className="btn-danger mr-auto" onClick={() => setConfirmArchive(true)}>
                <Archive className="h-4 w-4" aria-hidden /> Archiver
              </button>
            )}
            <button type="button" className="btn-ghost" onClick={onClose}>
              Annuler
            </button>
            <button type="submit" className="btn-primary" disabled={save.isPending || missingDays || missingTasks}>
              {c ? "Enregistrer" : "Créer la connexion"}
            </button>
          </div>
        )}
      </form>
    </Modal>
  );
}
