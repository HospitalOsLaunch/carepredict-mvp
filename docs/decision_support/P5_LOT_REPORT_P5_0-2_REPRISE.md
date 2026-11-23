# P5 — Reprise ciblée de P5.0–P5.2 après revue statique (14 novembre 2026)

Entrées : paquet `HospitalOS_P5_Lots_P5.0-2_20261114.zip` (`cce77c03…bcc1`). Revue
`HospitalOS_Revue_P5_Lots_0_2_20261114.zip` (`02fcb521…1acc`, 9/9 empreintes conformes). Prompt
et rapport identiques aux pièces jointes. Le prompt de reprise ne crée **aucune** autorisation :
ce travail reste dans D11-i (mise en œuvre et pilote, lots P5.0–P5.2, sous compteur).

**Non fait, faute d'accord :**
- installation de scikit-learn (D4) ;
- ajustements de chronométrage ;
- nouveau pilote sur une partition engagée ;
- toute génération ou lecture réservée ;
- push, merge, rebase.

Les valeurs `U_dev_only` n'ont pas été analysées.

## 1. Registre (repris sans remise à zéro)

État reçu : 11 enregistrements, 8,383 s, terminal `d2a5cf00…be1f6`, identique à l'état local,
historique prolongé. État final : **17 enregistrements, 13,769 s / 1200 s**, terminal
`7582b1a9…870b`.

| Lot | Plafond | Utilisé |
|---|---:|---:|
| P5.0 | 30 s | 2,682 s (+0,215 : engagement E1) |
| P5.1 | 130 s | 8,563 s (+5,171 : lint, 2 passages de tests, refus volontaire à 0 s) |
| P5.2 | 40 s | 2,524 s (inchangé, reliquat 37,476 s) |

P0–P4 : inchangé (175 enregistrements, 421,325 s).

## 2. Corrections P5 (code séparé, moteur v6 intact)

| Constat | Correction | Fichier |
|---|---|---|
| P5L-02 : gel enregistré mais pas imposé | Avant tout lancement, le compteur refuse : un lot non autorisé ; un programme qui n'est ni l'interpréteur exact de l'environnement approuvé ni un outil statique autorisé ; un gel hors de la liste approuvée (gel D3, plus un futur gel post-installation inscrit par une note `environment_approved`). Chaque refus est consigné, à 0 s. | `scripts/p5_budget_run.py` |
| P5L-02/03 : engagement non revérifié à la reprise | `integrity.verify(effective_commitment())` : sources, graines scellées et moteur v6 contre le dernier engagement du registre. Le pilote refuse en cas d'écart. `p5_pilot.py`, `pilot.py` et `integrity.py` sont désormais engagés. | `src/hospitalos/p5/integrity.py`, `scripts/p5_commit.py` |
| P5L-03 : reprise par indices ordinaux | Identité d'exécution immuable (engagement, code, partition, empreintes de structure sans graine, parents, K, régimes, environnement) et répertoire `runs/<run_id>/` par exécution. Une identité différente est refusée, jamais mélangée. Le pilote E0 est conservé intact. | `src/hospitalos/p5/pilot.py`, `scripts/p5_pilot.py` |
| P5L-03 : erreurs non bloquantes | Arrêt avec `FAILURE_RECEIPT.json` sur violation, univers modifié ou plan recommandé hors univers. Une exécution arrêtée ne peut pas être reprise sous la même identité. Les véritables abstentions sont évaluées comme HABITUAL-1 et comptées. | `src/hospitalos/p5/pilot.py` |
| P5L-01 : identité des offres | Unicité publique de `offer_key` contrôlée à la construction de l'annexe ; un doublon arrête le générateur. Aucune collision n'est revendiquée. | `src/hospitalos/p5/generator.py` |

