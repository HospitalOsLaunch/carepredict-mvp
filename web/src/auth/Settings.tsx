import { type FormEvent, useCallback, useEffect, useState } from "react";
import { HttpError } from "../api/http";
import { measurementId } from "../analytics";
import { useAccount } from "./AuthGate";
import { type Account, type Role, adminApi, settingsApi } from "./api";

const ROLE: Record<Role, string> = { admin: "Administrateur", pilot: "Pilote" };
const STATUS: Record<Account["status"], string> = { invited: "Invitation envoyée", active: "Actif", disabled: "Désactivé" };

function errorText(error: unknown): string {
  return error instanceof HttpError ? error.detail : "Service injoignable. Réessayez.";
}

function useAction() {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    setFeedback(null);
    try {
      setFeedback({ ok: true, text: await action() });
    } catch (error) {
      setFeedback({ ok: false, text: errorText(error) });
    } finally {
      setBusy(false);
    }
  };
  return { busy, feedback, run };
}

function Feedback({ value }: { value: { ok: boolean; text: string } | null }) {
  if (!value) return null;
  return (
    <p className={value.ok ? "notice" : "notice notice--error"} role={value.ok ? "status" : "alert"}>
      {value.text}
    </p>
  );
}

export function Settings({ units }: { units: Array<{ id: string; name: string }> }) {
  const account = useAccount();
  if (!account)
    return (
      <div className="stack">
        <header className="page-head">
          <h1>Paramètres</h1>
          <p>Démonstration hors ligne : aucun compte n'est connecté.</p>
        </header>
      </div>
    );
  return (
    <div className="stack settings">
      <header className="page-head">
        <h1>Paramètres</h1>
        <p>
          Connecté en tant que <strong>{account.me.email}</strong> · {ROLE[account.me.role]}
        </p>
      </header>
      <Profile units={units} />
      <Security />
      <Privacy />
      {account.me.role === "admin" ? <Administration /> : null}
      <section className="panel">
        <div className="panel__body settings__logout">
          <button type="button" className="btn" onClick={() => void account.logout()}>
            Se déconnecter
          </button>
        </div>
      </section>
    </div>
  );
}

function Profile({ units }: { units: Array<{ id: string; name: string }> }) {
  const account = useAccount()!;
  const [form, setForm] = useState({
    display_name: account.me.display_name,
    job_title: account.me.job_title,
    establishment: account.me.establishment,
    default_unit: account.me.default_unit,
  });
  const { busy, feedback, run } = useAction();
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      account.setMe((await settingsApi.save(form)).user);
      return "Profil enregistré.";
    });
  };
  return (
    <section className="panel" aria-labelledby="profil">
      <div className="panel__head">
        <h2 className="panel__title" id="profil">
          Profil
        </h2>
      </div>
      <form className="panel__body settings__form" onSubmit={submit}>
        <TextField id="display_name" label="Nom affiché" value={form.display_name} onChange={set("display_name")} max={80} />
        <TextField id="job_title" label="Fonction" value={form.job_title} onChange={set("job_title")} max={80} placeholder="Cadre de santé, gestionnaire de lits…" />
        <TextField id="establishment" label="Établissement" value={form.establishment} onChange={set("establishment")} max={120} />
        <div className="field">
          <label htmlFor="default_unit">Unité affichée à l'ouverture</label>
          <select id="default_unit" className="select" value={form.default_unit} onChange={(e) => set("default_unit")(e.target.value)}>
            <option value="">La première unité</option>
            {units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </div>
        <Feedback value={feedback} />
        <button className="btn btn--primary" type="submit" disabled={busy}>
          Enregistrer
        </button>
      </form>
    </section>
  );
}

function TextField(props: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  max: number;
  type?: string;
  autoComplete?: string;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <div className="field">
      <label htmlFor={props.id}>{props.label}</label>
      <input
        id={props.id}
        className="input"
        type={props.type ?? "text"}
        value={props.value}
        maxLength={props.max}
        placeholder={props.placeholder}
        autoComplete={props.autoComplete ?? "off"}
        required={props.required}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </div>
  );
}

function Security() {
  const account = useAccount()!;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const change = useAction();
  const sessions = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void change.run(async () => {
      if (next !== confirm) throw new HttpError(422, "Les deux mots de passe ne sont pas identiques.", null);
      account.setMe((await settingsApi.password(current, next)).user);
      setCurrent("");
      setNext("");
      setConfirm("");
      return "Mot de passe modifié. Vos autres appareils ont été déconnectés.";
    });
  };
  return (
    <section className="panel" aria-labelledby="securite">
      <div className="panel__head">
        <h2 className="panel__title" id="securite">
          Sécurité
        </h2>
      </div>
      <form className="panel__body settings__form" onSubmit={submit}>
        <TextField id="current" label="Mot de passe actuel" type="password" value={current} onChange={setCurrent} max={256} autoComplete="current-password" required />
        <TextField id="new" label="Nouveau mot de passe (12 caractères au moins)" type="password" value={next} onChange={setNext} max={256} autoComplete="new-password" required />
        <TextField id="confirm" label="Confirmer le nouveau mot de passe" type="password" value={confirm} onChange={setConfirm} max={256} autoComplete="new-password" required />
        <Feedback value={change.feedback} />
        <button className="btn btn--primary" type="submit" disabled={change.busy}>
          Changer le mot de passe
        </button>
      </form>
      <div className="panel__body">
        <Feedback value={sessions.feedback} />
        <button
          type="button"
          className="btn"
          disabled={sessions.busy}
          onClick={() =>
            void sessions.run(async () => {
              await settingsApi.revokeOthers();
              return "Vos autres sessions ont été fermées.";
            })
          }
        >
          Déconnecter mes autres appareils
        </button>
      </div>
    </section>
  );
}

