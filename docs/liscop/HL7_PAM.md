# Mouvements patients : HL7 v2.5 IHE PAM France

Module `movement-ingest`. Les mouvements arrivent du SI (GAM ou EAI) en HL7 v2.5,
extension française d'IHE PAM (transaction ITI-31), ou, à défaut, de l'agent de computer
use qui lit l'écran du logiciel de gestion des lits. Les deux chemins passent par le même
code : `domain/hl7_pam.py` (pur) et `movement_service.py` (application en base).

## Sources

| Réf. | Document | Accès dans cette session |
|---|---|---|
| [ANS] | ANS, *IHE PAM – Extension nationale française*, v2.10.2, <https://interop.esante.gouv.fr/document/IHE_France_PAM_National_Extension_v2.10.2.pdf> | Lu (texte extrait des §1 à §5 ; les tableaux du §6 ne sont pas sortis à l'extraction) |
| [HL7] | HL7 International, *HL7 v2.5*, chapitres 2 (structures, ACK, ERR) et 3 (ADT) | **Non relu ici** (pages de référence bloquées). Repris de la connaissance du standard : à vérifier |
| [PY] | python-hl7 0.4.5, code source installé (`hl7/parser.py`, `hl7/containers.py`) | Lu. <https://python-hl7.readthedocs.io> était bloqué |

## Faits retenus

### Événements (ITI-31, [ANS] §2.2 p. 13-14 et §5.3.2 p. 23-24)

