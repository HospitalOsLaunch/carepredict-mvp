"""Exercise the built cockpit, live API, human confirmation and delayed data in Chromium."""

from __future__ import annotations

import argparse
import os
import re
from itertools import product
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Browser, Page, Request, Response, expect, sync_playwright

CONFIRM_UNIT = re.compile(r"^Valider (?:l.action|les \d+ actions|le maintien du planning)$")


def open_section(page: Page, label: str) -> None:
    page.get_by_role("navigation", name="Sections").get_by_role(
        "link", name=label, exact=True
    ).first.click()


def check_unit_board(page: Page, evidence: dict[str, list[str]] | None = None) -> None:
    for label in ("Libérer", "Lits", "Attribuer"):
        controls = page.get_by_role("group", name="Colonne affichée")
        if controls.count():
            controls.get_by_role("button", name=label, exact=True).click()
        else:
            tab = page.get_by_role("tab", name=label, exact=True)
            if tab.count():
                tab.click()
        region = page.get_by_role("region", name=label, exact=True)
        expect(region.get_by_role("heading", name=label, exact=True)).to_be_visible()
        for value in (evidence or {}).get(label, []):
            expect(region.get_by_text(value, exact=True).first).to_be_visible()
    expect(page.get_by_role("button", name=CONFIRM_UNIT)).to_have_count(0)


def confirmation_requests(page: Page) -> list[str]:
    requests: list[str] = []

    def record(request: Request) -> None:
        if request.method == "POST" and urlsplit(request.url).path.endswith("/plans/confirm"):
            requests.append(request.url)

    page.context.on("request", record)
    return requests


def check_width(page: Page) -> None:
    layout = page.evaluate("""async () => {
        await document.fonts.ready;
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const width = document.documentElement.scrollWidth;
        const overflow = Array.from(document.body.querySelectorAll("*"))
            .filter(el => el.getBoundingClientRect().right + scrollX > innerWidth + .25 ||
                    (el.scrollWidth > el.clientWidth + 1 && el.clientWidth))
            .map(el => [el.tagName, String(el.className), el.clientWidth, el.scrollWidth])
            .slice(0, 25);
        return { width, viewport: innerWidth, scrollX, overflow };
    }""")
    assert layout["width"] <= layout["viewport"], layout


def unit_journey(
    browser: Browser, url: str, entry: str, site: str, phone: bool, screenshots: Path | None
) -> None:
    page = browser.new_page(
        viewport={"width": 390 if phone else 1440, "height": 844 if phone else 940}, locale="fr-FR"
    )
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    confirmations = confirmation_requests(page)
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
        check_unit_board(page)
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
        census = initial["ward_state"]
        check_unit_board(
            page,
            {
                "Libérer": [c["id"] for c in census["cases"] if c["kind"] == "discharge"],
                "Lits": [f"{census['capacity_beds']} lits équipés · {ward_label}"],
                "Attribuer": [c["id"] for c in census["cases"] if c["kind"] == "admission"],
            },
        )
        panel.get_by_role("link", name="Ouvrir dans Action").click()
        expect(page).to_have_url(re.compile(r"#/action$"))
        expect(hospital).to_have_value(site)
        expect(ward).to_have_value("u6")
        expect(priority).to_have_value("bed_wait")
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
        confirm = panel.get_by_role("button", name=CONFIRM_UNIT)
        expect(confirm).to_be_enabled()
        action_title = panel.get_by_role("heading", level=2).inner_text()
        open_section(page, "Unité")
        expect(hospital).to_have_value(site)
        expect(ward).to_have_value("u6")
        check_unit_board(page)
        expect(panel.get_by_role("heading", name=action_title, exact=True)).to_be_visible()
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=screenshots / f"{site}-unite-u6.png", full_page=True)
        open_section(page, "Action")
        expect(priority).to_have_value("uncovered_care")
        expect(panel.get_by_role("heading", name=action_title, exact=True)).to_be_visible()
        expect(panel.get_by_text(f"{formatted} minutes", exact=True).first).to_be_visible()
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
        check_width(page)
        assert confirmations == [confirmation.value.url], confirmations
        assert not errors, errors
        print(f"{site}/u6 : recommandation locale validée et journal repris", flush=True)
    finally:
        page.close()


