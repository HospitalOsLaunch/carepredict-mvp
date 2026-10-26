# Variante v2 : décision nécessaire sur la reprise après activation d’un modèle

État : implémentation suspendue conformément à la consigne de signaler dans la PR
tout conflit entre le parcours demandé et le code existant.

## Conflit constaté

Le parcours demandé comporte ces étapes : basculer le portail en v2, constater
l’échec du script et la reprise humaine, activer Claude dans les paramètres, puis
voir la reprise. Si cette dernière étape désigne **un nouvel envoi sur la même
tâche**, elle est incompatible avec la reprise actuellement autorisée.

Dans `services/admissions_agent/router.py`, `Router.handle` appelle
`api.begin_write` **avant** `_run`, y compris pour le playbook. Un sélecteur absent
peut donc faire échouer le script alors que l’autorisation d’écriture a déjà été
enregistrée, même si aucun formulaire n’a été envoyé.

Dans `services/admissions_smr/api/routes_agent.py` :

- `begin_write` conserve `write_started_at` et le jeton de réservation ;
- `task_out` expose `reconcile_only` dès que `write_started_at` est renseigné ;
- `retry` remet la tâche en file sans effacer ce marqueur ;
- `begin_write` refuse une nouvelle réservation pour cette écriture.

Dans `Router.handle`, une tâche `reconcile_only` est relue puis terminée, ou remise
en reprise humaine si le résultat attendu n’est pas présent. Aucun moteur ne la
réécrit. Le test existant
`test_model_engines_are_refused_without_data_permission_or_budget`, dans
`services/admissions_agent/tests/test_agent_e2e.py`, vérifie explicitement cette
restriction après activation tardive du modèle et relance.

La relecture d’un état apparemment inchangé ne prouve pas qu’aucune écriture
différée n’a été soumise. Effacer le marqueur après cet échec affaiblirait donc
le garde-fou demandé ; cette solution est exclue.

## Ce qui reste compatible avec les garde-fous actuels

Si le modèle est autorisé **avant la première exécution**, le routeur peut passer
du script au modèle pendant la même réservation, après une relecture complète
confirmant un état inchangé. Une écriture inattendue ou une relecture impossible
arrête toujours le parcours. Ce relais ne permet pas de reprendre ultérieurement
une tâche déjà passée en vérification humaine.

## Options à arbitrer

1. **Conserver intégralement la reprise actuelle.** Montrer l’échec avec le script
   seul sur un premier dossier fictif, puis activer Claude et donner l’accord sur
   un second dossier. Celui-ci montre le parcours « script échec → modèle succès ».
   Le premier reste en reprise humaine. Cette option change le scénario de démo,
   pas les garanties d’écriture.
2. **Permettre la reprise du même dossier uniquement si aucune action d’écriture
   n’a pu commencer.** Concevoir un contrôle préalable strictement en lecture
   seule, avant l’autorisation d’écriture. Il doit prouver l’absence de toute
   interaction susceptible d’écrire, résister aux changements du DOM entre le
   contrôle et l’action et conserver les marqueurs dès la première action à
   risque. Cette évolution exige ses propres tests de courses et de réservation ;
   elle ne consiste pas à déplacer le marqueur juste avant le bouton d’envoi,
   car un portail peut enregistrer dès la saisie.

La première option est recommandée pour cette démonstration : elle rend visible
la valeur du relais sans modifier le protocole de reprise. Aucune option n’est
appliquée sans arbitrage.

## Portée de cette PR

Cette PR contient uniquement ce diagnostic. Elle ne livre pas la variante v2,
le nouvel affichage des moteurs ni l’adaptation de `demo_check.py`. Aucun fichier
de migration, politique par défaut, mécanisme de gel ou calcul North Star n’est
modifié. Aucun vrai modèle n’est appelé.

La validation de la branche existante ne constitue pas une validation du scénario
v2 demandé : celui-ci reste à implémenter après l’arbitrage.
