# Mesurer la pratique ordinaire d'une unité

La grandeur du cockpit est le délai entre la relève où le geste est faisable et le moment où l'équipe le demande effectivement. Un geste déjà demandé avant la relève appartient aux engagements connus. Lorsque l'éligibilité commence avant la relève, conserver aussi son début. Le temps écoulé depuis la première éligibilité et le délai restant à la relève répondent à deux questions différentes.

| Champ de la fiche de recueil | Règle de saisie |
|---|---|
| Épisode pseudonyme, unité, garde, type de geste, séjour ou lit pseudonyme | Une ligne par occasion et geste. Relier les relèves successives au même épisode pour décrire leur dépendance. |
| Première éligibilité et origine de relève | Dater séparément l'éligibilité attestée et la relève. Si l'éligibilité est inconnue, conserver le motif et compter le cas à part. |
| État à la relève | Documenter la préparation déjà engagée, les blocages observés, les demandes en cours et les disponibilités. Conserver les valeurs inconnues. |
| Exposition au conseil | Dater la première présentation du conseil, un changement manuel, la validation ou le refus. Pour estimer la pratique usuelle, utiliser une période en observation silencieuse ou le suivi antérieur à l'exposition. |
| Demande, début d'exécution et résultat physique | Pour le transport, distinguer demande, prise en charge et départ. Pour le nettoyage, distinguer priorité demandée, début de nettoyage et lit disponible. Pour la réservation, dater l'affectation. Pour renfort et entrée programmée, distinguer demande, confirmation et prise de poste ou admission. |
| Survenue et disponibilité de chaque événement | Conserver l'identifiant source, la révision, l'heure physique et l'heure de disponibilité. Rejouer le journal tel qu'il était connu à la relève. Utiliser les corrections ultérieures uniquement à l'analyse, avec une date de gel du suivi. |
| Dernier instant de suivi complet et issue concurrente | Distinguer geste réalisé, aucune réalisation pendant une période complètement couverte, perte d'éligibilité, panne du flux ou fin du suivi. Inclure les occasions où aucun geste n'a été demandé. |

Pour chaque unité, garde et geste, compter à 30, 60 et 120 minutes à partir de la relève. Sur N occasions éligibles sans demande préalable, A est le nombre de demandes attestées avant l'échéance incluse et U le nombre dont l'issue à cette échéance demeure inconnue. La proportion compatible avec le suivi se situe entre A/N et (A+U)/N. Une perte définitive d'éligibilité documentée avant toute demande clôt l'occasion. Une source interrompue avant l'échéance laisse l'issue inconnue. Ces bornes décrivent le manque de suivi. L'incertitude d'échantillonnage est à estimer séparément, en tenant compte des épisodes et gardes répétés.

Rapporter aussi la part d'occasions présentes à plusieurs relèves et la fréquence de préparation déjà en cours. Pour valider ensuite un chiffre d'attente, rejouer la distribution commune du geste, du délai et de la préparation, avec les autres tâches réalisées par l'équipe. Un délai médian isolé ne détermine pas le gain causal. Garder les propositions de l'équipe validées, modifiées et refusées pour l'analyse de faisabilité.

Le dépôt possède déjà des événements rétrospectifs versionnés avec `occurred_at`, `available_at`, rétraction et fin de suivi, ainsi qu'un mode d'observation sans commande. La fiche ci-dessus décrit les événements de pratique à collecter auprès des logiciels pilotes. Aucune fréquence ni aucun délai d'équipe n'est renseigné par les reçus synthétiques. [Contrat rétrospectif existant](../../../src/hospitalos/hybrid/retrospective.py) · [Épisode d'observation existant](../../../src/hospitalos/hybrid/live_models.py)
