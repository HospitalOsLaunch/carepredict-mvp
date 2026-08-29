# HFWM-R0 — matrice de réutilisation M0

Cette matrice est bornée au premier vertical slice. Elle ne vaut ni validation scientifique, ni autorisation d'utiliser une source externe.

| Composant | Preuve observée | Décision | Action bornée |
|---|---|---|---|
| Registre `HFWM_R0_DATA_RIGHTS.yaml` et fixture `hfwm_r0_internal_synthetic_fixture` | Politique deny-by-default ; usage local train/eval/benchmark autorisé par la mission, publication et poids interdits ; revue IP/juridique encore requise | **REUSE** | Seule source admise dans D0 |
| DREES, Synthea, MIMIC-IV, données site/partenaire | Version, licence, DUA ou autorisation absentes de la baseline | **DEFER** | Ne pas ingérer avant décision documentée |
| Générateur synthétique CarePredict historique | Provenance/licence non établies ; adaptateur et features historiques ne portent pas le contrat HFWM-R0 | **REPLACE** | Employer la fixture interne et le corpus HFWM gelé |
| `CanonicalEvent` et `EventLedger` P-0D | `event_time`, `recorded_at`, `available_at`, `ingested_at`, correction append-only, replay déterministe ; snapshots point-in-time testés | **REUSE** | Construire D0 sur cette API |
| Schéma Timescale bitemporel `05_p0d_bitemporal.sql` | Contrat SQL présent, mais aucune exécution Timescale fraîche dans M0 | **REPAIR** | Ajouter plus tard une preuve d'intégration ; non requis pour le slice mémoire |
| Générateur `hfwm.corpus`, HDC, HDB et HTL | Corpus déterministe reproduit : 25 680 événements, 60 épisodes, 240 fenêtres, 60 corrections, 60 silences, split 42/9/9, hash gelé | **REUSE** | Source et projections de D0 |
| Splits, temporalité et décontamination | Split avant fenêtrage, familles de corrections indivisibles, contrôles de fuite/replay couverts par les tests ciblés | **REUSE** | Exécuter ces contrôles à chaque build D0 |
| Préenregistrement HFWM-R0 | 11 contrats valides ; manifest SHA-256 stable ; main runs autorisés par le validateur | **REUSE** | Lier le manifest D0 aux identifiants gelés |
| Baseline historique HGBR/CQR (`carepredict_quantile.py`, `carepredict_cqr.py`) | Commande connue, mais cible `load_proxy`, feature `surge_flag` dérivée de la charge, split/calibration incompatibles avec le cohort/horizons HFWM | **REPAIR** | Conserver comme fallback ; retirer la fuite et adapter le contrat avant comparaison |
| Artefacts de baseline historiques | Métriques non rattachées au corpus, aux cinq tâches et aux horizons R0 | **DEFER** | Ne pas les présenter comme résultat R0 |
| Modèles HFWM mécaniste/local/shared committés | Implémentations présentes, aucun entraînement autorisé dans M0 | **DEFER** | Évaluer seulement après acceptation de D0 |
| JEPA/RSSM, TFT et Moirai historiques | Contrats de données/actions différents ou preuves synthétiques anciennes | **DEFER** | Aucun portage dans le premier slice |
| `src/hfwm/baselines`, `src/hfwm/bakeoff` et tests associés non suivis | Travail hérité/interrompu, hors HEAD et non gelé | **DEFER** | Audit séparé après D0 ; aucune preuve revendiquée ici |
| P-0₀ V8 | Candidat final présent, contrat valide et worktrees propres ; revue hostile avec blockers logiciels | **DEFER** | Figer sans V9 ; usage possible comme harness local, pas comme chaîne de preuve forte |
| Tests P-0D/corpus/évaluation | 38 tests ciblés verts ; Ruff et Mypy strict verts sur 23 fichiers | **REUSE** | Gate minimal de D0 |

## Premier vertical slice : `HFWM-R0-D0-SYNTHETIC-PIT`

**Entrée.** Uniquement `hfwm_r0_internal_synthetic_fixture`, configuration gelée et aucun téléchargement.

**Chaîne.** `CanonicalEvent` → `EventLedger` append-only → snapshot `as_of` → épisode HDC → affectation train/validation/test avant fenêtrage → fenêtres pour `occupancy`, `inflow`, `discharges`, `staffing`, `pressure` aux horizons 6 h, 24 h et 72 h. L'horizon 168 h reste conditionnel et non exécuté. Les actions restent `ACTION_CONDITIONING_NOT_IDENTIFIABLE`.

**Sortie.** Un manifest JSON adressé par contenu et un rapport qualité JSON, sans données brutes, poids ni métriques de modèle.

**Critères d'acceptation.** Hash et cardinalités déterministes ; aucun événement avec `available_at > as_of` ; correction invisible avant sa disponibilité ; aucun épisode, groupe de correction ou doublon sémantique entre splits ; replay et manifest identiques sur deux constructions ; droits et contrats gelés référencés.

**Commandes de référence.** Installation : `python -m pip install ".[dev]"`. Gate ciblé : `PYTHONPATH=src pytest -p no:cacheprovider tests/p0d tests/hfwm/corpus tests/hfwm/evaluation tests/hfwm/data_slice -q`, puis Ruff et Mypy strict sur les mêmes modules. La baseline historique reste reproductible par `PYTHONPATH=. python carepredict_cqr.py --synthetic`, mais cette commande entraîne un modèle et n'a donc pas été exécutée dans M0.

**Prochaine modification précise.** Ajouter `src/hfwm/data_slice/__init__.py`, `src/hfwm/data_slice/builder.py`, `scripts/hfwm/build_data_slice.py` et `tests/hfwm/data_slice/test_builder.py`. Le builder doit seulement composer les primitives existantes et écrire, sur demande explicite, `artifacts/hfwm-r0/data-slice/manifest.json` et `quality.json`.
