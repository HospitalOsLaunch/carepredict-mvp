"""
Tests de reproductibilité, d'étanchéité temporelle et de causalité, sur un monde court (v0.3).

Usage : python tests.py            (environ 1 minute)
"""
import copy
import datetime as dt
import gzip
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from . import hospsim as hs
from . import observation as ob
from . import parcours as pc
from . import notes as nt
from . import extraction as ex
from . import run

UNITES = run.ECHELLES["pole"]
ICI = Path(__file__).resolve().parent


def monde(seed=11, jours=26, warmup=12):
    debut = dt.date(2025, 1, 1) - dt.timedelta(warmup)
    exo = hs.Exo(UNITES, debut, debut + dt.timedelta(jours), seed)
    h0, h1 = warmup * 24, (jours - 4) * 24
    sim = hs.Sim(exo, "pole", h0, h1)
    j = run.Journal(sim)
    snaps = []
    viol = Counter()
    cap = {}
    st, _ = run.simuler(sim, j, lambda h, s: snaps.append((h, s.clone())) if h0 <= h < h1 else None, viol=viol,
                        capture=cap)
    sim.capture = cap.get("etat")
    return sim, j, st, snaps, viol


def livraisons(sim, j):
    base = np.datetime64(sim.x.debut.isoformat())
    return ob.observer(run.evenements(j, UNITES, sim.h1_rec), sim.x, sim.x.seed, base)[0]


def verite(sim, j):
    et = pd.DataFrame(j.etats)
    et = et[(et.h >= sim.h0_rec) & (et.h < sim.h1_rec)].copy()
    et["entite"] = np.array(UNITES)[et.u.values]
    return {(r["entite"], r["h"]): r for r in et.to_dict("records")}


def vues(sim, j, livr):
    mi = sim.h0_rec + (sim.h1_rec - sim.h0_rec) // 2
    return ob.vues_apprentissage(livr, verite(sim, j), UNITES, sim.h0_rec, sim.h1_rec, (mi, mi + 48), embargo=24)


