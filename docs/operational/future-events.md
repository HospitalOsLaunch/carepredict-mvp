# WM-0 — arrivées et perturbations après D

24 octobre 2026. Extension du prototype hybride en scénarios synthétiques.
Elle qualifie des mécanismes locaux ; aucune prévision d'arrivée, fréquence de
panne, calibration probabiliste ni efficacité réelle n'est établie.

## Frontière d'information

Les faits observés restent des `HYBRID_MVP_2` bitemporels. Le planificateur ne lit
que ceux disponibles à l'origine D. Les événements de scénario sont distincts :
`FutureAssumptions`, version `HYBRID_FUTURE_1`, provenance obligatoirement
`synthetic_hypothesis` et `declared_at <= D`. Les temps sont des minutes après D.
Ce format décrit une hypothèse conditionnelle, pas un calendrier réel importé.
Une déclaration datée à D ne démontre pas à elle seule sa provenance : la
traçabilité d'un futur connecteur restera à qualifier.

Une vague d'arrivées déclare un support discret d'horaires et de volumes, les
unités compatibles, les besoins et une priorité de scénario. Les tirages sont
uniformes sur les entrées du support, répétitions incluses. Aucun paramètre n'est
appris et aucune loi saisonnière/binomiale négative n'est ajustée dans ce lot.
La priorité est une entrée du scénario ; aucun triage clinique n'est calculé.

Les identités des nouveaux patients sont générées avec le préfixe `hypothetical:`.
Ils entrent dans la file à leur arrivée simulée, jamais dans l'état observé ni
dans les cibles des actions immédiates. Leur attente est intégrée à partir de
cet instant. Ils ne peuvent pas repartir pendant l'horizon : la durée de séjour
et la dynamique clinique des nouveaux admis restent hors périmètre.

## Événements pris en charge

| Événement | Effet explicite |
| --- | --- |
| Arrivée | Ajoute des patients à la cohorte et à la file, avec compatibilités déclarées |
| `staffed_beds` | Modifie le plafond de nouvelles admissions ; conserve les patients présents |
| `cleaning_teams` | Modifie le plafond de nouveaux nettoyages ; les nettoyages engagés se terminent |
| `transport` | Modifie le plafond de nouvelles missions ; les missions engagées vont jusqu'au retour |
| `downstream` | Modifie le quota cumulatif de places accessibles à la cohorte depuis D ; les places déjà engagées restent comptées |
| `bed_admissions` | Ferme/réouvre les admissions du lit, sans évacuation ni disparition de patient |

Un changement de quota d'aval de 1 à 0 puis à 1 ne recrée pas une place déjà
consommée. Une augmentation à 2 après une consommation ouvre seulement une
place supplémentaire. Ce quota n'est pas une observation instantanée de places
libres : un connecteur ne doit pas confondre les deux.

Les fermetures concernent l'admission, pas une contamination ou une évacuation.
Un lit occupé reste occupé ; son départ déjà autorisé peut se produire. Un
nettoyage en cours peut se terminer, mais aucune admission ni nouveau nettoyage
n'est engagé sur le lit fermé. La réouverture d'un lit initialement `closed`
le remet à l'état sale pour exiger un nettoyage. Pour un lit dont l'hygiène était
déjà connue, une fermeture des admissions n'altère pas cet état.

Les réservations de lits devenues incompatibles avec une fermeture ou la
capacité sont annulées dans la simulation et journalisées. Les engagements de
plus faible priorité sont retirés en premier, puis départagés par identifiant.
Les patients restent dans la file. Aucune annulation n'est envoyée à un SI.

Les événements exogènes d'un même instant sont tous appliqués avant les fins
de service puis les nouveaux engagements. Deux modifications du même attribut
de ressource au même instant sont rejetées. Une restauration de capacité relance
les files, y compris si la capacité était nulle à D pour une demande déjà attestée.
Une capacité future ne rend pas admissible à D une action dont les prérequis
actuels ne sont pas satisfaits.

## Surcharges et règle de sélection

Une baisse de plafond ne fait pas disparaître les engagements existants. Les
tâches ne sont pas interrompues : c'est une hypothèse de service non préemptif,
pas une simulation d'une équipe qui abandonne physiquement une mission.
La pression excédentaire est mesurée séparément dans quatre unités :