def adjusted_unit_journey(browser: Browser, url: str, screenshots: Path | None) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844}, locale="fr-FR")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    confirmations = confirmation_requests(page)
    try:
        page.goto(url.rstrip("/") + "/#/unite")
        expect(page.get_by_role("combobox", name="Établissement")).to_have_value("rives")
        expect(page.get_by_role("combobox", name="Unité suivie")).to_have_value("u6")
        panel = page.get_by_role("region", name="Recommandation de l’unité")
        check_unit_board(page, {"Libérer": ["S2"], "Attribuer": ["A2", "A3"]})
        open_section(page, "Action")
        panel.get_by_text("Comparer les alternatives", exact=True).click()
        panel.get_by_role("radio", name=re.compile(r"^Maintenir le planning actuel")).check()
        open_section(page, "Unité")
        expect(panel.get_by_role("heading", name="Maintenir le planning actuel")).to_be_visible()
        page.reload()
        expect(panel.get_by_text("Alternative sélectionnée", exact=True)).to_be_visible()
        open_section(page, "Action")
        expect(panel.get_by_role("heading", name="Maintenir le planning actuel")).to_be_visible()
        panel.get_by_role("button", name="Ajuster les actions").click()
        choices = panel.get_by_role("group", name="Actions du plan ajusté")
        for box in choices.get_by_role("checkbox").all():
            if box.is_checked():
                box.uncheck()
        replacement = choices.get_by_role("checkbox", name=re.compile(r"Remplacer l.IDE absente"))
        replacement.check()
        confirm = panel.get_by_role("button", name="Valider l’action", exact=True)
        expect(confirm).to_have_count(0)
        open_section(page, "Unité")
        check_unit_board(page)
        expect(panel.get_by_role("heading", name="Composition à évaluer")).to_be_visible()
        expect(
            panel.get_by_text(re.compile(r"Remplacer l.IDE absente.*Observation courte 6"))
        ).to_be_visible()
        page.reload()
        expect(panel.get_by_role("heading", name="Composition à évaluer")).to_be_visible()
        open_section(page, "Action")
        expect(replacement).to_be_checked()
        expect(choices.locator("input:checked")).to_have_count(1)
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
        action_title = panel.get_by_role("heading", level=2).inner_text()
        open_section(page, "Unité")
        check_unit_board(page)
        expect(panel.get_by_role("heading", name=action_title, exact=True)).to_be_visible()
        open_section(page, "Action")
        expect(replacement).to_be_checked()
        expect(confirm).to_be_enabled()
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=screenshots / "rives-u6-ajustement.png", full_page=True)
        # A second browser tab is reading the very same hospital and episode before validation.
        mirror = page.context.new_page()
        mirror.goto(url.rstrip("/") + "/#/")
        mirror_panel = mirror.get_by_role("region", name="Recommandation de l’unité")
        expect(mirror_panel.get_by_role("link", name="Ouvrir dans Action")).to_be_visible()
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
        assert len([entry for entry in saved["journal"] if entry["event"] == "confirmed"]) == 1
        expect(mirror_panel.get_by_text("Choix enregistré", exact=False)).to_be_visible()
        expect(mirror_panel.get_by_role("heading", name=action_title, exact=True)).to_be_visible()
        mirror.close()
        open_section(page, "Unité")
        check_unit_board(page)
        page.get_by_role("link", name="Journal", exact=True).first.click()
        page.reload()
        journal = page.get_by_role("region", name="Journal des décisions")
        expect(journal.get_by_text("Décision validée", exact=True)).to_be_visible()
        expect(
            journal.get_by_text(re.compile(r"Remplacer l.IDE absente.*Observation courte 6"))
        ).to_be_visible()
        check_width(page)
        assert confirmations == [result.value.url], confirmations
        assert not errors, errors
        print("Rives/u6 : remplacement IDE évalué, validé et relu dans le journal", flush=True)
    finally:
        context.close()


