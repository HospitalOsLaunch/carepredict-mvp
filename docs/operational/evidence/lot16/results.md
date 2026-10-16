# Lot 16 — résultats de la comparaison SMR

Le moteur conserve les places et les mouvements SMR dans les 18 mondes de la variante :
**51 840 photographies horaires** rapprochées indépendamment du journal, avec les événements
de chauffe. Le premier prévisionniste n’est pas supérieur à toutes les références.

## Prévisions à 24 h

MSE macro : moyenne par entité, puis par hôpital de validation. Six sites par bras ;
les six mêmes configurations hors mécanisme SMR sont appariées. « Meilleure référence »
est le minimum descriptif parmi persistance, même heure quotidienne et climatologie train.
Le comparateur principal préspécifié reste la référence quotidienne ; ses scores et
les intervalles exploratoires par hôpital sont dans les rapports complets.

| Bras | Entrées → niveau évalué | Cible | Réseau | Meilleure référence | MSE référence | Variation du réseau |
|---|---|---|---:|---|---:|---:|
| SMR fini | unit → unit | Occupation | 6.248 | Persistance | 6.194 | +0.9 % |
| SMR fini | unit → unit | File urgences | 2.043 | Climatologie train | 2.462 | -17.0 % |
| SMR fini | unit → unit | Proxy de charge | 975.789 | Même heure quotidienne | 1853.506 | -47.4 % |
| SMR fini | hospital → hospital | Occupation | 78.801 | Persistance | 76.695 | +2.7 % |
| SMR fini | hospital → hospital | File urgences | 28.607 | Climatologie train | 36.540 | -21.7 % |
| SMR fini | hospital → hospital | Proxy de charge | 7467.375 | Même heure quotidienne | 13357.478 | -44.1 % |
| Délai historique | unit → unit | Occupation | 8.385 | Persistance | 9.408 | -10.9 % |
| Délai historique | unit → unit | File urgences | 0.863 | Climatologie train | 1.059 | -18.5 % |
| Délai historique | unit → unit | Proxy de charge | 1364.809 | Même heure quotidienne | 2324.855 | -41.3 % |
| Délai historique | hospital → hospital | Occupation | 92.503 | Persistance | 115.468 | -19.9 % |
| Délai historique | hospital → hospital | File urgences | 9.566 | Climatologie train | 12.183 | -21.5 % |
| Délai historique | hospital → hospital | Proxy de charge | 12126.411 | Même heure quotidienne | 21020.071 | -42.3 % |

Une variation positive signifie une erreur plus élevée. Les cibles diffèrent entre bras :
la baisse de MSE brute du contrôle au SMR fini ne démontre pas un progrès du modèle.

## Occupation d’unité selon le régime SMR

| Hypothèse de capacité | Sites validation | MSE réseau | MSE persistance | Variation |
|---|---:|---:|---:|---:|
| Fluide | 2 | 11.258 | 11.480 | -1.9 % |
| Saturé | 2 | 2.053 | 1.011 | +103.0 % |
| Tendu | 2 | 5.431 | 6.091 | -10.8 % |

**Le régime saturé révèle un échec : l’erreur du réseau sur l’occupation est environ
deux fois celle de la persistance.** Une explication plausible est la faible variabilité des lits
durablement occupés, favorable à cette référence ; les ablations devront l’éprouver. Ce constat motive des références plus fortes et une ablation
du contexte ; il ne justifie pas de déclarer le modèle validé.

## Stocks et files dans les six mondes de validation

| Monde | Hypothèse | Places SMR | Occupation SMR moyenne | Journées-patient en attente de capacité | File urgences moyenne |
|---|---|---:|---:|---:|---:|
| H16_validation_00 | Fluide | 63 | 87.7 % | 27.6 | 1.44 |
| H16_validation_01 | Tendu | 52 | 95.9 % | 1100.9 | 2.75 |
| H16_validation_02 | Saturé | 29 | 95.9 % | 6264.4 | 9.43 |
| H16_validation_03 | Tendu | 36 | 95.8 % | 1498.4 | 4.57 |
| H16_validation_04 | Saturé | 21 | 96.1 % | 5236.6 | 8.25 |
| H16_validation_05 | Fluide | 129 | 78.4 % | 0.0 | 3.33 |

L’attente de capacité compte les demandes hospitalières prêtes administrativement
et sans place compatible libre, intégrées à chaque fin d’heure. Les demandes encore
ouvertes sont incluses. Ce compteur ne mesure ni le délai de préparation ni le délai
de transport après réservation. L’occupation SMR exclut les places seulement réservées.
Les sites et leur activité diffèrent entre régimes : ce tableau n’est pas une estimation
causale de l’effet de lits supplémentaires.

## Reproductibilité et périmètre

Chaque bras : 12 sites train, six validation, 120 jours après 28 jours de chauffe,
trois granularités, un réseau de 6 755 paramètres, 60 époques. Deux configurations
de test final par bras restent réservées, sans trajectoires générées.
Les paramètres, entrées et budget sont restés fixes après les premiers résultats.
La correction de mortalité est active dans les deux bras. Les anciens résultats
du lot 15 restent conservés ; ils ne sont pas écrasés par ce contrôle.

Les poids, protocoles, registres et rapports complets compressés sont conservés ici.
Les grandes trajectoires et les matrices de prévisions restent reproductibles par
les commandes du [lot 16](../../lot16.md) ; leurs empreintes sont dans les manifestes.
Le paquet ne contient pas ces grandes matrices. Les deux poids se rechargent avec
`hospitalos.operational.forecast.load_frozen_model` dans le dossier du bras choisi.

Les nouveaux événements SMR sont dans la vérité du simulateur. Le modèle conserve
les anciennes entrées observées ; il ne reçoit pas directement les ressources SMR.
Les valeurs sont des hypothèses, sans validation clinique, transfert réel, incertitude
calibrée, dynamique multi-pas ni porte SYN franchie. EHPAD/HAD et coordination restent ouverts.

La première tentative interrompue et le contrôle ajouté contre les écritures CSV
incomplètes sont documentés dans `execution_notes.json`. La cause système n’est
pas établie. Les deux corpus finaux ont été régénérés avec vérification des écritures.
