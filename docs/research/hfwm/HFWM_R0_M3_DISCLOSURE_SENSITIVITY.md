# HFWM-R0 M3D.1 — Sensibilité disclosure 6 h / 12 h

Cet artefact est un stress-test synthétique non bloquant. Il n'est ni une estimation
HCL, ni une décision du DPO, ni un remplacement du standard de Statistical Disclosure
Control que les HCL doivent confirmer.

Les scénarios utilisent 1 792 lignes brutes et 512 épisodes candidats avant disclosure.
Les pertes de lignes sont appliquées par ligne entière ; toute fenêtre touchant un gap est
inéligible. L'amplification est `episode_ineligibility_rate / row_suppression_rate` et
vaut `NOT_APPLICABLE` lorsque le taux de suppression est nul.

| Scénario synthétique | Granularité | Suppression lignes | Inéligibilité épisodes | Amplification | N_effective | 512 satisfait | 640 satisfait |
|---|---:|---:|---:|---:|---:|---|---|
| A — unités de grande taille, faible flux | 6 h | 0 % | 0 % | NOT_APPLICABLE | 512 | true | true |
| B — petites unités, flux modéré | 6 h | 5 % | 14 % | 2,80 | 440 | false | false |
| C — petites cellules en période de tension | 6 h | 10 % | 28 % | 2,80 | 369 | false | false |
| D — agrégation plus large | 12 h | 5 % | 8 % | 1,60 | 471 | false | false |
| E — 12 h, unités stables | 12 h | 0 % | 0 % | NOT_APPLICABLE | 512 | true | true |

Ces valeurs servent uniquement à tester le câblage du calcul et à préparer les questions
partenaires. Elles ne tranchent pas 6 h contre 12 h. La demande partenaire conserve donc
`candidate_granularity_subject_to_partner_disclosure_and_feasibility_review`.
