# Hôpital virtuel multi-unités — temps réel et mémoire

`python3 demo.py` ouvre désormais **Hôpital Saint-Clair · virtuel**, un établissement
unique H1 : gériatrie (18 lits), médecine polyvalente (24), pneumologie (15),
chirurgie (21). Les 78 lits sont dotés dans les hypothèses synthétiques. La vue
hôpital agrège les observations des quatre unités ; le sélecteur et les cartes
ouvrent leur cockpit, leurs propositions et leur journal. Patients, lits, sources,
sessions et décisions sont identifiés par unité ; leurs identifiants physiques
sont uniques à l'échelle de H1. Les ressources de nettoyage restent propres à chaque
unité. Les patients en attente peuvent être placés dans une autre unité déclarée compatible,
après accord explicite du cadre receveur. Le transfert de patients déjà installés
n’est pas couvert.

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

Le dossier `.hospitalos-workplace` contient le manifeste de l'hôpital (origine UTC,
graine, configuration), les bases opérationnelles et les bases d'observations et
de modèles par unité. La mécanique WORKPLACE_1 est distincte des anciennes bases `.hospitalos-campus`
et `.hospitalos-virtual` :
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
- `GET /product/hospitals/H1/workspace` : file hospitalière, tâches, capacités, entrées et prévisions.
- `POST /product/hospitals/H1/operations` : commande nommée, révision du journal et
  empreintes des observations concernées ; contrôle métier côté serveur.
- L’ancienne route `POST …/units/{unit_id}/decisions` refuse les commandes H1 afin
  de ne pas contourner le journal hospitalier.
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
mono-processus, sans authentification. Les profils nommés sont des identités de
démonstration sélectionnables, pas une preuve d’identité professionnelle.

Les tests couvrent l'unicité des identifiants, le routage et les décisions par unité,
les périodes d'apprentissage/validation, l'export complet, la persistance du modèle,
le rattrapage après arrêt et le changement d'heure du 25 octobre 2026.


## Priorités du poste intégrées

La revue hostile était simulée : les évolutions ci-dessous ne constituent pas une
validation par de vrais utilisateurs hospitaliers.

| Besoin | Comportement disponible |
| --- | --- |
| Sorties crédibles | Seules les sorties en préparation apparaissent ; autorisation attendue, documents, transport et aval sont distincts. Une absence d’autorisation n’est pas un avis défavorable. |
| Placement hospitalier | File commune, recherche, alternatives par lit et raisons d’exclusion ; une demande attend le cadre receveur avant la réservation et l’installation. |
| Capacité du poste | Le cadre déclare une capacité, un motif et une durée, ou ferme un lit libre. Les patients installés restent en place ; les nouvelles installations sont contrôlées. |
| Travail et relève | Responsable nommé fictif, accord, refus motivé, transmission, relance, échéance et historique. « Pris en charge » et « résultat observé » sont deux états distincts. |
| Admissions prévues | Trois admissions synthétiques par unité chaque jour, à 08 h, 11 h et 15 h de Paris ; visibilité 48 h et protection motivée d’un lit propre. |
| Préparer le prochain poste | Prévisions directes à 8 h et 24 h, plage empirique, capacité déclarée, entrées prévues et sorties en préparation. |

Dans « Travail du poste », choisir l’identité de démonstration adaptée au parcours.
Un bed manager demande un placement, puis le profil du cadre de l’unité receveuse
accepte dans « Relève & suivi ». Sans cet accord, aucune installation ne découle
de la demande ; celle-ci expire après son échéance de suivi et remet le patient
à disposition de l’allocation autonome. Le lit proposé n’est pas immobilisé
pendant l’attente : sa disponibilité et la capacité sont revérifiées à l’accord.
Deux demandes ne peuvent donc pas installer deux patients dans le même lit.

Le cadre de chaque unité peut réduire la capacité jusqu’à zéro, y compris en
dessous de l’occupation actuelle. Les patients restent installés ; les nouvelles
admissions sont bloquées. Les déclarations expirent à l’heure indiquée. Les
versions des déclarations empêchent une ancienne expiration d’annuler une nouvelle
capacité ou une nouvelle fermeture. Les protections d’admission consomment dès
maintenant un lit propre et une place dotée ; ce n’est pas une réservation sur une
sortie future incertaine. Elles ne sont consommables que par le patient nommé.

Les équipes virtuelles de documents, transport et aval accusent réception en
arrière-plan. Les confirmations prennent respectivement 10–20, 30–60 et 60–120
minutes selon les hypothèses déterministes. Les équipes ordinaires continuent
aussi leur travail sans utilisateur. Les confirmations logistiques sont propres au patient : un transport confirmé
pour l’un ne rend pas les autres sorties prêtes. Une tâche ne devient terminée qu’après
observation du résultat ; aucune commande ne délivre une autorisation médicale.

## Durabilité des opérations et limites

`operations.sqlite` conserve chaque commande, son identifiant idempotent, son
heure, son acteur fictif, ses arguments et les observations à l’appui. Le verrou
hospitalier sérialise validation et mutation ; une révision ou une observation
périmée est refusée. Un envoi dont la réponse est perdue peut être retenté avec le
même identifiant sans doubler son effet. La reprise reconstruit les quatre unités
sur une même chronologie, applique les commandes dans l’ordre et retrouve les
tâches ainsi que leurs résultats observés. Les réponses automatiques suivent des
frontières de minute identiques pendant l’exécution et le rejeu.

Les prévisions à 8 h et 24 h sont ajustées séparément sur les observations passées.
Leurs cibles d’entraînement précèdent les cibles de validation. Le choix entre
ridge et persistance et les quantiles d’erreur 10–90 % utilisent la validation
synthétique : la plage affichée n’est pas une garantie de couverture sur des
patients réels ni un test indépendant. Les modèles demeurent figés. Ils ne
simulent pas causalement une nouvelle fermeture, une protection ou une modification
d’effectif ; ces contraintes et les admissions déclarées sont présentées à côté.

La file hospitalière rapproche les observations des unités ; chaque flux conserve
son délai. Les données affichées peuvent donc précéder une déclaration immédiate
pendant un cycle de livraison. La mutation revérifie l’état courant du monde
virtuel. Les 500 dernières tâches et décisions sont exposées au cockpit ; le
journal SQLite intégral reste conservé. Les profils et compatibilités sont
fictifs, sans connexion au SI, authentification, gestion d’astreinte réelle ou
validation clinique. Un état antérieur reste intact mais n’est pas migré vers
WORKPLACE_1 : choisir le nouveau dossier par défaut ou un dossier vide.
