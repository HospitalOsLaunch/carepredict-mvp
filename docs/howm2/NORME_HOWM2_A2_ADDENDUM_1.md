# NORME HOWM2-A′ — Addendum A2-1 (choix de construction, consignés avant toute mesure)

Le programme ne fixe pas les choix ci-dessous. Ils sont consignés ici **avant** les mesures
qu'ils régissent. Le code correspondant est `src/hospitalos/howm2/nowcast.py`.

## 1. Constat préalable (FACTS_CHECK_A2.json, registre n° 33)

**Peu d'événements en attente.** Aux 96 instants de décision, les événements en attente qui
modifient l'état sont peu nombreux : environ 1,3 par instant en tout. Les soins dus (`care_due`)
ne changent pas l'état.

| Type | Par instant |
|---|---:|
| authorised | 0,23 |
| cleaning_start | 0,19 |
| ready | 0,18 |
| cleaning_done | 0,18 |
| placed | 0,13 |
| departure | 0,11 |
| transport_done | 0,10 |
| bed_dirty | 0,09 |
| request_arrival | 0,07 |
| transport_start | 0,03 |
| transport_accepted | 0,03 |

**E_pend n'est pas la seule différence entre S_pub et S_true.** Le § 2 du programme l'affirme ; ce
n'est pas exact. L'état vrai d'un instant est cloné **avant** le pas t0, alors que S_pub contient
déjà les événements de t0 publiés avec un retard nul. Par instant, cela représente :

| Événement déjà public mais pas encore vrai | Par instant |
|---|---:|
| Demandes de transport habituelles | 0,94 |
| Plan habituel | 0,52 |
| Offres de renfort | 0,38 |

L4-N **ne modifie pas** ces différences : il part de S_pub, comme le prescrit le programme. Elles
sont rapportées comme une part de l'écart avec C_full qui n'est **pas** de l'état présent masqué.

## 2. Construction de L4-N (§ 2 du programme)

1. **Monde.** On tire (θ, mécanisme, régime à τ, retard moyen θ_lag) dans la postérieure de L4,
   **inchangée** : le code de A `sample_world` et la même graine. La postérieure du retard est
   `Ladder.lag_post` : loi floor(Exp(θ_lag)), avec la troncature des paires récentes, inférée des
   paires (event_min, avail_min) publiées.
2. **Éléments.** Ce sont les éléments publics en cours à t :
   - séjour non autorisé ;
   - séjour autorisé mais pas prêt ;
   - transport demandé non accepté ;
   - transport en cours ;
   - nettoyage en cours ;
   - offre du pool non confirmée.
3. **Tirage de E.** Pour chaque élément, on tire l'instant E de son événement de fin selon la loi du
   générateur sachant le début de l'étape (méthodes de `TruthProvider`, même convention de
   conditionnement que `refresh_private`). E est accepté avec la probabilité d'être encore
   non publié à t :
   - 1 si E ≥ t0 ;
   - P(retard > 15·(t0 − E)) = exp(−(15k + 1)/θ_lag) si E < t0.
4. **Échantillonnage par rejet.**
   - Tirages clés (`"nowcast"`, tentative a), au plus 64 tentatives. Au-delà, l'élément est déclaré
     non en attente, et ce repli est compté.
   - Les ticks passés dont la probabilité d'attente est < 10⁻⁶ sont traités comme publiés : c'est la
     fenêtre K.
   - Si K = 0, aucune attente n'est possible, et L4-N renvoie S_pub **inchangé**. C'est ce qui
     garantit (N-c).
5. **Application des événements.** Les événements tirés en attente (E < t0) sont appliqués au clone
   de S_pub dans l'ordre du temps, chacun **à son propre tick**, selon la sémantique du moteur :
   - autorisation, puis tirage de la disponibilité (même règle, donc chaînes comprises) ;
   - disponibilité, puis départ pour un séjour sans transport ;
   - fin de transport, puis départ ;
   - fin de nettoyage ;
   - confirmations.

   Les préconditions sont vérifiées par le moteur. Une violation est comptée (`eng.rejected`),
   jamais corrigée.
6. **Arrivées non publiées et non révélées**, par unité et par heure passée de la fenêtre.
   - Loi exacte de l'amincissement négatif binomial (Gamma-Poisson, r = 3) : sachant n arrivées
     connues, on tire NB(r + n, p′) avec p′ = (r/μ + 1 − q)/(r/μ + 1), où q = P(retard > t − 60h).
     μ suit la formule du générateur avec le θ tiré.
   - Une arrivée est « connue » si son événement est publié ou si son placement publié la révèle.
   - Attributs (isolement, acuité, transport) : constantes du générateur.
   - L'arrivée est datée du début de son heure.
7. **Non modélisé, déclaré :**
   - les décisions de l'opérateur (placements, débuts de transport et de nettoyage) : elles ne
     sont **pas** antidatées, l'opérateur les prend à t0 depuis l'état estimé ;
   - la présence des offres : décidée par l'offre, sans effet sur l'état avant t0 ;
   - les soins dus ;
   - le régime des heures passées : celui tiré à τ pour L4-N, le vrai pour L5-N.

   E = t0 n'est pas en attente : l'événement survient au pas t0, comme dans la vérité.
8. **Déroulés.** Après l'estimation, les déroulés amorcent tous les éléments restants comme en A,
   c'est-à-dire sachant qu'ils ne sont pas survenus à t0 :
   - planificateur : `TruthProvider(s2, 201+m)` ;
   - A2.COV : `ModelProvider` B0-local, clés de R1.

