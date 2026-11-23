// End-to-end check of the decision view with the preinstalled Playwright/Chromium.
//   node web/decision/e2e.mjs
// Starts the local stdlib server as a child process and always stops it (no orphan).
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

const server = spawn("python3", ["web/decision/serve.py", "--port", "0"], {
  cwd: ROOT, env: { ...process.env, PYTHONPATH: "src:." }, stdio: ["ignore", "pipe", "inherit"], detached: true,
});
const url = await new Promise((ok, ko) => {
  const timer = setTimeout(() => ko(new Error("server did not start")), 10000);
  server.stdout.on("data", (b) => { const m = /READY (\S+)/.exec(String(b)); if (m) { clearTimeout(timer); ok(m[1]); } });
});

async function audit(page, label) {
  const r = await page.evaluate(async () => {
    const nodes = [...document.querySelectorAll("[data-src]")];
    const docs = {};
    let bad = [];
    for (const n of nodes) {
      const [doc, ptr] = n.dataset.src.split("#");
      docs[doc] ??= await (await fetch(`/api/doc/${doc}`)).json();
      const value = ptr.split("/").slice(1).reduce((c, t) => (Array.isArray(c) ? c[Number(t.replace(/~1/g, "/").replace(/~0/g, "~"))] : c?.[t.replace(/~1/g, "/").replace(/~0/g, "~")]), docs[doc]);
      if (JSON.stringify(value ?? null) !== n.dataset.raw) bad.push(n.dataset.src);
    }
    const loose = [...document.querySelectorAll(".ds-fig b, td.n")].filter((b) => {
      const c = b.cloneNode(true); c.querySelectorAll("[data-src]").forEach((s) => s.remove());
      return /\d/.test(c.textContent);
    }).length;
    return { total: nodes.length, bad, loose };
  });
  check(`T32:${label}`, r.total > 0 && r.bad.length === 0 && r.loose === 0, JSON.stringify(r));
  return r;
}

let browser;
const status = (page, scope) => page.locator(`${scope} [data-testid=status]`).first().getAttribute("data-status");
try {
  browser = await playwright.chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  await page.goto(url);
  await page.waitForSelector("#auto-body [data-testid=status]");
  check("T15:auto_without_input", (await status(page, "#auto-body")) === "RECOMMENDATION_READY");
  check("T15:manual_form_closed_on_open", await page.locator("[data-testid=manual-form]").isHidden());
  check("P4:actions_listed", (await page.locator("[data-testid=actions] li").count()) >= 1);
  check("T11:conditional_visible", (await page.locator("[data-testid=conditional]").count()) <= 1);
  await audit(page, "auto");
  await page.screenshot({ path: resolve(OUT, "captures/01_auto_nominal.png"), fullPage: true });

  // manual X1/X2 from the automatic plan
  await page.click("[data-testid=modify]");
  await page.waitForSelector("[data-testid=manual-form]:not([hidden])");
  const x1 = await page.locator("select[name=x1]").inputValue();
  check("P4:manual_prefilled_from_auto", x1 === "S01", x1);
  await page.fill("[data-testid=x2-t]", "4");
  await page.click("[data-testid=run-manual]");
  await page.waitForSelector("[data-testid=manual-card] [data-testid=status]");
  const mStatus = await status(page, "#manual-body");
  check("P4:manual_computed", ["RECOMMENDATION_READY", "NO_ACTION_PREFERRED"].includes(mStatus), mStatus);
  check("T18:locks_shown", (await page.locator("[data-testid=manual-actions] .ds-tag--lock").count()) === 2);
  check("P4:branches", (await page.locator("[data-testid=branches] tbody tr").count()) === 3);
  await audit(page, "manual");
  await page.screenshot({ path: resolve(OUT, "captures/02_manual_x1x2.png"), fullPage: true });

  // hypothesis: discharge without authorisation
  await page.selectOption("select[name=x1]", "S04");
  await page.selectOption("select[name=x1_basis]", "hypothesis_only");
  await page.click("[data-testid=run-manual]");
  await page.waitForSelector("[data-testid=manual-card] [data-status=HYPOTHETICAL_ONLY]");
  check("T06:hypothesis_not_approvable", await page.locator("[data-testid=manual-card] [data-testid=approve]").isDisabled());

  // new information -> invalidation -> explicit recomputation
  await page.click("[data-testid=inject-revoke_S01]");
  await page.click("#auto-body [data-testid=approve]");
  await page.waitForSelector("#auto-body [data-testid=review-feedback][data-outcome]");
  check("T27:invalidated", (await page.getAttribute("#auto-body [data-testid=review-feedback]", "data-outcome")) === "INVALIDATED");
  await page.click("[data-testid=recompute]");
  await page.waitForSelector("#auto-body [data-testid=status]");
  const after = await page.locator("#auto-body [data-testid=actions]").innerText().catch(() => "");
  check("T05:revoked_stay_not_proposed", !after.includes("S01"), after);
  await page.click("#auto-body [data-testid=approve]");
  await page.waitForSelector("#auto-body [data-testid=review-feedback][data-outcome]");
  const outcome = await page.getAttribute("#auto-body [data-testid=review-feedback]", "data-outcome");
  check("P4:approve_in_demo_no_command", outcome === "APPROVED_IN_DEMO" || (await status(page, "#auto-body")) === "NO_ACTION_PREFERRED", outcome);
  await page.screenshot({ path: resolve(OUT, "captures/03_after_new_information.png"), fullPage: true });
  await page.click("text=Réinitialiser la démo");

  for (const [unit, expected] of [["insufficient_data", "INSUFFICIENT_DATA"], ["no_action", "NO_ACTION_PREFERRED"]]) {
    await page.selectOption("[data-testid=unit]", unit);
    await page.waitForSelector(`#auto-body [data-status=${expected}]`);
    check(`T16_T17:${unit}`, true, expected);
    if (unit === "insufficient_data") {
      check("T17:diagnostics_shown", (await page.locator("[data-testid=diagnostics] li").count()) >= 1);
      await page.screenshot({ path: resolve(OUT, "captures/04_abstention.png"), fullPage: true });
    } else await audit(page, "no_action");
  }

  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
  await phone.goto(url);
  await phone.waitForSelector("#auto-body [data-testid=status]");
  const overflow = await phone.evaluate(() => {
    const extra = document.documentElement.scrollWidth - window.innerWidth;
    const wide = [...document.querySelectorAll("body *")].filter((n) => n.getBoundingClientRect().right > window.innerWidth + 0.5)
      .slice(0, 3).map((n) => `${n.tagName}.${n.className}`);
    return { extra, wide };
  });
  check("P4:no_horizontal_scroll_390px", overflow.extra <= 0, JSON.stringify(overflow));
  await phone.screenshot({ path: resolve(OUT, "captures/05_phone_390.png"), fullPage: true });
} catch (error) {
  check("e2e:exception", false, String(error && error.stack || error));
} finally {
  if (browser) await browser.close();
  try { process.kill(-server.pid, "SIGTERM"); } catch { /* already stopped */ }
}
const failed = checks.filter((c) => !c.ok);
writeFileSync(resolve(OUT, "e2e_result.json"), JSON.stringify({ url_was_loopback: url.startsWith("http://127.0.0.1"), checks, failed: failed.length }, null, 1) + "\n");
console.log(JSON.stringify({ passed: checks.length - failed.length, failed: failed.length }));
process.exit(failed.length ? 1 : 0);
