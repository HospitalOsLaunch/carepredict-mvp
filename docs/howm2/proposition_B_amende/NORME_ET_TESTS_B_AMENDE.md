# Tranche B amendée — Note normative, matrice de tests et plan de calcul

**NON EXÉCUTÉE.** Rien de ce document n'est lancé sous la décision n° 5.

## Note normative (à consigner avant toute mesure, si un accord l'adopte)

**N-B1. Code et isolement.**
- Code nouveau dans `src/hospitalos/howm_v2/`.
- HOWM-1 (G0 et F1) et les résultats R1, A, A′ et C1 ne sont pas modifiés.

**N-B2. Clés et partitions.**
- Clés `key("HOWM2v2", partition, i)`, disjointes de toutes les partitions existantes, ce qui est
  testé.
- Partitions :
  - `REF2_TUNE` : 60 établissements, avec leurs instants ;
  - `REF2_CONF` : 200 établissements, plus 24 × 4 instants, générés seulement après le gel de
    conception ;
  - `RESERVE_v2` : scellée au gel G0-v2.

**N-B3. Convention temporelle** du § 2 de la conception. Les tests T-B03 à T-B03d doivent réussir
avant toute mesure G_ID.

**N-B4. Itérations de conception.**
- Au plus 3, sur TUNE seulement.
- Chacune consigne :
  - le changement ;
  - la validation du filtre (identité, exactitude par énumération, calibration de l'addendum 2) ;
  - les mesures G_ID sur TUNE, qui sont **indicatives**.

**N-B5. Gel de conception.** On sélectionne **une** conception. On gèle alors le code, les a priori,
la règle de choix du meilleur concurrent public et le script d'analyse, avec leurs empreintes.

**N-B6. Confirmation.**
- Une seule campagne sur `REF2_CONF`.
- Aucune retouche ni réutilisation en cas d'échec.

**N-B7. Porte G_ID**, telle que définie au § 5 de la conception : unités, intervalles, unités de
rééchantillonnage et agrégation. La valeur de l'information privilégiée et le gain depuis
l'historique public sont rapportés séparément.

**N-B8. Arrêt.**
- Confirmation réussie : gel G0-v2 et rapport.
- Échec : verdict `PAS_DE_MARGE_IDENTIFIABLE_A_CETTE_ECHELLE`, à portée limitée au dispositif, et
  rapport.
- Rien d'autre n'est lancé.

## Matrice de tests

| ID | Objet | Condition de réussite |
|---|---|---|
| T-B01 | Espace de clés v2 | Disjoint de G0, de HOWM2_* et des partitions C1 ; réserve v2 scellée. |
| T-B02 | Chaîne de régime v2 | Loi stationnaire et durée moyenne empiriques égales à la loi déclarée (3 000 tirages, tolérance 0,03). |
| T-B03 | Convention à t | S_pub(t) = S_true(t) champ par champ, dans un monde sans retard ni état caché. |
| T-B03b | Événements de t à retard nul | Présents dans S_true(t) et dans S_pub(t). |
| T-B03c | Déroulés | Identiques bit à bit depuis S_true et depuis S_pub, dans le monde de T-B03, sous mêmes clés. |
| T-B03d | Action | Appliquée une fois, avant t0 + 1 (journal d'application). |
| T-B04 | Décisions de l'opérateur | Retard nul pour les placements et les débuts de transport et de nettoyage. |
| T-B05 | Effet des actions selon l'état caché | Effet nul en régime normal, positif en régime lent (1 000 tirages appariés). |
| T-B06 | Dérive de θ | Marche aléatoire de variance déclarée. |
| T-B07 | G_alt-v2 indépendant | Aucun code partagé hors numpy ; marges reproduites à 10 % près sur 5 statistiques déclarées. |
| T-B08 | L4-v2 exact | Énumération et forward-backward indépendant, écart ≤ 1e-9. |
| T-B09 | L4-N-v2 | Identité bit à bit dans un monde sans retard. |
| T-B10 | Séparation TUNE / CONF | CONF n'est générée qu'après le gel de conception, ce que vérifient l'horodatage du registre et l'empreinte du gel. |
| T-B11 | Fichiers gelés | G0 et F1 de HOWM-1, ainsi que tous les résultats livrés, sont inchangés (hash). |

## Plan de calcul (proposé, non autorisé à la dépense)

CPU, 0 €, registre `BUDGET_LEDGER_HOWM2_B`.

| Lot | Contenu | Plafond (s) |
|---|---|---:|
| B.SETUP | Consignation, code v2, G_alt-v2, tests T-B01 à T-B11 | 1 200 |
| B.ITER × 3 | Par itération, sur TUNE : génération, échelle, filtre, décision | 3 × 2 400 |
| B.CONF | Gel de conception, génération de CONF, campagne unique | 2 400 |
| B.REST | Gel G0-v2 (si confirmation réussie), rapport, paquet, reçu | 600 |
| **Total** | | **11 400** |

**Enveloppe.** Le total est conservé à 11 400 s. Les itérations passent de 3 000 à 2 400 s, au
profit de la confirmation séparée.
