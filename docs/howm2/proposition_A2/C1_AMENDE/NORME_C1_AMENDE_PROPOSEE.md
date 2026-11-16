# NORME HOWM2-C1a (proposée, non adoptée)

Cette norme reprend `proposition_BCD/NORME_HOWM2_C1_PROPOSEE.md` (N1–N12), avec les
modifications ci-dessous. Elle est consignée dans `BUDGET_LEDGER_HOWM2_C1` avant toute mesure.

**N5′. Systèmes.** C.1, C.2a et C.2b, comme définis dans `DESIGN_C1_AMENDE.md`. Aucun autre
système. Le code nouveau est dans `src/hospitalos/howm2/` ; `nets.py` n'est pas modifié.

**N7′. Critère principal.**
- Statistique : ΔC(h) = L(R) − L(modèle), où R est la meilleure de {L2, L2c} choisie **dans
  chaque réplique**. L2c est fixé par `evidence/howm2/L2C_PARAMS.json`.
- Agrégation R1, bootstrap par grappes d'établissement, B = 2 000.

| Verdict | Condition |
|---|---|
| `C1_BAT_REF` | borne basse > 0 à H6 **et** à H24 |
| `C1_NE_BAT_PAS_REF` | borne haute < 0 à H6 **et** à H24 |
| `C1_INDETERMINE` | sinon |

Le verdict est rendu par système. Le système de tête est choisi sur CVAL.

**N8′. Lecture principale.**
- ρ_f(h) = (L_R − L_modèle)/(L_R − L_L4) par famille, avec intervalle à 95 %, sur les familles
  validées en A.
- Ambition : ρ ≥ 0,5 sur l'agrégat des familles validées, à H6 et à H24.
- Pour C.2b, la lecture de ρ prime : battre R y est attendu par construction.

**N9′. Paliers.**
- Palier 1 : N ∈ {100, 1 000}, 3 graines par système.
- Palier 2 : N = 10 000, 1 graine par système, puis 2 graines du meilleur selon CVAL. Il est lancé
  si et seulement si, pour au moins un système, CVAL(100) − CVAL(1 000) > 2 × l'écart-type entre
  graines à N = 1 000.
- Sinon, le point retenu est 1 000 et la loi d'échelle a deux points ; c'est déclaré.

**N12′. Arrêt.**
- Si un dépassement est projeté, ou si un point est infaisable ou contradictoire : arrêt et
  question avec options.
- Le palier 2 est la seule adaptation permise sans question.
