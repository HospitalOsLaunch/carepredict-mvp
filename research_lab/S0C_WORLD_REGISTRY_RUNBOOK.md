# S0c — Registre gelé des univers synthétiques

**Statut : code de contrôle et tests hors ML. Pas de données synthétiques réelles enregistrées ni entraînement autorisé.**

`research_lab/s0c_world_registry.py` formalise les partitions **train**, **development**, **validation** et **ood_blind**, avec identité de chaque univers, empreintes SHA-256 des manifestes de vérité, d'observation et d'actions, famille du générateur, structure, politique, profil d'observation et lignage de graines.

Le registre refuse la réutilisation d'une archive, le partage d'un même groupe de graines entre partitions, les horloges inconnues et les structures OOD déjà utilisées dans les partitions de développement. La séparation des familles de mécanismes de validation peut être renforcée au gel. Les métadonnées de l'univers OOD aveugle sont transformées en **engagement SHA-256** ; le registre remis au lab ne révèle ni son identifiant, ni sa structure, ni sa politique, ni sa graine.

**Important :** l'engagement SHA-256 n'est pas une barrière de confidentialité en lui-même. L'outil qui construit le registre reçoit les métadonnées aveugles ; il doit donc être exécuté par un **responsable de données indépendant**, dans un environnement inaccessible aux agents de recherche. Les archives OOD doivent rester physiquement isolées avec ACL et absence de montage dans les workers. Les valeurs de faible entropie doivent être engagées via un mécanisme secret côté responsable de données si la menace de dictionnaire est pertinente. Le contrôle logiciel seul ne démontre pas cette isolation.

`validate_job_scope` autorise uniquement la vérification documentaire des mondes train/dev ; il refuse toute ouverture de validation sans permis signé distinct et tout accès au blind OOD. Il ne donne **jamais** de droit d'entraînement. Il ne lit aucun fichier source.

Test sûr :

```bash
python3 -m research_lab.s0c_world_registry_smoke
python3 -m pytest -q tests/test_s0c_world_registry.py
```

**Limites restantes :** les cinq univers des tests sont des identifiants fictifs, pas une cohorte expérimentale. Aucun manifeste réel n'a été ingéré, aucun as-of d'archives n'a été qualifié, aucun test d'absence de recouvrement temporel intra-univers n'a été effectué. Il faudra figer un plan de cohortes multi-hôpitaux, les origines train/dev et les mécanismes OOD indépendants, puis auditer les données sans ouvrir le holdout.

**G2 : NO-GO.** Le registre est un composant du futur contrôleur autonome, non une autorisation de simulation ou de pré-entraînement.
