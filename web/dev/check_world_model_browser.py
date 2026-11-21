"""Exercise the built cockpit, live API, human confirmation and delayed data in Chromium."""

from __future__ import annotations

import argparse
import os
import re
from itertools import product
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Browser, Response, expect, sync_playwright


def unit_journey(
    browser: Browser, url: str, entry: str, site: str, phone: bool, screenshots: Path | None
) -> None:
    page = browser.new_page(
        viewport={"width": 390 if phone else 1440, "height": 844 if phone else 940}, locale="fr-FR"
    )
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(url.rstrip("/") + "/" + entry)
        hospital = page.get_by_role("combobox", name="Établissement")
        ward = page.get_by_role("combobox", name="Unité suivie")
        panel = page.get_by_role("region", name="Recommandation de l’unité")
        priority = page.get_by_role("combobox", name="Priorité de l’unité")
        expect(hospital).to_be_visible()
        expect(panel).to_be_visible()
        expect(hospital).to_have_value("rives")
        expect(ward).to_have_value("u6")
        expect(priority).to_have_value("bed_wait")
        expect(page.get_by_role("combobox", name="Contexte synthétique")).to_have_count(0)
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and "/world-model/sessions/" in response.url
                and response.request.post_data_json.get("context_id") == site
            )
        ) as opened:
            hospital.select_option(site)
        session = opened.value.json()
        assert session["context"]["id"] == site and session["phase"] == "planning"
        identifier = session["id"]
        ward_label = next(w["label"] for w in session["wards"] if w["id"] == "u6")
        menu_path = "/world-model/sessions/" + identifier + "/plans"

        def matching_menu(response: Response, objective: str) -> bool:
            loc = urlsplit(response.url)
            query = parse_qs(loc.query)
            return (
                response.request.method == "GET"
                and loc.path.endswith(menu_path)
                and query.get("ward_id") == ["u6"]
                and query.get("objective") == [objective]
            )

        expect(ward).to_be_enabled()
        if ward.input_value() == "u6":
            ward.select_option("u1")
            expect(ward).to_have_value("u1")
        with page.expect_response(lambda response: matching_menu(response, "bed_wait")) as response:
            ward.select_option("u6")
        initial = response.value.json()
        assert initial["context_id"] == site and initial["ward_id"] == "u6"
        assert initial["ward_state"]["context_id"] == site
        assert (
            initial["ward_state"]["ward_id"] == "u6" and initial["ward_state"]["as_of_hour"] == 12
        )
        assert initial["reference"]["ward_metrics"] is not None
        expect(ward.locator("option:checked")).to_contain_text(ward_label)
        with page.expect_response(
            lambda response: matching_menu(response, "uncovered_care")
        ) as revised:
            priority.select_option("uncovered_care")
        menu = revised.value.json()
        assert menu["ward_state"] == initial["ward_state"]
        assert menu["objective"] == "uncovered_care" and menu["context_id"] == site
        recommended = menu["recommendations"][0]
        assert recommended["context_id"] == site and recommended["ward_id"] == "u6"
        local = recommended["ward_metrics"]
        minutes = local["uncovered_ide_minutes"] + local["uncovered_as_minutes"]
        formatted = page.evaluate(
            "v => new Intl.NumberFormat('fr-FR', {maximumFractionDigits: 2}).format(v)", minutes
        )
        expect(panel.get_by_text(f"Soins non couverts · {ward_label}", exact=True)).to_be_visible()
        expect(panel.get_by_text(f"{formatted} minutes", exact=True).first).to_be_visible()
        button_name = r"^Valider (?:l.action|les \d+ actions|le maintien du planning)$"
        confirm = panel.get_by_role("button", name=re.compile(button_name))
        expect(confirm).to_be_enabled()
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=screenshots / f"{site}-unite-u6.png", full_page=True)
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlsplit(response.url).path.endswith(menu_path + "/confirm")
            )
        ) as confirmation:
            confirm.click()
        saved = confirmation.value.json()
        assert saved["id"] == identifier and saved["context"]["id"] == site
        assert saved["phase"] == "confirmed" and saved["decision_ward_id"] == "u6"
        assert saved["decision_objective"] == "uncovered_care"
        assert saved["confirmed_plan"]["id"] == recommended["id"]
        assert saved["confirmed_plan"]["action_ids"] == recommended["action_ids"]
        assert saved["plan_snapshot"]["ward_id"] == "u6" and saved["observation"] is None
        assert [e["ward_id"] for e in saved["journal"] if e["event"] == "confirmed"] == ["u6"]
        ward.select_option("u1")
        expect(
            panel.get_by_role("heading", name="Décision enregistrée pour " + ward_label)
        ).to_be_visible()
        expect(confirm).to_have_count(0)
        ward.select_option("u6")
        page.get_by_role("link", name="Journal", exact=True).first.click()
        expect(page).to_have_url(re.compile(r"#/journal$"))
        page.reload()
        journal = page.get_by_role("region", name="Journal des décisions")
        expect(
            journal.get_by_role("heading", name="Décisions de " + session["context"]["label"])
        ).to_be_visible()
        expect(journal.get_by_text("Décision validée", exact=True)).to_be_visible()
        expect(journal.get_by_text(ward_label, exact=False).first).to_be_visible()
        page.get_by_role("link", name="Unité", exact=True).first.click()
        expect(hospital).to_have_value(site)
        expect(ward).to_have_value("u6")
        expect(confirm).to_have_count(0)
        expect(panel.get_by_text("Choix enregistré", exact=False)).to_be_visible()
        # The archived scientific workstation can open its own episode in this hospital.
        page.goto(url.rstrip("/") + "/#/laboratoire")
        lab = page.get_by_role("combobox", name="Contexte synthétique")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and "/world-model/sessions/" in response.url
                and response.request.post_data_json.get("context_id") == site
            )
        ) as separate:
            lab.select_option(site)
        experiment = separate.value.json()
        assert experiment["id"] != identifier and experiment["context"]["id"] == site
        assert experiment["phase"] == "planning" and experiment["confirmed_plan"] is None
        page.goto(url.rstrip("/") + "/#/unite")
        expect(ward).to_have_value("u6")
        expect(panel.get_by_text("Choix enregistré", exact=False)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
        print(f"{site}/u6 : recommandation locale validée et journal repris", flush=True)
    finally:
        page.close()


def adjusted_unit_journey(browser: Browser, url: str, screenshots: Path | None) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844}, locale="fr-FR")
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(url.rstrip("/") + "/#/unite")
        expect(page.get_by_role("combobox", name="Établissement")).to_have_value("rives")
        expect(page.get_by_role("combobox", name="Unité suivie")).to_have_value("u6")
        panel = page.get_by_role("region", name="Recommandation de l’unité")
        panel.get_by_role("button", name="Ajuster les actions").click()
        choices = panel.get_by_role("group", name="Actions du plan ajusté")
        for box in choices.get_by_role("checkbox").all():
            if box.is_checked():
                box.uncheck()
        replacement = choices.get_by_role("checkbox", name=re.compile(r"Remplacer l.IDE absente"))
        replacement.check()
        confirm = panel.get_by_role("button", name="Valider l’action", exact=True)
        expect(confirm).to_have_count(0)
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/plans/preview")
        ) as result:
            panel.get_by_role("button", name="Évaluer les actions").click()
        preview = result.value.json()
        assert preview["context_id"] == "rives" and preview["ward_id"] == "u6"
        assert preview["action_ids"] == ["replacement-ide"] and preview["feasible"]
        assert preview["access_warnings"] == [] and preview["cost_eur"] == 190
        assert preview["realized"]["replacement-ide"] == 240 and preview["ward_metrics"]
        expect(confirm).to_be_enabled()
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=screenshots / "rives-u6-ajustement.png", full_page=True)
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/plans/confirm")
        ) as result:
            confirm.click()
        assert result.value.request.post_data_json["preview_id"] == preview["id"]
        saved = result.value.json()
        assert saved["context"]["id"] == "rives" and saved["decision_ward_id"] == "u6"
        assert saved["confirmed_plan"]["id"] == preview["id"]
        assert saved["confirmed_plan"]["action_ids"] == ["replacement-ide"]
        assert saved["phase"] == "confirmed" and saved["observation"] is None
        page.get_by_role("link", name="Journal", exact=True).first.click()
        page.reload()
        journal = page.get_by_role("region", name="Journal des décisions")
        expect(journal.get_by_text("Décision validée", exact=True)).to_be_visible()
        expect(
            journal.get_by_text(re.compile(r"Remplacer l.IDE absente.*Observation courte 6"))
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
        print("Rives/u6 : remplacement IDE évalué, validé et relu dans le journal", flush=True)
    finally:
        page.close()


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
        page.goto(url.rstrip("/") + "/#/laboratoire")
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
            unit_journey(browser, url, "", "parc", False, screenshots)
            unit_journey(browser, url, "#/simulation", "belvedere", True, screenshots)
            adjusted_unit_journey(browser, url, screenshots)
            cases = [("rives", 1440, 940), ("parc", 390, 844), ("belvedere", 390, 844)]
            families = ("transport", "cleaning", "staffing", "smr", "beds")
            for (context_id, width, height), family in product(cases, families):
                page = browser.new_page(viewport={"width": width, "height": height}, locale="fr-FR")
                page_errors: list[str] = []
                page.on("pageerror", lambda error, errors=page_errors: errors.append(str(error)))
                page.goto(url.rstrip("/") + "/#/laboratoire")
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
