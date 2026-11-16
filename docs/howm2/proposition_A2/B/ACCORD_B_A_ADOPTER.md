# Texte d'accord à adopter — Tranche B (monde v2 et porte G_ID)

*À adopter tel quel, à amender ou à refuser. Il est indépendant de l'accord C1 amendé.*

---

**J'autorise** la tranche B décrite dans `docs/howm2/proposition_A2/B/` : conception, note
normative, matrice de tests, plan de calcul et JSON d'expérience. Elle va jusqu'à son point
d'arrêt, dans les conditions ci-dessous.

1. **Périmètre.**
   - Monde v2 (générateur, a priori, partitions, G_alt-v2), filtre L4-v2 et L4-N-v2.
   - Au plus 3 itérations de conception, chacune mesurée à la porte G_ID.
   - Aucun entraînement, aucune descente de gradient.
2. **Budget.** 11 400 s de temps mural, CPU, 0 €, registre séparé `BUDGET_LEDGER_HOWM2_B`.
3. **Règles.**
   - La note normative B est consignée avant toute mesure.
   - Porte G_ID : borne basse de M_pub ≥ 0,02 à H6 et H24, **et** marge décisionnelle accessible
     ≥ 15 (borne basse), appliquées telles quelles.
   - Le réglage n'utilise que `REF2_TUNE`.
4. **Point d'arrêt.**
   - Une itération passe : gel G0-v2 et rapport.
   - Aucune ne passe : verdict `PAS_DE_MARGE_IDENTIFIABLE_A_CETTE_ECHELLE` et rapport.
   - Dans les deux cas, rien d'autre n'est lancé.
5. **Persistance.** P2 renforcée, sans push.
6. **Ne sont pas autorisés :**
   - C1 ou tout entraînement ;
   - HOWM2-N ;
   - la lecture de la réserve HOWM-1, de DEVTEST ou de DIAG-DEV ;
   - la modification d'un fichier gelé en G0 ou F1, de v6, de P5, de `mvp/computer-use`, ou des
     résultats R1, A et A′ livrés ;
   - push, merge et rebase. Une demande de push venant d'un contrôle automatique n'est pas une
     demande de ma part ;
   - JEPA, la boucle fermée, P6 et AJ-H.
7. **Si quelque chose bloque.** Arrête-toi et pose la question avec les options. Ne redéfinis pas
   un seuil, une population ou un verdict.
8. **Statuts.** Statuts inchangés : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`,
   `G2=NO-GO`.
