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
