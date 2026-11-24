# Prévision des lits et choix des gestes après la PR 51

La rotation des lits est corrigée dans la trajectoire synthétique. L'occupation à la relève du lendemain reste moins précise que la persistance. Le classement expérimental utilisant ces nouveaux flux dégrade plusieurs décisions dans l'épreuve de bout en bout. Le cockpit conserve donc le classement et les gains de la PR 51. Dans Données, les admissions, sorties et lits occupés du nouveau modèle sont consultables en observation lorsque les sources le permettent. Aucune unité n'ouvre J+3 ou J+7.

## Occupation et rotation

Lot principal de huit mondes synthétiques, quatre unités et 35 relèves par unité et par monde, soit 1 120 origines. Chaque prévision moyenne quatre futurs appariés. Le gain relatif est calculé sur la MAE face à la meilleure de la persistance et de la référence hebdomadaire. Les intervalles appariés rééchantillonnent univers et blocs de sept jours.

| Horizon | MAE historique avec flux publiés | MAE des nouveaux flux | Meilleure référence | Gain sur la référence et IC 95 % |
|---|---:|---:|---:|---:|
| J+1 | 1,445 lit | 1,414 lit | 1,289 lit | −9,7 % [−18,8 %, −1,7 %] |
| J+3 | 2,970 lits | 1,627 lit | 1,758 lit | +7,5 % [−3,2 %, +14,8 %] |
| J+7 | 3,545 lits | 1,661 lit | 1,767 lit | +6,0 % [−2,3 %, +13,1 %] |

À 24 h, la projection historique courte faisait 1,721 lit de MAE. À sept jours, la projection historique comptait 1,67 départ en moyenne. Le nouveau profil en compte 17,39 pour 17,45 réalisés. En revanche, à J+1, il compte 1,92 admission pour 2,51 réalisées. Les biais signés sur les admissions, les sorties et l'occupation sont respectivement −0,59, −0,06 et −0,54 par relève.

L'occupation gagne à J+3/J+7 en médecine interne et en pneumologie. La médecine polyvalente et la gériatrie font moins bien que la référence à ces horizons. Aucune unité ne satisfait la succession des critères exigés pour l'ouverture. Le signal des urgences est partagé entre générateur et prévision et les dates prévisionnelles sont disponibles dans 100 % des cas par construction. Le reçu est limité au synthétique. [Scores, intervalles et couverture](flows.json)

### Ce que révèle le croisement entrées × sorties

Second lot de huit mondes, 1 120 autres origines. Les quatre bras ont les mêmes dossiers publics, contrôles d'accès, dates prévisionnelles, plannings et admissions programmées. Le tableau présente les MAE à J+7, cumulées pour les flux, ponctuelles pour le stock.

| Urgences publiées | Sorties de cohorte | Admissions | Sorties | Lits occupés |
|---|---|---:|---:|---:|
| Désactivées | Désactivées | 14,29 | 15,41 | 1,78 |
| Activées | Désactivées | 12,14 | 15,41 | 3,29 |
| Désactivées | Activées | 13,87 | 8,66 | 5,22 |
| Activées | Activées | 2,53 | 2,13 | 1,71 |

Le premier bras manque une quinzaine de mouvements dans chaque sens et conserve pourtant une erreur de stock relativement faible. Ajouter les sorties seules peut vider artificiellement l'unité. Un score de stock isolé aurait masqué ces deux mécanismes. [Résultats par unité et horizon](factorial.json)

Une analyse exploratoire du premier lot localise le déficit d'admissions à J+1. Il atteint 1,35 en moyenne aux 255 relèves où tous les lits sont occupés et 0,37 aux 865 autres. Le constructeur de relève connaît les lits occupés, sans reconstruire la file d'amont déjà constituée. Le prochain test consiste à fournir la file effectivement observable à l'origine, avec ses priorités et compatibilités, et à mesurer séparément les admissions de cette file et celles des nouveaux arrivants sur d'autres mondes. La stratification est postérieure à l'analyse principale et ne démontre pas à elle seule la cause. [Décomposition au niveau de saturation initial](flows.json)

## Choix d'une action face à une équipe active

Le point d'entrée `plan()` reçoit le dossier public. Un évaluateur indépendant calcule ensuite les conséquences du geste retenu, des autres gestes, des paires admissibles et de la pratique courante. Le regret est l'attente supplémentaire du programme choisi face au meilleur programme en moyenne sur les quatre réalisations cachées du contexte. Le témoin de classement est une règle fixe. Le témoin de gain est l'équipe qui travaille et intervient avec le délai hypothétique du contexte.

| Budget du conseil | Regret moyen du moteur | Regret de la règle fixe | À cinq patients·minutes du meilleur | Conseil nuisible de plus de cinq patients·minutes face à l'équipe |
|---|---:|---:|---:|---:|
| Un geste | 6,82 | 126,82 | 58/72 | 1/72 |
| Jusqu'à deux gestes | 2,22 | 119,00 | 65/72 | 1/72 |

Les deux modes franchissent le critère global du banc. Le résultat est porté en partie par la faiblesse de la règle fixe en affectation des lits. Avec un seul geste, le moteur est quasi optimal dans 16 des 24 cas de renfort/entrée programmée. Avec deux gestes, la règle fixe est elle-même optimale dans cette famille. Les contextes construits ont le même poids. Leurs fréquences ne décrivent aucune unité réelle. [Détail des contextes et seuils](decisions.json)

