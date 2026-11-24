# Système visuel du cockpit

La charte complète (plateforme de marque, voix, logo, jetons, composants) vit dans le
design system « HospitalOS » ; ce fichier en résume ce qui touche le code. Logo : `public/brand/`,
régénérable par `python web/dev/build_brand.py web/public/brand`.

## Direction « Lumière »

Une bouffée d'air et de lumière pour les cadres et les gestionnaires de lits : fond « Air »
(#f4f7ff) éclairé d'un halo soleil en haut de page, cartes blanches à l'ombre douce, encre
« Nuit » (#121a3a), une marque « Outremer » (#3047e6) qui agit, un « Soleil » (#ffb61a) qui
montre ce que touche la proposition, et des états francs : Menthe (prêt), Abricot (à faire),
Framboise (bloqué). Titres et chiffres en Lexend, texte et identifiants en Atkinson
Hyperlegible Next. Formes douces (6 / 14 / 20 px, pilules).

## Logo

Deux lits, et entre eux un soleil qui se lève : la place qui se libère laisse entrer la
lumière, et l'ensemble dessine le H. Pilules en `--brand`, soleil en `--sun`. Logotype Lexend
600 vectorisé. Zone de protection : le diamètre du soleil. Minimum : 16 px (favicon), 96 px en
horizontal. Au chargement, le soleil se lève une fois (700 ms, coupé sous reduced-motion).

## Voix

Chaleureuse, claire, encourageante : « Bonjour. Voici votre unité à 08:30. »,
« C'est vous qui décidez. », « Merci, c'est noté. », « Tout roule. », « Pas de proposition pour
l'instant. Mieux vaut ne rien proposer que se tromper. » Signature : « Libérer. Attribuer.
Respirer. »

## Sobriété sous tension

Une seule chose forte par écran : la carte « Action suivante ». Tout le reste se lit en
chiffres et en mots courts.

- Pas de phrase là où un chiffre suffit : compteurs à côté des titres (« Libérer 5 »), bande de
  tension en valeur + deux mots, fraîcheur de la proposition dans le bandeau.
- Carte proposition : titre, deux faits concrets au plus, l'effet en grand, deux boutons. La
  méthode de simulation passe en infobulle et dans le détail.
- Étiquettes des maillons de sortie une seule fois en tête de colonne ; « Libère L02 pour… »
  seulement sur la sortie concernée ; l'âge d'une information seulement quand elle vieillit.
- Raccourcis clavier affichés seulement après la première touche utilisée (`?` les liste).
- Démonstration signalée par une étiquette discrète, pied de page sur une ligne.

## Cycle de vie d'une proposition

HospitalOS propose, la personne décide et agit ; l'outil garde la trace. Valider n'envoie rien.

```
proposée ──Valider (O)──▶ validée, à faire ──C'est fait (F)──▶ faite
    │                          └──Finalement non + motif──▶ finalement non
    ├──Refuser (N) + motif (1–6)──▶ refusée
    ├──Choisir plutôt une autre option──▶ refusée (« autre option préférée ») + option validée
    ├──fraîcheur dépassée──▶ sans réponse
    └──nouvelle évaluation de l'unité──▶ remplacée
```

- **Une réponse en un geste** : `O` valide, `N` puis `1`–`6` refuse avec un motif. Chaque pas
  s'annule (bouton « Annuler » dans la carte et dans le toast, 6 s).
- **Après validation** : la carte passe en abricot « Validée, à faire » et dit quoi faire hors
  outil (« Appelez le transport pour P-0412. »). « C'est fait » la passe en menthe et invite à
  réévaluer : l'état de l'unité a changé.
- **Après refus** : le motif s'affiche, une note libre peut le préciser pour l'équipe, et les
  autres options utiles s'ouvrent.
- **Plusieurs propositions** : la carte garde la première, la plus utile ; « N autres options
  utiles » liste celles qui battent « ne rien faire » sans enfreindre de règle (simulées une à une,
  effets non cumulables). Une option validée et non faite reste visible sous la carte
  (« En cours de votre côté ») pendant que de nouvelles propositions arrivent. Entre unités, le
  sélecteur et le badge « Journal » comptent ce qui reste à faire.
- **Journal des décisions** (`J`) : « À suivre » (à faire et en attente, toutes unités),
  « Historique » filtrable (recherche patient, lit, personne, motif ; unité ; période ; moi ou
  tout le monde ; statut), une fiche par décision avec sa chronologie (qui, quand, motif, notes)
  et un lien partageable `#/journal/<id>`, « Transmission » à copier et export CSV. Les décisions
  sont signées (nom et rôle). Prototype : le journal vit sur le poste ; le partage entre collègues
  passe par l'API (README, « Suite côté API »).

## Provenance des décisions

Une décision dit toujours d'où elle vient et sur quoi elle porte.

- **Deux journaux, jamais mélangés** : celui de l'unité en observation (`hospitalos.journal.v2.live`)
  et celui de la démonstration (`…v2.demo`). Chaque fiche porte son origine (unité en observation,
  démonstration, plan 24 h) et l'empreinte de l'état évalué ; l'origine fait partie de
  l'identifiant. En connexion directe, un sélecteur permet de consulter le journal de démonstration
  sans le confondre. L'ancien journal sans origine (`v1`) est rangé côté démonstration, marqué
  « origine non enregistrée ».
- **Un rejeu n'est pas l'unité** : la situation enregistrée rejouée sur patients fictifs s'appelle
  « Observation rejouée » et propose « Recalculer », jamais « Évaluer maintenant ».
- **Destination explicite** : un lit d'une autre unité est nommé avec son unité ; un renfort prêté
  nomme l'unité qui prête (« prêté par … ») ; un lit n'est « prêt » que pour le premier patient de
  la file, les suivants lisent « L08 ira d'abord à U-1043 ».
- **Base de chaque action du plan 24 h** : autorisation médicale observée, consigne validée,
  hypothèse, option de renfort — chacune son étiquette.

## Horloge de démonstration

Chaque plan d’unité conserve son heure de relève, son empreinte et les dates civiles des
créneaux. Les situations de démonstration se rejouent à cette origine. Les calculs API
utilisent les dates d’observation reçues.

## Motif de refus

Refuser une action ou un plan, c'est un appui et un motif (1 à 6), puis une note facultative.
Même liste pour les deux, sauf le n° 5 : « Lit inadapté » pour une action, « Inadapté à l'unité
(effectif, compétences, règles) » pour un plan. Aucun texte n'impose de nomenclature ; l'AI Act
demande de pouvoir écarter la sortie du système et d'en suivre l'usage (art. 14 §4, art. 26 §5),
le guide HAS/CNIL sur l'IA en contexte de soins (document de travail, février 2026) demande le
contrôle humain et la traçabilité des usages. Le motif rend les refus lisibles sans ralentir.

## Plan à 24 h

Le profil versionné `HYBRID_UNIT_PLAN_1` identifie ce contrat API.
Le sélecteur d’unité reste actif dans toutes les focales. Action et Plan lisent le même
`plan_id` de `hybrid.plan`, la même relève et la même empreinte. Une demande déjà
programmée figure aussi dans le témoin. Le renfort mobilise une personne confirmée,
pour une compétence, une unité et une fenêtre identifiées. Les deux gestes sont
combinables avec le transport, le nettoyage et la réservation. Les réponses humaines
sont enregistrées au même endroit, sur la page de l’unité.

## Bloc Action (retours du 24 novembre au soir)

- **Juste sous « Bonsoir »**, avant la bande de tension : c'est la première chose à faire.
- **Actions évaluées ensemble.** Le planificateur peut combiner transport, bionettoyage,
  réservation de lit, renfort et préparation d’une entrée programmée. Lorsque chaque geste
  isolé laisse l’attente inchangée, il teste les paires admissibles. Une paire initiale ou un
  geste ajouté doit améliorer l’objectif d’au moins 1 % de sa valeur témoin et d’au moins
  une minute d’attente cumulée, en respectant la garde sur les ressources dans chaque scénario.
  Le bloc affiche le gain total et la contribution de chaque geste dans l’ordre évalué.
- **Le gain en heures, avec son unité** : « Ce que vous gagnez d'ici 03:10 — −6 h 06 d'attente en
  moins pour les patients à placer (−27 %) », puis « Sans rien faire 22 h 51 / Avec la proposition
  16 h 45 », et une ligne qui dit ce qu'est l'attente cumulée (somme des attentes, moyenne de
  32 scénarios).
- **Source et fraîcheur au pied du bloc** : heure du calcul, moteur, état utilisé, dernière
  réception, information la plus ancienne, et **Recalculer**.
- **Alternatives visibles**, un cran en dessous (fond plus pâle, bouton secondaire), chacune avec
  son gain seule : plus de repli « 1 autre option utile ».
- **Vide ou en erreur, le bloc rapetisse** : une ligne (« Rien à changer pour l'instant », « Pas
  de proposition pour l'instant ») et « 41 données à vérifier ▾ » replié.

## Toutes les unités

`#/unites` (raccourci T, lien en pied du sélecteur d'unité) : une ligne par unité, la plus tendue
en premier ; à placer (attente max), lits utilisables (à nettoyer), sorties prêtes, action
prioritaire et son gain, état et heure. Une unité aux données douteuses affiche « ? », jamais 0.
Au téléphone, chaque ligne devient une carte.

## Plan : focales

Un seul onglet **Plan**, cinq focales : **Maintenant · 12 h · 24 h · 3 jours · 7 jours**
(`#/plan/<focale>`, 24 h par défaut).

- **Maintenant** : l'action prioritaire du planificateur de l'unité (le même que le bloc Action).
- **12 h et 24 h** affichent l’attente réellement simulée dans chaque fenêtre pour les mêmes gestes.
  Chaque valeur du plan est traçable au reçu moteur par un pointeur JSON `data-src` et sa valeur
  brute `data-raw`. Une nouvelle sélection d’unité invalide le rendu précédent.
- **3 et 7 jours** affichent la perspective non planifiée lorsque la qualification de l’horizon
  ou d’une source manque. L’onglet Données détaille les contrôles.
- Les données de démonstration du moteur d’unité sont rejouées à l’heure d’origine pour préserver
  les identités et les jours civils du planning.

Options explorées pour la flexibilité d'horizon :

| Option | Pour | Contre | Verdict |
| --- | --- | --- | --- |
| Un onglet, des focales (retenu) | les effets d’une même proposition se lisent à plusieurs échéances | les focales longues exigent des sources à jour et une prévision qualifiée | retenu |
| Curseur d'horizon continu (1 h → 7 j) | très flexible | laisse croire qu'un plan existe à chaque heure ; trop fin pour une relève | écarté |
| Un onglet par horizon | lisible séparément | multiplie la navigation ; les plans se contredisent d'un onglet à l'autre | écarté |
| Frise zoomable (type Gantt) | vue d'ensemble des actions dans le temps | lourde au téléphone ; une frise vide au-delà de 24 h trompe | à reconsidérer quand un moteur planifiera sur plusieurs jours |
| Moteur étendu à 3 et 7 jours | projection de l’unité à plusieurs jours | exige quatre sources à jour et les seuils de précision du protocole | implémenté sous conditions, fermé dans les quatre unités du [banc synthétique](../docs/operational/unit-planning-results/README.md) |

## Tests d'usage du 24 novembre 2026

Trois testeurs simulés (gestionnaire de lits, cadre de santé, IDE), au bureau, sur tablette et
au téléphone. Retours appliqués :

- **Jamais de faux zéro** : quand des informations sont périmées ou manquantes, « À placer »,
  « Lits utilisables » et « Sorties » affichent « ? · inconnu » ; plus de « Belle accalmie » sur des
  données douteuses.
- **Le geste se voit** : après « C'est fait », la chaîne de sortie affiche « Transport demandé :
  fait · 16:30 · vous, en attente de confirmation par les données » (et « nettoyage demandé » sur
  le lit) : pas de second appel au transport.
- **Priorité explicite** : « 4/5 », légende « 5 = la plus urgente », saisie par l'équipe ; un lit
  prêt pour un patient plus prioritaire se lit « L08 aussi possible, après U-1043 ».
- **À venir** : les hypothèses déclarées (transport coupé, arrivées des urgences, lit rouvert)
  sous la bande de tension et dans la carte quand elles touchent l'action.
- **Gain faible** dit comme tel ; unité des chiffres sous la comparaison ; « Avis médical attendu :
  voir avec le médecin » (on ne « renseigne » pas une décision médicale).
- **Chiffres et clavier** : un chiffre seul ne change plus d'unité (U puis le chiffre) ; il ne sert
  qu'au motif quand les motifs sont affichés.
- **Plan 24 h** : une décision par plan, conservée au rechargement ; un seul plan validé par unité
  (remplacement confirmé) ; « Choisir plutôt ce plan » pour l'autre plan ; case « J'ai revérifié
  l'autorisation médicale de sortie de … » avant de valider ; statut de confirmation sur chaque
  renfort ; exemples précalculés marqués « imposé dans l'exemple » ; bouton Valider collant au
  téléphone ; plan recalé sur la relève de 20:00 du jour (jamais de sortie à 6 h ni de renfort à
  3 h fabriqués par le recalage).
- **Journal** : chiffres et conditions figés dans la fiche d'un plan ; signature jamais
  rétroactive ; note libre « pour la relève » ; transmission par unité avec l'état de l'unité, les
  notes et les conditions, sans « (vous) » ; rôles IDE et IDE de nuit ; décisions de démonstration
  rattachées à leur situation.
- **Mots** : champs de la source et indicateurs de l'onglet Données en français ; ton factuel
  (« C'est noté. L'état se mettra à jour à la prochaine réception des données. »).

Non traités ici (données ou back-end) : critères de placement au-delà de l'oxygène (sexe,
isolement, chambre seule), journal partagé entre
postes, motif enregistré par le moteur dans son reçu de revue.

## Illustrations

Des illustrations « spot » fines et légères donnent un peu de chaleur au cockpit, comme une
plante sur un bureau (`src/ui/illustrations.tsx`). Une seule grammaire sur une grille de 64 :
un blob doux en teinte lavée (soleil, menthe, lavande ou abricot), un trait d'encre de 1,5 px
qui ne grossit jamais avec la taille, une ou deux aplats de la palette et une étincelle de soleil.

- **Où** : la salutation (fenêtre du matin, lueur du soir, lune et tisane de garde), les trois
  zones (porte entrouverte pour Libérer, lit pour Lits, clé pour Attribuer), la proposition
  (le dessin montre ce qu'elle demande : véhicule, spray de bionettoyage, clé, tasse quand tout
  roule, nuage quand les données manquent), les titres de page et de bloc, les états vides
  (« Belle accalmie. » avec un voilier), l'aide aux raccourcis.
- **Tailles** : 56 px salutation et proposition, 36 px zones, 32 px blocs, 64 px titres de page,
  72 px états vides ; réduites sur téléphone.
- **Règles** : décoratives seulement (`aria-hidden`), jamais porteuses d'information ; toutes les
  couleurs viennent des jetons, donc le thème de nuit suit ; masquées en couleurs forcées. Seul
  mouvement : le soleil du matin se lève et les étincelles s'allument une fois, coupés sous
  reduced-motion.

## Zoning sous tension

1. Barre haute : symbole, sélecteur d'unité avec statut (`U`, `1`–`9`), sections, heure de l'état.
2. Bande de tension : à placer, lits utilisables, sorties, données ; chaque cellule mène à sa zone.
3. Action suivante : titre à l'impératif, effet simulé, deux réponses (`O`, `N` puis `1`–`6`).
4. Flux en trois colonnes, dans l'ordre physique : Libérer → Lits → Attribuer. Sur téléphone,
   un onglet par zone, ouvert sur celle que touche la proposition.

## Intention

- **Qui** : gestionnaire de lits à son bureau, téléphone qui sonne, deux écrans ;
  cadre de santé en mouvement, sur tablette ou téléphone, entre deux transmissions.
- **Verbe** : débloquer une sortie ; attribuer un lit.
- **Sensation** : une fenêtre qu'on ouvre le matin. Lumineux et vivant, dense mais lisible,
  jamais alarmiste. La couleur vive marque un état ou une action, jamais une décoration.

## Signatures du produit

1. **La chaîne de libération** : cinq maillons par sortie, la seule étape manquante à l'impératif.
2. **Le soleil** : tout ce que touche la proposition (sortie, lit) porte l'anneau et le halo `--sun`.
3. **L'encre qui pâlit** : chaque information porte son âge ; périmée, elle passe en abricot.

## Jetons

| Rôle | Clair | Garde de nuit |
|---|---|---|
| `--board` Air | #f4f7ff | #0c1230 |
| `--sheet` carte | #ffffff | #141b3d |
| `--well` encart | #ebf0fb | #1b2450 |
| `--ink` / `-2` / `-3` / `-4` Nuit | #121a3a / #3a4468 / #5a6385 / #98a0bd | #eef1ff / #c3c9e6 / #959cc0 / #67709a |
| `--brand` Outremer, action | #3047e6 | #8b99ff |
| `--sun` Soleil, ce que touche la proposition | #ffb61a | #ffc94d |
| `--bloc` / `--mint` Menthe, prêt | #08754f / #2bd49b | #4fe0ae / #3ddca6 |
| `--sac` / `--sac-mark` Abricot, à faire | #a04d00 / #ff9f43 | #ffb25c |
| `--alerte` Framboise, bloqué | #c81e4a | #ff7a96 |
| `--magnet` lit occupé | #dde3ff | #2a3570 |

Contrastes texte vérifiés ≥ 4,5:1 dans les deux thèmes ; `--ink-4`, `--sun` et `--mint` ne portent
jamais de texte sur fond clair. Audit axe-core : 0 violation.

- **Type** : Lexend 600 (titres, chiffres, logotype) + Atkinson Hyperlegible Next (texte,
  identifiants), auto-hébergées. Échelle 1,25 sur 15 px : 12 · 13,5 · 15 · 19 · 23 · 29 · 36.
- **Espacement** : base 4 px ; cartes 16–20 px.
- **Profondeur** : ombre douce `--lift` + bordure `--line-soft` ; halo `--glow` en haut de page.
- **Rayons** : 6 (aimants) · 14 (cartes) · 20 (dialogues) · pilules (étiquettes, toasts) ; boutons 12.
- **Mouvement** : le soleil se lève au chargement (une fois) ; ailleurs < 200 ms,
  `cubic-bezier(0.23, 1, 0.32, 1)`, transform/opacité, coupé sous `prefers-reduced-motion`.

### Contrôles des quatre sources

Dans Données, chaque horizon a son propre bilan. Le cockpit donne le logiciel,
la version, la réception, la synchronisation, la fin de couverture et les motifs
de rejet. Pour les séjours et les jours d’urgences, le numérateur et le dénominateur
remontent du contrôle backend. Un export complet vide, une panne et un reçu
absent ont des états distincts.

La requête du cockpit demande jusqu’à sept jours. Le serveur retourne la durée
effectivement autorisée, ses fenêtres calculées et les motifs par horizon. La
qualification appartient à la version du prédicteur et au profil synthétique
évalué. Les créneaux du plan conservent leurs dates absolues entre les journées.
