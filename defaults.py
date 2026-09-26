"""Valeurs par défaut des paramètres de tarification.

IMPORTANT : ces montants sont des ordres de grandeur indicatifs (FCFA, marché
abidjanais) destinés à rendre l'application utilisable dès le premier lancement.
Ils ne remplacent pas les prix d'achat et taux horaires réels : chaque valeur
est marquée « à valider » dans la page Paramètres tant qu'elle n'a pas été
confirmée par le contrôle de gestion.

Ce fichier ne sert qu'à initialiser ``data/parametres.json``. Une fois ce
fichier créé, toutes les modifications se font depuis l'application.
"""

from __future__ import annotations

import re

from .models import (
    POSTE_CONSOMMABLES,
    POSTE_DECOUPE,
    POSTE_FINITION,
    POSTE_IMPRESSION,
    POSTE_MATIERES,
    POSTE_PAPIER,
    POSTE_RAINAGE,
    Intrant,
    Machine,
)
from .utils import normalize

SCHEMA_VERSION = 1

# Prix d'achat par unité d'achat (paquet, rouleau, carton, bidon…) — FCFA.
PRIX_INTRANTS: dict[str, float] = {
    "IMPUT1": 20_000, "IMPUT2": 19_000, "IMPUT3": 29_000, "IMPUT4": 35_000,
    "IMPUT5": 18_000, "IMPUT6": 13_500, "IMPUT7": 40_000, "IMPUT8": 60_000,
    "IMPUT9": 120_000, "IMPUT10": 150_000, "IMPUT11": 100_000, "IMPUT12": 170_000,
    "IMPUT13": 32_000, "IMPUT14": 55_000, "IMPUT15": 120_000, "IMPUT16": 75_000,
    "IMPUT17": 90_000, "IMPUT18": 87_500, "IMPUT19": 120_000, "IMPUT20": 100_000,
    "IMPUT21": 25_000, "IMPUT22": 50_000, "IMPUT23": 43_200, "IMPUT24": 125_000,
    "IMPUT25": 15_000, "IMPUT26": 40_000, "IMPUT27": 12_500, "IMPUT28": 10_000,
    "IMPUT29": 7_500, "IMPUT30": 25_000, "IMPUT31": 3_000, "IMPUT32": 10_000,
    "IMPUT33": 25_000, "IMPUT34": 22_000, "IMPUT35": 5_000, "IMPUT36": 150_000,
    "IMPUT37": 60_000, "IMPUT38": 5_000, "IMPUT39": 150_000, "IMPUT40": 40_000,
    "IMPUT41": 8_000, "IMPUT42": 12_000, "IMPUT43": 25_000, "IMPUT44": 60_000,
    "IMPUT45": 45_000, "IMPUT46": 12_000, "IMPUT47": 45_000, "IMPUT48": 35_000,
    "IMPUT49": 90_000, "IMPUT50": 30_000,
}

# Taux horaire complet (amortissement, énergie, main-d'œuvre, maintenance) — FCFA/h.
MACHINES: dict[str, tuple[float, str]] = {
    "MACH1": (60_000, POSTE_IMPRESSION),   # HP Indigo
    "MACH2": (45_000, POSTE_IMPRESSION),   # Presstek DI
    "MACH3": (8_000, POSTE_IMPRESSION),    # Imprimante DTF
    "MACH4": (4_000, POSTE_IMPRESSION),    # Poudreuse / four DTF
    "MACH5": (3_000, POSTE_IMPRESSION),    # Presse à chaud plate
    "MACH6": (6_000, POSTE_IMPRESSION),    # Imprimante sublimation
    "MACH7": (2_500, POSTE_IMPRESSION),    # Presse à mug
    "MACH8": (5_000, POSTE_IMPRESSION),    # Carrousel sérigraphie
    "MACH9": (3_000, POSTE_IMPRESSION),    # Insoleuse
    "MACH10": (4_000, POSTE_IMPRESSION),   # Tunnel de séchage
    "MACH11": (6_000, POSTE_DECOUPE),      # Massicot (valorisé à la coupe, voir OPERATIONS)
    "MACH12": (5_000, POSTE_FINITION),     # Plieuse / piqueuse
    "MACH13": (8_000, POSTE_FINITION),     # Relieuse dos carré collé
    "MACH14": (3_000, POSTE_FINITION),     # Relieuse spirale
    "MACH15": (5_000, POSTE_FINITION),     # Pelliculeuse
    "MACH16": (5_000, POSTE_DECOUPE),      # Plotter de découpe
    "MACH17": (30_000, POSTE_FINITION),    # Jet Varnish
    "MACH18": (10_000, POSTE_IMPRESSION),  # Imprimante grand format
    "MACH19": (40_000, POSTE_IMPRESSION),  # Presse offset
    "MACH20": (3_000, POSTE_FINITION),     # Poste finition grand format
}

