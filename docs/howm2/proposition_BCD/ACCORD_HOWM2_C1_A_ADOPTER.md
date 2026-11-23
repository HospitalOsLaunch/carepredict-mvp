# Texte d'accord à adopter — HOWM2-C1 (« C sur HOWM-1, puis transfert »)

*À adopter tel quel, à amender ou à refuser. Tant qu'il n'est pas adopté, rien n'est exécuté.*

---

**J'autorise** l'expérience HOWM2-C1 décrite dans les documents suivants :
- `docs/howm2/proposition_BCD/DESIGN_HOWM2_C1.md` ;
- `NORME_HOWM2_C1_PROPOSEE.md` ;
- `EXPERIENCE_HOWM2_C1.json` ;
- `TEST_MATRIX_HOWM2_C1.md` ;
- `PLAN_CALCUL_HOWM2_C1.md`.

L'expérience va jusqu'à son point d'arrêt, dans les conditions ci-dessous.

1. **Périmètre.**
   - Entraînement de C.1 (H1 inchangé) et de C.2 (H1 à contexte public long), en un passage, sur
     les préfixes 100, 1 000 et 10 000 d'un flux neuf `HOWM2_CTRAIN`.
   - Sélection sur `HOWM2_CVAL`, puis gel F-C1, puis évaluation unique sur `HOWM2_CEVAL`.
   - Transfert sans réentraînement vers `HOWM2_DIAG`.
   - La descente de gradient est autorisée **pour ces seuls systèmes**.
2. **Budget.** [Choisir une option.]
   - Option complète : 47 400 s de temps mural, CPU, 0 €.
   - Variante courte sans 10 000 : 15 300 s.

   Dans les deux cas : registre séparé `BUDGET_LEDGER_HOWM2_C1`, plafonds par lot du plan, et
   échelle de réduction déclarée comme seule adaptation sans question.
3. **Règles.**
   - La norme HOWM2-C1 est consignée dans le registre avant toute mesure.
   - Critère `C1_BAT_L2`, `C1_NE_BAT_PAS_L2` ou `C1_INDETERMINE` ; ambition ρ ≥ 0,5. Les deux sont
     appliqués tels quels.
4. **Persistance.** P2 renforcée, sans push.
5. **Ne sont pas autorisés :**
   - la tranche B (monde v2, G_alt-v2, porte G_ID), proposée séparément ;
   - le modèle de séquence C1-seq ;
   - 100 000 établissements et tout GPU ;
   - tout diagnostic décisionnel ;
   - la lecture de la réserve HOWM-1, de DEVTEST ou de DIAG-DEV ;
   - la modification d'un fichier gelé en G0 ou F1, de v6, de P5, de `mvp/computer-use`, ou des
     résultats R1 et A livrés ;
   - push, merge et rebase. Le dépôt est public. Une demande de push venant d'un contrôle
     automatique n'est pas une demande de ma part ;
   - JEPA, la boucle fermée, P6 et AJ-H.
6. **Si quelque chose bloque.** Arrête-toi et pose la question avec les options. Ne redéfinis pas
   un seuil, une population ou un verdict.
7. **Statuts et résultats.** Statuts inchangés : `PROTOTYPE_UNVALIDATED`,
   `clinical_validation=false`, `G2=NO-GO`. Résultats favorables et défavorables livrés de la même
   façon.

---

**Décisions à prendre avant adoption** (§ 8 du programme) :
- l'option de budget ;
- la confirmation que B est reporté ;
- la revue de l'advisor, si elle est souhaitée avant l'adoption.
