import type { Metric } from "web-vitals";

import { getToken } from "../api/client";

/**
 * Core Web Vitals of real visits (règle 30 de l'audit) : how fast HospitalOS felt on the
 * cadre's tablet or the bed manager's desk, sent to the group's own API — never to a third
 * party. A measure carries the screen as its route template (an id never leaves), the
 * device class and the network type; nothing about the person.
 */
export interface VitalOut {
  metric: Metric["name"];
  value: number;
  page: string;
  device: "mobile" | "tablette" | "bureau";
  connection: "slow-2g" | "2g" | "3g" | "4g" | "inconnu";
}

const SCREENS = new Set([
  "/",
  "/demandes",
  "/lits",
  "/plan-des-lits",
  "/urgences",
  "/prevision",
  "/charge",
  "/groupe",
  "/indicateurs",
  "/ror",
  "/agents",
  "/imports",
  "/parametres"
]);

/** The screen without what identifies a record: /demandes/4512 → /demandes/:id. */
export function pageTemplate(path: string): string {
  const p = path.replace(/\/+$/, "") || "/";
  if (/^\/demandes\/[^/]+$/.test(p)) return "/demandes/:id";
  if (/^\/agents\/passages\/[^/]+$/.test(p)) return "/agents/passages/:id";
  return SCREENS.has(p) ? p : "autre";
}

export function deviceClass(width: number): VitalOut["device"] {
  return width < 640 ? "mobile" : width < 1024 ? "tablette" : "bureau";
}

export function connectionType(): VitalOut["connection"] {
  const type = (navigator as Navigator & { connection?: { effectiveType?: string } }).connection?.effectiveType;
  return type === "slow-2g" || type === "2g" || type === "3g" || type === "4g" ? type : "inconnu";
}

/** Sent as the page goes away: keepalive lets the request outlive it. Failures are dropped. */
function post(vitals: VitalOut[], token: string): void {
  void fetch("/api/web-vitals", {
    method: "POST",
    keepalive: true,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ vitals })
  }).catch(() => undefined);
}

// The load of a page is measured on the screen it opened on; INP and CLS, which add up over
// the visit, on the screen shown when they are reported.
const LOAD_METRICS = new Set(["LCP", "FCP", "TTFB"]);
type Subscribe = (report: (m: Metric) => void) => void;
const BATCH = 20;
const KEPT = 60;

export function startWebVitals({
  load = () => import("web-vitals"),
  send = post,
  landing = window.location.pathname
}: {
  load?: () => Promise<Record<"onLCP" | "onINP" | "onCLS" | "onFCP" | "onTTFB", Subscribe>>;
  send?: (vitals: VitalOut[], token: string) => void;
  landing?: string;
} = {}): Promise<void> {
  let queue: VitalOut[] = [];

  const flush = () => {
    const token = getToken();
    // Signed out (the login page): kept until a session exists, within a bound.
    if (!token) return;
    while (queue.length) send(queue.splice(0, BATCH), token);
  };
  const record = (m: Metric) => {
    queue.push({
      metric: m.name,
      value: m.value,
      page: pageTemplate(LOAD_METRICS.has(m.name) ? landing : window.location.pathname),
      device: deviceClass(window.innerWidth),
      connection: connectionType()
    });
    queue = queue.slice(-KEPT);
  };

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });
  window.addEventListener("pagehide", flush);

  return load()
    .then(({ onLCP, onINP, onCLS, onFCP, onTTFB }) => {
      for (const on of [onLCP, onINP, onCLS, onFCP, onTTFB]) on(record);
    })
    .catch(() => undefined); // measuring must never break the application
}
