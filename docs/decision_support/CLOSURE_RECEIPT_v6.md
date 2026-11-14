# Reçu de clôture — défaut V5-R01, état des portes (14 novembre 2026)

**Référence conservée :** `HospitalOS_DS_P0-P4_20261114_v6.zip`, SHA-256
`4fca8aecde4fa35a47bc18696785d28df7465b5191b48e8a2881b0ec1e117f90`, arbre `856a57c`.
**Audit d'entrée :** `HospitalOS_Audit_DS_v6_20261114.zip`, SHA-256 `a3c1bb58…ebd34` (42/42 conformes ;
rapport et prompt identiques aux fichiers reçus).

## Décision

- **V5-R01 : clos** sur le périmètre audité, de façon indépendante (capacité unique par prêteur ×
  compétence × heure ; second prêt refusé dans les deux ordres ; engagements antérieurs conservés).
- Les constats antérieurs (F01–F08, V4-R01/R02/R03, V4-D01) sont clos sur leurs cas.
- Aucune v7 du moteur : aucun nouveau défaut établi.
- **Statut global : `PARTIAL_WITH_CHECKPOINT`.** Statut scientifique inchangé :
  `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

## État exact des portes

| Porte | État | Pour la fermer |
|---|---|---|
| Défauts du moteur F01–F08, V4-*, V5-R01 | **Fermée** (audits indépendants v4, v5, v6) | — |
| Python **3.11.9** exact | **Ouverte** | Interpréteur 3.11.9 (téléchargement non autorisé) ou décision explicite de changer la version de référence, puis rejeu. 3.11.18 : 181 réussis + 1 ignoré (exécutions d'auteur). |
| Rejeu React / navigateur indépendant | **Ouverte** | Environnement indépendant disposant des dépendances du cockpit. Vitest 72/72, e2e 17/17 et 19/19 : exécutions d'auteur seulement. |
| `mypy --strict` | Non exécuté | Limite déclarée, pas une porte acceptée. |
| `test_decision_guard.py` | Exclu | `fit_benchmark` ajuste des modèles : apprentissage non autorisé. |
| P5 / P6 | Fermés, non commencés | Mandat, protocole et budget distincts. |

## Ce qui a été fait pour cette clôture

Vérification d'intégrité du dossier d'audit ; vérification que les 166 enregistrements du final v6
sont un préfixe exact de la lignée de l'audit (chaîne, ancre et empreinte terminale
`9056a4a1…b973` valides) puis adoption : **175 enregistrements, 421,325 s, reliquat 178,675 s**.
Correction documentaire de la mention historique « 163/163 » (générateur de `STATUS.json`, § 6 du
rapport) ; les JUnit et preuves de tests ne sont pas modifiés ; le paquet v6 scellé non plus
(statut corrigé : `evidence/decision_support/STATUS_CLOSURE_v6.json`).
**Aucune exécution** de test, de build ni d'installation dans cette clôture.

Prochaine étape possible, distincte et documentaire : rédiger le protocole P5 (population réservée,
comparateur, métriques, critères d'arrêt, budget) sans générer de corpus ni lancer d'expérience.
