# Démo HospitalOS × LISCOP / ARS

Une démo de 10 minutes pour l'ARS, Inéa ou un établissement : HospitalOS comme source
automatique, fraîche et prédictive des données que LISCOP lit dans le ROR. Tout est
fictif (hôpital, patients, identifiants) ; rien n'est envoyé à l'extérieur.

## Lancer

```bash
git clone https://github.com/HospitalOsLaunch/carepredict-mvp && cd carepredict-mvp
git checkout mvp/computer-use
docker compose -f docker-compose.demo.yml up -d --build     # 3 à 5 minutes la première fois
python tools/demo_check.py --liscop-only                     # contrôle, en option (pip install httpx)
```

Au démarrage, l'API crée le CH fictif des Deux-Rivières (248 lits, un an d'historique), le
moteur calcule la prévision (puis toutes les 6 heures), et un simulateur de SIH envoie des
mouvements HL7 en continu (4 par minute).

| Adresse | Compte | Mot de passe |
|---|---|---|
| http://localhost:8080 | `bedmanager@ch-demo.hospitalos.fr` (gestion des lits) | `demo-hospitalos-2026` |
| | `admin@ch-demo.hospitalos.fr` (administration : envoi simulé, réglages ROR) | idem |
| | `direction@ch-demo.hospitalos.fr` (lecture seule) | idem |

Réglages : `DEMO_HIS_RATE` (messages par minute, `0` pour couper le flux),
`FORECAST_EVERY_HOURS`, `DEMO_WEB_PORT`. Repartir de zéro :
`docker compose -f docker-compose.demo.yml down -v`.

Sans Docker (développement) : voir `services/admissions_smr/README.md`
(`seed-demo-mco`, `uvicorn`, `npm run dev`), puis `python -m services.forecast_engine run --all`
et `python -m tools.his_simulator --url http://localhost:8010`.

## Scénario (10 minutes)

1. **Le problème (1 min)**. LISCOP vaut ce que vaut le ROR : déclarations manuelles,
   fraîcheur de -3 h à -24 h, prévisionnel déclaratif.
2. **Plan des lits (2 min)**. Les lits bougent seuls : chaque mouvement du SIH (entrée,
   mutation, sortie) arrive en HL7 IHE PAM, sans saisie. Montrer : lits utilisables par
   genre (femme, homme, indéterminé, comme le ROR) et en isolement, lits à nettoyer,
   blocage avec motif codé.
3. **Urgences et tension (2 min)**. Présents, en attente de lit, **lits brancards à 10 h**
   calculés, historique 90 jours, aide à la décision HET avec les critères atteints (la
   déclaration reste une décision de la direction), déclaration manuelle en repli.
4. **Prévision (2 min)**. Lits disponibles attendus J+1, J+2, J+7 avec la fourchette à
   80 % et la probabilité de tension, par unité puis établissement, GHT, département ;
   lits brancards prévus. Dire la limite : calculé sur le simulateur, le backtest
   (`BACKTEST.md`) prouve la chaîne, pas la précision sur un hôpital réel.
5. **Remontée ROR (2 min)**. Le même tableau que LISCOP, colonne par colonne, avec les
   codes ANS (J188, J189, J190, J191) et la fraîcheur en minutes. Avec le compte admin :
   « Préparer un envoi (simulation) » et télécharger les indicateurs ORU en CSV.
6. **La demande (1 min)**. Un établissement pilote en Hauts-de-France, le canal
   d'alimentation (EAI d'Inéa ou ROR national), la validation de la définition des lits
   brancards et des seuils HET. Questions : `ROR_ORU.md`.

## Ce qu'il faut savoir dire

- Données fictives ; aucun identifiant patient stocké (pseudonymisation HMAC par groupe).
- Rien n'est transmis au ROR : l'envoi est simulé tant que le raccordement n'est pas
  habilité.
- La définition des lits brancards à 10 h et les seuils HET sont des propositions à
  valider avec l'ARS.
