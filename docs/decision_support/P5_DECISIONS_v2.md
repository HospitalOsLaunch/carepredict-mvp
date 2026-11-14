# P5 — Relevé des décisions D1–D12 (14 novembre 2026)

Déclaration de l'utilisateur : « J'approuve D1 à D12 selon tes recommandations ».
**Statut : `PROTOCOL_APPROVED_EXECUTION_NOT_AUTHORISED`.** Rien n'a été exécuté.

L'approbation porte sur les fichiers suivants, **inchangés** depuis leur livraison :

| Fichier | SHA-256 |
|---|---|
| `P5_PROTOCOL_v2.md` | `ad0fdaa592d84461f61f3c68f3470f94b941bde006d0fe57af69a4005797881c` |
| `P5_PROTOCOL_PARAMS_v2.json` | `1d284b0e9ebe2f0f8eb9b9dc052eb67ae73c5bcc5faca7514552213a51f8d0f7` |
| `P5_CHANGES_v1_to_v2.md` | `c9309083e1a09818c9f6a1f55015384f41da3ba60e1faa5601949736f36a10d4` |
| `HospitalOS_P5_Protocol_v2_20261114.zip` | `6ab61a12af755d11a28199f45783af72ef33bd5436620c87a1e7682f6f6c30a9` |

| # | Décision retenue | Effet |
|---|---|---|
| D1 | P5-PROTO-2 = base du gel | tout amendement = P5-PROTO-3 |
| D2 | 1200 s + échelle de repli L1–L3, 30 s/commande, 0 € | budget approuvé, utilisable seulement après autorisation d'exécution ; registre P5 pas encore créé ; reliquat P0–P4 non utilisé |
| D3 | Python 3.11.18 + gel `bf540981…b6da` | porte produit 3.11.9 toujours ouverte |
| D4 | l'installation est une décision distincte, qui n'autorise pas les ajustements | **installation de scikit-learn non autorisée par ce relevé** ; P5b bloqué tant qu'elle ne l'est pas |
| D5 | évaluation réservée P5b : 30 structures × 4 parents × 2 jumeaux | option v1 (8 × 15) abandonnée |
| D6 | vérité des renforts telle qu'écrite (R1 p_pub indépendantes ; R2 0,5, ρ = 0,5 par pool) | — |
| D7 | précontrôle des jumeaux : 25 min², K = 3, partition d'entraînement | — |
| D8 | `early_stopping=False`, paramètres du § 6.4, `OMP_NUM_THREADS=1` | — |
| D9 | borne Clopper–Pearson par structure, seuil 10 % | — |
| D10 | décomposition des ressources descriptive | — |
| D11 | autorisations d'exécution séparées, dans l'ordre (i) mise en œuvre + pilote P5.0–P5.2, (ii) évaluation réservée P5a, (iii) ajustements et évaluation P5b | **aucune n'est accordée par ce relevé** |
| D12 | cockpit hors P5 ; rejeu React indépendant = porte produit séparée | — |

**Encore requis avant toute exécution** : autorisation explicite (i) ; autorisation explicite
d'installer scikit-learn (avant P5b) ; puis (ii) et (iii).

Statuts inchangés : `PARTIAL_WITH_CHECKPOINT` (portes Python 3.11.9 exact et rejeu navigateur
indépendant ouvertes), `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`, P6 fermé.
Registre P0–P4 non prolongé (175 enregistrements, 421,325 s, terminal `9056a4a1…b973`).