class Moteur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = monde()
        cls.b = monde()
        cls.livr = livraisons(cls.a[0], cls.a[1])

    def test_meme_graine_meme_monde(self):
        self.assertEqual(self.a[1].etats, self.b[1].etats)
        self.assertEqual(self.a[1].events, self.b[1].events)

    def test_graine_differente_monde_different(self):
        c = monde(seed=12)
        self.assertNotEqual(self.a[1].etats, c[1].etats)

    def test_invariants_lits_sans_violation(self):
        viol = self.a[4]
        self.assertGreater(viol["heures_controlees"], 0)
        self.assertEqual({k: v for k, v in viol.items() if k != "heures_controlees" and v}, {})

    def test_meme_graine_memes_livraisons(self):
        self.assertEqual(self.livr, livraisons(self.b[0], self.b[1]))

    def test_observation_ne_change_pas_la_physique(self):
        ancien = dict(ob.OBS)
        try:
            ob.OBS["p_absence"] = 0.5
            autre = livraisons(self.a[0], self.a[1])
        finally:
            ob.OBS.clear()
            ob.OBS.update(ancien)
        self.assertNotEqual(len(autre), len(self.livr))
        self.assertEqual(self.a[1].etats, monde()[1].etats)

    def test_livraisons_futures_sans_effet_sur_le_passe(self):
        sim, j = self.a[0], self.a[1]
        coupure = sim.h0_rec + 48
        plein, _ = vues(sim, j, self.livr)
        prefixe, _ = vues(sim, j, [o for o in self.livr if o["t_disponible"] <= coupure])
        self.assertEqual([r for r in plein if r["h"] <= coupure], [r for r in prefixe if r["h"] <= coupure])

    def test_doublons_sans_effet_sur_les_variables(self):
        sim, j = self.a[0], self.a[1]
        plein, _ = vues(sim, j, self.livr)
        double = sorted(self.livr + copy.deepcopy(self.livr), key=lambda o: (o["t_disponible"], o["event_id"], o["event_version"]))
        self.assertEqual(plein, vues(sim, j, double)[0])

    def test_rejeu_depuis_capture_reproduit_le_factuel(self):
        sim, j, _, snaps, _ = self.a
        self.assertGreater(len(snaps), 0)
        self.assertEqual(run.test_rejeu(sim, snaps, j.etats, n=3), 0)

    def test_levier_inapplicable_sans_effet(self):
        sim, _, _, snaps, _ = self.a
        h0, st0 = snaps[0]
        ref = run.metriques(sim, st0.clone(), h0, 48)[0]
        st = st0.clone()
        st.surge_until[0] = h0 + 500           # lits supplémentaires déjà actifs
        st2 = st.clone()
        self.assertEqual(sim.appliquer(st, 0, 1, h0), 0)
        a, b = run.metriques(sim, st, h0, 48)[0], run.metriques(sim, st2, h0, 48)[0]
        for k in a[48]:
            np.testing.assert_array_equal(a[48][k], b[48][k])
        self.assertTrue(any((ref[48][k] != a[48][k]).any() for k in ref[48]))

    def test_contrefactuel_deterministe(self):
        sim, _, _, snaps, _ = self.a
        h0, st0 = snaps[-1]
        st1, st2 = st0.clone(), st0.clone()
        sim.appliquer(st1, 1, 0, h0)
        sim.appliquer(st2, 1, 0, h0)
        a, b = run.metriques(sim, st1, h0, 48)[0], run.metriques(sim, st2, h0, 48)[0]
        for k in a[48]:
            np.testing.assert_array_equal(a[48][k], b[48][k])

    def test_actions_factuelles_imposees_reproduisent_le_factuel(self):
        sim, _, _, snaps, _ = self.a
        h0, st0 = snaps[3]
        fact, dec = run.metriques(sim, st0.clone(), h0, 48, politique=True)
        for u in range(sim.U):
            imp, _ = run.metriques(sim, st0.clone(), h0, 48, politique=True, force=(h0, u, None, list(dec[u][2])))
            for k in fact[48]:
                np.testing.assert_array_equal(fact[48][k], imp[48][k])

    def test_recommandation_non_vue_sans_effet(self):
        sim, _, _, snaps, _ = self.a
        x = sim.x
        for h0, st0 in snaps:
            d = h0 // 24
            u = next((u for u in range(sim.U) if x.u_expo[u, d] >= hs.P["p_exposition"]), None)
            if u is None:
                continue
            ref, _ = run.metriques(sim, st0.clone(), h0, 48, politique=True, force=(h0, u, [0, 0, 0, 0], None))
            for k in range(4):
                r = [int(j == k) for j in range(4)]
                res, dec = run.metriques(sim, st0.clone(), h0, 48, politique=True, force=(h0, u, r, None))
                self.assertEqual(dec[u][1], 0)
                for m in ref[48]:
                    np.testing.assert_array_equal(ref[48][m], res[48][m])
            return
        self.skipTest("aucun jour sans exposition dans ce monde court")

    def test_informations_du_staff_sans_effet_sur_la_physique(self):
        ancien = dict(hs.INFO)
        try:
            hs.INFO.update(p_dsp_jamais=0.9, dsp_informativite=3.0, p_destination_juste=0.1)
            autre = monde()
        finally:
            hs.INFO.clear()
            hs.INFO.update(ancien)
        self.assertEqual(self.a[1].etats, autre[1].etats)
        self.assertNotEqual([e for e in self.a[1].events if e["type"] == "DATE_SORTIE_PREVISIONNELLE"],
                            [e for e in autre[1].events if e["type"] == "DATE_SORTIE_PREVISIONNELLE"])

    def _sejours(self, livr):
        sim = self.a[0]
        mi = sim.h0_rec + (sim.h1_rec - sim.h0_rec) // 2
        var = []
        for v, _ in pc.iter_vues_sejours(livr, {}, sim.x.debut, sim.h0_rec, sim.h1_rec, (mi, mi + 48), embargo=24):
            var.extend(v)
        return var

    def test_sejours_livraisons_futures_sans_effet_sur_le_passe(self):
        coupure = self.a[0].h0_rec + 72
        plein = self._sejours(self.livr)
        prefixe = self._sejours([o for o in self.livr if o["t_disponible"] <= coupure])
        self.assertEqual([r for r in plein if r[1] <= coupure], [r for r in prefixe if r[1] <= coupure])
        self.assertGreater(len([r for r in plein if r[1] <= coupure]), 0)

    def test_sejours_doublons_sans_effet(self):
        double = sorted(self.livr + copy.deepcopy(self.livr), key=lambda o: (o["t_disponible"], o["event_id"], o["event_version"]))
        self.assertEqual(self._sejours(self.livr), self._sejours(double))

    def test_censure_sans_information_posterieure(self):
        sim, j, st = self.a[0], self.a[1], self.a[2]
        cap = sim.capture
        self.assertIsNotNone(cap)
        for p in cap.patients.values():
            self.assertLess(p.admit_h, sim.h1_rec)
        tard = [p for p in st.patients.values() if p.admit_h >= sim.h1_rec]
        self.assertTrue(all(p.pid not in cap.patients for p in tard))

    def test_notes_reproductibles(self):
        sim, j = self.a[0], self.a[1]
        a = nt.generer(sim, j, sim.h0_rec, sim.h1_rec, sim.h1_rec - 48, 11)
        b = nt.generer(self.b[0], self.b[1], sim.h0_rec, sim.h1_rec, sim.h1_rec - 48, 11)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1], b[1])

    def test_notes_ne_dependent_pas_du_futur(self):
        """Couper le journal à T ne change aucune note disponible avant T."""
        sim, j = self.a[0], self.a[1]
        T = sim.h0_rec + 120
        plein = nt.generer(sim, j, sim.h0_rec, sim.h1_rec, sim.h1_rec - 48, 11)[0]

        class J:
            events = [e for e in j.events if e["h"] < T]
        coupe = nt.generer(sim, J, sim.h0_rec, T, sim.h1_rec - 48, 11)[0]
        self.assertEqual([n for n in plein if n["t_disponible"] < T], coupe)
        self.assertGreater(len(coupe), 50)

    def test_extraction_lit_seulement_le_texte(self):
        sim, j = self.a[0], self.a[1]
        ns = nt.generer(sim, j, sim.h0_rec, sim.h1_rec, sim.h1_rec - 48, 11)[0][:200]
        for n in ns:
            self.assertEqual(ex.extraire(n["texte"]), ex.extraire(str(n["texte"])))
        self.assertTrue(any(ex.extraire(n["texte"]) for n in ns))

    def test_clone_independant(self):
        sim, _, _, snaps, _ = self.a
        h0, st0 = snaps[0]
        avant = sorted((p.pid, p.dis_h) for p in st0.patients.values())
        run.metriques(sim, st0.clone(), h0, 24)
        self.assertEqual(avant, sorted((p.pid, p.dis_h) for p in st0.patients.values()))


