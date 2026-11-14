# Correction du test indépendant, pas du produit

Le premier passage des neuf tests supplémentaires a donné sept échecs et deux réussites.
Les sept assertions erronées examinaient toutes les capacités de la fixture alors que leur
oracle portait uniquement sur U-LOAN/IDE. La fixture conserve R3, prêteur distinct U-CARDIO-SYN,
avec marge zéro : sa capacité était incluse dans les ensembles et écrasait le dictionnaire par heure.
Les vérifications sont maintenant bornées explicitement à U-LOAN/IDE. Les observations,
les règles de capacité et les assertions sur les approbations ne sont pas modifiées.
Les calculs du produit continuent à recevoir l'instantané complet.

Le fichier initial, son JUnit rouge et son journal sont conservés. Ce passage ne constitue
pas une régression de v6. Aucun code produit ni test d'auteur n'a été modifié.
