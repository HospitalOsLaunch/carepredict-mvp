# HFWM-R0 — Protocole d’exécution économe

Version : `hfwm-r0.execution-protocol.v1`
Installé le : `2026-08-28`
Dépôt : `HospitalOsLaunch/carepredict-mvp`

Ce protocole gouverne les milestones suivants de cette conversation. Le rail
produit conserve le harness P-0 existant et HGBR/CQR comme fallback. Le rail
scientifique HFWM-R0 est prioritaire. Aucun échec ne déclenche automatiquement
une nouvelle version du harness.

## Règles d’exécution

1. `SINGLE_AGENT_EXECUTION` est le mode par défaut.
2. Un seul milestone peut être `IN_PROGRESS`.
3. Un milestone peut avoir au maximum deux subagents actifs et quatre subagents
   au total.
4. Une délégation exige une tâche indépendante, des fichiers disjoints, un
   artefact vérifiable et une économie probable d’au moins vingt minutes.
5. Aucun reviewer n’est lancé avant l’existence d’un candidat exécutable.
6. Un même blocker reçoit au maximum deux cycles de correction.
7. Un plan, une synthèse ou une opinion ne constituent pas un progrès.
8. Chaque milestone produit au moins un diff, un test, un artefact, un résultat
   de commande, une métrique ou un candidat explicitement tué.
9. Les logs bruts restent dans les artefacts ; ils ne sont pas recopiés dans le
   chat.
10. Les updates utilisateur contiennent uniquement le résultat obtenu, sa
    preuve, l’action en cours et le blocker éventuel.
11. Aucune `Vn+1` n’est lancée automatiquement pour contourner un échec.
12. Les statuts ou claims `P0 PASS`, `HFWM PASS`, `VALIDATED WORLD MODEL` et
    `PROVEN FOUNDATION MODEL` sont interdits.

## Discipline de milestone

- `CURRENT_MILESTONE.yaml` est la seule source locale de l’état du milestone.
- Le compteur de subagents et de cycles de correction y est tenu à jour avant
  toute délégation ou correction.
- Un changement de milestone clôt ou remplace explicitement le précédent ; deux
  milestones ne peuvent pas être actifs simultanément.
- Les modifications préexistantes ou interrompues sont préservées et
  inventoriées. Elles ne sont ni assimilées à une preuve ni exécutées sans gate.
- Les processus sains ne sont pas interrompus. Un processus orphelin ou bloqué
  n’est arrêté qu’après inspection et justification.

## Autorité et claims

Les agents peuvent produire des candidats et des preuves techniques, jamais un
PASS humain, une validation Nantes, une preuve causale, une preuve de Foundation
Model ou une autorisation d’exécution opérationnelle.
