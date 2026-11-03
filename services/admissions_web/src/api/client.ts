const TOKEN_KEY = "hos-adm-token";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the session lasts as long as the page */
  }
}

let onUnauthorized: () => void = () => undefined;
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : String(d)))
      .join(" ; ");
  }
  return "La requête a échoué.";
}

async function request(path: string, init: RequestInit & { json?: unknown } = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "Serveur injoignable. Vérifiez la connexion puis réessayez.");
  }
  if (response.status === 401 && token) {
    setToken(null);
    onUnauthorized();
  }
  if (!response.ok) {
    let message = `Erreur ${response.status}`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      message = describe(data.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, message);
  }
  return response;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const response = await request(path, init);
  const type = response.headers.get("Content-Type") ?? "";
  if (type.includes("application/json")) return (await response.json()) as T;
  return (await response.text()) as unknown as T;
}

/** Binary GET with the bearer token (an <img src> cannot carry it), e.g. an agent frame. */
export async function apiBlob(path: string): Promise<Blob> {
  return (await request(path)).blob();
}
