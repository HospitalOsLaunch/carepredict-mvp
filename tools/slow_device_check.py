"""Opens HospitalOS the way a cadre does on a mid-range phone in a corridor, and checks budgets.

Règle 31 de l'audit de performance : tester sur un appareil et un réseau lents, pas seulement
sur le poste du développeur. The reference profile is the one Lighthouse uses for mobile
(processor slowed down 4 times, « slow 4G »: 150 ms round trip, 1.6 Mbit/s); a harsher
« 3g » profile (old tablet, weak signal) can be run by hand.

What is measured, on the production build served by nginx (compressed, cached):
- first visit (empty cache): the login page, then the first screen after signing in;
- each daily screen opened again (cache warm, as when a bookmark is opened during a round):
  time until the content is shown (title, no skeleton left), LCP, CLS, blocking time.

Only timings and sizes are printed: no patient, no name, nothing from the screens.

    python tools/slow_device_check.py --web http://127.0.0.1:8080
    python tools/slow_device_check.py --web http://127.0.0.1:8080 --profile 3g --no-budgets

Exit code 1 when a budget of the reference profile is exceeded.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass

from playwright.sync_api import Page, sync_playwright

PASSWORD = "demo-hospitalos-2026"


@dataclass(frozen=True)
class Profile:
    cpu: float  # how many times slower than this machine
    rtt_ms: int
    down_kbps: int
    up_kbps: int


PROFILES = {
    # Lighthouse mobile (« Moto G Power », slow 4G).
    "mobile": Profile(cpu=4, rtt_ms=150, down_kbps=1600, up_kbps=750),
    # Old tablet on a weak signal at the end of a corridor: informative, no budget.
    "3g": Profile(cpu=6, rtt_ms=300, down_kbps=750, up_kbps=250),
}

# The daily screens of the personas (MobileNav.PRIMARY), as a bed manager sees them.
SCREENS = ["/plan-des-lits", "/urgences", "/demandes", "/lits", "/groupe", "/prevision", "/agents"]

# Budgets for the reference profile. Thresholds of the Core Web Vitals (« good » up to
# 2.5 s for LCP, 0.1 for CLS) where they apply; times are generous enough for a shared CI
# runner, tight enough to catch a screen that doubles its weight or starts to jump.
BUDGETS = {
    "login_lcp_ms": 4000,  # beyond 4 s, the Core Web Vitals call the LCP « poor »
    "login_js_kb": 150,
    "first_screen_ms": 6000,
    "screen_ready_ms": 5000,
    "screen_cls": 0.1,
}

OBSERVERS = """
window.__perf = { lcp: 0, cls: 0, tbt: 0 };
const watch = (type, add) =>
  new PerformanceObserver((l) => l.getEntries().forEach(add)).observe({ type, buffered: true });
