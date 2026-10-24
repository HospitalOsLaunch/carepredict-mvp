# Système visuel du cockpit

## Intention

- **Qui** : gestionnaire de lits à son bureau, téléphone qui sonne, deux écrans ;
  cadre de santé en mouvement, sur tablette ou téléphone, entre deux transmissions.
- **Verbe** : débloquer une sortie ; attribuer un lit.
- **Sensation** : un tableau des lits bien tenu un matin calme. Dense mais lisible,
  jamais alarmiste. La couleur signifie un état, jamais une décoration.

## Monde de référence

Tableau des lits émaillé et ses aimants, blouses vert bloc, sacs de linge jaunes,
lino gris-vert, étiquettes rouges réservées à l'urgence.

## Signature

1. **La chaîne de libération** : cinq maillons par sortie, le maillon manquant saute
   aux yeux, et le lit libéré est relié aux patients qui pourraient le prendre.
2. **L'encre qui pâlit** : chaque information porte son âge ; vieillissante elle se
   souligne en pointillés, périmée elle passe en ambre et l'aimant se hachure.
3. **Les aimants** : le tableau des lits reprend l'objet physique de l'unité.

## Défauts rejetés

| Défaut | Remplacé par |
|---|---|
| Rangée de tuiles KPI | Une phrase de situation |
| Bleu médical + blanc | Encre ardoise sur émail, un seul accent vert bloc |
| Barre latérale d'icônes | Trois sections, barre d'onglets en bas sur mobile |
| Tableau de lits générique | Aimants, état par couleur + libellé + motif |

## Jetons

| Rôle | Clair | Sombre (garde de nuit) |
|---|---|---|
| `--board` page | #edf0ee | #0d1311 |
| `--sheet` panneau | #fbfcfb | #141c19 |
| `--well` encart | #e3e8e5 | #1b2521 |
| `--ink` / `-2` / `-3` / `-4` | #15201d / #3c4945 / #59655f / #8b9692 | #e5ebe8 / #b9c4bf / #8f9b96 / #66726d |
| `--bloc` utilisable, action | #1b6a55 | #57b898 |
| `--sac` à faire, ancien | #8f5606 (texte), #d99a2b (trait) | #e6aa4c |
| `--alerte` bloqué | #a3302a | #f08a7e |
| `--magnet` lit occupé | #2a3834 | #c9d4cf |

Contrastes texte vérifiés ≥ 4,5:1 sur leur surface ; `--ink-4` réservé aux traits.

- **Type** : Atkinson Hyperlegible Next (auto-hébergée, aucun appel externe),
  chiffres tabulaires partout. Échelle 1,25 sur 15 px : 12 · 13,5 · 15 · 19 · 23 · 29 · 36.
- **Espacement** : base 4 px ; panneaux 16–20 px ; densité « établi ».
- **Profondeur** : bordures et variations de surface uniquement, pas d'ombres.
- **Rayons** : 4 (contrôles, aimants) · 8 (panneaux) · 12 (dialogues).
- **Mouvement** : < 200 ms, `cubic-bezier(0.23, 1, 0.32, 1)`, transform/opacité
  seulement, désactivé sous `prefers-reduced-motion`.

## Composants récurrents

- Bouton : 44 px de haut, 0 16 px, rayon 4, 15/600 ; primaire vert bloc, un seul par vue.
- Maillon : pastille 22 px ; fait (plein), à faire (ambre + horloge), bloqué (rouge + croix),
  inconnu (hachuré + ?), non requis (pointillé + tiret). Libellé texte toujours présent.
- Aimant : ≥ 64 px de haut, identifiant 15/700, état 12 px, badge O₂, trait bas de sortie.
- Barre de comparaison : 8 px, extrémité arrondie 4 px ancrée à la base, trait de pire décile.

## Sources de méthode

Skills de conception appliqués : `anthropics/skills` frontend-design,
`Dammyjay93/interface-design`, `vercel-labs/agent-skills` web-design-guidelines,
`wondelai/skills` ux-heuristics, `nextlevelbuilder/ui-ux-pro-max-skill` (priorités
accessibilité/tactile ; sa palette « bleu médical » a été écartée comme défaut).
