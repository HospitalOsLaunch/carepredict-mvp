# HFWM-R0 — blockers et limites d'assurance

Version de pré-enregistrement : `hfwm-r0.1`. Ce registre sépare les blockers de
construction, les blockers de revue et les limites d'assurance. Il n'invente aucun
résultat.

## P-0₀ V8 — gel après revue hostile

Verdict reviewer figé : `BLOCKERS_FOUND`. Aucun V9 n'est lancé par cette mission.
Le code HFWM peut continuer localement, mais P-0₀ V8 ne peut pas être utilisé comme
preuve normative forte tant que les findings suivants ne sont pas résolus et
re-revus :

| Finding | Classe | Conséquence |
|---|---|---|
| Gate normatif `pytest` inexécutable dans l'environnement reviewer | Reproductibilité | Résultat normatif non reproduit |
| TOCTOU entre inspection et lecture des ressources | Intégrité temporelle | Identité de ressource non garantie |
| Contrat source et objet exécuté non liés cryptographiquement | Identité | Preuve non attribuable au bon objet |
| Preuves tautologiques auto-attestées | Chaîne de preuve | Indépendance insuffisante |
| Confinement non hermétique | Runtime | Lectures/imports hors surface fermée possibles |
| Faux E2E et cardinalités ne correspondant pas au contrat | Couverture | Surface normative non exercée |
| Mutants non liés aux objets gelés | Mutation | Kill des mutants non probant |
| Budgets et stimulus incomplets | Ressources | Limites non fail-closed |
| Divergence de mesure entre harness et candidat réel | Métrologie | Observation non transférable au candidat |

## Blockers HFWM ouverts

- Le corpus P0D point-in-time, ses snapshots et son manifest de droits ne sont pas
  encore gelés ; aucun run principal n'est autorisé avant R0-D0.
- L'identité, la licence et l'exposition d'entraînement d'un checkpoint TSFM local
  compatible ne sont pas vérifiées : comparateur `NOT_EXECUTED`.
- Les données disponibles ne prouvent pas trois organisations indépendantes ni un
  établissement entier non vu : `FOUNDATION_EVIDENCE_INSUFFICIENT`.
- L'exécution réelle des actions, leur dose, timing, déviation, concurrence, support
  et facteurs de décision ne sont pas prouvés :
  `ACTION_CONDITIONING_NOT_IDENTIFIABLE`.
- HGBR/CQR reste un comparateur final gelé. Sa fuite cible/split doit être réparée
  uniquement pour intégrité et reproductibilité, sans cycle d'optimisation.

## Limites d'assurance, non blockers de construction locale

L'absence de store WORM externe, de PKI externe, de principals cryptographiques
externes, de sink invisible et d'environnement Linux certifié limite le niveau
d'assurance et peut bloquer une revue humaine finale. Elle n'interdit ni la
construction locale sur données autorisées/synthétiques, ni les tests déterministes,
ni le bake-off rétrospectif. Aucun de ces travaux ne peut compenser ou masquer cette
limite.

## Décision humaine requise ultérieurement

L'autorité humaine devra décider quels blockers doivent être levés avant un gate
comparatif, une intégration shadow ou une revue externe. Aucun statut de ce registre
ne constitue une validation, une preuve causale, une preuve Foundation ou une
autorisation d'exécution.
