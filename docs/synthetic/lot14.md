# Mesures de réalisme et cible gériatrie–aval — lot 14

Ce lot commence le plan accepté le 15 octobre 2026 : mesures corrigées → scénario
gériatrie avec aval contraint → benchmark corrigé → première expérience de dynamique
apprise. Il livre le premier maillon et une configuration de développement de 250
lits de médecine. Il ne valide pas le réalisme hospitalier, ne construit pas encore
les capacités territoriales d'aval et n'entraîne pas un nouveau modèle.

## Entrées et sorties

Le module `hospitalos.synthetic.realism` lit une exécution de vérité terminée et
vérifie les empreintes de sa configuration, de ses événements et de ses états
horaires. Il refuse les partitions de test avant de lire leurs fichiers de vérité,
ainsi que les exports portant un marqueur d'overlay expérimental non versionné.
Ce dernier contrôle détecte le prototype fourni ; ce n'est pas une preuve contre
toute modification arbitraire d'un processus Python.

```bash
PYTHONPATH=src python -m hospitalos.synthetic.realism \
  --source runs/synthetic/annual \
  --references configs/synthetic/realism_references_v1.json \
  --output runs/synthetic/realism-annual
```

La sortie atomique contient `scorecard.json` et un manifeste : empreinte de
l'entrée, du module de mesure et du référentiel, versions Python/NumPy et empreinte
du résultat. Le chemin doit être nouveau. Le JSON interdit les NaN ; une mesure
impossible reste `null`, assortie d'un motif. Les rapports sont des diagnostics de
vérité et ne sont pas des entrées d'apprentissage.

## Définitions et populations

| Mesure | Population ou dénominateur |
|---|---|
| Admissions | Admissions physiques dans `[0, fin)`, même si la demande vient de la chauffe |
| Sorties et DMS descriptive | Sorties dans `[0, fin)`, y compris admissions antérieures ; durée hospitalière écoulée |
| DMS admis-et-sortis | Sous-population distincte, explicitement affectée par la sélection des séjours terminés |
| Journées-lits | Somme des intersections des segments de présence avec `[0, fin)` ; séjours ouverts inclus |
| Occupation | Heures-lits occupées / heures-lits ouvertes ; distribution des ratios horaires séparée |
| Présence après première disponibilité médicale | Même fenêtre, y compris les séjours déjà présents et encore présents |
| Attente urgences | Cohorte de demandes dans la fenêtre ; admissions, orientations et demandes encore ouvertes séparées |
| File d'attente cumulée | Heures-patients d'attente dans la fenêtre, y compris demandes antérieures à janvier |
| Effectifs | Présence nette, déficit et surplus par rapport au prévu ; pas l'absentéisme brut |
| Charge | Minutes de proxy synthétique ; aucune conversion en SIIPS |

Les segments suivent les admissions, transferts et sorties réels. Chaque unité et
chaque heure sont réconciliées avec les états horaires pour l'occupation et les
files d'urgence. Une incohérence interrompt la production du rapport. L'hébergement
ne transfère pas rétroactivement toutes les heures à l'unité demandée. Les volumes
d'admissions par unité demandée et par unité effective sont exposés séparément.

Les pôles et le périmètre hospitalier agrègent les numérateurs/dénominateurs avant
de calculer les ratios. Ainsi, la part d'heures avec une unité pleine diffère de la
part d'heures où tout le périmètre est plein. La part d'heures avec un déficit de
soins à l'échelle de l'hôpital signifie qu'au moins une unité a un déficit : les
excédents d'autres unités ne compensent pas implicitement ce déficit.

Les quantiles de délai jusqu'à admission sont conditionnels à l'admission. Les
patients réorientés et encore en attente ont leurs effectifs et délais séparés.
Les délais de disponibilité médicale des patients encore présents sont des bornes
inférieures censurées ; aucune médiane de population non censurée n'est prétendue.
`ORIENTATION_HORS_PERIMETRE` peut désigner le reste de l'établissement : ce n'est pas
une preuve de transfert vers un autre hôpital.

