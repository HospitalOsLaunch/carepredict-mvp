# HOWM-2 A — Addendum 2 : validation de L4 amendée (décision HOWM-2 n° 2)

**Origine.** Décision de l'utilisateur du 16 novembre 2026 (« Amend (a) and (b) »), répondant à la
question posée après le blocage consigné au registre HOWM-2 n° 20.

Le constat est consigné dans `evidence/howm2/DIAG_PIT.json` et `LADDER_A.json` : les règles (a) et (b)
du § 4 sont contradictoires.
- **(a)** rejette aussi la loi exacte L5, parce que les PIT d'un même élément, noté à plusieurs
  origines, sont dépendants.
- **(b)** « L4 ≤ L3 » est impossible par construction, puisque L3 connaît le vrai θ.

Le présent addendum est consigné **avant** le nouveau calcul des PIT et avant tout verdict. Il
remplace A3 (a) et (b) de la note ; (c) est inchangé et a déjà réussi.

- **(a′) Calibration.**
  - PIT randomisé de L4 à H24, **un seul par élément**, pris à sa première origine de notation.
  - Le seuil reste D ≤ max(0,02 ; 1,63/√n).
  - La famille passe (a′) si L4 passe.
  - L5, calculé de la même façon, est rapporté comme **témoin positif**. Si L5 échoue aussi, la
    limite du test est signalée, sans changer la règle.
- **(b′) Ordre.** Une famille est en violation si l'intervalle à 95 % de L4 − L5 est entièrement
  < 0, à un horizon quelconque. La condition « L4 ≤ L3 » est supprimée.
- **Exclusions.** Une famille qui échoue à (a′), (b′) ou (c) sort du critère, comme prévu en A3.

Le reste de la note est inchangé : M_pub, δ_id = 0,02, libellés de verdict, état caché, décision et
puissance.
