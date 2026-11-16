# Tranche B amendée — Monde v2 et porte d'identifiabilité

**NON EXÉCUTÉE.** Proposition préparée sous la décision n° 5. Cette décision n'autorise **aucune**
génération expérimentale, simulation de validation, mesure G_ID ou descente de gradient pour B.
L'enveloppe proposée de 11 400 s n'est pas autorisée à la dépense.

Elle remplace `proposition_A2/B/`, qui n'a pas été adoptée. Elle tient compte de l'addendum de
clôture de A′ : κ ne borne pas un estimateur optimal, l'attribution de l'écart avec C_full n'est pas
mesurée, et le concurrent pertinent est C_full contre la règle.

Statuts : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. Les hypothèses
synthétiques ci-dessous **ne valent pas validation clinique**.

## 1. Pourquoi B

A′ n'a pas mis en évidence, sur HOWM-1, d'état caché dont la récupération **par L4-N** franchisse le
seuil décisionnel de 15. B est une voie pour **construire** un monde où un état caché persistant pèse
sur les décisions et laisse des traces publiques. Ce n'est pas une conséquence démontrée de A′
(addendum de clôture, conclusion corrigée).

## 2. Convention temporelle commune (§ 6 a du mandat)

L'instant de décision est t, au tick t0 = t/15. La convention est la même pour l'état vrai,
l'historique public, le contrôleur privilégié, les références et tous les déroulés.

| Élément | Convention v2 |
|---|---|
| État vrai S_true(t) | État du moteur **après** application de tous les événements de date ≤ t, y compris ceux du tick t0, et **avant** toute décision prise à t. Le clonage a lieu **après** le pas t0. Écart corrigé par rapport à HOWM-1, où le clonage avait lieu avant. |
| Observations publiques | Événement e visible à t si et seulement si `avail(e) ≤ t`. Les événements de date ≤ t à retard nul en font partie. |
| Événements à retard nul | Ils appartiennent à la fois à S_true(t) et à l'historique public. Ceux de date t, y compris les plans habituels et les demandes de transport habituelles, sont donc **dans les deux**, et aucun ne figure dans l'un sans l'autre. |
| Décisions de l'opérateur | Placements, débuts de transport et débuts de nettoyage sont publiés avec un retard nul (levier 5). |
| Application de l'action | Le plan candidat est appliqué à t, après S_true(t), **avant** le premier pas du déroulé. Pour tous les systèmes, il s'applique sur l'état de départ propre au système. |
| Début du déroulé | Premier pas au tick t0 + 1. Aucun événement de date ≤ t n'est rejoué. Toutes les durées en cours sont tirées conditionnellement à ce qui s'est écoulé jusqu'à t. |

**Tests obligatoires (T-B03 à T-B03d), qui doivent réussir avant toute mesure G_ID :**
- **T-B03 :** dans un monde v2 sans retard et sans état caché, S_pub(t) = S_true(t) champ par champ,
  à tout instant de décision.
- **T-B03b :** tout événement de date = t et de retard nul est présent dans S_true(t) **et** dans
  S_pub(t).
- **T-B03c :** déroulés depuis S_true(t) et depuis S_pub(t), dans le monde du test T-B03, sous mêmes
  clés : trajectoires identiques bit à bit.
- **T-B03d :** l'action candidate est appliquée une seule fois, avant t0 + 1 ; le contrôle se fait
  par un journal d'application.

## 3. Mécanismes et justification (§ 6 b)

| Variable cachée | Processus hospitalier représenté (hypothèse) | Indices publics | Information inférable | Incertitude irréductible | Information privilégiée (diagnostics seulement) |
|---|---|---|---|---|---|
| Régime d'équipe partagée (normal ou lent), sur 6 unités, ≥ 1 poste | Sous-effectif ou surcharge d'une équipe de brancardage ou de bionettoyage commune, durant un poste | Durées des services terminés sur **toutes** les unités ; files d'attente publiques | Régime courant, à partir des durées récentes publiées, avec des dizaines d'événements par poste | Moment exact de la bascule ; durées individuelles | Trajectoire de régime vraie |
| Dérive lente de θ sur 4 semaines | Évolution des pratiques et des effectifs | Historique long des durées | Tendance, par filtrage | Innovations récentes | θ(t) vrai |
| Retard de publication | Saisie différée dans le système d'information | Paires (événement, publication) publiées | Loi du retard | Retards individuels en cours | Retards vrais |
| Effet d'une action selon le régime | Un renfort ou une coordination n'aide qu'en régime lent | Aucun, directement ; via le régime inféré | Valeur espérée de l'action sachant la postérieure du régime | Réalisation future | Régime vrai au moment de l'action |

