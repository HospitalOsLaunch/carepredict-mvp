# Matrice de tests C1 amendé (proposée)

Elle reprend T-C01 à T-C16 de `proposition_BCD/TEST_MATRIX_HOWM2_C1.md`. T-C05 et T-C06 sont
remplacés, et quatre tests s'ajoutent.

| ID | Objet | Condition de réussite |
|---|---|---|
| T-C05′ | Contexte long sans fuite (C.2a) | Toute table horaire entrante est publique à t. Retirer les observations postérieures à t laisse l'entrée inchangée. |
| T-C06′ | C.2a réduit à C.1 | Avec une séquence tronquée à 24 h, C.2a reproduit la passe avant de H1 à 1e-6 près, poids identiques. |
| T-C17 | C.2b réduit à C.1 | Avec les 8 entrées L2 mises à 0 et des poids d'entrée nuls, C.2b reproduit H1 à 1e-6 près. |
| T-C18 | Entrées L2 de C.2b | Elles égalent les intercepts de `l2_predict` (tranche A) sur 3 établissements, à 1e-12 près. |
| T-C19 | Référence R | La meilleure de {L2, L2c} est recalculée dans chaque réplique. L2c reproduit `L2C_A2.json` sur 3 établissements de HOWM2_REF. |
| T-C20 | Règle de palier | La décision du palier 2 est calculée à partir du seul journal CVAL, consignée avant tout lancement à 10 000, et testée sur des journaux synthétiques. |
