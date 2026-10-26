# HospitalOS Admissions SMR

Pilote d'admissions et d'occupation pour les **groupes SMR privés**. Le produit
fait une chose : remplir chaque lit libérable avec le bon patient, en répondant
plus vite à l'adresseur.

- `services/admissions_smr/` : API FastAPI, autonome (aucune dépendance à torch, Dagster
  ou Feast).
- `services/admissions_web/` : application React (Vite, TypeScript, Tailwind).

## Ce que fait la V1

| Écran | Usage |
| --- | --- |
| Demandes | File priorisée des demandes. Pour chacune : sites compatibles, lits prévus jour par jour, accord en un clic à la date choisie, refus motivé, réorientation vers un autre site du groupe, brouillon de message pour l'adresseur, historique, notes. Si la demande vient d'un portail, l'état du report de la réponse par l'agent (en file, fait et relu, à reprendre à la main). |
| Lits et sorties | Lits libres prévus sur 14 jours par site et par mention ; patients présents avec probabilité de sortie sous 7 jours ; saisie du niveau de soins, des dates de sortie prévues (historisées) et des sorties. |
| Charge en soins | Minutes de soins attendues sur 14 jours par unité, face aux heures soignantes prévues : grille des journées en tension, détail jour par jour avec fourchette, saisie de la semaine type et des jours particuliers, rejeu de fiabilité. |
| Vue groupe | Occupation, demandes en attente, sorties à 7 jours et lits fermés, site par site. |
| Indicateurs pilote | North Star (journées-lits récupérées) avec intervalle, délai de réponse, parcours des demandes, motifs de refus et de perte, lits fermés par motif, fiabilité de la prévision. |
| Imports | CSV des lits, des séjours (avec niveau de soins) et des demandes ; vérification complète avant import. |
| Paramètres | Sites et lits, utilisateurs et identité fédérée, période de référence et termes du contrat (gel), priorisation, minutes de soins par niveau, agent et routage des moteurs, journal d'audit. |

Les deux propositions de valeur fortes :

1. **Prédictions** : sorties (par patient, par unité, par jour) et charge en soins
   qui en découle, comparée aux effectifs. Méthodes et fiabilité mesurée plus bas.
2. **Computer use** : un agent qui relève les demandes sur les portails
   d'orientation et y reporte les réponses, en routant chaque tâche entre un
   script, des modèles open source auto-hébergés et des modèles propriétaires
   selon la tâche, le coût et ce que chaque moteur a le droit de voir. Voir
   [`services/admissions_agent/README.md`](../admissions_agent/README.md).

Hors V1, volontairement : world model, module RH, bed management MCO, simulation.

## Lancer en local

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r services/admissions_smr/requirements-dev.txt

export ADM_DATABASE_URL=sqlite:///./admissions_demo.db
python -m services.admissions_smr.cli seed-demo          # groupe synthétique
uvicorn services.admissions_smr.main:app --port 8010      # API : http://localhost:8010/api/docs

cd services/admissions_web && npm ci && npm run dev       # http://localhost:5174
```

Le schéma est créé et mis à jour par **Alembic** au démarrage de l'API
(`python -m services.admissions_smr.cli migrate` pour le faire à part). PostgreSQL
en production, SQLite accepté en développement uniquement.

Pour voir l'agent travailler sur la démo, avec le portail fictif fourni :

```bash
uvicorn services.admissions_agent.demo_portal.app:app --port 8020
AGENT_API_EMAIL=agent@demo.hospitalos.fr AGENT_API_PASSWORD=demo-hospitalos-2026 \
AGENT_PORTAL_USERNAME=demo AGENT_PORTAL_PASSWORD=demo-portail \
  python -m services.admissions_agent once
```

Comptes de démonstration (mot de passe `demo-hospitalos-2026`, ou `ADM_DEMO_PASSWORD`) :
`admin@`, `coordination@`, `tilleuls@` (limité à un site), `direction@` (lecture),
`agent@` (compte de service) `demo.hospitalos.fr`.

Premier groupe réel :

```bash
python -m services.admissions_smr.cli init-group --name "Groupe X" \
  --admin-email admin@groupe-x.fr --admin-name "Prénom Nom"
