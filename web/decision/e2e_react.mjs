// End-to-end check of the React cockpit "Plan 24 h" route against the live decision engine.
//   npm --prefix web run build && node web/decision/e2e_react.mjs
// Starts web/decision/serve.py (8765) and `vite preview` (4317, proxying /api/decision), and
// always stops both (process groups), even on failure.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require("playwright"); } catch { playwright = require("/opt/node22/lib/node_modules/playwright"); }
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const OUT = resolve(ROOT, "evidence/decision_support");
mkdirSync(resolve(OUT, "captures"), { recursive: true });
const checks = [];
const check = (id, ok, detail = "") => { checks.push({ id, ok: Boolean(ok), detail }); if (!ok) console.error(`FAIL ${id} ${detail}`); };

const procs = [];
const start = (cmd, args, env = {}) => {
  const p = spawn(cmd, args, { cwd: ROOT, env: { ...process.env, ...env }, stdio: "ignore", detached: true });
  procs.push(p);
  return p;
};
async function waitFor(url, ms = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { if ((await fetch(url)).ok) return; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`timeout waiting for ${url}`);
}

async function audit(page, label) {
  const r = await page.evaluate(async () => {
    const nodes = [...document.querySelectorAll("[data-src]")];
    const docs = {};
    const bad = [];
    for (const n of nodes) {
      const [doc, ptr] = n.dataset.src.split("#");
      docs[doc] ??= await (await fetch(`/api/decision/doc/${doc}`)).json();
      const value = ptr.split("/").slice(1).reduce((c, raw) => {
        const t = raw.replace(/~1/g, "/").replace(/~0/g, "~");
        return Array.isArray(c) ? c[Number(t)] : c?.[t];
      }, docs[doc]);
      if (JSON.stringify(value ?? null) !== n.dataset.raw) bad.push(n.dataset.src);
    }
    return { total: nodes.length, bad };
  });
  check(`T32:${label}`, r.total > 0 && r.bad.length === 0, JSON.stringify(r));
}