function Privacy() {
  const account = useAccount()!;
  const enabled = measurementId(account.config) !== null;
  const { busy, feedback, run } = useAction();
  const consent = account.me.analytics_consent;
  return (
    <section className="panel" aria-labelledby="confidentialite">
      <div className="panel__head">
        <h2 className="panel__title" id="confidentialite">
          Confidentialité
        </h2>
      </div>
      <div className="panel__body settings__form">
        {enabled ? (
          <>
            <p>
              Mesure d'audience (Google Analytics) : pages consultées seulement, sans identifiant, sans donnée
              de patient, sans publicité. Statut :{" "}
              <strong>{consent === true ? "acceptée" : consent === false ? "refusée" : "pas encore choisie"}</strong>.
            </p>
            <Feedback value={feedback} />
            <div className="settings__row">
              <button
                type="button"
                className="btn"
                disabled={busy || consent === false}
                onClick={() =>
                  void run(async () => {
                    account.setMe((await settingsApi.save({ analytics_consent: false })).user);
                    return "Mesure d'audience refusée.";
                  })
                }
              >
                Refuser
              </button>
              <button
                type="button"
                className="btn btn--primary"
                disabled={busy || consent === true}
                onClick={() =>
                  void run(async () => {
                    account.setMe((await settingsApi.save({ analytics_consent: true })).user);
                    return "Mesure d'audience acceptée.";
                  })
                }
              >
                Accepter
              </button>
            </div>
          </>
        ) : (
          <p>Aucune mesure d'audience dans cet environnement.</p>
        )}
        <p className="field__hint">
          Votre journal de décisions et vos paramètres ne sont visibles que par vous. Les patients affichés sont
          fictifs.
        </p>
      </div>
    </section>
  );
}

function Administration() {
  const account = useAccount()!;
  const [users, setUsers] = useState<Account[] | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("pilot");
  const invite = useAction();
  const row = useAction();
  const load = useCallback(() => {
    adminApi
      .users()
      .then((r) => setUsers(r.users))
      .catch(() => setUsers([]));
  }, []);
  useEffect(load, [load]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void invite.run(async () => {
      await adminApi.invite(email, role, name);
      setEmail("");
      setName("");
      load();
      return `Invitation envoyée à ${email.trim().toLowerCase()}.`;
    });
  };
  const act = (label: string, action: () => Promise<unknown>) =>
    void row.run(async () => {
      await action();
      load();
      return label;
    });

  return (
    <section className="panel" aria-labelledby="administration">
      <div className="panel__head">
        <h2 className="panel__title" id="administration">
          Administration des accès
        </h2>
      </div>
      <form className="panel__body settings__form settings__invite" onSubmit={submit}>
        <TextField id="invite_email" label="Email du pilote à inviter" type="email" value={email} onChange={setEmail} max={254} required />
        <TextField id="invite_name" label="Nom (facultatif)" value={name} onChange={setName} max={80} />
        <div className="field">
          <label htmlFor="invite_role">Rôle</label>
          <select id="invite_role" className="select" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="pilot">Pilote</option>
            <option value="admin">Administrateur</option>
          </select>
        </div>
        <Feedback value={invite.feedback} />
        <button className="btn btn--primary" type="submit" disabled={invite.busy}>
          Envoyer l'invitation
        </button>
      </form>
      <div className="panel__body">
        <Feedback value={row.feedback} />
        {users === null ? (
          <div className="skeleton" aria-busy="true" aria-label="Chargement des comptes" />
        ) : (
          <table className="table settings__users">
            <caption className="visually-hidden">Comptes</caption>
            <thead>
              <tr>
                <th scope="col">Compte</th>
                <th scope="col">Rôle</th>
                <th scope="col">Statut</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.display_name || u.email}
                    {u.display_name ? <div className="field__hint">{u.email}</div> : null}
                  </td>
                  <td>{ROLE[u.role]}</td>
                  <td>{STATUS[u.status]}</td>
                  <td className="settings__actions">
                    {u.id === account.me.id ? (
                      <span className="field__hint">Vous</span>
                    ) : (
                      <>
                        {u.status === "invited" ? (
                          <button type="button" className="btn btn--small" disabled={row.busy} onClick={() => act("Invitation renvoyée.", () => adminApi.resend(u.id))}>
                            Renvoyer
                          </button>
                        ) : null}
                        {u.status === "active" ? (
                          <button type="button" className="btn btn--small" disabled={row.busy} onClick={() => act("Compte désactivé.", () => adminApi.update(u.id, { status: "disabled" }))}>
                            Désactiver
                          </button>
                        ) : null}
                        {u.status === "disabled" ? (
                          <button type="button" className="btn btn--small" disabled={row.busy} onClick={() => act("Compte réactivé.", () => adminApi.update(u.id, { status: "active" }))}>
                            Réactiver
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="btn btn--small btn--quiet"
                          disabled={row.busy}
                          onClick={() =>
                            act("Rôle modifié.", () => adminApi.update(u.id, { role: u.role === "admin" ? "pilot" : "admin" }))
                          }
                        >
                          {u.role === "admin" ? "Retirer admin" : "Rendre admin"}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