```

Déploiement : `docker-compose.admissions.yml` (PostgreSQL + API + web derrière nginx,
agent en option avec `--profile agent`). Guide d'hébergement HDS :
[`docs/DEPLOIEMENT_HDS.md`](docs/DEPLOIEMENT_HDS.md). Projet d'AIPD :
[`docs/AIPD.md`](docs/AIPD.md).

## Rôles

| Rôle | Droits |
| --- | --- |
| `admin_groupe` | Tout, dont imports, utilisateurs, référence et contrat. |
| `coordination` | Traiter les demandes, sorties, lits ouverts. Peut être limité à un site. |
| `direction` | Lecture seule. |
| `ingestion` | Compte de service de l'agent : dépôt des demandes, file de tâches `/api/agent/*`. Aucun accès à l'interface. |

Chaque groupe est un tenant isolé ; chaque action est écrite dans le journal d'audit.

## Connexion

- **OIDC** (Pro Santé Connect ou fournisseur d'identité du groupe : Entra ID,
  Keycloak, Okta...) : flux « authorization code » avec PKCE, `state` signé, `nonce`,
  jeton d'identité vérifié contre les clés publiées (signature, émetteur, audience,
  expiration). Aucun compte n'est créé à la volée : l'administrateur crée
  l'utilisateur, la première connexion lie l'identité (par e-mail, `sub`, ou un
  identifiant professionnel comme le `SubjectNameID` RPPS de Pro Santé Connect,
  lu dans le jeton ou dans `userinfo`). Le jeton de session revient dans le
  fragment d'URL, jamais dans un journal serveur. Le rattachement par e-mail exige
  `email_verified: true` (booléen) et ne remplace jamais une identité déjà liée.
  Si `userinfo` fournit des attributs, son `sub` doit correspondre à celui du jeton.
- **Mot de passe** : désactivable pour les personnes (`ADM_PASSWORD_LOGIN=0`) ;
  les comptes de service le gardent.

| Variable | Exemple Pro Santé Connect |
| --- | --- |
| `ADM_OIDC_ISSUER` | URL de l'émetteur de l'environnement (bac à sable ou production) |
| `ADM_OIDC_CLIENT_ID`, `ADM_OIDC_CLIENT_SECRET` | fournis à l'inscription du service |
| `ADM_OIDC_REDIRECT_URI` | `https://admissions.groupe.fr/api/auth/oidc/callback` |
| `ADM_OIDC_SCOPES` | `openid scope_all` |
| `ADM_OIDC_ACR_VALUES` | `eidas2` (authentification forte) |
| `ADM_OIDC_MATCH_CLAIM` | `SubjectNameID` |
| `ADM_OIDC_AUTHORIZATION_ENDPOINT`, `..._TOKEN_ENDPOINT`, `..._JWKS_URI`, `..._USERINFO_ENDPOINT` | si la découverte automatique n'est pas utilisée |
| `ADM_FRONTEND_URL` | `https://admissions.groupe.fr` |

Les URL exactes de Pro Santé Connect dépendent de l'environnement et de
l'inscription du service auprès de l'ANS : les reprendre de la documentation
fournie à l'inscription, pas de ce fichier.

## Dépôt des demandes et agent de computer use

Toute source (agent, intégration, saisie) dépose sur `POST /api/ingest/requests`.
L'appel est idempotent sur `(source, external_ref)` : une demande déjà reçue
n'est jamais dupliquée ni modifiée. Contrat : schéma `RequestCreate` dans `/api/docs`.

L'agent tire ses tâches de `/api/agent/tasks/claim` (bail de 10 minutes, nombre
de tentatives borné, puis reprise humaine). Un accord ou un refus sur une demande
venue d'un portail crée une tâche de report si l'agent est déclaré pour le groupe.

## Données

- Seules des **références patient pseudonymisées** sont acceptées. Une valeur
  qui ressemble à un NIR est refusée, à l'import comme à la saisie. Aucun nom,
  aucune adresse, aucun contact.
- Imports en **tout ou rien** : une ligne invalide et rien n'est importé ; chaque
  erreur est listée avec sa ligne et sa colonne.
- Un import de lits ne devine jamais le motif d'une fermeture (motif « autre »
  à préciser), pour ne pas fausser l'indicateur « manque de personnel ».

Modèles CSV : `GET /api/imports/templates/{lits|sejours|demandes}`.

## Prévision des sorties

Durée de séjour modélisée par mention avec un **Kaplan-Meier discret** : les
patients encore présents sont censurés, donc les longs séjours ne sont pas
sous-représentés. Repli sur l'ensemble des mentions puis sur un risque de queue
constant quand les données manquent.

**Patients avec une date de sortie prévue** : la sortie suit la date prévue
décalée d'un **glissement mesuré** sur l'historique du groupe. Chaque
modification de la date prévue est historisée ; le glissement est calculé avec la
dernière date connue la veille de la sortie, sur au moins 30 sorties. En dessous,
un a priori prudent (60 % le jour même, le reste sur 1 à 7 jours), signalé comme
tel dans l'écran.

**Patients sans date prévue** : les équipes fixent une date quand la sortie
approche, donc un patient sans date sort moins vite que la moyenne. Un modèle
« landmark » estime le risque de sortie conditionnel à l'absence de date, par
tranche d'ancienneté, à partir de l'historique (seulement après la première date
historisée + 14 jours, pour ne pas confondre « pas de date » et « date non
saisie »). Sans ce modèle, le rejeu surestimait les sorties (biais +13 sorties
à 7 jours, fourchette juste 17 % du temps).

Pour chaque jour, le nombre de sorties suit une loi de Poisson-binomiale
calculée exactement, d'où les fourchettes et la probabilité d'avoir au moins un
lit libre. Un lit est « sûr » à partir de 80 %. Les accords et confirmations
déjà donnés sont déduits.

Rejeu sur la démo (`/api/metrics/backtest`, sorties cumulées à 7 jours, données
connues chaque matin seulement) :

| Périmètre | Erreur absolue moyenne | Réel dans la fourchette à 80 % |
| --- | --- | --- |
| Groupe (265 lits installés) | 4,1 sorties (biais −3,4) | 83 % |
| Chaque site | 2,0 à 2,8 sorties | 75 % |

Limite connue : les admissions hors outil ne sont pas anticipées ; le biais
négatif au niveau groupe montre que la prévision reste un peu prudente.

## Charge en soins

Pour chaque unité et chaque jour à venir :

```
charge = Σ patients  P(présent ce jour) × minutes(niveau de soins)
       + P(sort ce jour) × minutes(sortie)
       + entrées promises × (minutes(niveau) + minutes(entrée))
       + entrées habituelles de ce jour de la semaine, bornées par les lits libres attendus
```

- Le niveau de soins (1 à 4) est saisi par patient ; un patient non coté compte au
  niveau 2, et la part de patients cotés est affichée.
- Les minutes par niveau sont des **hypothèses de départ** (45, 90, 150, 240 ; entrée
  60, sortie 30), modifiables par groupe : à caler sur l'outil de mesure de charge
  des unités.
- Les heures soignantes viennent d'une semaine type par unité, remplacée par une
  valeur datée pour les jours particuliers (absences, renforts).
- Fourchette à 80 % par approximation normale ; probabilité de dépasser l'effectif ;
  tension : < 90 % normale, 90 à 100 % vigilance, > 100 % tension.

Rejeu sur la démo (`/api/metrics/backtest/workload`, J+0 à J+6, 8 semaines) :
erreur moyenne **8,5 %** par unité et par jour, biais +1,8 %, réel dans la
fourchette **77,5 %** du temps (sous les 80 % visés : la fourchette est un peu
étroite). Ce rejeu mesure la prévision des présences et des admissions avec les
mêmes minutes par niveau des deux côtés ; il ne dit rien de la justesse des
minutes elles-mêmes.

## North Star et intéressement

**Journées-lits récupérées** par rapport à une période de référence gelée,
calculées unité par unité (site × mention).

Deux erreurs trouvées en construisant cette mesure sur le jeu de démo, qui ne
contient aucun effet simulé :

1. **Fermetures de lits comptées comme un gain.** Dans une unité saturée,
   fermer des lits fait monter mécaniquement le taux d'occupation. Une première
   version affichait +803 journées-lits avec un intervalle excluant zéro sur des
   données sans effet. Désormais, une unité dont la capacité ouverte change entre
   la référence et la période est **exclue**, et la liste des exclusions est
   affichée.
2. **Intervalles beaucoup trop étroits.** Le recensement quotidien est
   autocorrélé sur environ une durée de séjour. Un bootstrap par blocs de 7 ou
   28 jours donnait 25 à 30 % de faux positifs au lieu de 10 %.

Méthode retenue : **fenêtres placebo**. La même comparaison avant/après est
recalculée sur l'historique antérieur à la fin de la référence, où le produit
ne peut avoir aucun effet ; l'intervalle à 80 % vaut
`estimation − moyenne(placebo) ± 1,2816 × 1,25 × écart-type(placebo)`.

Calibration sur le générateur synthétique stationnaire :

| Condition | Résultat |
| --- | --- |
| Historique avant la fin de la référence < 3 × (référence + écart + période) | Écart-type sous-estimé d'environ 35 % : **aucun intervalle n'est donné et aucun intéressement ne peut être déclenché**. |
| Historique suffisant, 60 réplicats | Écart-type standardisé 1,09 à 1,23 au lieu de 1, d'où le facteur 1,25 ; biais résiduel −0,2. |
| Intéressement déclenché à tort (borne basse > 0 sans effet) | 2 à 7 % des réplicats. |
| Résultat négatif « significatif » sans effet | Plus fréquent (biais résiduel) : un résultat négatif n'est pas, à lui seul, la preuve d'une dégradation. |

Conséquences pour le contrat :

- **Demander 24 mois d'historique de séjours** avant la fin de la référence
  (référence de 4 mois + pilote de 3 à 4 mois).
- L'intéressement n'est dû que si **toute la fourchette à 80 % est positive**.
  Sur le groupe de démo (environ 170 lits comparables, pilote de 3 mois), la
  demi-largeur de l'intervalle est d'environ 600 journées-lits, soit près de
  4 points d'occupation : un gain plus petit ne sera pas démontrable par un
  avant/après. Un déploiement échelonné entre sites
  (sites témoins) donnerait un design plus puissant.
- Geler la référence, la valeur de la journée et le taux d'intéressement
  **avant** le démarrage ; tout dégel est motivé et tracé.
- Ces taux ont été mesurés sur des données synthétiques : ils doivent être
  re-mesurés sur l'historique réel du groupe avant signature.

## Ce qui reste à faire avant un pilote réel

Fait dans cette version : migrations Alembic, PostgreSQL testé, connexion OIDC,
historisation des dates de sortie prévues, agent de computer use, images Docker
construites en CI.

Reste, et ne peut pas être « fait » dans le code :

- **Hébergement HDS** de l'API, de la base, des sauvegardes et, si un modèle doit
  voir des écrans identifiants, du serveur GPU (guide : `docs/DEPLOIEMENT_HDS.md`).
- **AIPD** à finaliser avec le DPO du groupe (projet : `docs/AIPD.md`) et convention
  de sous-traitance (article 28 RGPD).
- **Inscription à Pro Santé Connect** auprès de l'ANS, ou paramétrage du fournisseur
  d'identité du groupe.
- **Script de l'agent pour ViaTrajectoire** : impossible à écrire sans accès au
  portail ; le script du portail de démonstration sert de modèle. Vérifier au
  préalable les conditions d'utilisation du portail et l'accord du GIP/ARS.
- **Calage des minutes par niveau de soins** sur les mesures de charge des unités.
- Re-mesurer la calibration du North Star sur l'historique réel avant signature.

## Tests

```bash
pytest -q services/admissions_smr/tests services/admissions_agent/tests
ADM_TEST_DATABASE_URL=postgresql+psycopg://user@host/db pytest -q services/admissions_smr/tests
ruff check services/admissions_smr services/admissions_agent
mypy --config-file services/admissions_smr/mypy.ini services/admissions_smr services/admissions_agent
cd services/admissions_web && npm test && npm run build
```
