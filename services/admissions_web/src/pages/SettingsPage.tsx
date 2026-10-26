import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Lock, Plus, Unlock } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { AuditEntry, GroupSettings, Site, User } from "../api/types";
import { useAuth } from "../auth";
import { ErrorNote, Modal, PageHeader, Spinner } from "../components/ui";
import { fmtDate, fmtDateTime, fmtPct } from "../lib/format";
import { label, useSites, useVocabulary } from "../lib/queries";
import { AgentTab } from "./AgentSettings";

type Tab = "sites" | "utilisateurs" | "contrat" | "priorite" | "charge" | "agent" | "audit";

const TABS: Array<{ value: Tab; label: string }> = [
  { value: "sites", label: "Sites et lits" },
  { value: "utilisateurs", label: "Utilisateurs" },
  { value: "contrat", label: "Référence et contrat" },
  { value: "priorite", label: "Priorisation" },
  { value: "charge", label: "Charge en soins" },
  { value: "agent", label: "Agent et routage" },
  { value: "audit", label: "Journal d'audit" }
];

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>("sites");
  return (
    <>
      <PageHeader title="Paramètres du groupe" />
      <div role="tablist" aria-label="Rubriques" className="mb-6 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.value}
            role="tab"
            aria-selected={tab === t.value}
            onClick={() => setTab(t.value)}
            className={`rounded-chip px-4 py-2 text-[15px] font-bold ${
              tab === t.value ? "bg-ink text-white" : "bg-paper text-ink-soft shadow-lift hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "sites" && <SitesTab />}
      {tab === "utilisateurs" && <UsersTab />}
      {tab === "contrat" && <ContractTab />}
      {tab === "priorite" && <WeightsTab />}
      {tab === "charge" && <CareMinutesTab />}
      {tab === "agent" && <AgentTab />}
      {tab === "audit" && <AuditTab />}
    </>
  );
}

function useInvalidateAll() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries();
}

function SitesTab() {
  const sites = useSites();
  const vocab = useVocabulary();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Site | null>(null);
  const [pool, setPool] = useState<Site | null>(null);
  if (sites.isLoading) return <Spinner />;
  if (sites.error) return <ErrorNote error={sites.error} />;
  return (
    <div className="space-y-4">
      <button className="btn-primary" onClick={() => setAdding(true)}>
        <Plus className="h-4 w-4" aria-hidden /> Ajouter un site
      </button>
      {sites.data?.map((s) => (
        <section key={s.id} className={`panel px-6 py-5 ${s.active ? "" : "opacity-60"}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2>
                {s.name}
                {!s.active && <span className="ml-2 font-sans text-[14px] text-ink-faint">inactif</span>}
              </h2>
              <p className="text-[14px] text-ink-soft">
                {[s.city, s.finess ? `FINESS ${s.finess}` : null].filter(Boolean).join(", ") || "Ville et FINESS non renseignés"}
              </p>
              <p className="mt-1 text-[14px] text-ink-soft">
                Prend en charge :{" "}
                {s.capabilities.length
                  ? s.capabilities.map((c) => label(vocab.data?.special_needs, c)).join(", ")
                  : "aucun besoin technique déclaré"}
              </p>
            </div>
            <div className="flex gap-2">
              <button className="btn-quiet" onClick={() => setEditing(s)}>
                Modifier
              </button>
              <button className="btn-quiet" onClick={() => setPool(s)}>
                Ajouter une mention
              </button>
            </div>
          </div>
          <table className="mt-4 w-full text-[15px]">
            <caption className="sr-only">Lits de {s.name}</caption>
            <thead>
              <tr className="text-left text-[13px] text-ink-faint">
                <th className="py-1 font-normal">Mention</th>
                <th className="py-1 text-right font-normal">Installés</th>
                <th className="py-1 text-right font-normal">Ouverts</th>
                <th className="py-1 text-right font-normal">Isolement</th>
                <th className="py-1 text-right font-normal">Occupés</th>
              </tr>
            </thead>
            <tbody>
              {s.pools.map((p) => (
                <tr key={p.mention} className="border-t border-line">
                  <td className="py-2">{label(vocab.data?.mentions, p.mention)}</td>
                  <td className="num py-2 text-right">{p.beds_installed}</td>
                  <td className={`num py-2 text-right ${p.beds_open < p.beds_installed ? "font-bold text-coral-dark" : ""}`}>{p.beds_open}</td>
                  <td className="num py-2 text-right">{p.isolation_rooms}</td>
                  <td className="num py-2 text-right">{p.occupied}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {adding && <SiteModal onClose={() => setAdding(false)} />}
      {editing && <SiteModal site={editing} onClose={() => setEditing(null)} />}
      {pool && <NewPoolModal site={pool} onClose={() => setPool(null)} />}
    </div>
  );
}

function SiteModal({ site, onClose }: { site?: Site; onClose: () => void }) {
  const vocab = useVocabulary();
  const invalidate = useInvalidateAll();
  const [name, setName] = useState(site?.name ?? "");
  const [finess, setFiness] = useState(site?.finess ?? "");
  const [city, setCity] = useState(site?.city ?? "");
  const [caps, setCaps] = useState<string[]>(site?.capabilities ?? []);
  const [active, setActive] = useState(site?.active ?? true);
  const save = useMutation({
    mutationFn: () =>
      api<Site>(site ? `/sites/${site.id}` : "/sites", {
        method: site ? "PATCH" : "POST",
        json: {
          name: name.trim(),
          finess: finess.trim() || null,
          city: city.trim() || null,
          capabilities: caps,
          ...(site ? { active } : {})
        }
      }),
    onSuccess: () => {
      invalidate();
      onClose();
    }
  });
  return (
    <Modal title={site ? `Modifier ${site.name}` : "Ajouter un site"} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
        className="space-y-4"
      >
        <div>
          <label className="field" htmlFor="s-name">
            Nom
          </label>
          <input id="s-name" required className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="field" htmlFor="s-finess">
              FINESS
            </label>
            <input id="s-finess" className="input" maxLength={9} value={finess} onChange={(e) => setFiness(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="s-city">
              Ville
            </label>
            <input id="s-city" className="input" value={city} onChange={(e) => setCity(e.target.value)} />
          </div>
        </div>
        <fieldset>
          <legend className="field">Besoins techniques pris en charge</legend>
          <div className="mt-2 grid grid-cols-2 gap-1">
            {Object.entries(vocab.data?.special_needs ?? {}).map(([code, text]) => (
              <label key={code} className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-sky">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-violet"
                  checked={caps.includes(code)}
                  onChange={(e) => setCaps(e.target.checked ? [...caps, code] : caps.filter((c) => c !== code))}
                />
                {text}
              </label>
            ))}
          </div>
        </fieldset>
        {site && (
          <label className="flex items-center gap-2">
            <input type="checkbox" className="h-4 w-4 accent-violet" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Site actif (reçoit des demandes)
          </label>
        )}
        {save.error && <ErrorNote error={save.error} />}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            {site ? "Enregistrer le site" : "Ajouter le site"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function NewPoolModal({ site, onClose }: { site: Site; onClose: () => void }) {
  const vocab = useVocabulary();
  const invalidate = useInvalidateAll();
  const [mention, setMention] = useState("");
  const [beds, setBeds] = useState("20");
  const [isolation, setIsolation] = useState("2");
  const save = useMutation({
    mutationFn: () =>
      api<Site>(`/sites/${site.id}/pools/${mention}`, {
        method: "PUT",
        json: {
          beds_installed: Number(beds),
          beds_open: Number(beds),
          isolation_rooms: Number(isolation),
          reason: "ouverture"
        }
      }),
    onSuccess: () => {
      invalidate();
      onClose();
    }
  });
  const existing = new Set(site.pools.map((p) => p.mention));
  return (
    <Modal title={`Ajouter une mention à ${site.name}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
        className="space-y-4"
      >
        <div>
          <label className="field" htmlFor="np-mention">
            Mention
          </label>
          <select id="np-mention" required className="input" value={mention} onChange={(e) => setMention(e.target.value)}>
            <option value="" disabled>
              Choisir
            </option>
            {Object.entries(vocab.data?.mentions ?? {})
              .filter(([code]) => !existing.has(code))
              .map(([code, text]) => (
                <option key={code} value={code}>
                  {text}
                </option>
              ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="field" htmlFor="np-beds">
              Lits installés et ouverts
            </label>
            <input id="np-beds" type="number" min={1} className="input" value={beds} onChange={(e) => setBeds(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="np-iso">
              Chambres d'isolement
            </label>
            <input id="np-iso" type="number" min={0} className="input" value={isolation} onChange={(e) => setIsolation(e.target.value)} />
          </div>
        </div>
        {save.error && <ErrorNote error={save.error} />}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn-primary" disabled={!mention || save.isPending}>
            Ajouter la mention
          </button>
        </div>
      </form>
    </Modal>
  );
}

function UsersTab() {
  const vocab = useVocabulary();
  const sites = useSites();
  const { user: me } = useAuth();
  const invalidate = useInvalidateAll();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const [adding, setAdding] = useState(false);
  const [linking, setLinking] = useState<User | null>(null);
  const toggle = useMutation({
    mutationFn: (u: User) => api<User>(`/users/${u.id}`, { method: "PATCH", json: { active: !u.active } }),
    onSuccess: invalidate
  });
  const siteName = (id: number | null) => sites.data?.find((s) => s.id === id)?.name ?? "Tous les sites";
  return (
    <div>
      <button className="btn-primary mb-4" onClick={() => setAdding(true)}>
        <Plus className="h-4 w-4" aria-hidden /> Ajouter un utilisateur
      </button>
      {users.isLoading && <Spinner />}
      {users.error && <ErrorNote error={users.error} />}
      {toggle.error && <ErrorNote error={toggle.error} />}
      <div className="panel relative overflow-x-auto">
        <table className="w-full min-w-[760px] text-[15px]">
          <caption className="sr-only">Utilisateurs</caption>
          <thead>
            <tr className="border-b border-line text-left text-[13px] text-ink-faint">
              <th className="px-5 py-3 font-normal">Nom</th>
              <th className="px-3 py-3 font-normal">Rôle</th>
              <th className="px-3 py-3 font-normal">Périmètre</th>
              <th className="px-3 py-3 font-normal">Identité fédérée</th>
              <th className="px-5 py-3 font-normal">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} className={`border-b border-line last:border-0 ${u.active ? "" : "text-ink-faint"}`}>
                <td className="px-5 py-3">
                  <p className="font-bold">{u.full_name}</p>
                  <p className="text-[13px] text-ink-faint">{u.email}</p>
                </td>
                <td className="px-3 py-3">{label(vocab.data?.roles, u.role)}</td>
                <td className="px-3 py-3">{u.role === "coordination" ? siteName(u.site_id) : "Tout le groupe"}</td>
                <td className="px-3 py-3">
                  {u.role === "ingestion" ? (
                    <span className="text-[13px] text-ink-faint">Compte de service, mot de passe</span>
                  ) : (
                    <button className="btn-ghost -ml-2 px-2 py-1 text-left text-[14px]" onClick={() => setLinking(u)}>
                      {u.oidc_subject ? (
                        <span className="flex items-center gap-1.5">
                          <BadgeCheck className="h-4 w-4 text-lagoon" aria-hidden />
                          <span className="num">{u.oidc_subject}</span>
                        </span>
                      ) : (
                        <span className="text-ink-faint">Lié à la 1re connexion</span>
                      )}
                    </button>
                  )}
                </td>
                <td className="px-5 py-3 text-right">
                  {u.id !== me?.id && (
                    <button className="btn-quiet px-3 py-1.5 text-[14px]" onClick={() => toggle.mutate(u)}>
                      {u.active ? "Désactiver" : "Réactiver"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {adding && <UserModal onClose={() => setAdding(false)} />}
      {linking && <IdentityModal user={linking} onClose={() => setLinking(null)} />}
    </div>
  );
}

function IdentityModal({ user, onClose }: { user: User; onClose: () => void }) {
  const invalidate = useInvalidateAll();
  const [subject, setSubject] = useState(user.oidc_subject ?? "");
  const save = useMutation({
    mutationFn: (value: string | null) =>
      api<User>(`/users/${user.id}`, { method: "PATCH", json: { oidc_subject: value ?? "" } }),
    onSuccess: () => {
      invalidate();
      onClose();
    }
  });
  return (
    <Modal title={`Identité fédérée, ${user.full_name}`} onClose={onClose}>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          save.mutate(subject.trim() || null);
        }}
      >
        <p className="text-ink-soft">
          Identifiant transmis par le fournisseur d'identité (Pro Santé Connect : identifiant national, RPPS précédé de 8 ;
          annuaire de l'établissement : identifiant de l'agent). Laissez vide pour lier le compte automatiquement à la première
          connexion, par l'adresse e-mail ou l'identifiant configuré.
        </p>
        <label className="field mt-4" htmlFor="oidc-sub">
          Identifiant
        </label>
        <input id="oidc-sub" className="input num" maxLength={255} value={subject} onChange={(e) => setSubject(e.target.value)} />
        {save.error && (
          <div className="mt-3">
            <ErrorNote error={save.error} />
          </div>
        )}
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          {user.oidc_subject && (
            <button type="button" className="btn-danger mr-auto" disabled={save.isPending} onClick={() => save.mutate(null)}>
              Délier
            </button>
          )}
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            Enregistrer
          </button>
        </div>
      </form>
    </Modal>
  );
}

function UserModal({ onClose }: { onClose: () => void }) {
  const vocab = useVocabulary();
  const sites = useSites();
  const invalidate = useInvalidateAll();
  const [form, setForm] = useState({ email: "", full_name: "", role: "coordination", site_id: "", password: "" });
  const save = useMutation({
    mutationFn: () =>
      api<User>("/users", {
        method: "POST",
        json: { ...form, site_id: form.site_id ? Number(form.site_id) : null }
      }),
    onSuccess: () => {
      invalidate();
      onClose();
    }
  });
  return (
    <Modal title="Ajouter un utilisateur" onClose={onClose}>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          save.mutate();
        }}
        className="space-y-4"
      >
        <div>
          <label className="field" htmlFor="u-name">
            Nom et prénom
          </label>
          <input id="u-name" required className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        </div>
        <div>
          <label className="field" htmlFor="u-email">
            Adresse e-mail
          </label>
          <input id="u-email" type="email" required className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="field" htmlFor="u-role">
              Rôle
            </label>
            <select id="u-role" className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {Object.entries(vocab.data?.roles ?? {}).map(([code, text]) => (
                <option key={code} value={code}>
                  {text}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="field" htmlFor="u-site">
              Limité au site
            </label>
            <select
              id="u-site"
              className="input"
              disabled={form.role !== "coordination"}
              value={form.site_id}
              onChange={(e) => setForm({ ...form, site_id: e.target.value })}
            >
              <option value="">Tous les sites</option>
              {sites.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="field" htmlFor="u-pw">
            Mot de passe initial
          </label>
          <input
            id="u-pw"
            type="password"
            minLength={10}
            required
            autoComplete="new-password"
            className="input"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          <p className="mt-1 text-[13px] text-ink-faint">10 caractères au moins. À transmettre par un canal séparé.</p>
        </div>
        {save.error && <ErrorNote error={save.error} />}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn-primary" disabled={save.isPending}>
            Ajouter l'utilisateur
          </button>
        </div>
      </form>
    </Modal>
  );
}

function useGroupSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api<GroupSettings>("/settings") });
}

function ContractTab() {
  const settings = useGroupSettings();
  const invalidate = useInvalidateAll();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [value, setValue] = useState("");
  const [rate, setRate] = useState("");
  const [unfreezing, setUnfreezing] = useState(false);
  const [reason, setReason] = useState("");
  const s = settings.data;

  useEffect(() => {
    if (!s) return;
    setStart(s.baseline.start ?? "");
    setEnd(s.baseline.end ?? "");
    setValue(String(s.value_per_bed_day));
    setRate(String(Math.round(s.success_fee_rate * 100)));
  }, [s]);

  const saveBaseline = useMutation({
    mutationFn: () => api<GroupSettings>("/settings/baseline", { method: "PUT", json: { start, end } }),
    onSuccess: invalidate
  });
  const saveContract = useMutation({
    mutationFn: () =>
      api<GroupSettings>("/settings", {
        method: "PUT",
        json: { value_per_bed_day: Number(value), success_fee_rate: Number(rate) / 100 }
      }),
    onSuccess: invalidate
  });
  const freeze = useMutation({
    mutationFn: () => api<GroupSettings>("/settings/baseline/freeze", { method: "POST" }),
    onSuccess: invalidate
  });
  const unfreeze = useMutation({
    mutationFn: () => api<GroupSettings>("/settings/baseline/unfreeze", { method: "POST", json: { reason } }),
    onSuccess: () => {
      invalidate();
      setUnfreezing(false);
      setReason("");
    }
  });

  if (settings.isLoading) return <Spinner />;
  if (settings.error) return <ErrorNote error={settings.error} />;
  if (!s) return null;
  const frozen = s.baseline.frozen_at !== null;

  return (
    <div className="max-w-3xl space-y-6">
      <section className={`panel px-6 py-5 ${frozen ? "ring-2 ring-sun" : ""}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2>{frozen ? "Référence gelée" : "Référence modifiable"}</h2>
          {frozen ? (
            <button className="btn-quiet" onClick={() => setUnfreezing(true)}>
              <Unlock className="h-4 w-4" aria-hidden /> Dégeler
            </button>
          ) : (
            <button
              className="btn-sun"
              disabled={!s.baseline.start || freeze.isPending}
              onClick={() => freeze.mutate()}
              title={!s.baseline.start ? "Enregistrez d'abord la période de référence" : undefined}
            >
              <Lock className="h-4 w-4" aria-hidden /> Geler la référence
            </button>
          )}
        </div>
        <p className="mt-2 text-ink-soft">
          {frozen
            ? `Gelée le ${fmtDateTime(s.baseline.frozen_at)}. Les données historiques, les capacités et les termes du contrat utilisés comme référence sont conservés. Les corrections ultérieures ne changent pas cette référence. Dégeler est tracé dans le journal d'audit.`
            : "Fixez la période de référence et les termes du contrat avant le démarrage du pilote, puis gelez-les avec l'établissement. Tant qu'elle n'est pas gelée, le résultat reste indicatif."}
        </p>
        {freeze.error && <ErrorNote error={freeze.error} />}

        <form
          className="mt-5 grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            saveBaseline.mutate();
          }}
        >
          <div>
            <label className="field" htmlFor="b-start">
              Référence du
            </label>
            <input id="b-start" type="date" className="input" disabled={frozen} value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="b-end">
              Au
            </label>
            <input id="b-end" type="date" className="input" disabled={frozen} value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <button className="btn-primary" type="submit" disabled={frozen || !start || !end || saveBaseline.isPending}>
            Enregistrer la période
          </button>
        </form>
        {saveBaseline.error && <div className="mt-3"><ErrorNote error={saveBaseline.error} /></div>}

        <form
          className="mt-5 grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            saveContract.mutate();
          }}
        >
          <div>
            <label className="field" htmlFor="c-value">
              Valeur d'une journée-lit (€)
            </label>
            <input id="c-value" type="number" min={0} step="1" className="input" disabled={frozen} value={value} onChange={(e) => setValue(e.target.value)} />
          </div>
          <div>
            <label className="field" htmlFor="c-rate">
              Intéressement (% de la valeur)
            </label>
            <input id="c-rate" type="number" min={0} max={100} step="1" className="input" disabled={frozen} value={rate} onChange={(e) => setRate(e.target.value)} />
          </div>
          <button className="btn-primary" type="submit" disabled={frozen || saveContract.isPending}>
            Enregistrer les termes
          </button>
        </form>
        {saveContract.error && <div className="mt-3"><ErrorNote error={saveContract.error} /></div>}
        <p className="mt-4 text-[14px] text-ink-soft">
          Actuellement : {s.baseline.start ? `du ${fmtDate(s.baseline.start)} au ${fmtDate(s.baseline.end)}` : "aucune période"},{" "}
          {s.value_per_bed_day.toLocaleString("fr-FR")} € la journée, intéressement de {fmtPct(s.success_fee_rate)} dû
          seulement si l'intervalle à 80 % est entièrement positif.
        </p>
      </section>

      {unfreezing && (
        <Modal title="Dégeler la référence" onClose={() => setUnfreezing(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              unfreeze.mutate();
            }}
          >
            <p className="text-ink-soft">
              Le motif est conservé dans le journal d'audit et visible par l'établissement.
            </p>
            <label className="field mt-4" htmlFor="uf-reason">
              Motif
            </label>
            <textarea id="uf-reason" required minLength={10} rows={3} className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
            {unfreeze.error && <div className="mt-3"><ErrorNote error={unfreeze.error} /></div>}
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setUnfreezing(false)}>
                Annuler
              </button>
              <button type="submit" className="btn-danger" disabled={reason.trim().length < 10 || unfreeze.isPending}>
                Dégeler la référence
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

const WEIGHT_LABELS: Record<string, string> = {
  disponibilite: "Lit disponible à la date souhaitée",
  attente: "Temps d'attente de la réponse",
  urgence: "Date d'entrée souhaitée proche",
  adresseur: "Adresseur régulier du groupe"
};

function WeightsTab() {
  const settings = useGroupSettings();
  const invalidate = useInvalidateAll();
  const [weights, setWeights] = useState<Record<string, number>>({});
  useEffect(() => {
    if (settings.data) setWeights(settings.data.scoring_weights);
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () => api<GroupSettings>("/settings", { method: "PUT", json: { scoring_weights: weights } }),
    onSuccess: invalidate
  });
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  if (settings.isLoading) return <Spinner />;
  return (
    <section className="panel max-w-2xl px-6 py-5">
      <h2>Ce qui fait monter une demande dans la file</h2>
      <p className="mt-1 text-ink-soft">Les poids sont ramenés à 100 %. Chaque demande affiche le détail de son score.</p>
      <div className="mt-5 space-y-5">
        {Object.keys(WEIGHT_LABELS).map((code) => (
          <div key={code}>
            <div className="flex justify-between">
              <label htmlFor={`w-${code}`} className="font-bold">
                {WEIGHT_LABELS[code]}
              </label>
              <span className="num font-bold">{fmtPct((weights[code] ?? 0) / total)}</span>
            </div>
            <input
              id={`w-${code}`}
              type="range"
              min={0}
              max={1}
              step={0.05}
              className="mt-2 w-full accent-violet"
              value={weights[code] ?? 0}
              onChange={(e) => setWeights({ ...weights, [code]: Number(e.target.value) })}
            />
          </div>
        ))}
      </div>
      {save.error && <div className="mt-3"><ErrorNote error={save.error} /></div>}
      <button className="btn-primary mt-6" onClick={() => save.mutate()} disabled={save.isPending}>
        Enregistrer la priorisation
      </button>
      {save.isSuccess && <p className="mt-2 text-[14px] text-lagoon-dark" role="status">Priorisation enregistrée.</p>}
    </section>
  );
}

const CARE_KEYS: Array<{ key: string; label: string; hint: string }> = [
  { key: "1", label: "Niveau 1, léger", hint: "autonome, surveillance simple" },
  { key: "2", label: "Niveau 2, modéré", hint: "aide partielle aux actes de la vie quotidienne" },
  { key: "3", label: "Niveau 3, lourd", hint: "aide totale, soins techniques fréquents" },
  { key: "4", label: "Niveau 4, très lourd", hint: "dépendance totale, soins techniques lourds" },
  { key: "entree", label: "Surcroît d'une entrée", hint: "accueil, recueil, installation" },
  { key: "sortie", label: "Surcroît d'une sortie", hint: "préparation, transmissions, lit" }
];

function CareMinutesTab() {
  const settings = useGroupSettings();
  const invalidate = useInvalidateAll();
  const [minutes, setMinutes] = useState<Record<string, string>>({});
  useEffect(() => {
    if (settings.data) setMinutes(Object.fromEntries(Object.entries(settings.data.care_minutes).map(([k, v]) => [k, String(v)])));
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () =>
      api<GroupSettings>("/settings", {
        method: "PUT",
        json: { care_minutes: Object.fromEntries(Object.entries(minutes).map(([k, v]) => [k, Number(v)])) }
      }),
    onSuccess: invalidate
  });
  if (settings.isLoading) return <Spinner />;
  if (settings.error) return <ErrorNote error={settings.error} />;
  return (
    <section className="panel max-w-3xl px-6 py-5">
      <h2>Minutes de soins par jour et par patient</h2>
      <p className="mt-1 text-ink-soft">
        La charge prévue multiplie ces minutes par la probabilité de présence de chaque patient. Les valeurs de départ sont des
        hypothèses : calez-les sur l'outil de mesure de charge de vos unités (temps soignant observé par niveau), puis vérifiez
        l'écart dans le rejeu de la page Charge en soins.
      </p>
      <form
        className="mt-5"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {CARE_KEYS.map((c) => (
            <div key={c.key}>
              <label className="field" htmlFor={`cm-${c.key}`}>
                {c.label}
              </label>
              <div className="flex items-center gap-2">
                <input
                  id={`cm-${c.key}`}
                  type="number"
                  min={0}
                  max={1440}
                  step={5}
                  required
                  className="input num"
                  value={minutes[c.key] ?? ""}
                  onChange={(e) => setMinutes({ ...minutes, [c.key]: e.target.value })}
                  aria-describedby={`cm-${c.key}-hint`}
                />
                <span className="mt-1 text-ink-soft">min</span>
              </div>
              <p id={`cm-${c.key}-hint`} className="mt-1 text-[13px] text-ink-faint">
                {c.hint}
              </p>
            </div>
          ))}
        </div>
        {save.error && (
          <div className="mt-3">
            <ErrorNote error={save.error} />
          </div>
        )}
        <button className="btn-primary mt-6" type="submit" disabled={save.isPending}>
          Enregistrer les minutes
        </button>
        {save.isSuccess && (
          <p className="mt-2 text-[14px] text-lagoon-dark" role="status">
            Minutes enregistrées. La charge prévue est recalculée.
          </p>
        )}
      </form>
    </section>
  );
}

function AuditTab() {
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api<AuditEntry[]>("/audit?limit=300") });
  if (audit.isLoading) return <Spinner />;
  if (audit.error) return <ErrorNote error={audit.error} />;
  return (
    <div className="panel relative overflow-x-auto">
      <table className="w-full min-w-[720px] text-[14px]">
        <caption className="sr-only">Journal d'audit</caption>
        <thead>
          <tr className="border-b border-line text-left text-[13px] text-ink-faint">
            <th className="px-5 py-3 font-normal">Quand</th>
            <th className="px-3 py-3 font-normal">Qui</th>
            <th className="px-3 py-3 font-normal">Action</th>
            <th className="px-5 py-3 font-normal">Détail</th>
          </tr>
        </thead>
        <tbody>
          {audit.data?.map((a, i) => (
            <tr key={i} className="border-b border-line last:border-0">
              <td className="whitespace-nowrap px-5 py-2">{fmtDateTime(a.at)}</td>
              <td className="px-3 py-2">{a.user ?? "Système"}</td>
              <td className="px-3 py-2 font-bold">{a.action}</td>
              <td className="px-5 py-2 text-ink-soft">
                {a.entity}
                {a.entity_id ? ` ${a.entity_id}` : ""}
                {a.detail ? `, ${a.detail}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