Le calendrier vient de la configuration et couvre les années bissextiles. La
convention du simulateur reste UTC+01 fixe. Le passage à Europe/Paris reste ouvert.

## Référentiel externe

`configs/synthetic/realism_references_v1.json` contient huit références ou lacunes
documentées : source, définition, population, valeur éventuelle, comparabilité et
rôle. Elles sont toutes `context_only`, sans bande d'acceptation. Le chargeur refuse
qu'une bande soit introduite silencieusement dans ce référentiel provisoire.

- Les 95 % DGOS sont un objectif de gestion, pas une moyenne observée.
- La DMS nationale de médecine ne constitue pas une cible de CSG ; les conventions
  PMSI et les durées horaires restent à harmoniser.
- La recherche d'un lit et le délai jusqu'à admission sont des étapes différentes.
- Une borne tarifaire GHS ne définit pas la disponibilité médicale.
- La présence après remplacement ne reconstitue pas les absences brutes.
- Les heures après disponibilité et une destination SMR/EHPAD ne démontrent pas
  un blocage causé par une capacité d'aval. Cet indicateur causal reste indisponible.
- Le temps de coordination est indisponible faute d'acteurs/tâches chronométrés.

Les sources publiques agrégées orientent le générateur ; aucun dossier réel n'est
utilisé. Une future validation externe devra réserver ses références avant les
ajustements. Une revue rédigée selon des personas ne compte pas comme entretien
terrain documenté.

## Archive GHT-600 reçue pendant le lot

`ght600_provenance.json` conserve les empreintes de l'archive et de ses sept membres.
La configuration importée `hospital_ght600_medical_scope_v1.json` reprend les neuf
unités, leurs volumes d'arrivée et les 18 fenêtres de fermeture. Elle utilise les
signaux documentaires `milestones_v1` et `request_delay_v1` du lot 13.

**250 lits standard sont simulés, dont 60 de CSG.** Les 600 lits décrivent le contexte
de l'établissement ciblé ; les 350 autres lits ne sont ni simulés ni représentés
comme ressources agrégées actives. Le moteur peut ajouter ses lits de renfort. Les
libellés MED_INT/MED_INF restent des variantes du même modèle MED_POLY, pas de nouvelles
spécialités cliniques.

Les changements de paramètres globaux de `fr_overlay.py` ne sont pas intégrés :
ils modifient les effectifs, destinations et épidémies sans apparaître dans
l'empreinte de configuration. Les résultats « 8 bandes sur 12 » de la note fournie
ne sont donc ni reproduits ni adoptés comme validation. Les quatre graines y sont
des répétitions d'une structure, pas quatre établissements indépendants. Le nouveau
profil est un scénario de développement, pas une famille française calibrée.

```bash
PYTHONPATH=src python -m hospitalos.synthetic \
  --config configs/synthetic/hospital_ght600_medical_scope_v1.json \
  --output runs/synthetic/ght600-medical-scope
PYTHONPATH=src python -m hospitalos.synthetic.realism \
  --source runs/synthetic/ght600-medical-scope \
  --references configs/synthetic/realism_references_v1.json \
  --output runs/synthetic/ght600-realism
```

## Vérification et suite

Les tests indépendants couvrent le calcul à la main des journées-lits, les deux
frontières, les transferts, les demandes non admises, les dénominateurs nuls, le
calendrier, les erreurs de stock, les mouvements impossibles, les empreintes,
les overlays, les références et le refus du test réservé. La CI ajoute le calcul
sur son année existante sans seuil hospitalier inventé.

Les preuves annuelles sont dans `evidence/lot14_validation.json` et
`evidence/lot14_validation.md`. La séquence acceptée et les critères des lots suivants
sont dans [realism_plan.md](realism_plan.md). Les faux recensements complets restent
au backlog et devront être éprouvés avant une évaluation finale de robustesse.
