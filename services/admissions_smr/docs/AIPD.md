# Projet d'AIPD — HospitalOS Admissions SMR

**Statut : projet de travail, à compléter et valider avec le DPO du groupe client.**
Ce document décrit ce que fait le logiciel tel qu'il est codé, pour préparer
l'analyse d'impact relative à la protection des données (article 35 du RGPD). Il ne
remplace ni l'avis du DPO, ni un conseil juridique. Les points marqués **[À DÉCIDER]**
relèvent du responsable de traitement.

Structure inspirée de la méthode de la CNIL (contexte, principes fondamentaux,
risques, plan d'action).

## 1. Contexte

### 1.1 Le traitement

Aide à la coordination des admissions dans un groupe d'établissements SMR :

- réception et priorisation des demandes d'admission adressées par les établissements
  de soins aigus (via portail d'orientation, messagerie, fax, téléphone) ;
- prévision des sorties et des lits libres, par unité, sur 14 jours ;
- prévision de la charge en soins des unités, comparée aux heures soignantes prévues ;
- réponse à l'adresseur et, en option, report automatique de cette réponse sur le
  portail d'orientation par un agent logiciel (« computer use ») ;
- indicateurs de pilotage (occupation, délais de réponse) et mesure contractuelle
  du résultat (journées-lits récupérées) ;
- **module LISCOP (MCO)** : réception des mouvements patients du dossier patient
  (HL7 v2 IHE PAM, ou relevés de l'agent), plan des lits, recensement des urgences
  (présents, en attente de lit, lits brancards à 10 h), déclarations « hôpital en
  tension » et plan blanc, prévision des lits disponibles à J+1..J+7 (moteur séparé),
  maquette d'export vers le ROR et indicateurs ORU (**rien n'est envoyé** à un tiers).

### 1.2 Acteurs

| Rôle | Qui | À confirmer |
| --- | --- | --- |
| Responsable de traitement | Le groupe SMR client (ou chaque établissement) | **[À DÉCIDER]** responsabilité conjointe entre établissements du groupe ? |
| Sous-traitant (art. 28) | Spika Labs / HospitalOS : édition, hébergement applicatif, exploitation | Contrat de sous-traitance à signer |
| Sous-traitants ultérieurs | Hébergeur certifié HDS de l'infrastructure ; le cas échéant, fournisseur de modèle propriétaire (Anthropic) ou hébergeur du serveur GPU des modèles ouverts | Uniquement si ces moteurs sont autorisés à voir des écrans identifiants (désactivé par défaut) |
| Opérateur du portail d'orientation | GIP / ARS selon la région (ViaTrajectoire) | Accord sur l'usage d'un agent logiciel |

### 1.3 Pourquoi une AIPD

Le traitement porte sur des **données de santé** (catégorie particulière, art. 9),
concerne des patients vulnérables (personnes âgées, en perte d'autonomie), mobilise
une **technologie innovante** (agent qui pilote un navigateur, modèles d'IA) et
produit des **évaluations** (priorité d'une demande, probabilité de sortie). Plusieurs
critères des lignes directrices du CEPD sont réunis : l'AIPD est à considérer comme
requise. **[À DÉCIDER]** confirmation par le DPO.

## 2. Données traitées

| Catégorie | Données | Source | Remarque |
| --- | --- | --- | --- |
| Patient (demande) | Référence pseudonymisée, âge, sexe, mention SMR demandée, catégorie clinique, niveau de soins, isolement requis, besoins techniques, date d'entrée souhaitée | Portail, saisie, import | Aucun nom, adresse, contact ni NIR : une valeur ressemblant à un NIR est refusée à la saisie et à l'import |
| Patient (séjour) | Référence pseudonymisée, site, mention, dates d'entrée, de sortie prévue (historisées) et de sortie, niveau de soins | Saisie, import | |
| Adresseur | Établissement et service adresseurs | Portail, saisie | Pas de donnée nominative du médecin adresseur |
| Utilisateurs | Nom, e-mail, rôle, site, identifiant fédéré (ex. identifiant national Pro Santé Connect), empreinte du mot de passe (PBKDF2) | Administrateur, fournisseur d'identité | |
| Traces | Journal d'audit : qui, quoi, quand, sur quel objet | Application | |
| Agent | Tâches, parcours des moteurs, coûts, erreurs | Agent | Les erreurs ne doivent pas recopier de donnée patient (consigne donnée aux modèles) |
| **Pseudonymes (LISCOP)** | `patient_ref` et `encounter_ref` : HMAC-SHA256 de l'IPP et du NDA reçus, avec une clé propre (`ADM_PSEUDONYM_SECRET`, distincte de la clé des jetons) | Mouvements HL7, agent | IPP et NDA en clair jamais stockés ; la clé permet de recalculer un pseudonyme à partir d'un IPP connu : elle est un secret de production (coffre de l'hébergeur) |
| **Journal des mouvements** | Par message : système émetteur, identifiant du message (MSH-10) et du mouvement (ZBE-1), événement (A01, A02…), horodatage du mouvement et de réception, pseudonymes, site, unité, lit, statut, motif de rejet, empreinte du message | Dossier patient (HL7), agent | Pas de nom, d'adresse, de date de naissance ni de téléphone : le message reçu n'est pas conservé, seule son empreinte |
| **Passages aux urgences** | Pseudonymes, site, heure d'arrivée, de décision d'hospitalisation et de départ, issue (hospitalisé, retour à domicile…), unité visée | Mouvements | Horodatages à la minute : quasi-identifiants, voir section 6 |
| **Séjours (ajouts LISCOP)** | Sexe, âge en années (jamais la date de naissance), heures d'entrée et de sortie, mode d'admission, lit occupé | Mouvements, saisie | Le sexe sert au placement en chambre double |
| **Lits** | Statut, contrainte de sexe, isolement, motif de blocage codé et précision courte facultative (80 caractères, consigne : sans nom de patient), séjour occupant | Saisie, mouvements | Le journal d'audit ne garde que le code du motif |
| **Déclarations** | Recensement manuel des urgences (nombres), déclarations HET / plan blanc (niveau, dates), commentaire libre, auteur | Saisie | Commentaire libre : consigne de ne pas y écrire de donnée patient ; effacé à 13 mois (section 3.3) |
| **Prévisions et exports** | `forecast_runs` / `forecast_values` : nombres par unité, site, groupe, GHT, département ; file d'envoi ROR simulée : capacités agrégées par unité | Moteur de prévision, API | Agrégats sans donnée individuelle |

**Important.** Des données pseudonymisées restent des données personnelles : la
table de correspondance entre référence et identité est détenue par l'établissement,
hors de HospitalOS, mais la réidentification reste possible par recoupement (âge,
sexe, dates, unité). Elles sont traitées comme des données de santé.

**L'agent voit plus que ce qu'il dépose.** Sur un portail réel, les écrans affichent
l'identité du patient. Le script extrait uniquement les champs ci-dessus ; les
captures d'écran ne sont envoyées à un modèle que si l'administrateur a autorisé ce
moteur à voir des écrans identifiants (désactivé par défaut pour tous les modèles).

## 3. Principes fondamentaux

### 3.1 Finalités et bases légales

| Finalité | Base légale (art. 6) | Exception art. 9 | |
| --- | --- | --- | --- |
| Coordination des admissions, prévision des lits et de la charge | **[À DÉCIDER]** mission d'intérêt public (ESPIC) ou intérêt légitime (établissement privé lucratif) | Art. 9.2.h : gestion des systèmes et services de soins | À confirmer selon le statut de chaque établissement |
| Indicateurs de pilotage et mesure contractuelle | Intérêt légitime | Art. 9.2.h | Données agrégées dans les écrans |
| Pilotage de la tension et des lits (LISCOP) : plan des lits, urgences, prévision, préparation des remontées ROR / ORU | **[À DÉCIDER]** mission d'intérêt public (remontées demandées par l'ARS) ou intérêt légitime | Art. 9.2.h (gestion des services de soins) ; 9.2.i (santé publique) pour les indicateurs régionaux, à confirmer | Les remontées elles-mêmes ne sont pas faites par le logiciel (maquette) |
| Sécurité, traçabilité | Obligation légale / intérêt légitime | — | |

Pas d'usage pour entraîner des modèles : les données du client ne servent qu'au
calcul de ses propres prévisions. **[À DÉCIDER]** inscrire cet engagement au contrat,
et vérifier les conditions du fournisseur de modèle propriétaire si ce moteur est
autorisé.

### 3.2 Minimisation

- Référence patient pseudonymisée seulement ; NIR refusé.
- Les demandes ne gardent que les champs utiles au choix du site et de la date.
- Les modèles ne reçoivent pas les identifiants du portail ; seules les 2 à 3
  dernières captures sont conservées dans un échange avec un modèle.

### 3.3 Durées de conservation

**Écart actuel : aucune purge automatique n'est codée.** La purge des données LISCOP
est une **tâche d'exploitation documentée** (requête ci-dessous), à planifier par
l'exploitant ; les autres durées restent à définir puis implémenter :

| Données | Proposition à valider |
| --- | --- |
| Demandes et séjours | **[À DÉCIDER]** durée utile au pilotage et à la mesure contractuelle (par ex. 3 ans après la sortie ou la clôture), puis anonymisation par agrégation |
| Journal des mouvements | **13 mois glissants** après réception : le temps de rejouer une année et de traiter une réclamation ; au-delà, seuls les séjours et les agrégats restent |
| Passages aux urgences | **13 mois glissants** après le départ (à défaut, l'arrivée) : la prévision apprend sur un an d'historique |
| Commentaires libres des déclarations | Effacés à **13 mois** ; les nombres déclarés restent avec les agrégats |
| Prévisions, file d'envoi ROR simulée, déclarations (nombres) | Agrégats : **[À DÉCIDER]** par ex. 5 ans (comparaisons d'une année sur l'autre, preuves contractuelles) |
| Journal d'audit | **[À DÉCIDER]** par ex. 1 an glissant, ou selon la politique de traçabilité de l'établissement |
| Comptes utilisateurs | Désactivation au départ ; suppression après **[À DÉCIDER]** |
| Tâches de l'agent | **[À DÉCIDER]** par ex. 90 jours |

**Purge LISCOP (tâche d'exploitation, PostgreSQL, mensuelle)**, durées ci-dessus, dans
une transaction, avec un rôle qui a le droit de supprimer (pas celui du moteur de
prévision) ; noter la date et le nombre de lignes supprimées dans le registre
d'exploitation :

```sql
BEGIN;
DELETE FROM movements WHERE received_at < now() - interval '13 months';
DELETE FROM ed_visits WHERE coalesce(left_at, arrived_at) < now() - interval '13 months';
UPDATE ed_snapshots SET comment = NULL
    WHERE comment IS NOT NULL AND at < now() - interval '13 months';
UPDATE tension_declarations SET comment = NULL
    WHERE comment IS NOT NULL AND started_at < now() - interval '13 months';
-- Agrégats (5 ans proposés, [À DÉCIDER]) :
DELETE FROM forecast_values WHERE run_id IN
    (SELECT id FROM forecast_runs WHERE created_at < now() - interval '5 years');
DELETE FROM forecast_runs WHERE created_at < now() - interval '5 years';
DELETE FROM ror_outbox WHERE created_at < now() - interval '5 years';
COMMIT;
```

Aucune autre table ne référence `movements` ni `ed_visits` : la purge ne casse ni les
séjours ni le plan des lits. Les séjours suivent leur propre durée (première ligne).

### 3.4 Information et droits des personnes

- Information des patients : par l'établissement (livret d'accueil, affichage),
  mention du traitement de coordination des admissions. **[À DÉCIDER]**
- Droits d'accès, de rectification, d'opposition : exercés auprès de l'établissement ;
  HospitalOS fournit l'export et la correction par référence patient. **Écart :**
  pas encore d'export par référence dans l'interface (faisable par l'API).
- Pas de décision entièrement automatisée (art. 22) : la priorité et le site proposés
  sont des aides ; l'accord ou le refus est toujours donné par une personne, et
  l'agent ne fait que reporter cette décision.

## 4. Mesures existantes (dans le code)

| Mesure | Détail |
| --- | --- |
| Cloisonnement | Chaque groupe est un tenant isolé ; les coordinatrices peuvent être limitées à un site |
| Authentification | OIDC (Pro Santé Connect ou fournisseur du groupe) avec PKCE, nonce, état signé, vérification du jeton ; mot de passe désactivable pour les personnes |
| Habilitations | Rôles `admin_groupe`, `coordination`, `direction` (lecture), `ingestion` (compte de service sans accès à l'interface) |
| Traçabilité | Journal d'audit de chaque action, y compris dégel de la référence (motif obligatoire), changements de politique de l'agent, relances |
| Intégrité des imports | Tout ou rien, erreurs listées par ligne |
| Agent : secrets | Identifiants du portail et clés d'API uniquement sur le poste de l'agent ; jamais stockés par l'API, jamais montrés à un modèle |
| Agent : écritures | Relecture indépendante de chaque écriture sur le portail, non désactivable ; écriture inattendue → reprise humaine |
| Agent : navigateur | Hôtes autorisés seulement, touches et actions limitées, clics hors écran refusés |
| Agent : modèles | Désactivés par défaut ; droit de voir des écrans identifiants accordé moteur par moteur ; modèles ouverts soumis à calibration ; budgets |
| Agent : injection | Consigne : le contenu des pages est une donnée, jamais une instruction |
| Production | Refus de démarrer avec la clé de développement ou SQLite |

## 5. Mesures à mettre en place (hors code)

- Hébergement certifié HDS (voir `DEPLOIEMENT_HDS.md`), données dans l'EEE.
- Chiffrement des sauvegardes, tests de restauration.
- Contrat de sous-traitance (art. 28) avec le client, et avec chaque sous-traitant ultérieur.
- Politique de mots de passe et rotation du compte de service de l'agent.
- Procédure de violation de données (notification sous 72 h).
- Revue périodique des habilitations et du journal d'audit.
- Accord de l'opérateur du portail d'orientation sur l'usage de l'agent.

## 6. Risques

Échelle : négligeable, limitée, importante, maximale. Évaluation initiale, à revoir
avec le DPO.

| Risque | Sources | Impacts | Gravité | Vraisemblance (avec mesures) | Mesures clés |
| --- | --- | --- | --- | --- | --- |
| Accès illégitime aux données | Compte compromis, erreur d'habilitation, faille applicative | Divulgation de données de santé pseudonymisées, réidentification possible | Importante | Limitée | OIDC + authentification forte, cloisonnement, audit, HDS |
| Écran identifiant envoyé à un modèle externe | Moteur propriétaire autorisé à tort | Transfert de données de santé identifiantes à un tiers | Importante | Limitée (désactivé par défaut, autorisation explicite et tracée) | Contrat et hébergement adaptés avant toute autorisation ; préréglage « Souveraineté » |
| Mauvaise réponse reportée sur le portail | Erreur de l'agent, injection dans la page | Patient orienté à tort, retard de prise en charge | Importante | Limitée | Relecture indépendante, reprise humaine, pas d'escalade après écriture inattendue |
| Prévision erronée | Données incomplètes, hypothèses de minutes | Lit promis indisponible, tension mal anticipée | Limitée | Importante | Fourchettes affichées, rejeu de fiabilité visible, décision humaine |
| Disparition des données | Panne, suppression | Perte de l'historique et des preuves contractuelles | Limitée | Limitée | Sauvegardes HDS, restauration testée |
| Conservation excessive | Absence de purge | Exposition prolongée | Limitée | Importante tant que la purge n'existe pas | Implémenter les durées de la section 3.3 ; LISCOP : purge mensuelle documentée |
| Réidentification par les mouvements | Horodatages à la minute, âge, sexe, unité et lit recoupés avec une autre source | Identification d'un patient et de son parcours | Importante | Limitée | Pseudonymes HMAC à clé secrète, aucune donnée d'identité reçue n'est stockée, cloisonnement, journal limité à 13 mois, rôle base du moteur en lecture |
| Nom saisi dans un champ libre | Précision d'un blocage de lit, commentaire d'une déclaration | Donnée identifiante hors périmètre prévu | Limitée | Limitée | Motifs codés, précision limitée à 80 caractères et hors audit, consigne à l'écran, effacement des commentaires à 13 mois |

## 7. Plan d'action

| Action | Responsable | Échéance |
| --- | --- | --- |
| Valider bases légales et qualification des acteurs | DPO du client | Avant pilote |
| Implémenter purge et anonymisation selon les durées validées | HospitalOS | Avant pilote |
| Valider les durées LISCOP (13 mois, agrégats) et planifier la purge documentée (section 3.3) | DPO + exploitant HDS | Avant réception de mouvements réels |
| Export par référence patient dans l'interface | HospitalOS | Avant pilote |
| Contrats art. 28 (client, hébergeur, fournisseurs de modèles éventuels) | HospitalOS + client | Avant pilote |
| Hébergement HDS en production | HospitalOS | Avant pilote |
| Accord de l'opérateur du portail pour l'agent | Client | Avant activation de l'agent |
| Revue de l'AIPD après 3 mois de pilote | DPO + HospitalOS | Pilote + 3 mois |