GENERAL: dict = {
    "arrondir_feuilles": True,        # feuilles de tirage arrondies à l'unité supérieure
    "hauteur_levee": 250,             # feuilles par levée au massicot (estimation des coupes)
    "grammage_min_rainage": 170,      # en dessous, un pli se fait sans rainage
    "emballage_defaut": "CARTON_M",
    "transport_defaut": "MOTO",
    "livraison_defaut": True,
}

FORMATS: list[dict] = [
    {"code": "SRA3", "libelle": "SRA3 (320 × 450 mm)", "feuilles_par_a0": 4},
    {"code": "A1", "libelle": "A1 presse offset (½ A0)", "feuilles_par_a0": 2},
    {"code": "A0", "libelle": "A0 (841 × 1 189 mm)", "feuilles_par_a0": 1},
]

OPERATIONS: list[dict] = [
    {
        "code": "DECOUPE", "libelle": "Découpe au massicot", "poste": POSTE_DECOUPE,
        "unite": "coupe", "base": "commande", "cout_unitaire": 25, "selon_papier": False,
        "machine": "MACH11", "estimation": "coupes_massicot", "actif": True, "valide": False,
    },
    {
        "code": "RAINAGE", "libelle": "Rainage", "poste": POSTE_RAINAGE,
        "unite": "rainage", "base": "exemplaire", "cout_unitaire": 5, "selon_papier": True,
        "machine": "", "estimation": "rainages_pliage", "actif": True, "valide": False,
    },
]

# Coût d'un rainage selon le papier (FCFA / rainage) — plus le support est épais, plus il coûte.
TARIFS_RAINAGE: dict[str, float] = {
    "IMPUT1": 3, "IMPUT2": 4, "IMPUT3": 5, "IMPUT4": 6, "IMPUT5": 2,
    "IMPUT6": 3, "IMPUT7": 8, "IMPUT8": 5, "IMPUT9": 7,
}

EMBALLAGES: list[dict] = [
    {"code": "CARTON_S", "libelle": "Petit carton (25 × 18 × 10 cm)", "cout_unitaire": 250, "valide": False},
    {"code": "CARTON_M", "libelle": "Carton standard (40 × 30 × 30 cm)", "cout_unitaire": 500, "valide": False},
    {"code": "CARTON_L", "libelle": "Grand carton (60 × 40 × 40 cm)", "cout_unitaire": 900, "valide": False},
    {"code": "KRAFT", "libelle": "Papier kraft et film (colis souple)", "cout_unitaire": 150, "valide": False},
]

TRANSPORTS: list[dict] = [
    {"code": "MOTO", "libelle": "Moto (coursier)", "cout_km": 150, "frais_fixes": 0, "valide": False},
    {"code": "UTILITAIRE", "libelle": "Véhicule utilitaire", "cout_km": 350, "frais_fixes": 0, "valide": False},
]

FRAIS: list[dict] = [
    {
        "code": "ATELIER", "libelle": "Frais d'atelier (consommables hors nomenclature)",
        "mode": "pourcentage", "valeur": 3, "assiette": "production", "actif": True, "valide": False,
    },
    {
        "code": "BAT", "libelle": "Préparation du fichier et BAT", "mode": "fixe",
        "valeur": 2_500, "assiette": "production", "actif": False, "valide": False,
    },
]


# --------------------------------------------------------------------------- #
# Règles pour les codes inconnus (nouvel intrant, nouvelle machine, nouveau procédé)
# --------------------------------------------------------------------------- #
def default_poste_intrant(intrant: Intrant) -> str:
    if intrant.is_paper_sheet or normalize(intrant.categorie_stock) == "papier":
        return POSTE_PAPIER
    if normalize(intrant.famille).startswith("consommable"):
        return POSTE_CONSOMMABLES
    return POSTE_MATIERES


def default_poste_machine(machine: Machine) -> str:
    text = normalize(f"{machine.atelier} {machine.libelle}")
    if "massicot" in text or "decoupe" in text:
        return POSTE_DECOUPE
    if "rain" in text:
        return POSTE_RAINAGE
    if "finition" in text:
        return POSTE_FINITION
    return POSTE_IMPRESSION


def default_procede(procede: str) -> dict:
    """Format de tirage et gâche intégrée (information) selon le procédé."""
    key = normalize(procede)
    if re.search(r"\boffset\b", key) and "presstek" not in key:
        return {"procede": procede, "format": "A1", "gache_pct": 8}
    if "presstek" in key:
        return {"procede": procede, "format": "SRA3", "gache_pct": 6}
    return {"procede": procede, "format": "SRA3", "gache_pct": 5}
