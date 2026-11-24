import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { resetAnalytics, sectionOf, trackPage } from "../analytics";
import { journal } from "../data/journal";
import { bindJournal } from "../data/journalSync";
import { AuthGate, useAccount } from "./AuthGate";
import { Settings } from "./Settings";
import { viewOf } from "./screens";

type Handler = (url: string, init: RequestInit) => { status: number; body: unknown } | undefined;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mockFetch(handler: Handler) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      const r = handler(url, init);
      if (!r) throw new TypeError("offline");
      return json(r.status, r.body);
    }),
  );
  return calls;
}

const USER = {
  id: "u1",
  email: "nadia@chu.example",
  role: "admin",
  status: "active",
  display_name: "Nadia B.",
  job_title: "Gestionnaire de lits",
  establishment: "CHU",
  default_unit: "",
  analytics_consent: null as boolean | null,
  created_at: "2026-11-24T08:00:00+00:00",
  last_login_at: null,
};
const PROD = { environment: "production", release: "v1", analytics: { provider: "ga4", measurement_id: "G-TEST123" } };

function Inside() {
  const account = useAccount();
  return <p>Dans le cockpit : {account ? account.me.email : "démonstration"}</p>;
}

beforeEach(() => {
  journal.reset();
  resetAnalytics();
  document.head.querySelectorAll("script").forEach((s) => s.remove());
  window.location.hash = "";
});

describe("sign-in gate", () => {
  it("asks to sign in, sends the security header, then opens the cockpit with the server journal", async () => {
    let signedIn = false;
    const calls = mockFetch((url, init) => {
      if (url === "/api/config") return { status: 200, body: PROD };
      if (url === "/api/auth/me") return signedIn ? { status: 200, body: { user: USER } } : { status: 401, body: { detail: "x" } };
      if (url === "/api/auth/login") {
        signedIn = true;
        return { status: 200, body: { user: USER, environment: "production" } };
      }
      if (url === "/api/journal" && (init.method ?? "GET") === "GET") return { status: 200, body: { revision: 3, records: [] } };
      return undefined;
    });
    render(
      <AuthGate>
        <Inside />
      </AuthGate>,
    );
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Adresse email"), { target: { value: "nadia@chu.example" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "correct-horse-battery" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByText("Dans le cockpit : nadia@chu.example")).toBeTruthy();
    const login = calls.find((c) => c.url === "/api/auth/login")!;
    expect((login.init.headers as Record<string, string>)["X-Requested-With"]).toBe("HospitalOS");
    expect(login.init.credentials).toBe("same-origin");
    expect(JSON.parse(String(login.init.body))).toEqual({ email: "nadia@chu.example", password: "correct-horse-battery" });
  });

  it("falls back to the offline demonstration when no platform answers", async () => {
    mockFetch(() => undefined);
    render(
      <AuthGate>
        <Inside />
      </AuthGate>,
    );
    expect(await screen.findByText("Dans le cockpit : démonstration")).toBeTruthy();
  });

  it("shows a generic error on wrong credentials", async () => {
    mockFetch((url) => {
      if (url === "/api/config") return { status: 200, body: PROD };
      if (url === "/api/auth/me") return { status: 401, body: {} };
      if (url === "/api/auth/login") return { status: 401, body: { detail: "Adresse email ou mot de passe incorrect." } };
      return undefined;
    });
    render(
      <AuthGate>
        <Inside />
      </AuthGate>,
    );
    await screen.findByRole("heading", { name: "Connexion" });
    fireEvent.change(screen.getByLabelText("Adresse email"), { target: { value: "x@y.fr" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Adresse email ou mot de passe incorrect.");
  });
});

describe("invitation links", () => {
  it("reads one-time links from the hash", () => {
    expect(viewOf("#/invitation?token=abc")).toEqual({ kind: "invitation", token: "abc" });
    expect(viewOf("#/reinitialisation?token=xyz")).toEqual({ kind: "reset", token: "xyz" });
    expect(viewOf("#/mot-de-passe-oublie")).toEqual({ kind: "forgot" });
    expect(viewOf("#/invitation")).toEqual({ kind: "login" });
  });

  it("accepts an invitation and forgets the token from the address bar", async () => {
    window.location.hash = "/invitation?token=tok123";
    let signedIn = false;
    const calls = mockFetch((url) => {
      if (url === "/api/config") return { status: 200, body: { ...PROD, environment: "staging", analytics: null } };
      if (url === "/api/auth/me") return signedIn ? { status: 200, body: { user: USER } } : { status: 401, body: {} };
      if (url.startsWith("/api/auth/invitation?")) return { status: 200, body: { email: "nadia@chu.example", display_name: "" } };
      if (url === "/api/auth/invitation/accept") {
        signedIn = true;
        return { status: 200, body: { user: USER, environment: "staging" } };
      }
      if (url === "/api/journal") return { status: 200, body: { revision: 0, records: [] } };
      return undefined;
    });
    render(
      <AuthGate>
        <Inside />
      </AuthGate>,
    );
    expect(await screen.findByText("Recette")).toBeTruthy();
    await screen.findByRole("heading", { name: "Bienvenue" });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "une phrase de passe" } });
    fireEvent.change(screen.getByLabelText("Confirmer le mot de passe"), { target: { value: "une phrase de passe" } });
    fireEvent.click(screen.getByRole("button", { name: "Créer mon accès" }));
    await screen.findByText("Dans le cockpit : nadia@chu.example");
    expect(window.location.hash).not.toContain("tok123");
    expect(JSON.parse(String(calls.find((c) => c.url === "/api/auth/invitation/accept")!.init.body)).token).toBe("tok123");
  });
});

