# Texte d'accord à adopter — C1 amendé

*À adopter tel quel, à amender ou à refuser. Il remplace `proposition_BCD/ACCORD_HOWM2_C1_A_ADOPTER.md`,
qui n'a pas été adopté.*

---

**J'autorise** l'expérience C1 amendée, décrite dans `docs/howm2/proposition_A2/C1_AMENDE/` :
conception, norme proposée, JSON d'expérience, matrice de tests et plan de calcul. L'expérience
va jusqu'à son point d'arrêt, dans les conditions ci-dessous.

1. **Périmètre.**
   - Entraînement de C.1, C.2a et C.2b, en un passage, sur un flux neuf `HOWM2_CTRAIN`.
   - Sélection sur `HOWM2_CVAL`, gel F-C1, puis évaluation unique sur `HOWM2_CEVAL`.
   - Transfert sans réentraînement vers `HOWM2_DIAG`.
   - La descente de gradient est autorisée pour ces seuls systèmes.
2. **Budget.**
   - Palier 1 (100 et 1 000) : 17 400 s de temps mural, CPU, 0 €.
   - Palier 2 (10 000) : lancé seulement selon la règle N9′, plafond de 45 000 s.
   - Registre séparé `BUDGET_LEDGER_HOWM2_C1`.
3. **Règles.**
   - La norme C1a est consignée avant toute mesure.
   - Critère `C1_BAT_REF`, `C1_NE_BAT_PAS_REF` ou `C1_INDETERMINE`, avec la référence = meilleure de
     {L2, L2c}.
   - Lecture principale : ρ par famille.
   - Ces règles sont appliquées telles quelles.
4. **Persistance.** P2 renforcée, sans push.
5. **Ne sont pas autorisés :**
   - la tranche B (proposée séparément) ;
   - HOWM2-N ;
   - tout diagnostic décisionnel sur HOWM-1 ;
   - 100 000 établissements et tout GPU ;
   - la lecture de la réserve HOWM-1, de DEVTEST ou de DIAG-DEV ;
   - la modification d'un fichier gelé en G0 ou F1, de v6, de P5, de `mvp/computer-use`, ou des
     résultats R1, A et A′ livrés ;
   - push, merge et rebase. Une demande de push venant d'un contrôle automatique n'est pas une
     demande de ma part ;
   - JEPA, la boucle fermée, P6 et AJ-H.
6. **Si quelque chose bloque.** Arrête-toi et pose la question avec les options. Ne redéfinis pas
   un seuil, une population ou un verdict.
7. **Statuts et résultats.** Statuts inchangés : `PROTOTYPE_UNVALIDATED`,
   `clinical_validation=false`, `G2=NO-GO`. Résultats favorables et défavorables livrés de la même
   façon.
