import { type ReactNode, createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { HttpError, UNAUTHORIZED_EVENT } from "../api/http";
import { applyConsent, measurementId, trackEvent, trackPage } from "../analytics";
import { bindJournal } from "../data/journalSync";
import { type Account, type Me, type PublicConfig, authApi, settingsApi } from "./api";
import { AuthScreens } from "./screens";

export interface AccountContextValue {
  me: Account;
  config: PublicConfig | null;
  setMe: (account: Account) => void;
  logout: () => Promise<void>;
}

const AccountContext = createContext<AccountContextValue | null>(null);

/** The signed-in account, or null in the offline demonstration (no platform reachable, or the demo build). */
export const useAccount = (): AccountContextValue | null => useContext(AccountContext);

type Phase =
  | { kind: "loading" }
  | { kind: "offline" }
  | { kind: "signed-out"; notice: string | null }
  | { kind: "signed-in"; me: Account };

function isNetworkError(error: unknown): boolean {
  return !(error instanceof HttpError);
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const stopJournal = useRef<(() => Promise<void>) | null>(null);

  const signIn = useCallback(
    async (me: Me, explicit: boolean) => {
      const user = me.user;
      stopJournal.current = await bindJournal({
        id: user.id,
        name: user.display_name || user.email,
        role: user.job_title,
      });
      setPhase({ kind: "signed-in", me: user });
      if (explicit) trackEvent("login");
    },
    [],
  );

  useEffect(() => {
    if (__DEMO_ONLY__) return;
    let cancelled = false;
    void (async () => {
      const [cfg, me] = await Promise.allSettled([authApi.config(), authApi.me()]);
      if (cancelled) return;
      if (cfg.status === "fulfilled") setConfig(cfg.value);
      if (me.status === "fulfilled") {
        try {
          await signIn(me.value, false);
        } catch {
          setPhase({ kind: "signed-out", notice: "Votre journal n'a pas pu être chargé. Reconnectez-vous." });
        }
      } else if (isNetworkError(me.reason) && cfg.status === "rejected") setPhase({ kind: "offline" });
      else setPhase({ kind: "signed-out", notice: null });
    })();
    return () => {
      cancelled = true;
    };
  }, [signIn]);

  // Consent and page views follow the account's choice and the current section.
  const consent = phase.kind === "signed-in" ? phase.me.analytics_consent : null;
  useEffect(() => {
    if (phase.kind !== "signed-in") return;
    applyConsent(config, consent);
    trackPage(window.location.hash);
    const on = () => trackPage(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, [phase.kind, config, consent]);

  // Any 401 after sign-in: the session expired or was revoked elsewhere.
  useEffect(() => {
    const on = () => {
      setPhase((p) => {
        if (p.kind !== "signed-in") return p;
        stopJournal.current = null;
        void import("../data/journal").then(({ journal }) => journal.unbind());
        return { kind: "signed-out", notice: "Votre session a expiré. Reconnectez-vous." };
      });
    };
    window.addEventListener(UNAUTHORIZED_EVENT, on);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, on);
  }, []);

  const setMe = useCallback((account: Account) => setPhase({ kind: "signed-in", me: account }), []);

  const logout = useCallback(async () => {
    const stop = stopJournal.current;
    stopJournal.current = null;
    if (stop) await stop();
    try {
      await authApi.logout();
    } finally {
      applyConsent(config, false);
      window.location.hash = "/";
      setPhase({ kind: "signed-out", notice: "Vous êtes déconnecté." });
    }
  }, [config]);

  if (__DEMO_ONLY__) return <>{children}</>;
  if (phase.kind === "loading") return <div className="skeleton" aria-busy="true" aria-label="Chargement" />;
  if (phase.kind === "offline") return <>{children}</>;
  if (phase.kind === "signed-out")
    return <AuthScreens notice={phase.notice} onSignedIn={(me) => signIn(me, true)} environment={config?.environment} />;

  const value: AccountContextValue = { me: phase.me, config, setMe, logout };
  return (
    <AccountContext.Provider value={value}>
      {children}
      {measurementId(config) && phase.me.analytics_consent === null ? (
        <ConsentBanner
          onChoice={async (accept) => {
            const res = await settingsApi.save({ analytics_consent: accept });
            setMe(res.user);
          }}
        />
      ) : null}
    </AccountContext.Provider>
  );
}

function ConsentBanner({ onChoice }: { onChoice: (accept: boolean) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const choose = async (accept: boolean) => {
    setBusy(true);
    try {
      await onChoice(accept);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="consent" role="region" aria-label="Mesure d'audience">
      <p>
        Nous aimerions mesurer l'usage du cockpit (pages consultées, sans identifiant ni donnée de patient)
        avec Google Analytics, pour l'améliorer. Vous pouvez changer d'avis à tout moment dans Paramètres.
      </p>
      <div className="consent__actions">
        <button type="button" className="btn" disabled={busy} onClick={() => void choose(false)}>
          Refuser
        </button>
        <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void choose(true)}>
          Accepter
        </button>
      </div>
    </section>
  );
}
