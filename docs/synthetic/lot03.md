# Registre de cohortes hospitalières — lot 03

GEN-003 fournit un plan de cohorte figé avant génération, des configurations par
établissement et répétition, puis un lot de parcours séparés par partition.
Le pipeline du [lot 02](lot02.md) peut produire les observations telles que connues,
les variables, les cibles et la référence à 24 h pour chaque monde.

Aucun modèle n'est entraîné dans ce lot. Le registre permet de préparer une
évaluation sur des structures inédites ; il ne démontre pas la généralisation.

## Première cohorte

Le plan `configs/synthetic/cohort_structures_v1.json` réserve :

| Ensemble | Structures | Hôpitaux | Pôles / hôpital | Unités / hôpital | Répétitions / hôpital |
|---|---:|---:|---:|---:|---:|
| Apprentissage | 1 | 2 | 2 | 4 | 2 |
| Validation | 1 | 2 | 3 | 6 | 2 |
| Test réservé | 1 | 2 | 4 | 8 | 2 |

Chaque répétition simule une année 2025 après 61 jours de chauffe. Il s'agit de
deux réalisations indépendantes de la même période par établissement, et non de
deux années successives. Les 12 mondes sont inscrits au registre ; seuls les
8 mondes d'apprentissage et de validation sont matérialisés par défaut.

Les structures sont déclarées explicitement dans le plan, pas découvertes ni
tirées aléatoirement. Les paramètres varient par établissement : 20–32 lits
standard par unité, multiplicateurs d'arrivées et de services communs entre
0,8 et 1,2. Les proportions de lits spécialisés reprennent les quatre profils.
Ces plages servent à éprouver le logiciel ; elles ne sont pas calibrées sur des
statistiques hospitalières. Le renfort hérité ajoute jusqu'à deux lits par unité.

## Exécuter

Depuis la racine, avec les dépendances légères du lot 01 :

```bash
PYTHONPATH=src python -m hospitalos.synthetic.cohort freeze \
  --plan configs/synthetic/cohort_structures_v1.json \
  --output runs/synthetic/cohort-registry

PYTHONPATH=src python -m hospitalos.synthetic.cohort generate \
  --registry runs/synthetic/cohort-registry \
  --output runs/synthetic/cohort-data \
  --with-learning
```

La première commande ne produit aucune trajectoire. Elle sauvegarde le registre,
son empreinte, le plan, toutes les configurations effectives et les empreintes du
code. La seconde vérifie ces éléments et les versions Python/NumPy/Pandas/Pydantic,
puis exécute chaque monde choisi. Une modification du code ou des dépendances
nécessite de restaurer la version figée ou de créer une nouvelle version du registre.

Les chemins de sortie doivent être nouveaux. La génération publie le lot entier
seulement après succès ; un échec supprime les fichiers intermédiaires de ce lot.
Il n'y a pas encore de reprise partielle. Aucun fichier du registre n'est modifié.

`--partitions train` permet de ne générer que l'apprentissage.
Ouvrir le test exige de le nommer explicitement dans `--partitions` et de fournir
`--test-protocol IDENTIFIANT`. Cette ouverture est consignée dans le manifeste.
Ce mécanisme prévient une consultation accidentelle ; il n'est pas un contrôle
d'accès, une preuve de préenregistrement ni un compteur garantissant un test unique.
Les configurations de test sont visibles ; leurs trajectoires et scores ne sont
pas produits par défaut. Après consultation ayant influencé les choix, reclasser
les mondes concernés en validation et réserver une nouvelle cohorte de test.

## Ce qui est réservé

- **Établissement entier :** ses répétitions restent dans la même partition et
  partagent les mêmes lits, paramètres d'arrivée et capacités communes.
- **Structure complète :** l'empreinte conserve les spécialités et leurs
  multiplicités dans chaque pôle. Elle ignore les noms, l'ordre et les paramètres
  numériques. Renommer un hôpital ou changer ses tailles ne permet pas de
  répartir cette structure entre apprentissage et test.