class Extracteur(unittest.TestCase):
    """Négations, apostrophes, abréviations : cas écrits à la main, valeur et statut attendus."""
    CAS = [("Pas d'oxygénothérapie.", "oxygene", (False, "negation")),
           ("Pas d’oxygénothérapie.", "oxygene", (False, "negation")),
           ("Pas d'O2.", "oxygene", (False, "negation")),
           ("Sans oxygène.", "oxygene", (False, "negation")),
           ("SpO2 96 % en AA.", "oxygene", (False, "documente")),
           ("SpO2 85 % en AA, mise sous O2 2 L/min.", "oxygene", (True, "documente")),
           ("Ss O2 2L.", "oxygene", (True, "documente")),
           ("Pas d'aide à dom.", "aides_existantes", (False, "negation")),
           ("Pas d’aide à domicile.", "aides_existantes", (False, "negation")),
           ("Aucune aide en place.", "aides_existantes", (False, "negation")),
           ("Absence de trouble mnésique.", "troubles_cognitifs", (False, "negation")),
           ("Pas de troubles cognitifs connus.", "troubles_cognitifs", (False, "negation")),
           ("Possible syndrome démentiel débutant ?", "troubles_cognitifs", (True, "hypothese")),
           ("Vit seule à dom.", "vit_seul", (True, "documente")),
           ("Vit avec son époux.", "vit_seul", (False, "documente")),
           ("Pas de perte d'autonomie récente.", "perte_autonomie_recente", (False, "negation")),
           ("Sa fille assure l'essentiel de l'aide.", "aidant_present", (True, "documente")),
           ("Pas d'entourage proche.", "aidant_present", (False, "negation")),
           ("Logement individuel, personne ne vit avec lui.", "vit_seul", (True, "negation")),
           ("Vit avec son époux en appartement au 2e étage sans ascenseur.", "vit_seul", (False, "documente")),
           ("Ne fait plus ses courses depuis le mois dernier.", "perte_autonomie_recente", (True, "documente"))]

    def test_motif_le_plus_specifique(self):
        self.assertEqual(ex.extraire("Conclusion : Pneumopathie d'inhalation base droite.")["motif"]["valeur"], "inhalation")

    def test_cas(self):
        for texte, var, attendu in self.CAS:
            e = ex.extraire(texte).get(var)
            self.assertEqual((e["valeur"], e["statut"]) if e else None, attendu, texte)

    def test_portage_bacterien_n_est_pas_une_aide(self):
        self.assertNotIn("aides_existantes", ex.extraire("Isolement contact : portage d'entérobactérie BLSE."))

    def test_etat_documentaire_sans_effacement(self):
        lignes = [dict(sejour_id="S1", note_id="N1-1", version=1, type_note="OBS_URGENCES", h_disponible=1.5,
                       h_utilisable=2, split="train", **{v: None for v in ex.VARIABLES},
                       **{v + "_statut": None for v in ex.VARIABLES}),
                  dict(sejour_id="S1", note_id="N1-2", version=1, type_note="OBS_ENTREE", h_disponible=5.2,
                       h_utilisable=6, split="train", **{v: None for v in ex.VARIABLES},
                       **{v + "_statut": None for v in ex.VARIABLES})]
        lignes[0].update(autonomie=3, autonomie_statut="documente", vit_seul=True, vit_seul_statut="documente")
        lignes[1].update(vit_seul=False, vit_seul_statut="documente")
        et = ex.etat_documentaire(lignes)
        self.assertEqual(et[1]["autonomie"], 3)
        self.assertEqual(et[1]["autonomie_source"], "OBS_URGENCES")
        self.assertEqual(et[1]["vit_seul"], False)
        self.assertTrue(et[1]["vit_seul_conflit"])

    @staticmethod
    def _historique_fusion():
        textes = ["Vit avec son époux.", "Veuve, vit seule.",
                  "Vit avec son époux.\n\nComplément : Fille très présente, passe tous les jours.",
                  "Vit avec son époux.\n\nComplément : Fille très présente, passe tous les jours.\n\nRelecture : RAS."]
        notes, lignes = [], []
        for h, nid, version, typ, texte in zip([1.5, 5.2, 9.3, 11.2], ["N1-2", "N1-3", "N1-2", "N1-2"],
                                             [1, 1, 2, 3], ["OBS_ENTREE", "RECUEIL_IDE", "OBS_ENTREE", "OBS_ENTREE"], textes):
            notes.append(dict(sejour_id="S1", note_id=nid, version=version, type_note=typ,
                              h_disponible=h, ts_modification="2025-01-01T00:00:00+01:00", texte=texte))
            ext = ex.extraire(texte)
            lignes.append(dict(sejour_id="S1", note_id=nid, version=version, type_note=typ, h_disponible=h,
                               h_utilisable=int(np.ceil(h)), split="train",
                               **{v: ext.get(v, {}).get("valeur") for v in ex.VARIABLES},
                               **{v + "_statut": ext.get(v, {}).get("statut") for v in ex.VARIABLES}))
        return lignes, notes

    def test_complement_et_ras_ne_rafraichissent_pas_les_faits_copies(self):
        lignes, notes = self._historique_fusion()
        et = ex.etat_documentaire(lignes, notes)
        for r in et[1:]:
            self.assertIs(r["vit_seul"], True)
            self.assertEqual(r["vit_seul_h_source"], 5.2)
            self.assertEqual(r["vit_seul_note_id_source"], "N1-3")
            self.assertEqual(r["vit_seul_version_source"], 1)
            self.assertEqual(r["vit_seul_extrait_source"], "Veuve, vit seule.")
            self.assertTrue(r["vit_seul_conflit"])
        self.assertEqual(et[2]["aidant_present_h_source"], 9.3)
        self.assertEqual(et[3]["aidant_present_h_source"], 9.3)

    def test_reaffirmation_explicite_identique_actualise_la_source(self):
        lignes, notes = self._historique_fusion()
        # La valeur est identique à celle de la version médicale initiale, mais la phrase
        # est réellement répétée dans le nouveau complément : elle peut reprendre priorité.
        notes[-1]["texte"] += "\nVit avec son époux."
        et = ex.etat_documentaire(lignes, notes)
        self.assertIs(et[-1]["vit_seul"], False)
        self.assertEqual(et[-1]["vit_seul_h_source"], 11.2)
        self.assertEqual(et[-1]["vit_seul_note_id_source"], "N1-2")
        self.assertEqual(et[-1]["vit_seul_version_source"], 3)

    def test_correction_explicite_resout_un_conflit(self):
        lignes, notes = self._historique_fusion()
        notes[-1]["texte"] += "\nRectification : Vit seule à domicile."
        et = ex.etat_documentaire(lignes, notes)
        self.assertIs(et[-1]["vit_seul"], True)
        self.assertEqual(et[-1]["vit_seul_h_source"], 11.2)
        self.assertFalse(et[-1]["vit_seul_conflit"])

    def test_fusion_avec_versions_futures_preserve_le_prefixe(self):
        lignes, notes = self._historique_fusion()
        self.assertEqual(ex.etat_documentaire(lignes, notes)[:2], ex.etat_documentaire(lignes[:2], notes))

    def test_fusion_refuse_historique_incomplet_ou_reecrit(self):
        lignes, notes = self._historique_fusion()
        with self.assertRaises(ValueError):
            ex.etat_documentaire(lignes[2:], notes)
        with self.assertRaises(ValueError):
            ex.etat_documentaire(lignes)
        notes[2]["texte"] = "Texte entièrement remplacé."
        with self.assertRaises(ValueError):
            ex.etat_documentaire(lignes, notes)


