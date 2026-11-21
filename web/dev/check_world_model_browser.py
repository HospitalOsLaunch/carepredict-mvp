"""Exercise the built cockpit, live API, human confirmation and delayed data in Chromium."""

from __future__ import annotations

import argparse
import os
from itertools import product
from pathlib import Path

from playwright.sync_api import Browser, expect, sync_playwright


def composed_journey(
    browser: Browser, url: str, context: str, subset: bool, screenshots: Path | None
) -> None:
    phone = context != "rives" or subset
    page = browser.new_page(
        viewport={"width": 390 if phone else 1440, "height": 844 if phone else 940}, locale="fr-FR"
    )
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(url.rstrip("/") + "/#/simulation")
        page.get_by_role("combobox", name="Contexte synthétique").select_option(context)
        expect(page.get_by_role("heading", name="Comparer les plans composés")).to_be_visible()
        page.get_by_role("combobox", name="Critère du plan à midi").select_option("bed_wait")
        if context == "rives":
            with page.expect_response(lambda r: r.url.endswith("/plans/preview")) as res:
                page.get_by_role("button", name="Essayer le plan à 8 actions").click()
            example = res.value.json()
            assert example["feasible"] and len(example["action_ids"]) == 8
            if subset:
                with page.expect_response(lambda r: r.url.endswith("/plans/optimize")) as res:
                    page.get_by_role("button", name="Comparer les sous-ensembles").click()
                assert res.value.json()["search"]["examined"] == 256
                page.get_by_role("region", name="Sous-plans du brouillon").get_by_role(
                    "radio"
                ).first.check()
        # Wait for the initial site/criterion request before acting on the current menu.
        confirm = page.get_by_role("button", name="Valider le plan en simulation")
        expect(confirm).to_be_enabled()
        with page.expect_response(lambda r: r.url.endswith("/plans/confirm")) as res:
            confirm.click()
        saved = res.value.json()
        assert saved["context"]["id"] == context and saved["phase"] == "confirmed"
        assert saved["decision_objective"] == "bed_wait" and saved["plan_report"] is None
        if context == "rives":
            assert saved["plan_snapshot"]["search"]["complete"] == subset
            assert len(saved["confirmed_plan"]["action_ids"]) in (range(1, 8) if subset else (8,))
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=screenshots / f"{context}-plan-{'partiel' if subset else 'complet'}.png",
                full_page=True,
            )
        with page.expect_response(lambda r: r.url.endswith("/advance")) as res:
            page.get_by_role("button", name="Avancer à 16 h").click()
        final = res.value.json()
        if context == "belvedere":
            assert final["observation"] is None and final["plan_report"] is None
            with page.expect_response(lambda r: r.url.endswith("/advance")) as res:
                page.get_by_role("button", name="Avancer à 18 h").click()
            final = res.value.json()
        assert final["phase"] == "review" and final["confirmed_plan"] == saved["confirmed_plan"]
        assert (final["plan_report"]["actual_metrics"] is not None) == (context == "rives")
        if context == "rives" and not subset:
            assert (
                final["plan_report"]["realized"]["A3"] == 0
                and saved["confirmed_plan"]["realized"]["A3"] == 1
            )
        page.reload()
        expect(page.get_by_role("region", name="Relevé du plan composé")).to_be_visible()
        expect(page.get_by_role("region", name="Plan composé validé")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        if screenshots:
            page.screenshot(
                path=screenshots
                / f"{context}-relecture-{'partielle' if subset else 'complete'}.png",
                full_page=True,
            )
        assert not errors, errors
        print(
            f"{context}: {len(saved['confirmed_plan']['action_ids'])} interventions relues",
            flush=True,
        )
    finally:
        page.close()


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
                expect(page.get_by_role("combobox", name="Contexte synthétique")).to_be_visible()
                page.get_by_role("combobox", name="Contexte synthétique").select_option(context_id)
                page.get_by_role("button", name="Action unique").click()
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
            for ctx, subset in (
                ("rives", False),
                ("rives", True),
                ("parc", False),
                ("belvedere", False),
            ):
                composed_journey(browser, url, ctx, subset, screenshots)
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    check(args.url, args.screenshots)