- **Structure effective du moteur :** v041 ignore les frontières des pôles pour
  l'allocation des ressources. Regrouper les mêmes spécialités dans d'autres
  pôles est donc également refusé entre partitions.
- **Graines :** paramètres d'établissement et trajectoires ont des tirages
  distincts. Les graines de trajectoire doivent être différentes dans le registre ;
  une collision 32 bits est détectée et impose une autre graine de cohorte.

Le tirage est indexé par identifiant de cohorte, graine, structure, numéro
d'établissement et répétition. Ajouter des établissements ou répétitions, ou
réordonner la liste des structures, conserve les configurations déjà inscrites.
Cela ne vaut pas pour un changement de durée : le moteur historique ne garantit
pas des préfixes de trajectoire identiques entre durées différentes.

`validate_worlds` peut contrôler l'union de plusieurs registres. Il faut appeler
ce contrôle avant de réunir des cohortes : aucun service global ne surveille les
registres indépendants. Des paramètres d'établissement modifiés sous la même
identité sont rejetés lors de ce contrôle. Employer un nouvel identifiant de
cohorte pour une nouvelle campagne incompatible.

**Réservation de mécanismes : non disponible avec le seul moteur v041.**
Le mode `split_axis="mechanism"` refuse une même famille dans plusieurs
partitions. Avec les familles actuellement implémentées, ce mode est refusé :
changer une graine ou une étiquette ne crée pas une physique inédite.
GEN-004 doit ajouter de véritables mécanismes avant une campagne G4.

## Sorties et clés

| Fichier ou répertoire | Rôle |
|---|---|
| Registre : `registry.json` | Plan et configurations complètes des 12 mondes |
| Registre : `manifest.json` | Empreintes, versions, tailles des partitions |
| Lot : `manifest.json` | Correspondance monde / hôpital / répétition / partition, chemins et empreintes des manifestes enfants, mondes réservés, ouverture éventuelle du test |
| Lot : `<partition>/<world_id>/truth/` | Export du lot 01 et son manifeste |
| Lot : `<partition>/<world_id>/learning/` | Export du lot 02, seulement avec `--with-learning` |

Les identifiants de séjour, d'événement, d'unité et de pôle ne suffisent pas pour
réunir des répétitions ou des établissements. Utiliser le `world_id` du manifeste
avec les identifiants locaux ; pour les variables, utiliser
`(world_id, entity_id, decision_h)`. Les lignes du lot 02 portent déjà leur propre
`run_id`, relié au monde par `learning_run_id` dans le manifeste de cohorte.

Les manifestes enfants contiennent les empreintes de leurs fichiers. Le manifeste
de cohorte contient les empreintes des manifestes enfants. La vérité, les variables
et les cibles restent dans leurs répertoires distincts ; ce lot ne concatène pas
leurs colonnes et ne construit pas encore un chargeur pour l'entraînement.

## Vérifications et limites

Les [preuves du lot](evidence/lot03_validation.md) consignent les exécutions.
Les tests contrôlent les clones renommés ou regroupés, le maintien des répétitions,
les mutations du registre, le refus d'un faux test G4, les empreintes, l'atomicité,
la reproductibilité octet pour octet et la propagation des partitions jusque dans
les variables. La CI utilise une cohorte courte jetable distincte de la cohorte
annuelle réservée, en plus de l'année de référence des lots précédents.

Cette petite cohorte est un essai d'infrastructure. Une seule structure par
partition ne suffit pas à isoler un effet de taille, un effet de composition et
un effet de regroupement. Les unités partagent partout les mêmes quatre profils,
les mêmes mécanismes et une politique utilisant des informations privilégiées.
G2 (pôles inédits) n'a pas encore sa campagne séparée. Les ressources locales,
le routage entre pôles, la diversité des mécanismes et les contrefactuels
multi-pôles restent le prochain lot GEN-004.
