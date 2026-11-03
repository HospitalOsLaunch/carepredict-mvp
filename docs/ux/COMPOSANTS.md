# Composants de l'interface : shadcn/ui

L'interface web (`services/admissions_web`) adopte [shadcn/ui](https://ui.shadcn.com) :
des composants accessibles (Radix UI) dont la source vit dans le dépôt, stylés avec
Tailwind et les jetons HospitalOS (`tailwind.config.cjs`). Ce n'est pas une dépendance
qui impose son style : on possède le code, et on l'adapte.

## Ce qui est en place

| Fichier | Rôle |
|---|---|
| `components.json` | Configuration shadcn (alias `@/components`, `@/lib/utils`, icônes lucide) |
| `src/lib/utils.ts` | `cn()` : combine les classes, la dernière l'emporte, jetons `rounded-panel`, `rounded-chip`, `shadow-lift` compris |
| `src/components/ui/button.tsx` | `Button` : variantes `primary`, `sun`, `dark`, `quiet`, `ghost`, `danger` ; tailles `default`, `sm`, `icon` ; `asChild` pour un lien du routeur |
| `src/components/ui/badge.tsx` | `Badge` : tons `neutral`, `violet`, `lagoon`, `lagoon-solid`, `coral`, `coral-solid`, `sun`, `ink` (tous AA) |
| `src/components/ui/dialog.tsx` | `Dialog` (Radix) : focus piégé puis rendu, Échap et le fond ferment, page masquée aux lecteurs d'écran |
| `src/components/ui/sheet.tsx` | `Sheet` : panneau qui glisse depuis un bord (le « Plus » du menu mobile) |

Déjà migrés : `Modal` (toutes les boîtes de dialogue de l'application, même interface),
`StatusChip` (sur `Badge`), le panneau « Plus » du menu mobile (sur `Sheet`), les boutons
de l'écran Agents (sur `Button`). Les composants maison restent dans
`src/components/common.tsx` (`Spinner`, `ErrorNote`, `PageHeader`, `Modal`, `Empty`…).

## Règles

- **Nouveau code** : `Button`, `Badge`, `Dialog`, `Sheet` plutôt que les classes `.btn-*`,
  `.chip` ou un `<dialog>` écrit à la main.
- **Code existant** : les classes `.btn-*` et `.chip` (`src/index.css`) restent valides et
  ont le même rendu ; on migre un écran quand on y travaille, pas en masse.
- **Couleurs** : uniquement les jetons (`ink`, `violet`, `sun`, `coral`, `lagoon`, `sky`,
  `paper`, `line`) ; les variantes des composants respectent le contraste AA (audit dans
  `UX_REVIEW.md`).
- **Tactile** : la classe `touch-target` (dans `Button` et les fermetures) garantit 44 px
  sur écran tactile.
- **Mouvement** : animations d'entrée et de sortie de `tailwindcss-animate`
  (`data-[state=open]:animate-in`…) ; `prefers-reduced-motion` les coupe (règle globale).

## Ajouter un composant

```bash
cd services/admissions_web && npx shadcn@latest add tooltip
```

Puis remplacer ses couleurs par les jetons (pas de `bg-primary`, `text-muted-foreground` :
le projet n'utilise pas les variables CSS de shadcn, `cssVariables: false`). Si le
registre shadcn n'est pas joignable (réseau filtré), copier la source du composant depuis
la documentation : c'est le principe de shadcn/ui.