| Événement | Sens | Annulé par | Traitement HospitalOS |
|---|---|---|---|
| A01 | Admission d'un hospitalisé | A11 | séjour créé, lit occupé |
| A04 | Enregistrement d'un patient externe ou des urgences | A11 | passage aux urgences si PV1-2 = E ; sinon ignoré |
| A02 | Mutation (UF d'hébergement, lit, UF médicale ou de soins) | A12 | même séjour : unité et lit changent |
| A03 | Sortie définitive | A13 | fin du séjour ou du passage |
| A06 | Externe ou urgences devient hospitalisé | A07 ([ANS] §5.3.5 p. 25) | passage clos « hospitalisé », séjour créé (`admission_mode = urgences`) |
| A07 | Hospitalisé devient externe ou urgences | A06 | ZBE-4 = CANCEL : annule l'A06 ; sinon ignoré |
| A21 / A22 | Absence provisoire (permission, plateau technique < 48 h) / retour | A52 / A53 | lit conservé |
| Z99 | Correction d'un mouvement, ZBE-4 = UPDATE uniquement ; « seul événement susceptible de modifier un mouvement » ([ANS] p. 24) | — | le mouvement visé par ZBE-1 est corrigé |
| A05, A14-A16, A38, A54, A55, A44… | Pré-admission, attentes, médecin responsable, dossier | — | accusés AA, journalisés `ignored` |

Annulation : le message reprend le ZBE-1 du mouvement annulé, avec ZBE-4 = CANCEL
([ANS] p. 25-26). A08 et A40 sont hors ITI-31 ([ANS] §2.2).

### Segment ZBE ([ANS] §6.13 p. 65-67, §5.3 p. 25-28)

| Champ | Contenu | Utilisation |
|---|---|---|
| ZBE-1 (EI, répétable) | identifiant du mouvement ; « chaque nouvelle transition provoque la création d'un nouvel identifiant » (p. 26) | `movements.movement_ref` ; cible des annulations et corrections |
| ZBE-2 (TS) | date du mouvement (« la date à laquelle le mouvement a été créé », p. 27) | `occurred_at` (prioritaire) |
| ZBE-4 (ID) | INSERT, UPDATE, CANCEL | `movements.action` ; doit être cohérent avec l'événement, sinon AE |
| ZBE-5 (ID) | indicateur de mouvement historique (Y / N dans les exemples, p. 28) | Y → AE (ZBE^1^5), sauf sur un Z99 (voir limites) |
| ZBE-6 (ID) | événement d'origine modifié par le Z99 (p. 25) | contrôlé contre le mouvement corrigé |
| ZBE-7 (XON) | UF de responsabilité médicale ([ANS] §5.1.1 p. 19-20) | repli si PV1-3.1 est vide : composant 10 (hypothèse, voir plus bas) |
| ZBE-8, ZBE-9 | UF de soins, nature du mouvement | non utilisés |

### PV1, PID, MSH, EVN

| Champ | Source | Utilisation |
|---|---|---|
| PV1-2 | [ANS] §6.10.1 p. 50 : E urgences, I hospitalisation complète, R partielle, O externe, N sans objet | `patient_class` |
| PV1-3.1 | [ANS] §5.1.1 : « le 1er composant du champ PV1-3 » porte l'UF d'hébergement | code UF → `bed_pools.uf_code` |
| PV1-3.2 / .3 / .4 | [HL7] PL : chambre, lit, établissement (HD) | chambre, lit, FINESS (9 caractères, dans HD-1 ou HD-2) |
| PV1-19 (CX) | [ANS] §5.1.3 et §5.4.2 : identifiant de venue | NDA → HMAC, jamais stocké en clair ; PV1-19.4 (autorité d'affectation) = domaine du pseudonyme |
| PV1-36 | [ANS] (table non extraite) : circonstance de sortie | issue du passage, hypothèse ci-dessous |
| PID-3 (CX, répétable) | [ANS] §4.4.1 : IPP de type `PI` ; l'INS a le type `INS` (OID 1.2.250.1.213.1.4.8 = INS-NIR) | IPP `PI` → HMAC ; PID-3.4 de la répétition retenue = domaine du pseudonyme. Les identifiants nationaux (INS, NIR…) sont ignorés, jamais lus ni stockés |
| PID-7 | [ANS] exemple « 19600530 » | âge en années à la date du mouvement, puis oublié |
| PID-8 | [ANS] exemple « F » ; [HL7] table 0001 | F, M ; toute autre valeur → U |
| PID-5, PID-11, PID-13… | nom, adresse, téléphone | jamais lus |
| MSH-1/2 | [HL7] ch. 2 | seuls `|` et `^~\&` sont acceptés (sinon AR) |
| MSH-3/4 | application et établissement émetteurs | `source_system` = `MSH-3/MSH-4` ; doit figurer dans `users.allowed_sources` du compte quand la liste est renseignée, sinon AR (HTTP 403), non journalisé |
| MSH-9 | `ADT^Axx` ; exemples [ANS] « ADT^A31^ADT_A05 » | type ≠ ADT → AR (code 200) |
| MSH-10 | identifiant du message | idempotence (`message_control_id`) avec l'empreinte du contenu |
| MSH-12 | [ANS] exemple « 2.5^FRA^2.9 » | doit commencer par « 2. » (sinon AR 203) |
| EVN-2 / EVN-6 | [HL7] date d'enregistrement / de survenue | replis de ZBE-2 : ZBE-2 → EVN-6 → EVN-2 → MSH-7 |

### Accusés de réception ([HL7] ch. 2, mode original)

`MSH` (émetteur et destinataire inversés, `ACK^<événement>^ACK`, version 2.5), `MSA-1`
AA / AE / AR, `MSA-2` = MSH-10 reçu, `MSA-3` = texte en français ; sur erreur, `ERR` en
v2.5 : ERR-2 emplacement, ERR-3 code de la table 0357 (`100` structure, `101` champ requis,
`102` type, `103` valeur, `200` type de message, `203` version, `207` erreur
applicative), ERR-4 = `E`. Les caractères spéciaux du texte sont échappés (`\F\ \S\ \T\
\R\ \E\`).

Sur HTTP, le corps est toujours l'ACK ; le code HTTP le reflète : AA → 200, AE → 422,
AR → 400, message trop gros → 413 (avec un ACK AR), émetteur non autorisé pour le compte →
403 (avec un ACK AR), type de contenu inconnu → 415.

Les textes des ACK et du journal sont fixes et désignent l'emplacement HL7 (ERR-2) ; une
valeur de l'émetteur n'y est reprise que si elle a la forme d'un code (`[A-Z0-9]`, 12 au
plus, avec un chiffre : UF, lit, FINESS), jamais un texte libre (un nom saisi dans le
mauvais champ ne revient pas dans l'ACK ni dans le journal).

**Contrôles avant lecture.** Caractère de contrôle C0 dans le message (NUL, ESC,
tabulation…, hors séparateur de segment) → AR, rien n'est lu ni stocké. Horodatage
invalide ou non représentable (mois 13, décalage ≥ 24 h, année 0, débordement) → AE 102
avec l'emplacement. Date du mouvement hors de [réception − 400 jours, réception + 24 h]
(`ADM_MOVEMENT_MAX_AGE_DAYS`, `ADM_MOVEMENT_MAX_FUTURE_HOURS`) → AE, journalisé avec la
date de réception à la place de la date reçue.

### python-hl7 ([PY])

`hl7.parse` ne sépare les segments que sur `\r` : HospitalOS normalise `\r\n` et `\n`,
retire l'encadrement MLLP (`\x0b … \x1c\r`). Le message est lu et analysé avant de
prendre le verrou d'écriture du groupe. `Segment.extract_field` désechappe les valeurs
mais lève `IndexError` quand le chemin dépasse une feuille : chaque lecture est protégée.
`Message.create_ack` n'écrit ni ERR ni MSA-3 : l'ACK est construit par HospitalOS.

## Correspondance avec le modèle de données

| Mouvement | `ed_visits` | `stays` | `beds` |
|---|---|---|---|
| A04 (E) | créé : `arrived_at` | — | — |
| A02 sur un passage en cours | `admit_decision_at`, `target_pool_id` (si l'UF n'est pas les urgences) | — | — |
| A06 | `left_at`, `outcome = hospitalise`, décision = A06 si absente ; `target_pool_id` garde l'unité de la décision, sinon l'unité d'admission | créé, `admission_mode = urgences` | lit occupé |
| A01 | si un passage est ouvert pour la même venue : clos « hospitalisé » ; l'unité cible reste celle de la décision (patient hébergé s'il est admis ailleurs) | créé (`admission_mode` = urgences si passage, sinon vide) | lit occupé |
| A02 sur un séjour | — | `site_id`, `mention`, `bed_id` changent ; `admission_date` = entrée dans l'unité ; `admitted_at` reste l'admission | ancien lit `a_nettoyer`, nouveau `occupe` |
| A03 sur un séjour | — | `discharged_at`, `discharge_date` ; `bed_id` vidé | `a_nettoyer`, `stay_id` vidé |
| A03 sur un passage | `left_at`, `outcome` (PV1-36, `sortie` par défaut) | — | — |
| A21 / A22 | — | inchangé | reste `occupe`, `status_reason` = « Absence provisoire (lit conservé) » / vidé |
| A11, A12, A13, A52, A53, A07-CANCEL | état d'avant | état d'avant | lit quitté par annulation → `libre` |
| Z99 | état recalculé | état recalculé | lit corrigé → `libre` |

Toujours : `source = hl7` (ou `agent`), `encounter_ref` = HMAC du NDA, `patient_ref` = HMAC
de l'IPP, `patient_sex`, `patient_age`.

**Pseudonymes et empreintes** (`domain/pseudonym.py`). Une clé par groupe et par usage,
dérivée de `ADM_PSEUDONYM_SECRET` par HKDF-SHA256 (RFC 5869, sel fixe,
`info = hospitalos/v1/<usage>/group/<id>`). Pseudonyme = HMAC-SHA256(clé « pseudonym » du
groupe, `type ␟ domaine ␟ valeur`), où le domaine est l'autorité d'affectation de
l'identifiant (PV1-19.4 pour le NDA, PID-3.4 pour l'IPP ; identifiant universel HD-2,
sinon espace de noms HD-1), ou à défaut le `source_system` (cas de l'agent) : deux
établissements qui émettent le même NDA donnent deux venues. Un mouvement dont le patient
diffère de celui déjà enregistré pour la venue est refusé (AE, ERR PID^1^3, sans valeur en
clair). Changer la règle de domaine, la dérivation ou la version (`VERSION`) change toutes
les références : c'est sans conséquence tant que rien n'est publié ; après, il faudra un
plan de migration. L'empreinte du journal est un HMAC-SHA256 avec la clé « digest » du
groupe : du message ER7 (encadrement MLLP retiré, fins de segment normalisées), ou du JSON
de l'agent après remplacement de l'IPP et du NDA par leurs pseudonymes (l'âge, qui dépend
du jour de lecture, n'y entre pas).

**Comment l'état d'avant revient.** Le journal `movements` est la vérité. Pour chaque
venue, les mouvements effectifs (`applied`, `INSERT`) sont rejoués dans l'ordre de
réception (`hl7_pam.project`) et les tables sont alignées sur le résultat. Une annulation
passe le mouvement visé à `cancelled` puis rejoue ; une correction modifie le mouvement
visé puis rejoue. Un mouvement incohérent avec l'histoire (sortie sans séjour, double
admission…) est refusé (AE) et rien n'est modifié (point de sauvegarde SQL).

**Idempotence.** Unicité (`group_id`, `source_system`, `message_control_id`) : un message
renvoyé à l'identique (même empreinte) reçoit AA « déjà reçu » sans effet ni nouvelle
ligne ; le même MSH-10 avec un autre contenu reçoit AE « MSH-10 réutilisé avec un contenu
différent » (ERR MSH^1^10) et la rejection est journalisée sur sa propre ligne (identifiant
suffixé par le début de l'empreinte), le mouvement d'origine restant intact. Deux envois
simultanés du même MSH-10 : le second obtient AA « déjà reçu » (l'identifiant est réservé
avant d'appliquer le mouvement). Le même mouvement (même ZBE-1, même événement, même action,
entrée ou annulation) sous un nouveau MSH-10 est journalisé `duplicate`, sans effet. Un
message `rejected` renvoyé avec le même MSH-10 (après correction du paramétrage) est
retraité. Côté agent, `/api/ingest/movements` valide chaque élément séparément : un
résultat par élément, une ligne invalide ne bloque pas les autres.

**Résolution de l'unité et du lit.** Site : FINESS de PV1-3.4 (`sites.finess`), sinon le
site unique du groupe, sinon le site de l'unique unité portant ce code UF dans le groupe
(cas de la démo, dont les sites n'ont pas de FINESS). Unité : `bed_pools.uf_code` dans ce
site. UF inconnue ou ambiguë → AE avec un message qui dit quoi renseigner. Lit : libellé
`PV1-3.3`, puis chambre + lit, puis chambre seule (chambre individuelle), dans le site ;
lit inconnu → mouvement appliqué sans lit, avec un avertissement.

**Contraintes de lit.** Le patient est physiquement là : le mouvement est appliqué et le
conflit est écrit dans `movements.error` (et le texte de l'ACK) : lit réservé à l'autre
sexe, chambre partagée avec un patient de l'autre sexe (même règle que le plan des lits,
`domain.beds.accepted_sexes`), lit occupé par un autre séjour ou lit bloqué (séjour alors
enregistré sans lit ; le blocage reste, le lit ne redevient pas « libre » à la sortie).

## Hypothèses (choix faits là où la norme ne tranche pas pour notre usage)

1. **Décision d'hospitalisation aux urgences** : aucun événement PAM dédié. Retenu : un A02
   sur une venue dont le passage est en cours, vers une UF qui n'est pas celle des urgences,
   marque la décision et l'unité cible ; le patient reste aux urgences jusqu'à l'A06. Sans
   un tel A02, l'heure de l'A06 sert de décision. Règle isolée dans `project` (branche A02).
2. **Mutation = même séjour.** Une venue (NDA) = un séjour (index unique `uq_stays_encounter`) ;
   l'ancienne unicité (`site_id`, `patient_ref`, `admission_date`) ne vaut plus que pour les
   séjours saisis ou importés (index partiel `encounter_ref IS NULL`) : une réadmission le
   même jour sous un nouveau NDA est un second séjour. `admission_date` devient l'entrée
   dans l'unité courante : le modèle de durée de séjour
   par unité (`domain/forecast.py`) mesure ainsi le temps passé dans l'unité, ce qui prédit
   la libération du lit. Revers : l'historique d'occupation de l'unité quittée, recalculé
   depuis `stays`, perd les jours avant la mutation ; le journal garde le parcours complet.
3. **UF de ZBE-7** : composant XON-10 (identifiant d'organisation), d'après la forme usuelle
   `libellé^^^^^^UF^^^code` ; non vérifié dans le tableau du §6.13 (non extrait).
4. **PV1-36** : codes PMSI de mode de sortie (6 mutation, 7 transfert, 8 domicile,
   9 décès) ; autre valeur ou absence → `sortie`. Non vérifié dans la table du §6.10.
5. **Heures sans fuseau** : heure légale de `ADM_TIMEZONE` (Europe/Paris). Une heure
   ambiguë au passage à l'heure d'hiver est lue comme la première occurrence ; une heure
   inexistante au passage à l'heure d'été (02:30 le dernier dimanche de mars) est lue avec
   le décalage d'hiver (01:30 UTC, soit 03:30 heure d'été). Épinglé par un test.
6. **Encodage** : UTF-8, sinon ISO 8859-1 (fréquent dans les flux français) ; MSH-18 n'est
   pas lu.
7. **A04 sans PV1-2 = E** (consultation externe) et **A07 sans CANCEL** : ignorés.

## Limites

- Seul le dernier mouvement effectif d'une venue peut être annulé ; les annulations et
  insertions de mouvements historiques (option *Historic Movement*, ZBE-5 = Y) sont
  refusées (AE), sauf la correction Z99 d'un mouvement passé.
- Ordre : les mouvements sont appliqués dans l'ordre de réception ; les dates viennent de
  ZBE-2/EVN. Un message arrivé avant celui dont il dépend (A03 avant A01) est refusé (AE) ;
  l'émetteur doit le renvoyer (comportement habituel des EAI sur AE).
- Pas de MLLP natif côté API (HTTP seulement) ; l'encadrement MLLP est seulement toléré.
- Taille maximale d'un message : 64 Ko (`ADM_HL7_MAX_BYTES`). Lot JSON : 500 mouvements.
- Fusions et changements d'identité (A40, A47, ITI-30) non traités.
- L'empreinte du message conservée pour l'audit est un HMAC à clé dérivée (voir
  « Pseudonymes et empreintes ») : sans la clé, impossible de la recalculer pour tester
  des identifiants candidats. (Une version précédente gardait un SHA-256 non clé et
  affirmait à tort qu'il ne permettait pas de retrouver un identifiant : le JSON de
  l'agent, court et prévisible, le permettait.)
