"""Exercise the built cockpit, live API, human confirmation and delayed data in Chromium."""

from __future__ import annotations

import argparse
import os
from itertools import product
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def check(url: str, screenshots: Path | None = None) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.getenv("HOSPITALOS_CHROME") or None)
        try:
            cases = [("rives", 1440, 940), ("parc", 390, 844), ("belvedere", 390, 844)]
            families = ("transport", "cleaning", "staffing", "smr", "beds")
            for (context_id, width, height), family in product(cases, families):
                page = browser.new_page(viewport={"width": width, "height": height}, locale="fr-FR")
                page_errors: list[str] = []
                page.on("pageerror", lambda error, errors=page_errors: errors.append(str(error)))
                page.goto(url.rstrip("/") + "/#/simulation")
                expect(page.get_by_role("heading", name="Simuler une affectation")).to_be_visible()
                page.get_by_role("combobox", name="Contexte synthétique").select_option(context_id)
                objective = {"staffing": "uncovered_care", "beds": "bed_wait"}.get(
                    family, "transfer_queue"
                )
                page.get_by_role("combobox", name="Critère de comparaison à midi").select_option(
                    objective
                )
                choice = page.locator(f'input[type="radio"][value^="{family}-"]:enabled').first
                expect(choice).to_be_visible()
                expect(page.get_by_role("button", name="Avancer à 16 h")).to_be_disabled()
                if screenshots and family == "beds":
                    screenshots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=screenshots / f"{context_id}-midi.png", full_page=True)
                choice.check()
                with page.expect_response(
                    lambda r: r.url.endswith("/confirm") and r.request.method == "POST"
                ) as result:
                    page.get_by_role("button", name="Valider en simulation").click()
                confirmed = result.value.json()
                assert confirmed["decision_objective"] == objective
                assert confirmed["context"]["id"] == context_id
                assert confirmed["selected_id"].startswith(f"{family}-")
                assert confirmed["phase"] == "confirmed" and confirmed["observation"] is None
                with page.expect_response(
                    lambda r: r.url.endswith("/advance") and r.request.method == "POST"
                ) as result:
                    page.get_by_role("button", name="Avancer à 16 h").click()
                end = result.value.json()
                if context_id == "belvedere":
                    assert end["decision_objective"] == objective
                    assert end["phase"] == "awaiting_report" and end["observation"] is None
                    expect(
                        page.get_by_role("heading", name="Le relevé de 16 h est en attente")
                    ).to_be_visible()
                    with page.expect_response(
                        lambda r: r.url.endswith("/advance") and r.request.method == "POST"
                    ) as result:
                        page.get_by_role("button", name="Avancer à 18 h").click()
                    end = result.value.json()
                assert end["decision_objective"] == objective
                assert end["phase"] == "review" and end["selected_id"] == confirmed["selected_id"]
                reading = page.get_by_role("region", name="Comparaison après relevé")
                expect(
                    reading.get_by_role("heading", name="La file observée à 16 h")
                ).to_be_visible()
                alternatives = reading.get_by_role("combobox")
                alternatives.select_option(index=1)
                if context_id != "rives":
                    expect(reading.get_by_text("Non renseignée").first).to_be_visible()
                page.reload()
                expect(page.get_by_role("region", name="Comparaison après relevé")).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                if screenshots and family == "beds":
                    page.screenshot(path=screenshots / f"{context_id}-releve.png", full_page=True)
                assert not page_errors, page_errors
                print(
                    f"{context_id}/{family}: {end['hour']} h, choix confirmé et journal repris",
                    flush=True,
                )
                page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    check(args.url, args.screenshots)