try {
  watch('largest-contentful-paint', (e) => { window.__perf.lcp = e.startTime; });
  watch('layout-shift', (e) => { if (!e.hadRecentInput) window.__perf.cls += e.value; });
  watch('longtask', (e) => { window.__perf.tbt += Math.max(0, e.duration - 50); });
} catch (e) { /* an observer this browser lacks: the value stays at 0 */ }
"""

READY = """() => {
  const h1 = document.querySelector('main h1');
  return !!h1 && !document.querySelector('[data-testid=skeleton]');
}"""


@dataclass
class ScreenResult:
    route: str
    ready_ms: int
    lcp_ms: int
    cls: float
    tbt_ms: int
    kb: int


def throttle(page: Page, p: Profile) -> None:
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": p.cpu})
    cdp.send("Network.enable")
    cdp.send(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "latency": p.rtt_ms,
            "downloadThroughput": p.down_kbps * 1000 / 8,
            "uploadThroughput": p.up_kbps * 1000 / 8,
        },
    )


def transferred_kb(page: Page, kind: str | None = None) -> int:
    script = """(kind) => {
      const size = (type) => performance.getEntriesByType(type)
        .filter((e) => !kind || e.initiatorType === kind || e.name.endsWith('.' + kind))
        .reduce((n, e) => n + e.transferSize, 0);
      return size('resource') + (kind ? 0 : size('navigation'));
    }"""
    total: int = page.evaluate(script, kind)
    return round(total / 1024)


def perf(page: Page) -> dict[str, float]:
    page.wait_for_timeout(300)  # the last layout shifts and the LCP candidate are reported
    return page.evaluate("window.__perf")  # type: ignore[no-any-return]


def run(web: str, email: str, profile: Profile) -> tuple[dict[str, int], list[ScreenResult]]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            device_scale_factor=2,
        )
        context.add_init_script(OBSERVERS)
        page = context.new_page()
        throttle(page, profile)

        # First visit: empty cache.
        page.goto(web + "/", wait_until="load")
        page.wait_for_selector("#email")
        login = perf(page)
        first: dict[str, int] = {
            "login_lcp_ms": round(login["lcp"]),
            "login_js_kb": transferred_kb(page, "js"),
        }
        page.fill("#email", email)
        page.fill("#password", PASSWORD)
        t0 = time.monotonic()
        page.click("button[type=submit]")
        page.wait_for_function(READY, timeout=60_000)
        first["first_screen_ms"] = round((time.monotonic() - t0) * 1000)

        screens: list[ScreenResult] = []
        for route in SCREENS:
            t0 = time.monotonic()
            page.goto(web + route, wait_until="commit")
            page.wait_for_function(READY, timeout=60_000)
            ready = round((time.monotonic() - t0) * 1000)
            m = perf(page)
            screens.append(
                ScreenResult(
                    route,
                    ready,
                    round(m["lcp"]),
                    round(m["cls"], 3),
                    round(m["tbt"]),
                    transferred_kb(page),
                )
            )
        browser.close()
        return first, screens


def over_budget(first: dict[str, int], screens: list[ScreenResult]) -> list[str]:
    out = [f"{k} = {v} > {BUDGETS[k]}" for k, v in first.items() if v > BUDGETS[k]]
    for s in screens:
        if s.ready_ms > BUDGETS["screen_ready_ms"]:
            out.append(f"{s.route} prêt en {s.ready_ms} ms > {BUDGETS['screen_ready_ms']}")
        if s.cls > BUDGETS["screen_cls"]:
            out.append(f"{s.route} CLS {s.cls} > {BUDGETS['screen_cls']}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--web", default="http://127.0.0.1:8080")
    ap.add_argument("--email", default="bedmanager@ch-demo.hospitalos.fr")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="mobile")
    ap.add_argument("--json", help="also write the results to this file")
    ap.add_argument("--no-budgets", action="store_true", help="report only")
    args = ap.parse_args()

    profile = PROFILES[args.profile]
    first, screens = run(args.web.rstrip("/"), args.email, profile)

    p = profile
    print(
        f"Profil « {args.profile} » : processeur ×{p.cpu:g}, {p.rtt_ms} ms, "
        f"{p.down_kbps / 1000:g} Mbit/s, écran 390 px"
    )
    print(
        f"Première visite : connexion LCP {first['login_lcp_ms']} ms, "
        f"JS {first['login_js_kb']} Ko ; premier écran en {first['first_screen_ms']} ms"
    )
    head = ("écran", "prêt (ms)", "LCP (ms)", "CLS", "blocage (ms)", "Ko")
    print(f"{head[0]:16} {head[1]:>10} {head[2]:>9} {head[3]:>6} {head[4]:>13} {head[5]:>5}")
    for s in screens:
        print(f"{s.route:16} {s.ready_ms:10} {s.lcp_ms:9} {s.cls:6.3f} {s.tbt_ms:13} {s.kb:5}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "profile": args.profile,
                    "first_visit": first,
                    "screens": [asdict(s) for s in screens],
                },
                f,
                indent=2,
            )

    if args.no_budgets or args.profile != "mobile":
        return 0
    failures = over_budget(first, screens)
    for failure in failures:
        print(f"::error title=Budget appareil lent::{failure}")
    if not failures:
        print("Budgets respectés.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
