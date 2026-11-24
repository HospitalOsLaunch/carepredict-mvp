# Environnements et mise en production

Deux environnements Internet, **staging** (recette) et **production**. Chacun a sa propre machine virtuelle,
sa propre base de comptes et son propre domaine. L'enclave hors ligne du CHU (`deploy/nantes`) suit sa propre
procédure ([`docs/nantes/deployment_envelope.md`](../nantes/deployment_envelope.md)).

| | staging | production |
|---|---|---|
| Rôle | recette : chaque commit vert de `main` | version validée, utilisée par les pilotes |
| Déclenchement | automatique après le workflow `ci` vert sur `main` | tag `vX.Y.Z`, puis **approbation** dans GitHub |
| Image | `sha-<12 caractères du commit>` | même image, re-taguée `vX.Y.Z` (même digest, aucune reconstruction) |
| Domaine | ex. `recette.hospitalos.fr`, non indexé (`X-Robots-Tag: noindex`) | ex. `app.hospitalos.fr` |
| Comptes | base séparée ; comptes de test | base séparée ; comptes réels des pilotes |
| Emails | SMTP réel (adresses de l'équipe) | SMTP réel |
| Google Analytics | **jamais** | GA4, après consentement de chaque utilisateur |
| Bandeau | « Recette » sur l'écran de connexion | aucun |

Données : **synthétiques** dans les deux environnements. Le statut reste `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`. Avant toute donnée de santé réelle, un hébergeur certifié HDS est
obligatoire (voir la dernière section).

## Architecture d'un environnement

```
Internet ──443/80──▶ edge (Caddy : HTTPS Let's Encrypt, HSTS, redirection HTTP)
                       │  réseau « edge »
                       ▼
                     cockpit (nginx : interface React, en-têtes de sécurité, CSP)
                       │  réseau « app » (interne, sans sortie)
                       ▼
                     platform (FastAPI : comptes, sessions, paramètres, journal, passerelle /api)
                       │                                   └── réseau « egress » : SMTP uniquement
                       ├──▶ hybrid-api   (moteur Libérer → Attribuer)
                       └──▶ decision-api (planificateur 24 h, un espace par compte)
```

- Un seul fichier compose pour les deux environnements : `deploy/cloud/docker-compose.yml`. Seul le
  fichier `.env` du serveur change (modèles : `deploy/cloud/env/{staging,production}.env.example`).
- Seul `edge` publie des ports, et seulement 80 et 443. Les services applicatifs sont en lecture seule,
  sans capacité Linux, avec `no-new-privileges`.
- La base des comptes (SQLite) est dans le volume `platform-data` ; Caddy garde ses certificats dans
  `caddy-data`.
- La porte `python scripts/deploy/check_release.py --profile cloud` vérifie ces règles en CI, ainsi que le
  `.env` du serveur (`--env`).

## Chaîne de mise en production

```
PR ──▶ ci vert ──▶ fusion dans main ──▶ ci vert sur main
                                         │
                                         ▼  workflow deploy, job build
                         images ghcr.io/hospitaloslaunch/hospitalos-{product,cockpit}:sha-<commit>
                                         │
                                         ▼  job staging (automatique)
                         recette : sauvegarde → pull → up → santé → retour arrière si échec → smoke
                                         │
                       recette validée ─┘  (checklist ci-dessous)
                                         │
                   git tag v1.4.0 <commit> && git push origin v1.4.0
                                         │
                                         ▼  job promote : vérifie que le commit est sur main et déjà construit,
                                            re-tague sha-<commit> → v1.4.0 (même digest)
                                         ▼  job production : attend l'approbation d'un relecteur, puis
                                            sauvegarde → pull → up → santé → retour arrière si échec → smoke
```

Fichiers :

| Fichier | Rôle |
|---|---|
| `.github/workflows/deploy.yml` | construit, promeut, enchaîne staging et production, retour arrière manuel |
| `.github/workflows/deploy-env.yml` | déploie un tag sur un environnement (SSH, empreinte du serveur épinglée) |
| `deploy/cloud/deploy.sh` | sur le serveur : contrôle du tag, sauvegarde de la base, pull, up, attente de la santé, retour arrière |
| `deploy/cloud/smoke.sh` | vérifications publiques : version, environnement, 401 sans session, HSTS, CSP, HTTPS, GA selon l'environnement |

### Publier une version

1. Vérifier que le commit voulu est en recette : `https://<recette>/api/platform/health` affiche
   `"release":"sha-<commit>"`.
2. Dérouler la **checklist de recette** (ci-dessous) sur ce commit.
3. Taguer **ce commit** et pousser le tag :
   ```bash
   git tag -a v1.4.0 <commit> -m "v1.4.0 : <résumé>"
   git push origin v1.4.0
   ```
4. Dans GitHub, onglet *Actions* → *deploy* → job **production** → *Review deployments* → *Approve*.
5. Le job vérifie la production. En cas d'échec, `deploy.sh` est déjà revenu à la version précédente ;
   le job échoue et le journal montre les 80 dernières lignes de la plateforme.

Numérotation : `MAJEUR.MINEUR.CORRECTIF`. Le majeur change si la base de comptes ou un usage change de
façon incompatible, le mineur pour une fonctionnalité, le correctif pour une correction.

### Checklist de recette (avant chaque tag)

- [ ] Connexion avec un compte pilote ; mauvais mot de passe : message générique.
- [ ] Mot de passe oublié : email reçu, lien valable une heure, à usage unique.
- [ ] Invitation par un administrateur : email reçu, création du mot de passe, arrivée dans le cockpit.
- [ ] Deux comptes distincts : le journal et le planificateur de l'un ne sont pas visibles par l'autre.
- [ ] Paramètres : profil enregistré, changement de mot de passe, « déconnecter mes autres sessions ».
- [ ] Administration : désactiver puis réactiver un compte ; le compte désactivé ne peut plus se connecter.
- [ ] Cockpit : unité, proposition, validation, journal ; planificateur 24 h, mode automatique puis manuel.
- [ ] Bandeau « Recette » visible ; aucune requête vers Google (onglet Réseau du navigateur).
- [ ] Le job *staging* et `smoke.sh` sont verts.

### Retour arrière

- **Automatique** : si la santé publique ne répond pas avec la nouvelle version en 2 minutes, `deploy.sh`
  revient au tag précédent.
- **Manuel** : *Actions* → *deploy* → *Run workflow* → environnement et tag existant (production :
  `vX.Y.Z` uniquement ; l'approbation reste requise). Équivalent sur le serveur :
  `bash /opt/hospitalos/production/deploy.sh production v1.3.2`.
- Les migrations de schéma de la base des comptes sont **additives** (jamais de suppression de colonne
  dans la même version) pour que la version précédente reste compatible. Si une version l'interdit,
  revenir aussi à la sauvegarde prise avant le déploiement (section Sauvegardes).

### Correctif urgent

Branche depuis `main`, PR, CI verte, fusion : le commit passe en recette automatiquement. Vérification
ciblée, puis tag `vX.Y.(Z+1)` et approbation. Il n'existe pas de chemin vers la production qui évite
la recette.

## Préparer un serveur (une fois par environnement)

Machine conseillée : 2 vCPU, 4 Go de RAM, 40 Go de disque, Debian 12 ou Ubuntu 24.04, dans l'UE.

1. **DNS** : un enregistrement A/AAAA par environnement (`recette.<domaine>`, `app.<domaine>`) vers l'IP
   du serveur.
2. **Pare-feu** : entrées 22 (SSH, restreint si possible), 80 et 443 (TCP) et 443 (UDP, HTTP/3).
   Tout le reste fermé.
3. **Docker** : Docker Engine et le plugin compose depuis le dépôt officiel de Docker.
4. **Utilisateur de déploiement** :
   ```bash
   sudo adduser --disabled-password --gecos "" deploy
   sudo usermod -aG docker deploy
   sudo install -d -o deploy -g deploy -m 750 /opt/hospitalos/staging     # ou production
   ```
   Générer une clé dédiée (`ssh-keygen -t ed25519 -f hospitalos-deploy-staging -N ""`), mettre la
   partie publique dans `~deploy/.ssh/authorized_keys`, la partie privée dans le secret GitHub
   (étape suivante). SSH : authentification par mot de passe désactivée.
5. **Fichier d'environnement** : copier le modèle en `/opt/hospitalos/<env>/.env`, droits `600`,
   propriétaire `deploy`, remplacer chaque `REPLACE_ME` (laisser `IMAGE_TAG=REPLACE_ME` : la première
   exécution de `deploy.sh` l'écrit). Contrôle :
   ```bash
   python3 scripts/deploy/check_release.py --profile cloud --env /opt/hospitalos/<env>/.env
   ```
   (seule `IMAGE_TAG` peut rester signalée avant le premier déploiement).

## Configurer GitHub (une fois)

*Settings → Environments* : créer **staging** et **production**.

| Où | Nom | Valeur |
|---|---|---|
| variable d'environnement | `DEPLOY_HOST` | IP ou nom du serveur |
| variable d'environnement | `DEPLOY_USER` | `deploy` |
| variable d'environnement | `PUBLIC_URL` | `https://recette.<domaine>` / `https://app.<domaine>` |
| secret d'environnement | `DEPLOY_SSH_KEY` | clé privée de déploiement de cet environnement |
| secret d'environnement | `DEPLOY_KNOWN_HOSTS` | sortie de `ssh-keyscan -t ed25519 <serveur>`, **comparée** à l'empreinte lue sur la console du serveur (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`) |

Protection de **production** : *Required reviewers* (au moins une personne autre que l'auteur du tag),
*Deployment branches and tags* : tags `v*` uniquement. Protection de **staging** : branche `main`
uniquement.

Tant que ces valeurs manquent, les jobs de déploiement se terminent avec un avertissement et ne font
rien ; la construction des images fonctionne dès la fusion du workflow dans `main`.

Les images sont privées dans GHCR. Le serveur s'authentifie à chaque déploiement avec le jeton éphémère
du job (lu sur l'entrée standard, session docker fermée à la fin) : aucun identifiant de registre ne reste
sur le serveur.

## Premier administrateur

Les comptes se créent uniquement par invitation. Le premier administrateur se crée sur le serveur, une
fois la plateforme démarrée :

```bash
cd /opt/hospitalos/production
docker compose exec platform python -m hospitalos.platform invite-admin prenom.nom@exemple.fr --name "Prénom Nom"
```

La commande envoie l'email d'invitation et affiche aussi le lien (valable 7 jours). Ensuite, tout se
fait depuis le cockpit : *Paramètres → Administration → Inviter* (rôle pilote ou administrateur),
renvoyer une invitation, désactiver un compte. Autres commandes : `users` (liste sans secret),
`migrate`, `backup <chemin>`.

## Emails (SMTP)

Un fournisseur transactionnel européen (ex. Brevo, Mailjet, Scaleway TEM) avec un domaine
d'expédition vérifié : SPF, DKIM et DMARC sur le domaine de `EMAIL_FROM`. Les messages contiennent
uniquement le nom de l'outil et un lien à usage unique (invitation 7 jours, réinitialisation 60 minutes),
aucune donnée métier. `EMAIL_BACKEND=console` est refusé hors développement.

## Google Analytics (production uniquement)

1. Créer une propriété GA4 et un flux Web pour le domaine de production ; noter l'identifiant `G-…`.
2. Dans GA4 : désactiver *Google Signals* et la personnalisation publicitaire, conservation des données
   à 2 mois, IP non stockées (comportement GA4 par défaut).
3. Renseigner `GA_MEASUREMENT_ID=G-…` dans `/opt/hospitalos/production/.env`, puis redéployer la même
   version (`deploy.sh production <version courante>`).

Comportement garanti par le code (tests `web/src/auth/auth.test.tsx`) :

- la plateforme n'expose l'identifiant **qu'en production** ; staging et développement ne chargent jamais
  GA ;
- le script Google n'est chargé **qu'après le consentement** explicite de l'utilisateur (bandeau à la
  première connexion ; choix modifiable dans *Paramètres → Confidentialité*, enregistré par compte) ;
- seuls des noms de section génériques sont envoyés (`/unite`, `/proposition`, `/plan`, `/journal`,
  `/donnees`, `/parametres`) : ni identifiant de compte, ni email, ni identifiant de lit, de patient ou de décision ;
  pas de signaux Google ni de personnalisation publicitaire ;
- la CSP de nginx n'autorise, en plus du site, que `www.googletagmanager.com` (script) et les domaines
  de collecte Google Analytics (`*.google-analytics.com`, `*.analytics.google.com`).

Points CNIL à traiter par le responsable de traitement : mention de la mesure d'audience dans la
politique de confidentialité ; refus aussi simple que l'acceptation (c'est le cas) ; durée de
conservation du choix limitée à 13 mois (**pas encore appliquée** : le choix est conservé jusqu'à ce que
l'utilisateur le modifie ou l'efface dans ses paramètres) ; transfert vers Google, à documenter
(Data Privacy Framework UE–États-Unis).

## Sauvegardes et restauration

- `deploy.sh` copie la base des comptes avant **chaque** déploiement dans
  `platform-data:/data/backups/pre-<tag>-<date>.sqlite3` (copie cohérente à chaud, conservée 30 jours).
- Sauvegarde quotidienne conseillée (cron de l'utilisateur `deploy`), copiée **hors du serveur** :
  ```bash
  15 2 * * * cd /opt/hospitalos/production && docker compose exec -T platform python -m hospitalos.platform backup /data/backups/daily-$(date +\%u).sqlite3
  ```
  puis export du volume vers un stockage objet chiffré de l'UE.
- Restauration :
  ```bash
  cd /opt/hospitalos/production
  docker compose stop platform
  docker run --rm -v hospitalos_platform-data:/data alpine \
    sh -c 'cp /data/platform.sqlite3 /data/backups/before-restore.sqlite3 && cp /data/backups/<fichier> /data/platform.sqlite3 && rm -f /data/platform.sqlite3-wal /data/platform.sqlite3-shm'
  docker compose up -d platform
  ```
  Tester une restauration en recette au moins une fois par trimestre.

## Surveillance

- Santé : `https://<domaine>/api/platform/health` (`status`, `environment`, `release`) ; à brancher sur un
  service de supervision externe (alerte si non-200 pendant 5 minutes).
- Journaux : `docker compose logs -f platform` (rotation 5 × 20 Mo par service). Les journaux ne
  contiennent ni mot de passe ni jeton.
- Traçabilité : *Paramètres → Administration* affiche le journal d'audit (connexions, échecs, invitations,
  changements de rôle ou de statut).
- Mises à jour du système : `unattended-upgrades` pour les correctifs de sécurité du serveur ; images de
  base épinglées par digest, mises à jour par PR (`scripts/deploy/pin_images.py`).

## Hébergement et données de santé

Le cadre actuel (données synthétiques) autorise un hébergeur cloud standard situé dans l'UE. **Dès qu'une
donnée de santé réelle, même pseudonymisée, entre dans l'outil**, l'hébergement doit être certifié HDS
(article L.1111-8 du Code de la santé publique), une analyse d'impact (AIPD) et un contrat de
sous-traitance avec l'établissement sont nécessaires, et la décision `G2` doit être revue. Le même compose
fonctionne sur une VM d'un hébergeur HDS.