describe("analytics", () => {
  it("loads GA4 only in production and only after consent", async () => {
    let user = { ...USER };
    mockFetch((url, init) => {
      if (url === "/api/config") return { status: 200, body: PROD };
      if (url === "/api/auth/me") return { status: 200, body: { user } };
      if (url === "/api/journal") return { status: 200, body: { revision: 0, records: [] } };
      if (url === "/api/settings" && init.method === "PUT") {
        user = { ...user, analytics_consent: JSON.parse(String(init.body)).analytics_consent };
        return { status: 200, body: { user } };
      }
      return undefined;
    });
    render(
      <AuthGate>
        <Inside />
      </AuthGate>,
    );
    await screen.findByText(/Dans le cockpit/);
    expect(document.querySelector('script[src*="googletagmanager"]')).toBeNull();
    expect(screen.getByRole("region", { name: "Mesure d'audience" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Accepter" }));
    await waitFor(() => expect(document.querySelector('script[src*="googletagmanager.com/gtag/js?id=G-TEST123"]')).toBeTruthy());
    expect(screen.queryByRole("region", { name: "Mesure d'audience" })).toBeNull();
    const config = window.dataLayer!.find((e) => (e as unknown[])[0] === "config") as unknown[];
    expect(config[2]).toMatchObject({ allow_google_signals: false, allow_ad_personalization_signals: false });
    trackPage("#/journal/rec-secret-id");
    const page = window.dataLayer!.at(-1) as unknown[];
    expect(JSON.stringify(page)).not.toContain("rec-secret-id");
    expect((page[2] as { page_path: string }).page_path).toBe("/journal");
  });

  it("never loads GA4 outside production", async () => {
    mockFetch((url) => {
      if (url === "/api/config") return { status: 200, body: { ...PROD, environment: "staging" } };
      if (url === "/api/auth/me") return { status: 200, body: { user: { ...USER, analytics_consent: true } } };
      if (url === "/api/journal") return { status: 200, body: { revision: 0, records: [] } };
      return undefined;
    });
    render(
      <AuthGate>
        <Inside />
      </AuthGate>,
    );
    await screen.findByText(/Dans le cockpit/);
    expect(document.querySelector('script[src*="googletagmanager"]')).toBeNull();
    expect(screen.queryByRole("region", { name: "Mesure d'audience" })).toBeNull();
  });

  it("names sections without parameters", () => {
    expect(sectionOf("#/journal/abc?x=1")).toBe("journal");
    expect(sectionOf("#/invitation?token=secret")).toBe("unite");
    expect(sectionOf("")).toBe("unite");
  });
});

describe("journal sync", () => {
  it("saves each change against the server revision and adopts the server copy on conflict", async () => {
    vi.useFakeTimers();
    const puts: unknown[] = [];
    let conflict = false;
    mockFetch((url, init) => {
      if (url === "/api/journal" && (init.method ?? "GET") === "GET") return { status: 200, body: { revision: 2, records: [] } };
      if (url === "/api/journal" && init.method === "PUT") {
        puts.push(JSON.parse(String(init.body)));
        if (conflict) return { status: 409, body: { detail: { message: "x", revision: 9, records: [{ id: "srv", events: [], proposedAt: "2026-11-24T08:00:00Z" }] } } };
        return { status: 200, body: { revision: 3 } };
      }
      return undefined;
    });
    const stop = await bindJournal({ id: "u1", name: "Nadia", role: "" }, 10);
    journal.discard("none"); // a change: commits the (empty) journal
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20);
    });
    expect(puts.at(-1)).toMatchObject({ base_revision: 2 });
    conflict = true;
    journal.discard("none");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20);
    });
    expect(puts.at(-1)).toMatchObject({ base_revision: 3 });
    expect(journal).toBeTruthy();
    await stop();
    vi.useRealTimers();
  });
});

describe("settings", () => {
  it("shows profile, security, privacy and, for an administrator, account management", async () => {
    mockFetch((url) => {
      if (url === "/api/config") return { status: 200, body: PROD };
      if (url === "/api/auth/me") return { status: 200, body: { user: { ...USER, analytics_consent: false } } };
      if (url === "/api/journal") return { status: 200, body: { revision: 0, records: [] } };
      if (url === "/api/admin/users")
        return { status: 200, body: { users: [USER, { ...USER, id: "u2", email: "p@chu.example", role: "pilot", status: "invited", display_name: "" }] } };
      return undefined;
    });
    render(
      <AuthGate>
        <Settings units={[{ id: "U1", name: "Médecine" }]} />
      </AuthGate>,
    );
    expect(await screen.findByRole("heading", { name: "Profil" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Sécurité" })).toBeTruthy();
    expect(screen.getByText("refusée")).toBeTruthy();
    expect(await screen.findByText("p@chu.example")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Renvoyer" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Médecine" })).toBeTruthy();
  });
});
