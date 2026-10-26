# Variante v2 : parcours retenu sur deux dossiers

Décision validée le 26 octobre 2026 : conserver les garde-fous de reprise existants.

1. Premier dossier, script seul : formulaire v2 incompatible, aucune réponse envoyée,
   reprise humaine. Ce dossier reste en vérification seule.
2. Activer explicitement un moteur et l’autorisation de voir le portail fictif.
3. Second dossier : script en échec, modèle appelé pendant la même réservation,
   puis relecture DOM indépendante de la décision, de la date et du message.

L’activation tardive du modèle ne débloque pas l’écriture du premier dossier.
`begin_write` reste appelé avant les interactions du moteur ; `write_started_at`,
le jeton de réservation et `reconcile_only` restent inchangés. Aucun marqueur n’est
retiré pour permettre un nouvel envoi. La référence gelée et le North Star ne sont
pas concernés.

Le parcours et ses limites sont documentés dans le README racine. La relecture
rejette une réponse inattendue mais n’annule pas une écriture déjà reçue par le
portail. Les tests de modèle scripté vérifient l’arrêt sans second envoi ; ils ne
mesurent pas les performances d’un vrai modèle.
