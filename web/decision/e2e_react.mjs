// Exercise the actual unit API, switching focal without issuing a second recommendation.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const procs = [];
function start(cmd, args) {
  procs.push(spawn(cmd, args, { cwd: root, stdio: "ignore", env: { ...process.env, PYTHONPATH: "src:." } }));
}
async function ready(url) {
  for (let n = 0; n < 120; n++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw Error(`Server did not start at ${url}`);
}
let browser;
try {
  start(process.env.PYTHON || "python3", ["-m", "uvicorn", "services.api.hybrid_app:app", "--port", "8000"]);
  start("node", [
    "web/node_modules/vite/bin/vite.js",
    "preview",
    "web",
    "--host",
    "127.0.0.1",
    "--port",
    "4317",
    "--strictPort",
  ]);
  await Promise.all([ready("http://127.0.0.1:8000/health"), ready("http://127.0.0.1:4317/")]);
  browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
  const page = await browser.newPage();
  const docs = new Map();
  const foreign = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/decision")) foreign.push(r.url());
  });
  page.on("response", async (r) => {
    if (r.url().endsWith("/hybrid/plan") && r.ok()) {
      const p = await r.json();
      docs.set(p.plan_id, p);
    }
  });
  await page.goto("http://127.0.0.1:4317/?situation=garde&horloge=fixe");
  const card = page.getByTestId("proposal");
  await card.waitFor();
  const id = await card.getAttribute("data-plan-id");
  const unit = await card.getAttribute("data-unit");
  assert(id && unit);
  async function audit(selector, required) {
    const data = await page
      .locator(selector + " [data-src]")
      .evaluateAll((ns) => ns.map((n) => [n.dataset.src, n.dataset.raw]));
    for (const suffix of required)
      assert(
        data.some(([ref]) => ref.endsWith("/" + suffix)),
        `Missing ${suffix}`,
      );
    for (const [ref, raw] of data) {
      const [doc, ptr] = ref.split("#");
      assert.equal(doc, id);
      const value = ptr
        .slice(1)
        .split("/")
        .reduce((x, k) => x[k], docs.get(doc));
      assert.deepEqual(JSON.parse(raw), value);
    }
  }
  await audit("[data-testid=proposal]", ["saved_wait", "baseline_wait", "selected_wait", "scenarios"]);
  for (const focal of ["maintenant", "12h", "24h"]) {
    await page.evaluate((f) => {
      location.hash = "/plan/" + f;
    }, focal);
    await page.getByTestId("unit-evaluation").waitFor();
    const pane = page.locator(".ds-page[data-plan-id]");
    assert.equal(await pane.getAttribute("data-plan-id"), id);
    assert.equal(await pane.getAttribute("data-unit"), unit);
    await audit(".ds-page", ["created_at", "saved_wait", "baseline_wait", "selected_wait", "until"]);
    assert.equal(await pane.locator(".steps li").count(), 2);
  }
  for (const focal of ["3j", "7j"]) {
    await page.getByTestId(`focal-${focal}`).click();
    await page.getByTestId("ds-perspective").waitFor();
    await audit("[data-testid=ds-perspective]", [
      "bookings",
      "estimated_departures",
      "min_staffed_beds",
      "expected_ed_full_day",
    ]);
  }
  await page.getByRole("link", { name: "Voir les contrôles de l’unité" }).click();
  await page.getByRole("heading", { name: "Qualité des données" }).waitFor();
  await audit("[data-testid=outlook-quality]", [
    "received_at",
    "synced_at",
    "covers_until",
    "expected",
    "covered",
  ]);
  await page
    .getByRole("button", { name: /Médecine polyvalente/ })
    .first()
    .click();
  await page.getByRole("option", { name: /Court séjour gériatrique/ }).click();
  await page.evaluate(() => {
    location.hash = "/plan/12h";
  });
  await page.getByRole("heading", { name: /12 h · Court séjour gériatrique/ }).waitFor();
  const changed = page.locator(".ds-page[data-plan-id]");
  await page.waitForFunction(
    (key) =>
      document.querySelector(".ds-page")?.dataset.unit &&
      document.querySelector(".ds-page").dataset.unit !== key,
    unit,
  );
  assert.notEqual(await changed.getAttribute("data-plan-id"), id);
  assert.deepEqual(foreign, []);
  console.log("PASS · API hybrid · cinq focales · deux unités · renfort + admission · T32");
} finally {
  await browser?.close();
  for (const proc of procs) proc.kill();
}
