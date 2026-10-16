# Première expérience sur le contrat commun — lot 15

Protocole exploratoire fixé avant entraînement et avant ouverture des cibles de
validation. Douze hôpitaux d’entraînement de 2, 4 ou 6 unités ; six hôpitaux de
validation de 3, 5 ou 7 unités. Chaque monde couvre 120 jours après 28 jours de
chauffe. Les deux mondes de test final réservés (9 et 11 unités) ne sont pas générés.

Un seul modèle de 6 755 paramètres, 60 époques et une seule graine d’entraînement.
Historique observé à 0, 6, 24, 48 et 168 h ; prévision à 24 h toutes les 6 h.
449 origines par hôpital et par granularité. Même modèle pour les flux unité,
pôle et établissement ; aucun ajustement des poids sur les hôpitaux de validation.

## Résultats

Erreur quadratique moyenne (MSE), moyenne des entités puis des hôpitaux.
La meilleure référence est choisie ici parmi persistance, même heure quotidienne
et climatologie d’entraînement pour décrire les résultats ; ce choix sur validation
ne constitue pas une nouvelle règle de sélection ou un test final.

| Entrées → niveau évalué | Cible | Meilleure référence | MSE référence | MSE modèle | Réduction descriptive |
|---|---|---|---:|---:|---:|
| Unités → unité | Occupation | Persistance | 9.543 | 8.998 | 5.7 % |
| Unités → unité | File d’urgence | Climatologie | 0.992 | 0.819 | 17.4 % |
| Unités → unité | Proxy de charge | Même heure quotidienne | 2411.886 | 1405.011 | 41.7 % |
| Unités → pôle | Occupation | Persistance | 27.583 | 24.966 | 9.5 % |
| Unités → pôle | File d’urgence | Climatologie | 2.689 | 2.168 | 19.4 % |
| Unités → pôle | Proxy de charge | Même heure quotidienne | 6111.758 | 3802.152 | 37.8 % |
| Unités → établissement | Occupation | Persistance | 116.218 | 101.439 | 12.7 % |
| Unités → établissement | File d’urgence | Climatologie | 10.267 | 7.758 | 24.4 % |
| Unités → établissement | Proxy de charge | Même heure quotidienne | 22219.903 | 14717.028 | 33.8 % |
| Pôles → pôle | Occupation | Persistance | 27.808 | 23.429 | 15.7 % |
| Pôles → pôle | File d’urgence | Climatologie | 2.689 | 2.271 | 15.5 % |
| Pôles → pôle | Proxy de charge | Même heure quotidienne | 6147.135 | 3403.656 | 44.6 % |
| Pôles → établissement | Occupation | Persistance | 116.928 | 93.049 | 20.4 % |
| Pôles → établissement | File d’urgence | Climatologie | 10.267 | 8.295 | 19.2 % |
| Pôles → établissement | Proxy de charge | Même heure quotidienne | 22287.362 | 12256.632 | 45.0 % |
| Établissement seul | Occupation | Persistance | 120.356 | 94.362 | 21.6 % |
| Établissement seul | File d’urgence | Climatologie | 10.267 | 8.317 | 19.0 % |
| Établissement seul | Proxy de charge | Même heure quotidienne | 22050.852 | 12264.354 | 44.4 % |

Le comparateur principal préspécifié est la référence quotidienne. Le rapport
complet fournit les différences appariées et intervalles bootstrap par hôpital,
ainsi que MAE, biais, déviance de moyenne de Poisson pour les comptes et résultats
sur les origines dont l’occupation cible atteint 90 % de la capacité nominale.
Ce seuil définit un sous-groupe de scénario, pas une norme clinique. Les unités
de MSE sont respectivement patients² et (minutes synthétiques/h)².

## Ce que cette expérience établit

- Une chaîne exécutable relie le générateur relu à un modèle appris via le contrat commun.
- Les mêmes poids traitent des nombres d’unités absents de l’entraînement.
- Les moyennes prédites se somment correctement pour une même frontière d’observation.
- Avec seulement les totaux, le modèle prévoit seulement les niveaux effectivement fournis.
- Les prévisions de validation sont enregistrées et empreintées avant la lecture de leurs cibles.
- Tous les points prévus sont évalués. Il n’y a toutefois aucune origine initiale manquante
  ou périmée de plus de 6 h dans cette campagne : elle ne valide pas les longues pannes.

## Limites et suite

Les quatre gabarits cliniques restent les mêmes, les sites restent indépendants,
le calendrier et les politiques du moteur sont hérités. Le biais de mortalité
identifié n’est pas corrigé dans cette livraison. Aucun effet clinique de la tension
n’est ajouté sans mécanisme et hypothèses explicites. Les cibles sont la vérité
synthétique, les entrées sont bruitées : une partie du gain peut venir du débruitage.

Il faut comparer à une référence lissée et au gradient boosting avec les mêmes
entrées, puis mesurer la contribution du contexte entre unités par ablation.
Cette campagne utilise un seul réseau/graine, six hôpitaux de validation et les
mêmes mois : elle ne prouve pas la généralisation au réel, aux saisons, aux
spécialités inconnues, aux mécanismes réservés ou aux GHT. Aucun gain SIIPS réel,
pré-entraînement JEPA, adaptation de site, intervalle calibré ou effet causal
n’est revendiqué. Le protocole final et la porte SYN restent ouverts.

## Preuves conservées

- `report.json.gz` : rapport complet, y compris résultats par entité et régime.
- `protocol.json` : paramètres, définitions et empreintes du code avant apprentissage.
- `cohort_registry.json` et `cohort_manifest.json` : mondes, partitions et sources.
- `model.pt` et `model_config.json` : poids et contrat de recharge vérifié.
- `predictions_frozen.json` : empreintes des prévisions antérieures à l’ouverture des cibles.
- `evidence_manifest.json` : empreintes de ce paquet et manifeste de l’exécution.

Les grandes trajectoires et tableaux de prévisions sont régénérables via les
commandes de [lot15.md](../../lot15.md), sans extraction réelle. Le paquet ne
prétend pas contenir ces grandes sorties. Les tests couvrent 457 cas du socle,
54 régressions historiques et 30 cas opérationnels, soit 541 cas locaux ; les
49 tests du correctif de validateur sont sur sa branche distincte.
