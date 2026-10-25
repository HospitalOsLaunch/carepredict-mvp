# HospitalOS Admissions SMR

Pilote d'admissions et d'occupation pour les **groupes SMR privés**. Le produit
fait une chose : remplir chaque lit libérable avec le bon patient, en répondant
plus vite à l'adresseur.

- `services/admissions_smr/` : API FastAPI, isolée du reste du monorepo
  (aucune dépendance à torch, Dagster ou Feast).
- `services/admissions_web/` : application React (Vite, TypeScript, Tailwind).

## Ce que fait la V1

| Écran | Usage |
| --- | --- |
| Demandes | File priorisée des demandes. Pour chacune : sites compatibles, lits prévus jour par jour, accord en un clic à la date choisie, refus motivé, réorientation vers un autre site du groupe, brouillon de message à coller dans ViaTrajectoire, historique, notes. |
| Lits et sorties | Lits libres prévus sur 14 jours par site et par mention ; patients présents avec probabilité de sortie sous 7 jours ; saisie des dates de sortie prévues et des sorties. |
| Vue groupe | Occupation, demandes en attente, sorties à 7 jours et lits fermés, site par site. |
| Indicateurs pilote | North Star (journées-lits récupérées) avec intervalle, délai de réponse, parcours des demandes, motifs de refus et de perte, lits fermés par motif, fiabilité de la prévision. |
| Imports | CSV des lits, des séjours et des demandes ; vérification complète avant import. |
| Paramètres | Sites et lits, utilisateurs et rôles, période de référence et termes du contrat (gel), pondérations de la priorisation, journal d'audit. |

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

Comptes de démonstration (mot de passe `demo-hospitalos-2026`, ou `ADM_DEMO_PASSWORD`) :
`admin@`, `coordination@`, `tilleuls@` (limité à un site), `direction@` (lecture),
`agent@` (compte de service) `demo.hospitalos.fr`.

Premier groupe réel :

```bash
python -m services.admissions_smr.cli init-group --name "Groupe X" \
  --admin-email admin@groupe-x.fr --admin-name "Prénom Nom"
```

Déploiement : `docker-compose.admissions.yml` (PostgreSQL + API + web derrière nginx).

## Rôles

| Rôle | Droits |
| --- | --- |
| `admin_groupe` | Tout, dont imports, utilisateurs, référence et contrat. |
| `coordination` | Traiter les demandes, sorties, lits ouverts. Peut être limité à un site. |
| `direction` | Lecture seule. |
| `ingestion` | Uniquement `POST /api/ingest/requests` (agent de computer use). |

Chaque groupe est un tenant isolé ; chaque action est écrite dans le journal d'audit.

## Brancher l'agent de computer use

L'agent qui lit ViaTrajectoire, les mails et les fax dépose chaque demande sur
`POST /api/ingest/requests` avec un compte `ingestion`. L'appel est idempotent
sur `(source, external_ref)` : une demande déjà reçue n'est jamais dupliquée ni
modifiée. Contrat : schéma `RequestCreate` dans `/api/docs`.

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
constant quand les données manquent. Une date de sortie prévue est suivie avec
un **a priori de glissement** (60 % le jour même, le reste sur 1 à 7 jours) :
c'est une hypothèse, à mesurer pendant le pilote.

Pour chaque jour, le nombre de sorties suit une loi de Poisson-binomiale
calculée exactement, d'où les fourchettes et la probabilité d'avoir au moins un
lit libre. Un lit est « sûr » à partir de 80 %. Les accords et confirmations
déjà donnés sont déduits.

Limite connue : les admissions qui ne passent pas par l'outil ne sont pas
anticipées. Le rejeu à dates passées (`/api/metrics/backtest`) mesure la
fiabilité réelle ; sur la démo, la fourchette à 80 % contient la réalité
75 % du temps.

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

- Hébergement HDS de l'API et de la base, TLS, sauvegardes chiffrées.
- Migrations de schéma (Alembic) : la V1 crée les tables au démarrage.
- Authentification forte (Pro Santé Connect ou SSO du groupe) à la place des mots
  de passe ; politique de rotation des comptes de service.
- AIPD (analyse d'impact RGPD) et convention avec le groupe.
- Historiser les dates de sortie prévues pour mesurer leur glissement réel
  (aujourd'hui un a priori) et l'inclure dans le rejeu.
- L'agent de computer use lui-même (seule son API de dépôt existe).

## Tests

```bash
pytest -q services/admissions_smr/tests       # 45 tests, dont la calibration
ruff check services/admissions_smr && mypy --strict services/admissions_smr
cd services/admissions_web && npm test && npm run build
```