**Engagement E1** (`COMMITMENT_E1.json`, `dbe20aec…f14f`, registre n° 15) : graines inchangées
(`276d965d…df45c`), code corrigé et documents v3 proposés, moteur v6 identique à `856a57c`. E0,
`SEEDS_SEALED.json`, le pilote initial et son rapport sont inchangés (`git diff` vide contre
`3ac18fd`).

## 3. Tests réellement exécutés, sous compteur

- n° 13 : 41/41 au premier passage (24 existants + 17 nouveaux), 3,43 s.
- n° 16 : **42/42 sous E1** (JUnit `pytest_p5_1_E1.xml`), 1,62 s.

Les nouveaux tests couvrent :
- **compteur** : mauvais interpréteur, gel modifié, gel post-installation accepté seulement
  s'il est inscrit, lot non autorisé, outil statique par chemin exact (le lancement de
  processus est remplacé par un double qui échoue s'il est appelé) ;
- **intégrité** : source conforme, source différente de l'engagement, graines différentes,
  dernier engagement effectif, engagement réel E1 vérifié sur le disque ;
- **pilote** (graine de développement 21, répertoire temporaire) :
  - identité et reprise sans doublon ;
  - ligne ou identité étrangère refusées, anciens relevés conservés ;
  - violation injectée ⇒ arrêt, reçu, reprise refusée ;
  - plan hors univers ⇒ arrêt, pas d'indice 0 silencieux ;
  - abstention véritable ⇒ HABITUAL-1 ;
  - univers modifié ⇒ arrêt ;
- **générateur** : clé d'offre dupliquée ⇒ arrêt.

Contrôle réel (n° 17) : `/usr/bin/python3.11` est refusé avant lancement (code 5, 0 s).

Limite : ces tests visent des chemins créés par la correction. Je ne les ai pas lancés contre
le code E0, qui n'avait pas ces fonctions.

## 4. P5-PROTO-3 proposé (non approuvé)

`P5_PROTOCOL_v3.md` (`dbf517ca…6ab6`) et `P5_PROTOCOL_PARAMS_v3.json` (`653a426a…18ac`) :
amendements A1–A11.
- A1 : clés sans régime ni jumeau.
- A2 : unicité de `offer_key`.
- A3 : gels F_a et F_b.
- A4 : K_precheck = 3, K_labels ∈ {3, 2}, K_eval = 3.
- A5 : contenu exact de L2 et banc de 6 ajustements sur une matrice tuilée de 1440 lignes, dans
  le reliquat P5.2, extrapolation déclarée.
- A6 : événement de dégradation.
- A7 : formule d'interaction.
- A8 : support réel de la population et couplage de `choose_offers`.
- A9 : contrôles d'exécution normatifs.
- A10 : erratum `not_requested`.
- A11 : devis recalculé.

v2 et D1–D12 sont conservés ; leur approbation reste liée aux seules empreintes v2.

## 5. Devis

Les postes mesurés (simulation 0,77 ms, recommandation 0,044 s, extraction 0,09 ms) donnent :
- P5.3 : 32–48 s ;
- P5.4 hors ajustements : 39–70 s ;
- 72 ajustements : **toujours non mesurés**, 135–1951 s selon l'hypothèse de 3 à 20 ns.

Le banc A5 est estimé à environ 5–35 s, plus les démarrages. Aucun palier de repli n'est
appliqué ; le plafond n'est pas augmenté.

## 6. Décisions demandées (aucune n'est prise ici)

| # | Décision |
|---|---|
| D13 | Approuver P5-PROTO-3 |
| D14 | Approuver D4 : installation isolée de scikit-learn, lot P5.I, avec un gel post-installation consigné |
| D15 | Autoriser le banc A5 (6 ajustements de chronométrage, modèles jetés) |
| D16 | Option : banc à 11 520 lignes (non recommandé avant D15) |

(ii) et (iii) restent séparées, après F_a et F_b.

Statuts inchangés : `PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`. P6 reste fermé. Pas de v7 du moteur.