**Hypothèses de plausibilité, synthétiques et à déclarer comme telles :**
- les durées des régimes sont de l'ordre d'un poste ;
- le facteur de ralentissement est de 1,5 à 2,5 ;
- la dérive est de quelques pour cent par semaine.

Elles ne sont calibrées sur aucune donnée hospitalière réelle.

## 4. Conception, puis confirmation séparée (§ 6 c)

1. **Conception.** Au plus **3 itérations**, exclusivement sur `REF2_TUNE` (60 établissements, et
   ses instants de décision). Les seuils G_ID peuvent guider le travail, mais **un passage sur TUNE
   ne vaut pas confirmation**.
2. **Sélection** d'une seule conception, puis **gel** de la conception et du protocole
   d'évaluation complet :
   - générateur v2 et G_alt-v2 ;
   - filtres L4-v2 et L4-N-v2 ;
   - concurrents et règle de choix du meilleur concurrent public ;
   - analyse.
3. **Confirmation unique** sur `REF2_CONF`, population indépendante, **jamais utilisée pour le
   réglage**, générée seulement après le gel : 200 établissements pour M_pub, et 24 × 4 instants
   pour la décision.
4. **Si la confirmation échoue**, le monde n'est pas retouché et la population n'est pas
   réutilisée. Verdict : `PAS_DE_MARGE_IDENTIFIABLE_A_CETTE_ECHELLE`.

## 5. Porte G_ID (§ 6 d)

**Condition 1 — M_pub.**
- M_pub(h) = L(meilleure de {L1-v2, L2-v2, L2c-v2}) − L(L4-v2), en nats par item.
- Agrégation de R1 sur les familles validées par la règle de calibration de l'addendum 2 de A,
  appliquée sur TUNE puis gelée.
- Établissements équipondérés ; choix de la meilleure référence refait dans chaque réplique.
- Bootstrap par grappes d'établissement, B = 2 000.
- **Seuil :** borne basse de l'IC à 95 % ≥ 0,02 à H6 **et** à H24.

**Condition 2 — marge décisionnelle accessible.**
- marge = U(meilleur concurrent public) − U(planificateur L4-N-v2), en unités de U
  (minutes-soignant), par instant puis en moyenne.
- **Meilleur concurrent public**, choisi par une procédure fixée au gel, sur TUNE seulement : le
  meilleur sur TUNE parmi la règle renforcée v2, C_param-v2, C_pub_snap-v2 et le planificateur L4-v2.
- Les actions, contraintes, objectifs, M, clés de choix et OBJ-LEX-1 sont **identiques** pour tous
  les systèmes.
- Bootstrap par grappes d'établissement, B = 2 000.
- **Seuil :** borne basse de l'IC à 95 % ≥ 15.

**Grandeurs séparées, toujours rapportées :**
- **valeur de l'information privilégiée** = U(meilleur concurrent public) − U(C_full-v2) ;
- **gain obtenu depuis l'historique public** = U(meilleur concurrent public) − U(L4-N-v2) ;
- **part** = gain / valeur, avec la mention « instable » si l'IC du dénominateur contient 0.

**Verdict.** `G_ID_CONFIRMEE` si les conditions 1 **et** 2 sont remplies sur `REF2_CONF` ; sinon
`PAS_DE_MARGE_IDENTIFIABLE_A_CETTE_ECHELLE`.

## 6. Arrêt et portée (§ 6 e)

- **Gel G0-v2** (réserve v2 scellée comprise) **uniquement** après une confirmation indépendante
  réussie.
- **En cas d'échec**, le verdict décrit **le dispositif testé** : ce monde, ces mécanismes, ces
  références et ce seuil. Ce n'est pas une impossibilité générale.
- Aucun entraînement dans B.
