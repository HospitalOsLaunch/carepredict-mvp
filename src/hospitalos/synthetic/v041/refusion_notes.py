"""Recalcule uniquement les états documentaires depuis le journal observé.

Usage : python refusion_notes.py ../data
Les extractions complètes, les notes et les trajectoires du monde sont conservées.
Relancer ensuite controles.py pour actualiser les contrôles et le manifeste.
"""
import argparse
import gzip
import json
from pathlib import Path

import pandas as pd

from . import extraction as ex
from .run import ecrire_csv


def main(root):
    root = Path(root)
    with gzip.open(root / "observe/notes.jsonl.gz", "rt", encoding="utf-8") as f:
        notes = [json.loads(ligne) for ligne in f]
    xn = pd.read_csv(root / "apprentissage/extraction_notes.csv.gz", low_memory=False)
    lignes = xn.astype(object).where(xn.notna(), None).to_dict("records")
    etat = pd.DataFrame(ex.etat_documentaire(lignes, notes))
    ecrire_csv(etat, root / "apprentissage/etat_notes_asof.csv.gz")
    rep = json.loads((root / "rapport_generation.json").read_text())
    focale = rep["unite_focale"]
    if focale:
        sejours = xn.loc[xn.unite == focale, "sejour_id"]
        ecrire_csv(etat[etat.sejour_id.isin(sejours)], root / f"unite_{focale}/etat_notes_asof.csv.gz")
    print(json.dumps(dict(etats_documentaires=len(etat), colonnes=len(etat.columns)), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("donnees", type=Path)
    main(parser.parse_args().donnees)