const statusOf = (page, scope) => page.locator(`${scope} [data-testid=ds-status]`).first().getAttribute("data-status");
let browser;
try {
  start("python3", ["web/decision/serve.py", "--port", "8765"], { PYTHONPATH: "src:." });
  start("node", ["web/node_modules/vite/bin/vite.js", "preview", "web", "--port", "4317", "--strictPort"]);
  await waitFor("http://127.0.0.1:8765/api/units");
  await waitFor("http://localhost:4317/");
  const base = "http://localhost:4317/";
  browser = await playwright.chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });

  await page.goto(base);
  await page.waitForSelector(".topbar");
  check("cockpit:existing_unit_screen_still_renders", (await page.locator("nav.nav a").count()) === 5);

  await page.click("nav.nav a[href='#/plan']");
  await page.waitForSelector("[data-testid=ds-auto] [data-testid=ds-status]");
  check("T15:auto_without_input", (await statusOf(page, "[data-testid=ds-auto]")) === "RECOMMENDATION_READY");
  check("T15:no_form_on_arrival", (await page.locator("[data-testid=ds-manual-form]").count()) === 0);
  check("api:live_engine_not_fixture", (await page.locator("[data-testid=ds-source]").count()) === 0);
  check("T11:conditional_visible", (await page.locator("[data-testid=ds-conditional]").count()) === 1);
  await audit(page, "auto");
  await page.screenshot({ path: resolve(OUT, "captures/react_01_plan_auto.png"), fullPage: true });

  await page.click("[data-testid=ds-modify]");
  await page.waitForSelector("[data-testid=ds-manual-form]");
  check("P4:manual_prefilled_from_auto", (await page.locator("select[name=x1]").inputValue()) === "S01");
  await page.fill("[data-testid=ds-x2-t]", "4");
  await page.click("[data-testid=ds-run-manual]");
  await page.waitForSelector("[data-testid=ds-manual] [data-testid=ds-status]");
  check("P4:manual_computed", ["RECOMMENDATION_READY", "NO_ACTION_PREFERRED"].includes(await statusOf(page, "[data-testid=ds-manual]")));
  check("T18:locks_shown", (await page.locator("[data-testid=ds-manual-actions] .ds-tag--lock").count()) === 2);
  check("P4:three_branches", (await page.locator("[data-testid=ds-branches] tbody tr").count()) === 3);
  await audit(page, "manual");
  await page.screenshot({ path: resolve(OUT, "captures/react_02_plan_manual.png"), fullPage: true });

  await page.selectOption("select[name=x1]", "S04");
  await page.selectOption("select[name=x1_basis]", "hypothesis_only");
  await page.click("[data-testid=ds-run-manual]");
  await page.waitForSelector("[data-testid=ds-manual] [data-status=HYPOTHETICAL_ONLY]");
  check("T06:hypothesis_not_approvable", await page.locator("[data-testid=ds-manual] [data-testid=ds-approve]").isDisabled());

  await page.click("[data-testid=ds-inject-revoke_S01]");
  await page.waitForSelector("[data-testid=ds-inject-revoke_S01][disabled]");
  await page.click("[data-testid=ds-auto] [data-testid=ds-approve]");
  await page.waitForSelector("[data-testid=ds-auto] [data-testid=ds-feedback]");
  check("T27:invalidated", (await page.getAttribute("[data-testid=ds-auto] [data-testid=ds-feedback]", "data-outcome")) === "INVALIDATED");
  await page.click("[data-testid=ds-recompute]");
  await page.waitForFunction(() => !document.querySelector("[data-testid=ds-auto] [data-testid=ds-feedback]"));
  const actions = await page.locator("[data-testid=ds-auto] [data-testid=ds-actions]").innerText().catch(() => "");
  check("T05:revoked_stay_not_proposed", !actions.includes("S01"), actions);
  await page.click("[data-testid=ds-auto] [data-testid=ds-approve]");
  await page.waitForSelector("[data-testid=ds-auto] [data-testid=ds-feedback]");
  check("P4:approve_in_demo_no_command", (await page.getAttribute("[data-testid=ds-auto] [data-testid=ds-feedback]", "data-outcome")) === "APPROVED_IN_DEMO");
  await fetch("http://127.0.0.1:8765/api/reset", { method: "POST", body: JSON.stringify({ unit: "nominal_auto" }) });

  await page.selectOption("[data-testid=ds-unit]", "insufficient_data");
  await page.waitForSelector("[data-testid=ds-auto] [data-status=INSUFFICIENT_DATA]");
  check("T17:abstention_with_diagnostics", (await page.locator("[data-testid=ds-diagnostics] li").count()) >= 1);

  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await phone.goto(`${base}#/plan`);
  await phone.waitForSelector("[data-testid=ds-auto] [data-testid=ds-status]");
  const overflow = await phone.evaluate(() => ({
    extra: document.documentElement.scrollWidth - window.innerWidth,
    wide: [...document.querySelectorAll("body *")].filter((n) => n.getBoundingClientRect().right > window.innerWidth + 0.5).slice(0, 3).map((n) => `${n.tagName}.${n.className}`),
  }));
  check("P4:no_horizontal_scroll_390px", overflow.extra <= 0, JSON.stringify(overflow));
  await phone.screenshot({ path: resolve(OUT, "captures/react_03_plan_phone.png"), fullPage: true });
} catch (error) {
  check("e2e:exception", false, String((error && error.stack) || error));
} finally {
  if (browser) await browser.close();
  for (const p of procs) { try { process.kill(-p.pid, "SIGTERM"); } catch { /* stopped */ } }
}
const failed = checks.filter((c) => !c.ok);
writeFileSync(resolve(OUT, "e2e_react_result.json"), JSON.stringify({ checks, failed: failed.length }, null, 1) + "\n");
console.log(JSON.stringify({ passed: checks.length - failed.length, failed: failed.length }));
process.exit(failed.length ? 1 : 0);