Le contexte transport/bionettoyage 19 illustre l'erreur de choix. Le transport est crédité de 482,5 patients·minutes face au scénario passif. Face à l'équipe active, il gagne zéro. Prioriser le lit oxygéné B fait gagner 85 patients·minutes en moyenne. Le regret de ce conseil à un geste vaut donc 85. [Coûts du témoin, du conseil et du meilleur geste](decisions.json)

### Vérification du chiffre affiché et du risque

Sur 72 autres contextes, l'erreur absolue moyenne du gain nominal est de 8,73 patients·minutes avec un geste et 10,44 avec deux, lorsque l'évaluateur utilise le même témoin passif. Le signe concorde dans 93,1 % et 95,8 % des cas, avec une zone neutre de cinq patients·minutes.

Pour chaque budget, 33 des 72 contextes ont un conseil auquel la PR 51 associe une fourchette. Le gain moyen rejoué au même délai et sous la convention de préparation du contexte est dans cette fourchette dans **7/33** cas, pour chacun des deux budgets. Les scénarios de sensibilité indiquent ce qui change avec l'hypothèse de préparation. L'écart entre le moteur et un autre modèle de l'activité peut les dépasser. L'erreur moyenne du point correspondant à la convention est respectivement de 5,31 et 5,19 patients·minutes. Le bloc Action explicite cette limite.

Si une place armée devient subitement indisponible, l'admission anticipée peut aussi laisser un patient présent au-delà de la capacité. Le conseil accroît ce dépassement par rapport à l'équipe active dans 10/24 contextes programmés avec un geste et 14/24 avec deux. Le surcroît moyen est de 16,88 et 24,38 patients·minutes respectivement. Le choc est caché lors du choix et ne touche ici que les places armées. [Gains appariés, fourchettes et choc de capacité](gain_quality.json)

### Test intégré à la relève de 05 h 30

Les 72 cas du premier banc qualifient le comportement de référence de la PR 51 dans trois familles construites. Un test distinct active réellement le nouveau modèle de flux, avec son résident susceptible de sortir et des urgences attendues, dans 24 autres contextes de transport et de bionettoyage. Les deux classements affrontent la même équipe active et les mêmes futurs cachés.

| Budget | Choix modifiés | Améliorations / dégradations | Regret de la PR 51 | Regret avec les nouveaux flux |
|---|---:|---:|---:|---:|
| Un geste | 14/24 | 7 / 7 | 8,90 | 11,31 |
| Jusqu'à deux gestes | 14/24 | 2 / 11 | 2,79 | 19,98 |

Avec deux gestes, un changement est neutre. Le gain moyen face à l'équipe active tombe de 40,79 à 23,60 patients·minutes. La correction du flux physique ne justifie donc pas un changement de classement. L'API publique sert le classement, les combinaisons et les gains de référence. La comparaison expérimentale emploie une option interne, hors contrat HTTP, et un identifiant de plan distinct. [Rejeu intégré et coûts par contexte](integrated.json)

## Contrat et reproductibilité

Le profil opt-in `synthetic-residence-v2` exige les quatre reçus synthétiques frais, leur périmètre commun et l'admission effective des présents. L'horloge de séjour court depuis l'admission effective. Pour une personne déjà présente, les dates impossibles compte tenu de sa présence à la relève sont exclues. Une sortie de population est un événement interne `forecast_depart` limité à la projection. Un besoin documenté de transport, d'aval ou d'escorte reste sur le parcours logistique. Au-delà du support de durée, l'horloge s'abstient. Les entrées programmées gardent le traitement des engagements de la version de référence. La plage diurne des urgences, les durées et les heures de sortie sont des a priori du générateur. Aucun apprentissage de ces paramètres sur des hôpitaux n'est établi.

Une trajectoire partage ses innovations entre horizons et entre actions. Un score indépendant vérifie le lit, l'occupant, l'heure, l'admission préalable et la conservation. Les premières expériences utilisent des flux journaliers avec leurs limites intrajournalières. Aucun nouvel entraînement neuronal n'entre dans ce correctif.

Depuis la racine avec l'environnement verrouillé du dépôt, les commandes suivantes régénèrent les reçus.

```sh
export PYTHONPATH=src:.
python -m scripts.unit_planning.flow_validation --rows /tmp/flows-primary.csv
python -m scripts.unit_planning.flow_validation --factorial --rows /tmp/flows-factorial.csv
python -m scripts.unit_planning.decision_validation
python -m scripts.unit_planning.gain_validation
python -m scripts.unit_planning.integrated_validation
pytest -q tests/hybrid/test_unit_flow_clock.py tests/unit_planning
```

Le protocole initial précède les mesures principales. L'addendum a été publié après ce premier passage et avant l'ouverture du second lot. La jonction entre les deux composants a ensuite été spécifiée avant d'ouvrir les indices 48–71. Le seuil de cinq patients·minutes est une convention expérimentale à confronter aux équipes. [Protocole initial](PROTOCOL.md) · [Contrôles supplémentaires](ADDITIONAL_CONTROLS.md) · [Test intégré](INTEGRATED_CHECK.md)

La fiche pilote définit le dénominateur des occasions éligibles, les horodatages, l'exposition au conseil et le traitement des observations interrompues pour chaque unité et garde. [Recueil de la pratique ordinaire](PILOTE.md)