def patient_unit_journey(browser: Browser, url: str, screenshots: Path | None) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 940}, locale="fr-FR")
    errors: list[str] = []
    evaluations: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    noon_confirmations = confirmation_requests(page)

    def count_assessments(request: Request) -> None:
        if request.method == "POST" and urlsplit(request.url).path.endswith("/hybrid/shadow"):
            evaluations.append(request.url)

    page.on("request", count_assessments)
    try:
        page.goto(url.rstrip("/") + "/#/")
        hospital = page.get_by_role("combobox", name="Établissement")
        with page.expect_response(lambda r: r.url.endswith("/hybrid/live")) as observed:
            hospital.select_option("ch-fictif")
        state = observed.value.json()["state"]
        assert state["hospital_id"] == "ch-fictif"
        assert [u["id"] for u in state["units"]] == ["medecine-polyvalente"]
        expect(page.get_by_text("08:30", exact=True).first).to_be_visible()
        release = page.get_by_role("region", name="Libérer", exact=True)
        beds = page.get_by_role("region", name="Lits", exact=True)
        queue = page.get_by_role("region", name="Attribuer", exact=True)
        expect(release.get_by_text("P-0412", exact=True)).to_be_visible()
        expect(beds.get_by_text("L02", exact=True)).to_be_visible()
        expect(queue.get_by_text("U-1041", exact=True)).to_be_visible()
        open_section(page, "Action")
        expect(page).to_have_url(re.compile(r"#/action$"))
        with page.expect_response(lambda r: r.url.endswith("/hybrid/shadow")) as assessment:
            page.get_by_role("button", name="Évaluer maintenant").click()
        submitted = assessment.value.request.post_data_json
        assert submitted["horizon_minutes"] == 480 and submitted["scenarios"] == 32
        measured = assessment.value.json()["assessment"]
        assert measured["snapshot"]["state"] == state
        assert measured["plan"]["selected"] == {
            "kind": "request_transport",
            "bed_id": "L02",
            "patient_id": "P-0412",
        }
        title = "Demander le transport de P-0412"
        plan = page.get_by_role("region", name=title, exact=True)
        expect(plan.get_by_role("heading", name=title)).to_be_visible()
        effect = plan.get_by_label("Effet simulé", exact=True).inner_text()
        open_section(page, "Unité")
        expect(plan.get_by_role("heading", name=title)).to_be_visible()
        expect(plan.get_by_label("Effet simulé", exact=True)).to_have_text(
            effect, use_inner_text=True
        )
        expect(beds.get_by_text("L02", exact=True)).to_be_visible()
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=screenshots / "ch-fictif-unite-patients.png", full_page=True)
        open_section(page, "Action")
        plan.get_by_role("button", name=re.compile(r"^Valider(?:\s+O)?$")).click()
        expect(plan.get_by_text("Validée, à faire", exact=False)).to_be_visible()
        open_section(page, "Journal")
        expect(
            page.get_by_role("heading", name="Journal des décisions", exact=True)
        ).to_be_visible()
        entries = page.get_by_role("link").filter(has_text=title)
        expect(entries.first).to_be_visible()
        links = {link.get_attribute("href") for link in entries.all()}
        assert len(links) == 1 and all(link and "/journal/" in link for link in links)
        entries.first.click()
        expect(page.locator("#jdetail-title")).to_have_text(title)
        open_section(page, "Unité")
        expect(hospital).to_have_value("ch-fictif")
        expect(plan.get_by_text("Validée, à faire", exact=False)).to_be_visible()
        expect(release.get_by_text("P-0412", exact=True)).to_be_visible()
        assert evaluations == [assessment.value.url] and not noon_confirmations
        check_width(page)
        assert not errors, errors
        print("CH fictif : P-0412, L02 et décision conservés entre les onglets", flush=True)
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
        check_width(page)
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
            patient_unit_journey(browser, url, screenshots)
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
                check_width(page)
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
