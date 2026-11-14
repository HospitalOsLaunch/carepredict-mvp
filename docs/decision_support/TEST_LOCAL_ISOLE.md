# Tester le prototype d'aide à la décision sur votre machine, isolé du projet computer use ARS

Ce kit installe **uniquement** la branche `claude/hospitalos-auto-first-p0-p4-s2dywn` (aide à la
décision « auto d'abord », cockpit « Plan 24 h ») dans **son propre dossier**, avec **son propre
environnement Python** et des **ports distincts**. Il ne récupère ni ne modifie la branche
`mvp/computer-use` (projet computer use pour l'ARS Hauts-de-France), ni son dossier, ni ses
dépendances.

- Données **synthétiques** uniquement.
- Aucune connexion à un système hospitalier : le bouton « Valider » du cockpit est une validation
  de démonstration.
- Le seul accès réseau est l'installation des dépendances. Statut : `PROTOTYPE_UNVALIDATED`,
  `clinical_validation=false`.

## 0. Règles d'isolement

| Ce qui est séparé | Comment |
|---|---|
| Code | clone **à branche unique** (`--single-branch`) dans un **dossier neuf** ; ne jamais faire `git checkout mvp/computer-use` dans ce dossier |
| Python | environnement virtuel `.venv-decision` **dans** ce dossier |
| Node (cockpit React, facultatif) | `node_modules` propre à `web/` de ce dossier |
| Ports | moteur de décision **8765**, cockpit React **5180** ; si le projet computer use utilise déjà un de ces ports, ne pas lancer les deux en même temps (§ 4) |
| Données | fichiers synthétiques du dépôt uniquement ; rien n'est lu dans le dossier du computer use |

Prérequis : `git`, **Python 3.11** (référence produit 3.11.9 ; environnement testé ici : 3.11.18)
et, pour le cockpit React seulement, Node ≥ 18.

## 1. Récupérer la branche dans un dossier séparé

macOS / Linux :

```bash
cd ~                                   # ou tout dossier HORS de celui du computer use
git clone --single-branch --branch claude/hospitalos-auto-first-p0-p4-s2dywn \
    https://github.com/HospitalOsLaunch/carepredict-mvp.git hospitalos-aide-decision
cd hospitalos-aide-decision
git branch -a                          # ne doit montrer que claude/hospitalos-auto-first-p0-p4-s2dywn
```

Windows (PowerShell) :

```powershell
cd $HOME
git clone --single-branch --branch claude/hospitalos-auto-first-p0-p4-s2dywn `
    https://github.com/HospitalOsLaunch/carepredict-mvp.git hospitalos-aide-decision
cd hospitalos-aide-decision
```

Ne pas utiliser `--depth` : certains tests comparent le moteur au commit de référence v6
(`856a57c`), qui doit être présent dans l'historique.

## 2. Environnement Python propre au prototype

macOS / Linux :

```bash
python3.11 -m venv .venv-decision
source .venv-decision/bin/activate
python -m pip install -r evidence/decision_support/p5/py311_venv_freeze_postD14.txt
export PYTHONPATH=src:.
export P5_VENV="$PWD/.venv-decision"     # utilisé par les tests de contrôle P5
```

Windows (PowerShell) :

```powershell
py -3.11 -m venv .venv-decision
.\.venv-decision\Scripts\Activate.ps1
python -m pip install -r evidence/decision_support/p5/py311_venv_freeze_postD14.txt
$env:PYTHONPATH = "src;."
$env:P5_VENV = "$PWD\.venv-decision"
```

Le fichier de gel installe exactement les versions de l'environnement de test : pydantic 2.14.3,
numpy 2.4.6, pytest 8.4.2, jsonschema 4.26.0, et, pour les scripts P5b, scikit-learn 1.8.0 et ses
dépendances. Pour le cockpit et les tests P0–P4 seuls, `pydantic numpy pytest jsonschema` suffisent.

## 3. Vérifier que tout fonctionne (tests)

```bash
python -m pytest -q tests/decision_support     # moteur, contrats, planificateur, cockpit autonome
python -m pytest -q tests/p5                   # générateur, adaptateur, analyses et contrôles P5 (87 tests)
```

- Un test de restauration est ignoré hors d'un paquet restauré : c'est attendu.
- Sous Windows, quelques tests P5 qui vérifient le chemin exact de l'interpréteur
  (`.venv-decision/bin/python`) peuvent échouer, car l'interpréteur s'y trouve dans `Scripts\`.
  Ce n'est pas un défaut du moteur.
- Un essai rapide de la recommandation automatique, sans interface :

```bash
python -m hospitalos.decision_support recommend tests/decision_support/fixtures/nominal_auto.json
python -m hospitalos.decision_support simulate  tests/decision_support/fixtures/scenario_x1x2.json
```

## 4. Tester le cockpit

### 4a. Cockpit autonome (le plus simple, sans Node)

```bash
python web/decision/serve.py --port 8765
```

Ouvrir **http://127.0.0.1:8765/**. Le serveur n'écoute que sur la machine locale. Arrêt :
`Ctrl-C`.

À l'ouverture, la **recommandation automatique** est calculée sur l'instantané synthétique, sans
scénario à saisir. On peut ensuite passer en **mode manuel** pour verrouiller des hypothèses (par
exemple X1/X2) et comparer.

Si le port 8765 est déjà pris par autre chose, choisir un autre port (`--port 8790`) : le cockpit
autonome n'en dépend pas.

### 4b. Cockpit React, route « Plan 24 h » (facultatif)

Dans un **deuxième terminal**, depuis le même dossier, le moteur de 4a restant lancé sur **8765** :

```bash
cd web
npm ci                                      # installe node_modules dans CE dossier uniquement
npm run dev -- --port 5180 --strictPort     # port distinct de celui d'un autre projet Vite
```

Ouvrir **http://localhost:5180/#/plan**.

Le cockpit React attend le moteur sur **8765** (configuration `web/vite.config.ts`). Si ce port
est occupé par le projet computer use, arrêter celui-ci pendant le test plutôt que de modifier la
configuration.

## 5. Désinstaller

Supprimer le dossier `hospitalos-aide-decision`. Rien n'est installé ailleurs : pas de paquet
global, pas de service.

## Ce que ce prototype est, et n'est pas

- Moteur explicite v6 : il observe l'instantané, anticipe 24 h, propose un plan, et accepte
  ensuite des hypothèses manuelles.
- Les expériences P5 restent synthétiques :
  - P5a : gain du planificateur contre la pratique habituelle, lecture exploratoire ;
  - P5b : pas de gain suffisant de la représentation enrichie.
- Rapports : `docs/decision_support/`.
- Ce n'est **pas** un outil validé pour un usage hospitalier : `G2=NO-GO`,
  `clinical_validation=false`.
