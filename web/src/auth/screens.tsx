import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { HttpError } from "../api/http";
import { Mark } from "../ui/icons";
import { type Environment, type Me, authApi } from "./api";

type View =
  | { kind: "login" }
  | { kind: "forgot" }
  | { kind: "invitation"; token: string }
  | { kind: "reset"; token: string };

/** Sign-in screens chosen from the location hash: #/invitation?token=…, #/reinitialisation?token=…, #/mot-de-passe-oublie. */
export function viewOf(hash: string): View {
  const [path = "", query = ""] = hash.replace(/^#\/?/, "").split("?");
  const token = new URLSearchParams(query).get("token") ?? "";
  if (path === "invitation" && token) return { kind: "invitation", token };
  if (path === "reinitialisation" && token) return { kind: "reset", token };
  if (path === "mot-de-passe-oublie") return { kind: "forgot" };
  return { kind: "login" };
}

/** Removes a one-time token from the address bar and history once it has been read. */
function forgetToken() {
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#/`);
}

function message(error: unknown): string {
  if (error instanceof HttpError) return error.detail;
  return "Service injoignable. Vérifiez votre connexion et réessayez.";
}

export function AuthScreens(props: {
  notice: string | null;
  onSignedIn: (me: Me) => Promise<void>;
  environment?: Environment;
}) {
  const [view, setView] = useState<View>(() => viewOf(window.location.hash));
  useEffect(() => {
    const on = () => setView(viewOf(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  return (
    <main className="auth" id="contenu">
      <div className="auth__card">
        <div className="auth__brand">
          <Mark />
          <span translate="no">HospitalOS</span>
          {props.environment === "staging" ? <span className="auth__env">Recette</span> : null}
        </div>
        {props.notice && view.kind === "login" ? (
          <p className="notice" role="status">
            {props.notice}
          </p>
        ) : null}
        {view.kind === "login" ? <Login onSignedIn={props.onSignedIn} /> : null}
        {view.kind === "forgot" ? <Forgot /> : null}
        {view.kind === "invitation" ? <Accept token={view.token} onSignedIn={props.onSignedIn} /> : null}
        {view.kind === "reset" ? <Reset token={view.token} /> : null}
      </div>
      <p className="auth__foot">Pilote en mode observation : HospitalOS propose, vous décidez. Données fictives.</p>
    </main>
  );
}

function Field(props: {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
  hint?: ReactNode;
  autoFocus?: boolean;
  optional?: boolean;
}) {
  return (
    <div className="field">
      <label htmlFor={props.id}>{props.label}</label>
      <input
        id={props.id}
        className="input"
        type={props.type ?? "text"}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        autoComplete={props.autoComplete}
        required={!props.optional}
        autoFocus={props.autoFocus}
      />
      {props.hint ? <p className="field__hint">{props.hint}</p> : null}
    </div>
  );
}

function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (e: FormEvent, action: () => Promise<void>) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function ErrorLine({ error }: { error: string | null }) {
  return error ? (
    <p className="notice notice--error" role="alert">
      {error}
    </p>
  ) : null;
}

function Login({ onSignedIn }: { onSignedIn: (me: Me) => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useSubmit();
  return (
    <form onSubmit={(e) => run(e, async () => onSignedIn(await authApi.login(email, password)))}>
      <h1 className="auth__title">Connexion</h1>
      <Field id="email" label="Adresse email" type="email" value={email} onChange={setEmail} autoComplete="username" autoFocus />
      <Field id="password" label="Mot de passe" type="password" value={password} onChange={setPassword} autoComplete="current-password" />
      <ErrorLine error={error} />
      <button className="btn btn--primary auth__submit" type="submit" disabled={busy}>
        Se connecter
      </button>
      <a className="auth__link" href="#/mot-de-passe-oublie">
        Mot de passe oublié ?
      </a>
    </form>
  );
}

function Forgot() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const { busy, error, run } = useSubmit();
  if (sent)
    return (
      <div>
        <h1 className="auth__title">Vérifiez vos emails</h1>
        <p role="status">{sent}</p>
        <a className="auth__link" href="#/">
          Retour à la connexion
        </a>
      </div>
    );
  return (
    <form onSubmit={(e) => run(e, async () => setSent((await authApi.forgot(email)).detail))}>
      <h1 className="auth__title">Mot de passe oublié</h1>
      <p className="auth__lead">Indiquez votre adresse : si un compte existe, vous recevrez un lien valable une heure.</p>
      <Field id="email" label="Adresse email" type="email" value={email} onChange={setEmail} autoComplete="username" autoFocus />
      <ErrorLine error={error} />
      <button className="btn btn--primary auth__submit" type="submit" disabled={busy}>
        Envoyer le lien
      </button>
      <a className="auth__link" href="#/">
        Retour à la connexion
      </a>
    </form>
  );
}

const PASSWORD_HINT = "Au moins 12 caractères. Une phrase de passe facile à retenir convient très bien.";

function Accept({ token, onSignedIn }: { token: string; onSignedIn: (me: Me) => Promise<void> }) {
  const [invite, setInvite] = useState<{ email: string; display_name: string } | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const { busy, error, run } = useSubmit();
  useEffect(() => {
    authApi
      .invitation(token)
      .then((i) => {
        setInvite(i);
        setName(i.display_name);
      })
      .catch((e: unknown) => setInvalid(message(e)));
  }, [token]);
  if (invalid)
    return (
      <div>
        <h1 className="auth__title">Invitation</h1>
        <p className="notice notice--error" role="alert">
          {invalid}
        </p>
        <a className="auth__link" href="#/">
          Aller à la connexion
        </a>
      </div>
    );
  if (!invite) return <div className="skeleton" aria-busy="true" aria-label="Vérification de l'invitation" />;
  return (
    <form
      onSubmit={(e) =>
        run(e, async () => {
          if (password !== confirm) throw new HttpError(422, "Les deux mots de passe ne sont pas identiques.", null);
          const me = await authApi.accept(token, password, name);
          forgetToken();
          await onSignedIn(me);
        })
      }
    >
      <h1 className="auth__title">Bienvenue</h1>
      <p className="auth__lead">
        Créez votre mot de passe pour <strong>{invite.email}</strong>.
      </p>
      <Field id="name" label="Nom affiché" value={name} onChange={setName} autoComplete="name" optional />
      <Field id="password" label="Mot de passe" type="password" value={password} onChange={setPassword} autoComplete="new-password" hint={PASSWORD_HINT} />
      <Field id="confirm" label="Confirmer le mot de passe" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" />
      <ErrorLine error={error} />
      <button className="btn btn--primary auth__submit" type="submit" disabled={busy}>
        Créer mon accès
      </button>
    </form>
  );
}

function Reset({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const { busy, error, run } = useSubmit();
  if (done)
    return (
      <div>
        <h1 className="auth__title">Mot de passe modifié</h1>
        <p role="status">{done}</p>
        <a className="auth__link" href="#/">
          Se connecter
        </a>
      </div>
    );
  return (
    <form
      onSubmit={(e) =>
        run(e, async () => {
          if (password !== confirm) throw new HttpError(422, "Les deux mots de passe ne sont pas identiques.", null);
          const res = await authApi.reset(token, password);
          forgetToken();
          setDone(res.detail);
        })
      }
    >
      <h1 className="auth__title">Nouveau mot de passe</h1>
      <Field id="password" label="Nouveau mot de passe" type="password" value={password} onChange={setPassword} autoComplete="new-password" hint={PASSWORD_HINT} autoFocus />
      <Field id="confirm" label="Confirmer le mot de passe" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" />
      <ErrorLine error={error} />
      <button className="btn btn--primary auth__submit" type="submit" disabled={busy}>
        Enregistrer
      </button>
    </form>
  );
}