**L5-N** suit la même construction avec θ, le mécanisme, θ_lag et les régimes horaires passés
vrais. Il sert de témoin positif seulement.

## 3. Validation

**(N-c).**
- Monde de test : VAL 0 avec `lag_min = 0`, donc tous les retards valent exactement 0.
- Aux 4 instants du jour 5, le test exige :
  - le moteur L4-N **est** S_pub ;
  - les U moyens des 16 candidats du planificateur L4-N sont égaux, bit à bit, à ceux de L4.

**(N-o).**
- Représentation de l'état :
  - pour chaque élément public de premier ordre (§ 2.2), un indicateur « en attente » ;
  - pour chaque (unité, heure passée de la fenêtre), le nombre d'arrivées non publiées et non
    révélées.
- La vérité vient des observations : event_min < t < avail_min.
- La prédiction de L4-N vient de S = 64 tirages par instant, avec lissage :
  - indicateurs : p̂ = (k + ½)/(S + 1) ;
  - comptes : p̂(c) = (n_c + ½)/(S + ½·(C + 1)) sur 0..C, où C est le plus grand compte observé ou
    tiré.
- La masse ponctuelle sur S_pub donne une NLL **infinie** à tout instant qui a au moins un
  événement en attente. Le test littéral est donc **dégénéré** : il réussit dès que de tels
  instants existent. Il est calculé et rapporté tel quel.
- **Compagnon pré-déclaré, plus strict : (N-o′).** On calcule la même différence en **score de
  Brier** (fini et propre), avec la même règle d'IC.
  - Si (N-o′) échoue, je m'arrête et je pose la question, comme pour un échec de (N-o).
  - (N-o′) ne remplace pas (N-o) ; il s'y ajoute.
- IC : bootstrap par grappes d'établissement, B = 2 000, graine `key("HOWM2", "A2", "bootstrap") mod 2^31`.

**(N-a).**
- Types : auth, ready, conf_transport, conf_offer, transport, cleaning, arrival.
- Par instant, on compare le compte vrai des événements en attente du type, chaînes comprises, à la
  distribution des comptes sous L4-N (S = 64 tirages).
- PIT randomisé : F(y⁻) + U·(F(y) − F(y⁻)), avec U clé.
- Instants : les 96 instants de décision ; seuil max(0,02 ; 1,63/√96).
- L5-N est calculé de la même façon.

## 4. A2.DEC

- **Planificateur L4.** Code et graines de A. Sur VAL, sa valeur doit reproduire `DECISION_A.json` ;
  c'est contrôlé.
- **Planificateur L4-N.** Mêmes tirages de monde (appariement), estimation de l'état de clés r =
  201+m, puis mêmes déroulés que L4 depuis l'état estimé.
- **Instants neufs.**
  - U d'évaluation, oracle, C_full, C_param et C_pub_snap : `controllers.evaluate_instant`
    (HOWM-1, inchangé), sur l'épisode avec `keep_instants`.
  - Règle : `strengthened_rule`.
- **Instants VAL.** On réutilise le précontrôle. Les U moyens de choix de C_full, nécessaires au
  diagnostic U minimal, sont recalculés avec `CHOICE_R`.
- **U minimal pur.** argmin des U moyens ; en cas d'égalité, le plus petit indice.
- **κ** = moyenne[U(L4) − U(L4-N)] / moyenne[U(L4) − U(C_full)]. L'IC est obtenu par le rapport
  recalculé dans chaque réplique, et rapporté même si le dénominateur est petit.
- **Bootstrap.** 24 grappes (12 VAL et 12 REF), B = 2 000, graine `key("HOWM2", "A2", "bootstrap")`.

## 5. A2.COV

Mêmes origines, cibles, M = 16 et clés que `DIAG_COVERAGE.json`. Le départ L4-N du déroulé j part
de l'estimation du tirage de monde j (graine clé par instant), avec les clés d'estimation r = 301+j.

Part récupérée = (x_N − x_pub)/(x_vrai − x_pub), pour la couverture à 90 % et à 50 % et pour le KS
du PIT.

## 6. A2.L2C

- **Sous-familles internes.** Confirmation de transport (début `transport_requested`) et
  confirmation d'offre du pool (début `offer_requested`, source pool).
- **Ajustement.** Base, profil horaire (`fit_hazard`) et intercept local, ajustés sur TRAIN 0–31.
- **Fenêtre de L2c.** Celle de L2 (tout le passé public), à laquelle s'ajoutent les offres du
  pool.
- **τ des deux sous-familles.** Critère de R1 : log-score prédictif des 24 h suivantes, origines
  TRAIN 0–31 telles que (H − 24) % 12 = 0, grille `TAU_GRID`. Le critère est appliqué à chaque
  sous-famille sur ses propres items, avec la fenêtre de L2c. Les autres familles et leurs τ sont
  ceux de L2, inchangés.
- **Score.** Les items de confirmation sont répartis par type de référence, puis réunis au score
  de la famille « confirmation ».
- **M_pub.**
  - Familles du critère final de A : ready, confirmation, présence, arrivées, soins.
  - Meilleure de {L2, L2c}, choisie dans chaque réplique.
  - Graine du bootstrap de A.
- **ρ_f** = (L_meilleure − L4) / (L2 − L4) par famille : c'est la part de l'écart de A qui reste à
  capter avec la référence corrigée. C'est mon interprétation de la formulation du programme ; les
  écarts absolus sont rapportés aussi.
