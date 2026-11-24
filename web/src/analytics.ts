// Google Analytics 4, production only, after explicit consent (CNIL): nothing is loaded before the person
// accepts, no identifier is sent (no user_id, no email, no unit or patient pseudonym), Google signals and ad
// personalisation are off, and page locations are generic section names, never the hash parameters.
import type { PublicConfig } from "./auth/api";

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

const SECTIONS: Record<string, string> = {
  unite: "Unité",
  proposition: "Proposition",
  plan: "Plan 24 h",
  journal: "Journal",
  donnees: "Données",
  parametres: "Paramètres",
  connexion: "Connexion",
};

/** Generic events only; anything else is dropped. */
const EVENTS = new Set(["login", "decision_validated", "decision_refused", "decision_done", "plan_simulated"]);

let loadedId: string | null = null;
let granted = false;

export function measurementId(config: PublicConfig | null): string | null {
  if (!config || config.environment !== "production" || config.analytics?.provider !== "ga4") return null;
  const id = config.analytics.measurement_id;
  return /^G-[A-Z0-9]+$/.test(id) ? id : null;
}

function gtag(...args: unknown[]) {
  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push(args);
}

function clearCookies() {
  for (const part of document.cookie.split(";")) {
    const name = part.split("=")[0]?.trim();
    if (name && (name === "_ga" || name.startsWith("_ga_"))) {
      document.cookie = `${name}=; Max-Age=0; path=/`;
      document.cookie = `${name}=; Max-Age=0; path=/; domain=${window.location.hostname}`;
    }
  }
}

/** Apply the person's choice: load GA4 on consent, deny and clear its cookies otherwise. */
export function applyConsent(config: PublicConfig | null, consent: boolean | null): void {
  const id = measurementId(config);
  if (!id) return;
  if (consent !== true) {
    if (loadedId) gtag("consent", "update", { analytics_storage: "denied" });
    granted = false;
    clearCookies();
    return;
  }
  granted = true;
  if (loadedId === id) {
    gtag("consent", "update", { analytics_storage: "granted" });
    return;
  }
  loadedId = id;
  window.gtag = gtag;
  gtag("consent", "default", {
    analytics_storage: "granted",
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
  });
  gtag("js", new Date());
  gtag("config", id, {
    send_page_view: false,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
  });
  const script = document.createElement("script");
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`;
  document.head.appendChild(script);
}

/** Section name from a location hash, without any parameter (journal ids, tokens). */
export function sectionOf(hash: string): string {
  const head = hash.replace(/^#\/?/, "").split(/[/?]/)[0] ?? "";
  return head in SECTIONS ? head : "unite";
}

export function trackPage(hash: string): void {
  if (!loadedId || !granted) return;
  const section = sectionOf(hash);
  gtag("event", "page_view", {
    page_title: `HospitalOS · ${SECTIONS[section]}`,
    page_location: `${window.location.origin}/${section}`,
    page_path: `/${section}`,
  });
}

export function trackEvent(name: string): void {
  if (!loadedId || !granted || !EVENTS.has(name)) return;
  gtag("event", name, {});
}

/** Tests only. */
export function resetAnalytics(): void {
  loadedId = null;
  granted = false;
  window.dataLayer = undefined;
  window.gtag = undefined;
}
