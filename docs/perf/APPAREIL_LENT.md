# HospitalOS sur un téléphone moyen et un réseau lent

Règle 31 de l'audit de performance : on ne juge pas la vitesse sur le poste du
développeur. Le cadre de santé ouvre HospitalOS sur une tablette au chariot ou sur son
téléphone, sur un Wi-Fi d'étage qui faiblit au bout du couloir.

## L'outil

`tools/slow_device_check.py` ouvre l'application comme ce cadre : Chromium réel, écran de
390 px, tactile, processeur ralenti, réseau limité. Il se connecte, puis rouvre chaque
écran quotidien. Il n'écrit que des durées et des tailles, rien de ce qui est affiché.

```bash
python tools/slow_device_check.py --web http://127.0.0.1:8080
```

```bash
python tools/slow_device_check.py --web http://127.0.0.1:8080 --profile 3g
```

| Profil | Processeur | Aller-retour | Débit | Budgets |
|---|---|---|---|---|
| `mobile` (référence, celui de Lighthouse) | ×4 plus lent | 150 ms | 1,6 Mbit/s | vérifiés, en CI |
| `3g` (vieille tablette, signal faible) | ×6 plus lent | 300 ms | 0,75 Mbit/s | informatif |

La CI le lance sur la démo complète (`docker-compose.demo.yml`, nginx réel), après
`demo_check.py`. Un budget dépassé fait échouer le job.

| Budget (profil `mobile`) | Seuil | Pourquoi |
|---|---|---|
| LCP de la page de connexion | 4 s | au-delà, les Core Web Vitals le jugent « mauvais » |
| JavaScript de la première visite | 150 Ko compressés | attrape un écran ou une bibliothèque qui revient dans le fichier principal |
| Premier écran après la connexion | 6 s | |
| Chaque écran quotidien prêt (titre affiché, plus de squelette) | 5 s | |
| CLS de chaque écran | 0,1 | seuil « bon » des Core Web Vitals |

## Mesures du 4 novembre 2026

Build de production, compression comme nginx, démo LISCOP (CH Deux-Rivières), compte
du gestionnaire de lits.

**Première visite, profil `mobile` :** page de connexion affichée en 1,3 s (LCP), 97 Ko
de JavaScript ; premier écran prêt 1,6 s après « Se connecter ».

| Écran | Prêt | LCP | CLS | Blocage du processeur |
|---|---|---|---|---|
| Plan des lits | 1,0 s | 0,7 s | 0 | 0,3 à 0,4 s |
| Urgences et tension | 0,9 s | 0,7 s | 0 | — |
| Demandes | 1,0 s | 1,0 s | 0 | — |
| **Lits et sorties** | **2,3 à 2,6 s** | 0,7 s | 0,006 | **1,3 s** |
| Vue groupe | 1,5 à 2,0 s | 1,6 à 2,1 s | 0 | — |
| Prévision | 1,0 s | 0,8 s | 0 | — |
| Agents | 1,2 s | 1,0 s | 0,051 | — |

Profil `3g` : connexion en 2,3 s, Lits et sorties prêt en 3,5 s (2,1 s de blocage), les
autres écrans entre 1,5 et 2,2 s.

## Ce que ces tests ont trouvé

| Constat | Visible seulement sur | Suite |
|---|---|---|
| Demandes : la liste descendait de 46 puis 94 px pendant le chargement (CLS 0,20). Les filtres prenaient la largeur de leur plus longue option, et le titre arrivait après la liste | le téléphone | **corrigé** : filtres à largeur fixe, place du titre réservée (CLS 0,005) |
| Lits et sorties : une image vide entre la liste des sites et le premier site | un processeur lent | **corrigé** : le site affiché est choisi pendant le rendu |
| Lits et sorties : 1,3 s de processeur bloqué pour afficher les 120 lignes des patients présents | un processeur lent | règle 23 (virtualisation des longues listes) |
| Vue groupe : `/api/dashboard` met 450 ms côté serveur ; `/api/stays` 400 ms ; `/api/requests?scope=a_traiter` 300 ms pour une liste vide | tous, mais plus sensible en 4G | règle 18 : les traces diront où passe ce temps avant d'y toucher |
