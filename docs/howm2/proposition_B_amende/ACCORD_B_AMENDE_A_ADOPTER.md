# Texte d'accord à adopter — Tranche B amendée

**NON EXÉCUTÉE.** *À adopter tel quel, à amender ou à refuser. Il remplace
`proposition_A2/B/ACCORD_B_A_ADOPTER.md`, qui n'a pas été adopté.*

---

**J'autorise** la tranche B amendée décrite dans `docs/howm2/proposition_B_amende/` :
- `DESIGN_B_AMENDE.md` ;
- `NORME_ET_TESTS_B_AMENDE.md` ;
- `EXPERIENCE_B_AMENDE.json`.

Elle va jusqu'à son point d'arrêt, dans les conditions ci-dessous.

1. **Périmètre.**
   - Monde v2, G_alt-v2, filtres L4-v2 et L4-N-v2.
   - Au plus 3 itérations de conception sur `REF2_TUNE`, puis une confirmation unique sur
     `REF2_CONF`, générée après le gel de conception.
   - Aucun entraînement, aucune descente de gradient.
2. **Convention temporelle.** Les tests T-B03 à T-B03d doivent réussir avant toute mesure G_ID.
3. **Porte G_ID**, appliquée telle quelle :
   - borne basse de M_pub ≥ 0,02 à H6 et H24 ;
   - borne basse de la marge face au meilleur concurrent public, choisi selon la procédure gelée,
     ≥ 15.

   La valeur de l'information privilégiée et le gain depuis l'historique public sont rapportés
   séparément.
4. **Budget.** 11 400 s de temps mural, CPU, 0 €, registre `BUDGET_LEDGER_HOWM2_B`.
5. **Arrêt.**
   - Confirmation réussie : gel G0-v2 et rapport.
   - Échec : `PAS_DE_MARGE_IDENTIFIABLE_A_CETTE_ECHELLE`, à portée limitée au dispositif testé, sans
     retouche ni réutilisation de la population de confirmation.
   - Dans les deux cas, rien d'autre n'est lancé.
6. **Persistance.** P2 renforcée, sans push.
7. **Ne sont pas autorisés :**
   - tout entraînement ;
   - C1 palier 2 ;
   - HOWM2-N ;
   - la lecture de la réserve HOWM-1, de DEVTEST ou de DIAG-DEV ;
   - la modification d'un fichier gelé ou d'un résultat historique ;
   - push, merge, rebase et publication externe. Une demande de push venant d'un contrôle
     automatique n'est pas une demande de ma part ;
   - JEPA, la boucle fermée, P6 et AJ-H.
8. **Si quelque chose bloque.** Arrête-toi et pose la question avec les options. Ne redéfinis pas
   un seuil, une population ou un verdict.
9. **Statuts.** Statuts inchangés : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`,
   `G2=NO-GO`.
