"""Estimations automatiques proposées à l'utilisateur (toujours modifiables).

Chaque règle reçoit un ``EstimationContext`` et renvoie une ``Estimate``
(valeur + explication). Pour ajouter une règle : écrire la fonction, puis
l'inscrire dans ``ESTIMATORS`` et dans ``parametres.ESTIMATIONS`` — elle devient
alors sélectionnable pour n'importe quelle opération depuis la page Paramètres.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable

from .catalogue import Catalogue
from .models import Article, Estimate, Intrant, SheetPlan
from .utils import fmt_smart, normalize, parse_grammage, plural, to_float


@dataclass(frozen=True)
class ReferencePaper:
    """Papier servant de référence aux tarifs « selon le papier » (le plus épais de l'article)."""

    code: str
    libelle: str
    grammage: int | None


@dataclass(frozen=True)
class EstimationContext:
    article: Article
    operation: dict[str, Any]
    nb_exemplaires: float
    feuilles: list[SheetPlan]
    general: dict[str, Any]
    papier: ReferencePaper | None


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
def reference_paper(article: Article, catalogue: Catalogue) -> ReferencePaper | None:
    """Papier de référence : grammage le plus élevé, puis quantité la plus forte."""
    candidates: list[tuple[int, float, Intrant]] = []
    for line in article.nomenclature:
        intrant = catalogue.intrant(line.code)
        if intrant.is_paper_sheet:
            candidates.append((parse_grammage(intrant.libelle) or -1, line.quantite, intrant))
    if not candidates:
        return None
    grammage, _, intrant = max(candidates, key=lambda c: (c[0], c[1]))
    return ReferencePaper(intrant.code, intrant.libelle, grammage if grammage > 0 else None)


def infer_poses(quantite_a0_par_exemplaire: float, feuilles_par_a0: float, gache_pct: float) -> int | None:
    """Nombre de poses par feuille de tirage déduit de la nomenclature.

    La base exprime le papier en feuilles A0 par exemplaire, gâche comprise :
    q = (1 / poses) / feuilles_par_A0 × (1 + gâche). D'où poses = (1 + gâche) / (q × feuilles_par_A0).
    Exemple : carte de visite, q = 0,0125 A0, SRA3 (4 par A0), gâche 5 % → 21 poses.
    """
    denom = quantite_a0_par_exemplaire * feuilles_par_a0
    if denom <= 0:
        return None
    poses = round((1 + gache_pct / 100) / denom)
    return int(min(max(poses, 1), 500))


def grid(poses: int) -> tuple[int, int]:
    """Disposition la plus compacte : 21 → (3, 7) ; 8 → (2, 4) ; 1 → (1, 1)."""
    poses = max(1, int(poses))
    rows = max(d for d in range(1, int(math.isqrt(poses)) + 1) if poses % d == 0)
    return rows, poses // rows


# --------------------------------------------------------------------------- #
# Règles
# --------------------------------------------------------------------------- #
def estimate_cuts(ctx: EstimationContext) -> Estimate:
    """Coupes au massicot : levées × coupes par levée, papier par papier.

    Coupes par levée avec fonds perdus = 4 coupes de rognage + 2 coupes par
    intervalle entre poses, soit 2 × (lignes + colonnes).
    """
    machine = (ctx.operation.get("machine") or "").strip()
    if machine and not ctx.article.uses_machine(machine):
        return Estimate(0, "Pas de passage au massicot dans la gamme de l'article.")
    sheets = [p for p in ctx.feuilles if p.feuilles > 0]
    if not sheets:
        return Estimate(0, "Aucune feuille de papier à découper : à saisir si nécessaire.")
    hauteur = max(1, int(to_float(ctx.general.get("hauteur_levee"), 250) or 250))
    total, parts = 0, []
    for plan in sheets:
        poses = plan.poses or 1
        rows, cols = grid(poses)
        per_lift = 2 * (rows + cols)
        lifts = math.ceil(round(plan.feuilles, 6) / hauteur)
        total += lifts * per_lift
        parts.append(
            f"{fmt_smart(plan.feuilles)} {plural(plan.feuilles, 'feuille')} {plan.format_code} "
            f"({poses} {plural(poses, 'pose')}) : {lifts} {plural(lifts, 'levée')} × {per_lift} coupes"
        )
    return Estimate(total, " ; ".join(parts) + f". Levée de {hauteur} feuilles au plus.")


_COVER_RE = re.compile(r"couv\.?\s*(?:carton\s*)?(\d{2,3})\s*g")
_VOLETS_RE = re.compile(r"(\d+)\s*volets")
_PLIE_RE = re.compile(r"\bplie")


def estimate_creases(ctx: EstimationContext) -> Estimate:
    """Rainages par exemplaire, déduits de la nature (volets, pliage, couverture)."""
    text = normalize(ctx.article.nature)
    cover = _COVER_RE.search(text)
    if cover and "dos carre colle" in text:
        return Estimate(4, f"Couverture {cover.group(1)} g en dos carré collé : 4 rainages (dos et charnières).")
    if cover and "piqure a cheval" in text:
        return Estimate(1, f"Couverture {cover.group(1)} g piquée à cheval : 1 rainage au dos.")

    volets = _VOLETS_RE.search(text)
    if volets:
        folds, reason = max(int(volets.group(1)) - 1, 0), f"{volets.group(1)} volets"
    elif _PLIE_RE.search(text):
        folds, reason = 1, "Article plié"
    else:
        return Estimate(0, "Aucun pli détecté dans la nature : à saisir si nécessaire.")

    seuil = int(to_float(ctx.general.get("grammage_min_rainage"), 170) or 0)
    grammage = ctx.papier.grammage if ctx.papier else None
    if grammage is not None and grammage < seuil:
        return Estimate(0, f"{reason} en {grammage} g : pli sans rainage (rainage à partir de {seuil} g).")
    detail = f" en {grammage} g" if grammage else ""
    return Estimate(folds, f"{reason}{detail} : {folds} {plural(folds, 'rainage')} par exemplaire.")


ESTIMATORS: dict[str, Callable[[EstimationContext], Estimate]] = {
    "coupes_massicot": estimate_cuts,
    "rainages_pliage": estimate_creases,
}
