# Hôpital virtuel multi-unités — temps réel et mémoire

`python3 demo.py` ouvre désormais **Hôpital Saint-Clair · virtuel**, un établissement
unique H1 : gériatrie (18 lits), médecine polyvalente (24), pneumologie (15),
chirurgie (21). Les 78 lits sont dotés dans les hypothèses synthétiques. La vue
hôpital agrège les observations des quatre unités ; le sélecteur et les cartes
ouvrent leur cockpit, leurs propositions et leur journal. Patients, lits, sources,
sessions et décisions sont identifiés par unité ; leurs identifiants physiques
sont uniques à l'échelle de H1. Les ressources de nettoyage restent propres à chaque
unité. Les unités ne transfèrent pas encore de patients entre elles.

## Démarrage et continuité

Python 3.11+, Node 22+ et npm. Depuis la racine :

```bash
python3 demo.py
python3 demo.py --check
```

Le premier démarrage construit les 28 jours précédents, archive leurs observations
et ajuste les modèles. Il peut prendre environ une minute selon la machine.
Les démarrages suivants rejouent encore le monde depuis son origine ; ils ne
réentraînent pas les modèles. Le lanceur attend jusqu'à 180 secondes. Une nouvelle
session indépendante peut être créée avec `--state-dir /chemin/nouveau-dossier`.

Le dossier `.hospitalos-campus` contient le manifeste de l'hôpital (origine UTC,
graine, configuration), les bases opérationnelles et les bases d'observations et
de modèles par unité. Il est distinct de l'ancienne démo `.hospitalos-virtual` :
les décisions X1/X2/X3 ne sont pas attribuées arbitrairement à H1. Aucune ancienne
base n'est effacée. La mécanique de reprise conserve les intentions de décision
et leurs preuves, puis les rejoue une seule fois dans chaque reconstruction.

L'horloge produit vaut **1 seconde simulée par seconde réelle**. Les instants sont
stockés en UTC, présentés en `Europe/Paris`, y compris lors des changements été/hiver.
Le cadran montre les secondes ; la date d'observation reste distincte. La veille
et l'arrêt du backend entraînent un rattrapage au redémarrage, sans fabriquer de
décisions humaines pendant l'absence. Le processus ne continue pas physiquement
à tourner lorsque la machine est éteinte. Un recul de l'horloge système ne rembobine
pas des événements déjà exécutés. L'option d'accélération est refusée dans le produit.
Le laboratoire historique reste accessible par `python3 demo.py --lab`.

## Historique réellement utilisé

Le passé et le présent proviennent d'une même trajectoire déterministe par unité,
avec arrivées, séjours, autorisations de sortie, départs, nettoyage et installations.
Les supports de durée sont fictifs, non calibrés cliniquement. Le passé est un
passé **observé par HospitalOS** ; il ne contient pas de fausses décisions attribuées
à des soignants. Le journal des décisions commence lors de l'utilisation effective.

Chaque première observation livrée d'une heure UTC est conservée dans SQLite :
occupation, attente et lits prêts. L'index horaire reste unique au changement d'heure.
Le flux contient son délai de livraison ; l'archive utilise uniquement les exports
observés et ne lit ni états futurs ni tirages cachés. Les observations continuent
à s'ajouter. L'interface présente la moyenne des échantillons par jour parisien
(jours partiels et nombre de mesures indiqués), les dates et l'export CSV intégral.
Ces moyennes horaires ne sont pas des intégrales exactes du temps d'occupation.

## Apprentissage et usage dans le produit

Un modèle **ridge de prévision d'occupation à une heure** est effectivement ajusté
pour chaque unité, avec NumPy (pas de téléchargement de poids ni de service externe).
Ses entrées sont l'occupation observée, les patients en attente et le sinus/cosinus
de l'heure parisienne. Le premier jour de mise en régime est exclu. Les quelque
20 jours suivants fournissent environ 480 paires horaires d'apprentissage ; les
sept derniers jours (168 paires) sont réservés à la validation chronologique.
La cible d'une paire est l'occupation de l'observation horaire suivante.

Les coefficients, périodes, taille des ensembles, erreur absolue moyenne en lits,
comparaison à la persistance et SHA-256 des lignes utilisées sont persistés dans
la table `models`. Le modèle demeure figé après redémarrage. La validation sert
à sélectionner ridge ou la persistance si celle-ci est meilleure ; ce n'est donc
pas un troisième ensemble de test indépendant. L'interface utilise effectivement
la prévision sélectionnée et affiche son heure de départ et son horizon. Elle
présente aussi les résultats défavorables. Il n'y a pas de réentraînement automatique.

Cette prévision ne remplace pas le planificateur hybride des actions : celui-ci
conserve ses hypothèses et son contrat de décision. Il ne s'agit ni d'un world model
JEPA entraîné, ni d'une preuve d'efficacité clinique, ni d'un SI hospitalier réel.

## Routes

- `GET /product/hospitals` : un établissement, quatre unités.
- `GET /product/hospitals/H1/overview` : capacités, occupations et attentes observées.
- `GET /product/hospitals/H1/units/{unit_id}` : cockpit de l'unité.
- `POST /product/hospitals/H1/units/{unit_id}/decisions` : validation/refus avec
  établissement, unité, session, révision et empreinte ; contrôle côté serveur.
- `GET /product/hospitals/H1/units/{unit_id}/history` : série récente, agrégats et modèle.
- `GET /product/hospitals/H1/units/{unit_id}/history/export` : observations complètes CSV.

Une erreur de flux bloque les nouvelles décisions. Une réponse tardive d'une autre
unité ne remplace ni sa situation ni son historique. Les routes de laboratoire ne
sont pas montées dans cette application. Les anciennes routes ambiguës « hôpital/unit »
sont refusées pour H1.

## Portée technique

Le moteur opérationnel évacue les patients sortis après la fenêtre de livraison,
mais conserve encore les journaux de vérité et les primitives en mémoire. La
reconstruction croît avec la durée depuis l'origine : une prochaine étape technique
sera un checkpoint physique sérialisable et versionné, avant un fonctionnement
continu de plusieurs mois. L'archive agrégée est durable ; elle n'est pas un dossier
patient longitudinal ou un entrepôt bitemporel complet. Le lancement est local,
mono-processus, sans authentification ; le signataire reste « Équipe de garde ».

Les tests couvrent l'unicité des identifiants, le routage et les décisions par unité,
les périodes d'apprentissage/validation, l'export complet, la persistance du modèle,
le rattrapage après arrêt et le changement d'heure du 25 octobre 2026.
