# Correctif des identités bitemporelles — revue du 15 octobre 2026

Le validateur de la PR #2 utilisait les chaînes des horodatages comme clés. Le
même instant écrit avec ou sans microsecondes pouvait être accepté deux fois.
Il confondait aussi deux actions de types ou de cibles différents, réalisées au
même instant et disponibles au même instant.

Les clés utilisent désormais les instants normalisés en UTC. La comparaison de
contenu normalise également ces deux horodatages : le doublon sémantique est un
doublon, tandis qu'une valeur différente à la même clé reste un conflit. Les
horaires répétés au changement d'heure d'automne restent deux instants distincts.

Pour les actions, la clé inclut le type et la cible effective (service émetteur
si cible absente). L'amplitude ne fait pas partie de la clé : deux amplitudes à
la même clé restent contradictoires. Le contrat v1 et son empreinte sont inchangés.

Limite conservée : v1 ne possède pas d'identifiant d'action. Il ne peut pas
distinguer deux occurrences légitimes du même type, vers la même cible, aux deux
mêmes instants. Un futur domaine d'événements devra fournir un `action_id` stable ;
ce correctif n'invente pas cette information et ne change pas silencieusement le
schéma gelé.

Vérification : 8 nouveaux cas, 49 tests du validateur et du contrat exécutés avec
succès ; Ruff et mypy strict passent sur les deux fichiers concernés. Les cas
incluent doublon avec représentation différente, conflit de contenu, actions
simultanées distinctes, cible implicite, révision et heure d'automne répétée.
