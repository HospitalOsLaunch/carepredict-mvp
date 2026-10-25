import { useState, type FormEvent } from "react";

import { useAuth } from "../auth";
import { Mark } from "../components/Mark";
import { ErrorNote } from "../components/ui";

export function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-violet px-14 py-16 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <Mark className="h-10 w-10" />
          <span className="font-display text-xl font-bold">HospitalOS</span>
        </div>
        <div>
          <p className="max-w-md font-display text-[44px] font-bold leading-[1.05] tracking-tight">
            Chaque lit qui se libère trouve son patient.
          </p>
          <p className="mt-5 max-w-md text-[17px] text-white/80">
            Les demandes d'admission en SMR, priorisées et prêtes à recevoir une réponse, avec les lits qui se
            libèrent sur les quinze prochains jours.
          </p>
        </div>
        <div aria-hidden className="flex gap-2">
          {[1, 1, 0.5, 1, 0, 0.5, 1, 1, 1, 0.5, 0, 1, 1, 1].map((v, i) => (
            <span
              key={i}
              style={{ animationDelay: `${300 + i * 70}ms` }}
              className={`lamp-on h-6 w-6 rounded-full ${
                v === 1
                  ? "bg-sun shadow-[0_0_16px_rgba(255,178,30,0.8)]"
                  : v === 0.5
                    ? "bg-sun/30 ring-2 ring-inset ring-sun"
                    : "bg-white/10"
              }`}
            />
          ))}
        </div>
      </section>
      <section className="flex items-center justify-center px-6 py-12">
        <form onSubmit={submit} className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <Mark className="h-9 w-9" />
            <span className="font-display text-xl font-bold">HospitalOS</span>
          </div>
          <h1>Connexion</h1>
          <p className="mt-2 text-ink-soft">Coordination des admissions SMR</p>
          <label className="field mt-8" htmlFor="email">
            Adresse e-mail
          </label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            required
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <label className="field mt-4" htmlFor="password">
            Mot de passe
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error !== null && (
            <div className="mt-4">
              <ErrorNote error={error} />
            </div>
          )}
          <button type="submit" className="btn-primary mt-6 w-full py-3" disabled={busy}>
            {busy ? "Connexion…" : "Se connecter"}
          </button>
          <p className="mt-6 text-[13px] text-ink-faint">
            Données pseudonymisées. Chaque action est tracée dans le journal d'audit.
          </p>
        </form>
      </section>
    </div>
  );
}
