# Déployer HospitalOS Admissions SMR sur un hébergement HDS

Guide technique. Il ne remplace pas l'avis de l'organisme certificateur ni celui du
DPO du client ; vérifier chaque point avec eux.

## 1. Le cadre, en bref

- Héberger des données de santé pour le compte d'un établissement exige la
  certification **HDS** (article L. 1111-8 du code de la santé publique).
- Le référentiel HDS publié le 16 mai 2024 (arrêté du 26 avril 2024) impose un
  hébergement physique des données **dans l'Espace économique européen**, et la
  transparence sur tout accès depuis un pays tiers ou toute exposition à une loi
  extra-européenne. Les hébergeurs déjà certifiés avaient jusqu'au 16 mai 2026 pour
  s'y conformer : exiger un certificat au **nouveau référentiel**.
- Six activités sont certifiables : (1) sites physiques, (2) infrastructure
  matérielle, (3) infrastructure virtuelle, (4) plateforme d'hébergement
  d'applications, (5) administration et exploitation du système d'information
  contenant les données de santé, (6) sauvegarde.

Schéma courant pour un éditeur SaaS : un hébergeur certifié pour les activités 1 à 4
et 6 (IaaS ou PaaS HDS), et l'éditeur certifié lui-même pour l'activité 5 s'il
administre et exploite l'application et ses données. **À confirmer avec un
organisme certificateur** : si HospitalOS exploite la production, la certification
de HospitalOS pour l'activité 5 est probablement nécessaire.

## 2. Architecture cible

```
             Internet (TLS)                       Réseau de l'établissement
                  │                                         │
          ┌───────▼────────┐                       ┌────────▼─────────┐
          │ Répartiteur    │◄──── HTTPS sortant ───┤ Agent (Docker)   │──► Portail d'orientation
          │ TLS 1.2+ / WAF │                       │ compte ingestion │──► Modèles autorisés
          └───────┬────────┘                       └──────────────────┘
                  │ réseau privé (hébergeur HDS, région EEE)
          ┌───────▼────────┐     ┌───────────────┐
          │ web (nginx)    │────►│ api (FastAPI) │────► PostgreSQL managé HDS
          └────────────────┘     └───────────────┘      (chiffré, sauvegardes HDS)
```

- `web`, `api`, `db` : les trois services de `docker-compose.admissions.yml`, ou leur
  équivalent sur l'orchestrateur de l'hébergeur (images construites par la CI).
- **PostgreSQL managé** de l'offre HDS plutôt que le conteneur `db` : chiffrement au
  repos, sauvegardes et restauration à point dans le temps fournis par l'hébergeur.
- L'**agent** tourne de préférence dans le réseau de l'établissement (poste ou VM),
  parce que les portails et leurs identifiants appartiennent à l'établissement. Il
  n'expose aucun port.
- **Serveur GPU des modèles ouverts** (optionnel) : s'il doit voir des écrans
  identifiants, il est lui-même dans le périmètre HDS (même hébergeur, ou dans
  l'établissement), en EEE.

## 3. Configuration de production

| Variable | Valeur |
| --- | --- |
| `ADM_ENV` | `production` (l'API refuse alors SQLite et la clé de développement) |
| `ADM_DATABASE_URL` | `postgresql+psycopg://…@<hôte privé>/admissions?sslmode=require` |
| `ADM_SECRET_KEY` | 32 caractères aléatoires au moins, dans le coffre de secrets de l'hébergeur |
| `ADM_CORS_ORIGINS` | vide (même origine derrière nginx) |
| `ADM_OIDC_*`, `ADM_FRONTEND_URL` | voir le README du module |
| `ADM_PASSWORD_LOGIN` | `0` une fois l'OIDC en place (les comptes de service gardent le mot de passe) |

Le schéma est migré par Alembic au démarrage de l'API. Pour un déploiement contrôlé,
lancer `python -m services.admissions_smr.cli migrate` comme étape distincte avant de
démarrer la nouvelle version.

## 4. Liste de contrôle

**Hébergeur**
- [ ] Certificat HDS au référentiel 2024, couvrant les activités utilisées.
- [ ] Données et sauvegardes dans l'EEE ; cartographie des transferts publiée par l'hébergeur lue et annexée.
- [ ] Contrat d'hébergement HDS (clauses de l'article R. 1111-11 du CSP) et contrat de sous-traitance art. 28.

**Réseau et accès**
- [ ] TLS 1.2 minimum au répartiteur, HSTS ; base et API sur réseau privé.
- [ ] Accès d'administration par bastion avec authentification forte, journalisé.
- [ ] Aucun accès d'administration depuis hors EEE, ou accès documenté et communiqué au client.

**Données**
- [ ] Chiffrement au repos de la base et des sauvegardes.
- [ ] Sauvegardes quotidiennes, rétention définie, **restauration testée** et datée.
- [ ] Purge et anonymisation selon les durées validées dans l'AIPD (à implémenter).

**Application**
- [ ] `ADM_ENV=production`, secret fort, OIDC configuré, mot de passe désactivé pour les personnes.
- [ ] Compte `ingestion` dédié à chaque agent, mot de passe long, rotation planifiée.
- [ ] Journaux applicatifs sans données patient, conservés selon la politique du client.
- [ ] Supervision de `/api/health` et alerte quand l'agent est signalé hors ligne (aucun signal depuis 5 minutes).

**Agent**
- [ ] Politique de routage revue par le client ; moteurs à modèle autorisés à voir des
      écrans identifiants **seulement** si leur hébergement ou contrat le permet.
- [ ] `AGENT_ALLOWED_HOSTS` limité aux portails nécessaires.
- [ ] Accord de l'opérateur du portail d'orientation.

## 5. Ce que ce dépôt ne fournit pas

- Le choix de l'hébergeur et le contrat.
- La certification HDS de HospitalOS pour l'activité 5, si elle est requise.
- La purge automatique des données (prévue au plan d'action de l'AIPD).
- La supervision et l'astreinte.