class Controles(unittest.TestCase):
    """Les contrôles doivent échouer quand on corrompt les données (tests de mutation)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.src = cls.tmp / "ref"
        units = run.ECHELLES["pole"]
        exo_args = dict(echelles={u: 1.0 for u in units})
        debut = dt.date(2025, 1, 1) - dt.timedelta(10)
        exo = hs.Exo(units, debut, debut + dt.timedelta(50), 5)
        sim = hs.Sim(exo, "pole", 240, 240 + 24 * 30)
        j, snaps, viol, cap = run.Journal(sim), [], Counter(), {}
        st, _ = run.simuler(sim, j, lambda h, s: snaps.append((h, s.clone())) if 240 <= h < sim.h1_rec else None,
                            viol=viol, capture=cap)
        # monde réduit écrit avec la même fonction que la génération complète ; contrefactuels autour des frontières
        mi = sim.h0_rec + 24 * 12
        choix = [0, 4, 5, 13, 20, 21]
        cf = []
        run._SIM, run._SNAPS = sim, [snaps[i] for i in choix]
        for i in range(len(choix)):
            cf.extend(run._worker(i))
        run.ecrire(sim, j, st, cap["etat"], cf, cls.src, units, "CSG", 5, exo_args["echelles"], 0, 0.0, viol,
                   frontieres=(mi, mi + 24 * 9))
        cls.ok = subprocess.run([sys.executable, "-m", "hospitalos.synthetic.v041.controles", str(cls.src)], capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def _mutant(self, nom, fichier, f=None):
        """fichier, f : une corruption ; ou fichier = liste de (fichier, f) appliquées ensemble."""
        d = self.tmp / nom
        shutil.copytree(self.src, d)
        for fic, fn in (fichier if isinstance(fichier, list) else [(fichier, f)]):
            p = d / fic
            if fic.endswith(".csv.gz"):
                df = pd.read_csv(p, low_memory=False)
                fn(df)
                df.to_csv(p, index=False, compression="gzip")
            else:
                rows = [json.loads(l) for l in gzip.open(p, "rt")]
                fn(rows)
                with gzip.open(p, "wt") as z:
                    for r in rows:
                        z.write(json.dumps(r, ensure_ascii=False) + "\n")
        r = subprocess.run([sys.executable, "-m", "hospitalos.synthetic.v041.controles", str(d)], capture_output=True)
        return json.loads((d / "rapport_controles.json").read_text())["controles"], r.returncode

    def test_reference_passe(self):
        self.assertEqual(self.ok.returncode, 0, self.ok.stdout.decode()[-2000:])

    def test_stock_flux_detecte(self):
        def f(df):
            i = df.index[(df.niveau == "unite") & (df.h == df.h.iloc[len(df) // 2])][0]
            df.loc[i, "lits_occupes"] += 1
        c, rc = self._mutant("m1", "verite/etats_horaires.csv.gz", f)
        self.assertNotEqual(rc, 0)
        self.assertFalse(c["conservation_stock_flux_horaire"] and c["partition_des_lits"])

    def test_fuite_temporelle_detectee(self):
        def f(df):
            df.loc[df.entree_disponible.notna(), "entree_disponible"] += 5
        c, rc = self._mutant("m2", "apprentissage/variables_asof.csv.gz", f)
        self.assertFalse(c["variables_disponibles_avant_l_instant"])

    def test_cible_corrompue_detectee(self):
        def f(df):
            df.loc[df.index[10], "cible_lits_occupes"] += 3
        c, _ = self._mutant("m3", "apprentissage/cibles.csv.gz", f)
        self.assertFalse(c["cibles_conformes_verite_et_horizon"])

    def test_doublon_divergent_detecte(self):
        def f(rows):
            r = dict(rows[100])
            r["empreinte"] = "x" * 64
            r["delivery_id"] = "L99999999"
            rows.append(r)
        c, _ = self._mutant("m4", "observe/livraisons.jsonl.gz", f)
        self.assertFalse(c["doublons_contenu_identique"])

    def test_propension_incoherente_detectee(self):
        def f(df):
            i = df.index[df.q_reco_lits_supplementaires == 0][0]
            df.loc[i, "r_lits_supplementaires"] = 1
        c, _ = self._mutant("m5", "causal/decisions.csv.gz", f)
        self.assertFalse(c["chaine_recommandation_execution_coherente"])

    def test_contrefactuel_altere_detecte(self):
        def f(df):
            i = df.index[(df.famille.str.startswith("A")) & (df.scenario != "aucun") & (df.n_concernes == 0)][0]
            df.loc[i, "attente_urg_patient_h_72h"] += 1
        c, _ = self._mutant("m6", "causal/contrefactuels.csv.gz", f)
        self.assertFalse(c["nombres_aleatoires_communs_scenarios_sans_effet"])

    def test_sejour_censure_avec_date_future_detecte(self):
        def f(df):
            i = df.index[df.issue == "censure"][0]
            df.loc[i, "ts_sortant_medical"] = "2026-01-03T10:00:00+01:00"
        c, _ = self._mutant("m7", "verite/sejours.csv.gz", f)
        self.assertFalse(c["sejours_figes_au_31_12_sans_date_posterieure"])

    def test_contrefactuel_franchissant_une_frontiere_detecte(self):
        def f(df):
            i = df.index[df.split == "embargo_ou_censure"][0]
            df.loc[i, "split"] = "train"
        c, _ = self._mutant("m8", "causal/contrefactuels.csv.gz", f)
        self.assertFalse(c["decoupage_contrefactuels_sans_franchissement"])

    def test_execution_sans_validation_detectee(self):
        def f(df):
            i = df.index[df.a_renfort_soignant == 0][0]
            df.loc[i, "x_renfort_soignant"] = 1
        c, _ = self._mutant("m9", "causal/decisions.csv.gz", f)
        self.assertFalse(c["chaine_recommandation_execution_coherente"])

    def test_factuel_altere_detecte(self):
        def f(df):
            i = df.index[df.scenario == "factuel"][0]
            df.loc[i, "attente_urg_patient_h_72h"] += 2
        c, _ = self._mutant("m10", "causal/contrefactuels.csv.gz", f)
        self.assertFalse(c["factuel_egal_action_imposee_identique"] and c["factuel_egal_verite"])

    def test_variable_privilegiee_dans_les_sejours_detectee(self):
        def f(df):
            df["jours_avant_sortie_reelle"] = 1
        c, _ = self._mutant("m11", "apprentissage/sejours_asof.csv.gz", f)
        self.assertFalse(c["sejours_colonnes_liste_fermee"])

    def test_date_previsionnelle_remplacee_par_la_vraie_detectee(self):
        sej = pd.read_csv(self.src / "verite/sejours.csv.gz")
        cfg = json.loads((self.src / "config/parametres.json").read_text())
        deb = pd.Timestamp(cfg["debut_simulation"])
        sortie = dict(zip(sej.sejour_id, (pd.to_datetime(sej.ts_sortie.str[:19]) - deb) / pd.Timedelta(hours=1)))

        def f(df):
            vrai = df.sejour_id.map(sortie) // 24 - df.h // 24
            m = df.dsp_event_id.notna() & vrai.notna()
            df.loc[m, "dsp_jours_restants"] = vrai[m]
        c, _ = self._mutant("m12", "apprentissage/sejours_asof.csv.gz", f)
        self.assertFalse(c["sejours_lignage_date_previsionnelle"])

    def test_note_avec_sortie_future_detectee(self):
        def f(rows):
            rows[5]["texte"] += "\nSortie prévue le 28/12/2025."
        c, _ = self._mutant("m14", "observe/notes.jsonl.gz", f)
        self.assertFalse(c["notes_sans_date_posterieure_a_leur_redaction"])
        self.assertFalse(c["notes_sans_mention_de_sortie_future"])

    def test_note_reecrite_detectee(self):
        def f(rows):
            i = next(k for k, r in enumerate(rows) if r["version"] == 2)
            rows[i]["texte"] = "X" + rows[i]["texte"]
        c, _ = self._mutant("m15", "observe/notes.jsonl.gz", f)
        self.assertFalse(c["notes_horloges_et_versions_en_ajout_seul"])

    def test_note_disponible_avant_redaction_detectee(self):
        def f(rows):
            rows[3]["ts_disponible"] = rows[3]["ts_creation"][:11] + "00:00:00+01:00"
        c, _ = self._mutant("m16", "observe/notes.jsonl.gz", f)
        self.assertFalse(c["notes_horloges_et_versions_en_ajout_seul"])

    def test_annotation_interdite_detectee(self):
        def f(rows):
            r = next(r for r in rows if r["faits"])
            r["faits"].append(dict(r["faits"][0], variable="destination_finale"))
        c, _ = self._mutant("m17", "verite/notes_annotations.jsonl.gz", f)
        self.assertFalse(c["notes_annotations_conformes_au_texte"])

    def test_annotation_manquante_detectee(self):
        def f(rows):
            for r in rows:
                avant = len(r["faits"])
                r["faits"] = [x for x in r["faits"] if x["variable"] != "oxygene"]
                if len(r["faits"]) < avant:
                    return
        c, _ = self._mutant("m18", "verite/notes_annotations.jsonl.gz", f)
        self.assertFalse(c["notes_annotations_completes_sur_marqueurs"])

    def test_erreur_volontaire_non_etiquetee_detectee(self):
        connus = set(pd.read_csv(self.src / "verite/sejours_cliniques.csv.gz").sejour_id)

        def f(rows):
            for r in rows:
                if r["sejour_id"] not in connus:
                    continue
                for x in r["faits"]:
                    if x["correct"] in ("perime", "faux"):
                        x["correct"] = "vrai"
                        return
            raise AssertionError("aucune erreur volontaire dans le monde de test")
        c, _ = self._mutant("m19", "verite/notes_annotations.jsonl.gz", f)
        self.assertFalse(c["notes_faits_conformes_a_la_verite"])

    def test_contradiction_d_assemblage_detectee(self):
        cible = {}

        def f_notes(rows):
            for r in rows:
                if r["type_note"] == "RECUEIL_IDE" and re.search(r"Vit seule? ", r["texte"]):
                    cible.update(note_id=r["note_id"], version=r["version"], debut=len(r["texte"]) + 1)
                    r["texte"] += " Époux aidant principal."
                    return
            raise AssertionError("aucune note IDE avec « vit seul »")

        def f_ann(rows):
            for r in rows:
                if r["note_id"] == cible["note_id"] and r["version"] == cible["version"]:
                    x = "Époux aidant principal."
                    r["faits"].append(dict(variable="aidant_present", valeur=True, statut="documente", correct="vrai",
                                           extrait=x, debut=cible["debut"], fin=cible["debut"] + len(x)))
        c, _ = self._mutant("m20", [("observe/notes.jsonl.gz", f_notes), ("verite/notes_annotations.jsonl.gz", f_ann)])
        self.assertFalse(c["notes_sans_contradiction_hors_erreurs_volontaires"])

    def test_effacement_dans_l_etat_documentaire_detecte(self):
        def f(df):
            for sid, g in df.groupby("sejour_id"):
                g = g[g.vit_seul.notna()]
                if len(g) >= 2:
                    df.loc[g.index[-1], "vit_seul"] = None
                    return
        c, _ = self._mutant("m21", "apprentissage/etat_notes_asof.csv.gz", f)
        self.assertFalse(c["etat_notes_sans_effacement_ni_futur"])

    def test_renfort_pourvu_absent_detecte(self):
        def f(df):
            i = df.index[df.scenario == "renfort_soignant_pourvu"][0]
            df.loc[i, "n_concernes"] = 0
        c, _ = self._mutant("m22", "causal/contrefactuels.csv.gz", f)
        self.assertFalse(c["renfort_pourvu_toujours_present"])

    def test_fait_copie_rafraichi_detecte(self):
        def f(df):
            i = df.index[df.vit_seul.notna() & (df.vit_seul_h_source < df.h_disponible - 1e-6)][0]
            df.loc[i, "vit_seul_h_source"] = df.loc[i, "h_disponible"]
        c, _ = self._mutant("m23", "apprentissage/etat_notes_asof.csv.gz", f)
        self.assertTrue(c["etat_notes_sans_effacement_ni_futur"])
        self.assertFalse(c["etat_notes_copies_sans_rafraichissement"])

    def test_provenance_de_fait_inventee_detectee(self):
        def f(df):
            i = df.index[df.vit_seul.notna()][0]
            df.loc[i, "vit_seul_note_id_source"] = "NOTE_INEXISTANTE"
        c, _ = self._mutant("m24", "apprentissage/etat_notes_asof.csv.gz", f)
        self.assertFalse(c["etat_notes_provenance_verifiable"])

    def test_information_sejour_future_detectee(self):
        def f(df):
            df.loc[df.index[len(df) // 2], "derniere_disponibilite"] += 3
        c, _ = self._mutant("m13", "apprentissage/sejours_asof.csv.gz", f)
        self.assertFalse(c["sejours_informations_disponibles_avant_l_instant"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
