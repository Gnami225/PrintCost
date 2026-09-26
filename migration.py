"""Copie des données d'une base à une autre (par exemple SQLite local vers Neon).

Usage :
    python -m digiprint.migration --cible "postgresql://…neon.tech/neondb"
    python -m digiprint.migration --source sqlite:///data/digiprint.sqlite --cible "$NEON_URL" --remplacer

Copie les paramètres, leurs sauvegardes, l'historique des calculs et les
versions importées de la base articles. Sans ``--remplacer``, la copie est
refusée si la base cible contient déjà des calculs ou des paramètres.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import delete, func, insert, select, text

from .stockage import TABLES, local_url, ouvrir_base


def copier(source_url: str, cible_url: str, remplacer: bool = False) -> dict[str, int]:
    source = ouvrir_base(source_url)
    cible = ouvrir_base(cible_url)
    if source.engine.url == cible.engine.url:
        raise ValueError("La source et la cible sont identiques.")
    with cible.engine.connect() as conn:
        occupees = [t.name for t in TABLES if conn.execute(select(func.count()).select_from(t)).scalar()]
    if occupees and not remplacer:
        raise ValueError("La base cible contient déjà des données (" + ", ".join(occupees)
                         + ") : relancez avec --remplacer pour les écraser.")
    compte: dict[str, int] = {}
    with source.engine.connect() as src, cible.engine.begin() as dst:
        for table in TABLES:
            rows = [dict(r._mapping) for r in src.execute(select(table))]
            dst.execute(delete(table))
            if rows:
                dst.execute(insert(table), rows)
            compte[table.name] = len(rows)
            if cible.est_postgres and "id" in table.c and rows:
                dst.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                                 f"(SELECT MAX(id) FROM {table.name}))"))
    return compte


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copie les données DIGIPRINT Tarification vers une autre base.")
    parser.add_argument("--source", default=local_url(), help="adresse de la base source (défaut : SQLite local)")
    parser.add_argument("--cible", required=True, help="adresse de la base cible (chaîne de connexion Neon)")
    parser.add_argument("--remplacer", action="store_true", help="écraser les données existantes de la cible")
    args = parser.parse_args(argv)
    try:
        compte = copier(args.source, args.cible, args.remplacer)
    except Exception as exc:  # message lisible en ligne de commande
        print(f"Copie impossible : {exc}", file=sys.stderr)
        return 1
    for nom, n in compte.items():
        print(f"{nom} : {n} ligne(s) copiée(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
