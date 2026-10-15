# Lot 13 — preuves de diversification documentaire

Campagne locale du 15 octobre 2026, exclusivement synthétique. Aucun modèle
entraîné, aucune trajectoire de test final générée ou évaluée.

## Périmètre

Six configurations du même hôpital de développement : 2 pôles, 4 unités,
365 jours en 2025 et 61 jours de chauffe, graine 41, profil de transmission
intermittent. Les quatre variantes sont exercées séparément ; une sixième
configuration combine les prévisions par étapes et les revues d’aval à quota.

## Résultats annuels

**Six campagnes réussies : 61 344 heures physiques contrôlées,
aucune violation des contraintes vérifiées ; 36 empreintes de fichiers et
les archives compressées vérifiées. 291 654 réceptions documentaires**
comparées exactement entre traitement incrémental et rejeu, chauffe comprise.

Les empreintes des patients entrants, états d’unité, actions, facteurs du cadre,
séjours terminés, tâches, événements physiques et capacités/files sont identiques
pour les six configurations. Les signaux documentaires varient :

| Configuration | Réceptions, chauffe incluse | Annonces de sortie dans l’année | Erreur absolue moyenne (jours) | Confirmations dans l’année | Délai médian confirmation–sortie (h) |
|---|---:|---:|---:|---:|---:|
| Référence v041 | 47 157 | 5 799 | 2.41 | 832 | 18 |
| Prévision depuis l’admission | 48 482 | 6 327 | 4.55 | 832 | 18 |
| Prévision par étapes | 51 355 | 8 865 | 3.87 | 832 | 18 |
| Confirmation après délai | 47 014 | 5 799 | 2.41 | 788 | 67 |
| Confirmation à quota | 46 661 | 5 799 | 2.41 | 470 | 95 |
| Étapes + quota | 50 985 | 9 012 | 3.94 | 474 | 47 |

Les erreurs moyennes portent seulement sur les annonces associées à une sortie
observée. Elles ne sont donc pas comparables comme un classement de modèles :
les annonces et leurs fréquences changent, les devenirs censurés sont exclus.
Les confirmations comptées dans l’année incluent celles sans sortie observée ;
les quantiles de délai excluent ces dernières. Les dénominateurs précis figurent
dans le rapport machine.

**Différence de mécanisme visible :** parmi les confirmations avec sortie
observée, 523 sur 831 surviennent exactement 18 h avant la sortie dans la
référence, contre 1 sur 781 après délai administratif et 0 sur 465 avec quota.
Les quantiles 10/50/90 % du délai sont respectivement 18/18/20 h,
3/67/221 h et 22/95/286,2 h. Cela montre une diversification des signaux,
pas une validation de leur réalisme.

Pour les trois configurations utilisant une nouvelle confirmation, tous les
messages contrôlés sont reliés à une demande non annulée : 921, 542 et 546
confirmations en incluant la chauffe. Les revues à quota ne dépassent jamais
**2 confirmations par jour ouvré à 14 h** dans cet hôpital à quatre unités.

Les deux plans sont figés séparément : **6 hôpitaux et 12 réalisations prévues
par plan**, dont 2 hôpitaux et 4 réalisations réservés au test. Les registres sont
produits, sans générer ces trajectoires. Cette réservation minimale porte sur
un axe à la fois et ne constitue pas encore le protocole final de généralisation.


## Contrôles locaux

- **433 tests synthétiques**, dont **31 nouveaux cas**, et **54 tests historiques**
  réussis : **487 tests au total**.
- Ruff lint/format et tous les groupes de typage strict de la CI validés.
- Exports courts reproductibles, contrats de soins compatibles, métadonnées
  documentaires conservées et cibles toujours séparées.


La référence est comparée au moteur publié du lot 03. Les mutations vérifient
l’exclusion des dates futures du contrat de prévision, l’insensibilité à une
date d’aptitude future changée tant que le constat présent reste identique,
le lien aux demandes, les annulations, réouvertures, quotas et calendriers.
Les variantes sont composées avec trois organisations de ressources et une
dynamique de sortie alternative. L’exécution sans journal conserve la physique.

Les deux registres réservent les familles par axe, conservent les paramètres
entre réplications et refusent une ouverture du test sans protocole. Aucun
établissement réservé n’est matérialisé pendant cette campagne.

## Interprétation et limites

- Les erreurs de prévision sont calculées par annonce pour les séjours dont
  la sortie est observée avant l’extraction. Les séjours censurés sont exclus
  du score ; les patients avec davantage de révisions pèsent davantage.
- Les confirmations sont des messages administratifs. Elles n’allouent pas de
  lit physique d’aval et ne contraignent pas la sortie ; absence de confirmation
  ne signifie pas absence de sortie possible.
- Les observations restent bruitées. La numérotation globale des événements
  peut changer les clés des tirages de transmission entre variantes ; seule
  la physique est comparée à tirages communs dans cette campagne.
- Ces mécanismes sont des hypothèses non calibrées. Leur inspection en
  développement ne constitue ni une évaluation aveugle ni une preuve G1–G4.
  Les limites historiques subsistent sur les axes laissés à `v041`.

## Reproduction

```bash
PYTHONPATH=src python scripts/validate_synthetic_documentary.py \
  --output runs/synthetic/lot13/annual
```

Utiliser un répertoire de sortie neuf. La CI exécute la même campagne et
conserve le rapport et les manifestes des registres. Les empreintes du code,
du script, des configurations, des états physiques et des manifestes sont
dans le [rapport machine](lot13_validation.json).