- patients-minutes au-delà de la capacité soignante ;
- équipes-minutes de nettoyage au-delà du plafond ;
- équipes-minutes de transport au-delà du plafond ;
- places-minutes d'aval engagées au-delà du quota.

Ces mesures sont calculées par le notateur à partir des engagements et des
changements de plafond ; elles ne sont pas additionnées dans une unité composite.
Une violation de mécanique désigne, elle, un **nouvel engagement** au-delà du
plafond actif, une admission incompatible, une conservation rompue, etc.
Ainsi, absence de violation mécanique ne signifie pas absence de tension.

Le choix conserve la fonction d'attente moyenne et de pire décile. Avant ce
classement, un candidat est exclu s'il augmente l'une de ces quatre expositions
dans au moins un scénario apparié face à la référence sans intervention. Le
nombre de scénarios concernés figure dans `pressure_regression_scenarios`.
Cette règle conservatrice vaut pour l'échantillon sous hypothèses ; elle ne
constitue ni une garantie de sûreté sur le réel, ni une optimisation clinique.
Une pression restante dans le candidat retenu produit un avertissement explicite.

## Couplage et notateur

Le tirage d'un futur dépend de la graine, du scénario, du mécanisme et de
l'identité de la vague, jamais de l'action. Un `FutureTape` immuable est transmis
au simulateur et séparément au notateur comme registre attendu. Les candidats
partagent les mêmes arrivées et perturbations, même si leurs files et événements
de service évoluent différemment.

Le notateur rejette les arrivées inventées, les événements attendus omis,
dupliqués, décalés ou portant une autre identité. Il vérifie aussi qu'aucune
admission/fabrication d'engagement ne précède les chocs au même instant.
Il ne reconstruit pas la vérité exogène à partir du seul journal généré.
Le contrat et son validateur d'entrée sont partagés ; le déroulement des
ressources reste recalculé séparément.

## Exécuter et inspecter

```bash
PYTHONPATH=src python -m hospitalos.hybrid --demo-future --show-trace
PYTHONPATH=src python -m hospitalos.hybrid --demo-future --show-input > /tmp/future.json
PYTHONPATH=src:. pytest -q tests/hybrid
```

La démo combine indisponibilité du transport, fermeture des admissions d'un lit,
nouvelles arrivées et baisse puis reprise de capacité soignante. Sous ses durées
fixées, le transport démarre à D+120, le nettoyage à D+210 et l'admission suivante
à D+300. Les nouveaux patients restent en attente. La sortie inclut les deux
journaux appariés et le registre exogène du scénario 0 ; aucune comparaison
chiffrée de cette fixture ne doit être présentée comme un bénéfice hospitalier.

Le contrat de réponse est `HYBRID_PLAN_3` ; les faits restent v2. Les anciennes
propositions doivent être régénérées et toute émission inconnue réconciliée.
Les hypothèses de futur font partie de l'identité et du contenu du plan persisté.
`service_status` couvre désormais la file initiale **et les arrivées simulées**.
Un état entièrement servi dans l'échantillon n'est pas une couverture calibrée.

Limites de calcul : 24 h, au plus 32 vagues et 200 arrivées potentielles, 128
changements, 128 scénarios et 32 actions candidates. Les modifications de
ressources sont des scripts conditionnels ; leur probabilité n'est pas estimée.

## Qualification et suite

Les tests couvrent les oracles temporels, conservation en cohorte ouverte,
fermetures, reprises, quotas consommés, réservations invalidées, intégrales de
surcharge, ordre simultané, information future et falsification du registre.
Une matrice de quatre graines × seize scénarios × deux politiques combine les
perturbations avec les durées stochastiques. Les tests des lots précédents restent
exécutés. Ce n'est pas l'intégralité de G2 ni une validation prédictive G1.

Restent à modéliser : interruption réelle d'une mission, réservation d'aval ou
tâche déjà en cours à D, fenêtres d'accueil, transferts, adhésion et échecs des
actions, sorties des nouveaux admis et replanification au fil d'observations.
L'apprentissage des arrivées/délais, leur calibration, CP-SAT et le raccordement
au terrain demeurent des étapes distinctes.
