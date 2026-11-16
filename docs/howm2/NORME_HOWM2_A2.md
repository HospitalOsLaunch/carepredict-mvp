# NORME HOWM2-A′ — L'état présent comme état caché

**Décision n° 3** (`docs/howm2/HOWM2_DECISION_3.json`) ; programme `docs/howm2/inputs/PROGRAMME_HOWM2_A2.md`
(sha256 b16000d9…475092). Consignée **avant toute mesure** de A′. Les §§ 2 à 4 du programme sont
repris tels quels ; l'addendum A2-1, consigné avec cette norme, fixe les choix que le programme ne
fixe pas.

Statuts inchangés : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. Aucun
entraînement, aucune descente de gradient. Ni la réserve HOWM-1, ni DEVTEST, ni DIAG-DEV ne sont
lus. Aucun fichier gelé (G0, F1), ni v6, P5, `mvp/computer-use`, ni les résultats R1 et A livrés ne
sont modifiés ; le code nouveau est dans `src/hospitalos/howm2/`. Aucun push, merge ni rebase.

## N1. Définitions

Celles du § 2 du programme : S_pub(t), S_true(t), E_pend(t), L4-N, L5-N, κ, L2c.

## N2. Validation de L4-N, dans cet ordre, avant tout usage

- **(N-c) Identité.** Sur un monde de test où tous les retards sont nuls, L4-N = L4 à l'octet près.
  Test automatisé.
- **(N-o) Ordre.** Sur les instants de décision, la NLL de l'état vrai sous L4-N doit être meilleure
  que sous l'état public seul (masse ponctuelle sur S_pub), avec un intervalle à 95 % hors de zéro.
- **(N-a) Calibration**, règle de l'addendum 2 :
  - par type d'événement en attente, on prend le nombre d'événements en attente à t ;
  - un PIT randomisé par instant ;
  - seuil D ≤ max(0,02 ; 1,63/√n) ;
  - L5-N sert de témoin positif ; un type où L5-N échoue aussi est signalé comme limite du test.

**Conduite.**
- Si (N-c) ou (N-o) échoue, arrêt et question.
- Si (N-a) échoue pour un type, ce type est rapporté et signalé dans chaque verdict concerné, puis
  le travail continue.

## N3. Mesures et verdicts

**A2.DEC.**
- Instants : 48 VAL (ceux de A) et 48 neufs (`HOWM2_REF` 0 à 11, jour 5, à 07, 11, 15 et 19 h).
- Dispositif de A.DEC, inchangé.
- Systèmes : habituel, règle renforcée, L4, **L4-N**, C_param, C_pub_snap, C_full, oracle.
- marge_N = U(règle) − U(L4-N) sur les 96 instants, bootstrap par grappes d'établissement,
  B = 2 000.

| Verdict | Condition |
|---|---|
| `NOWCAST_MARGE_GE_15` | borne basse de l'IC à 95 % ≥ 15 |
| `NOWCAST_MARGE_LT_15` | borne haute < 15 |
| `NOWCAST_INDETERMINE` | sinon |

- Rapportés aussi :
  - marge_N sur VAL seul et sur les instants neufs seuls ;
  - κ avec son IC ;
  - L4-N contre L4, apparié ;
  - tirages rejetés par l'opérateur.
- Diagnostic secondaire pré-déclaré, sans effet sur le verdict : sélection par U minimal pur pour
  L4, L4-N et C_full.

**A2.COV.**
- Cibles, origines et clés de `DIAG_COVERAGE.json`, avec trois départs : public, L4-N, vrai.
- Rapportés à 1, 6 et 24 h : couverture à 50 % et 90 %, couverture hors intervalles dégénérés, KS du
  PIT randomisé, part de l'écart récupérée.
- Mesure descriptive seulement.

**A2.L2C.**
- Sur les 200 `HOWM2_REF`, avec le protocole de score de A : tableau L0, L1, L2, L2c, L3, L4, L5.
- M_pub recalculé avec la meilleure de {L2, L2c}, choix refait à chaque réplique.
- ρ_f par famille.
- Signalement si la borne basse de M_pub est < 0,02 à H6 ou à H24.
- Le verdict `HOWM1_DISCRIMINANT` de A n'est pas modifié.

## N4. Budget (lots A2.*, plafonds fixés avant la première mesure)

3 600 s de temps mural, CPU, 0 €, dans `BUDGET_LEDGER_HOWM2`, enveloppe séparée de celle de A.
Plafonds par commande : 540 s, et 120 s par commande de test.

| Lot | Plafond (s) |
|---|---:|
| A2.FACTS | 60 |
| A2.TEST | 400 |
| A2.VALID | 600 |
| A2.DEC | 900 |
| A2.COV | 300 |
| A2.L2C | 600 |
| A2.REST | 400 |
| Total des plafonds | 3 260 |

Si un dépassement est projeté : arrêt et question. Aucun seuil, aucune population et aucun verdict
n'est redéfini.

## N5. Point d'arrêt

Verdicts, rapport `RAPPORT_HOWM2_A2.md`, preuves, paquet P2 et reçu de restauration. Ensuite, une
seule proposition bornée (§ 5 et § 6 du programme), rédigée et non exécutée.
