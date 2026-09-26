"""Modèles de données de l'application (structures immuables, sans logique d'accès).

Vocabulaire repris de la base articles DIGIPRINT :

- **nomenclature** : intrants (IMPUTn) consommés par unité d'article ;
- **gamme** : temps de passage machine (MACHn), en secondes par unité d'article ;
- **poste** : regroupement de coûts affiché à l'utilisateur (Papier, Impression…).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .utils import clean_text, fmt_duration, fmt_money, fmt_smart, normalize, to_float, unit_plural

# --------------------------------------------------------------------------- #
# Postes de coût
# --------------------------------------------------------------------------- #
POSTE_PAPIER = "Papier"
POSTE_MATIERES = "Matières premières"
POSTE_CONSOMMABLES = "Encres et consommables"
POSTE_IMPRESSION = "Impression"
POSTE_FINITION = "Finition"
POSTE_DECOUPE = "Découpe"
POSTE_RAINAGE = "Rainage"
POSTE_EMBALLAGE = "Emballage"
POSTE_TRANSPORT = "Transport"
POSTE_AUTRES = "Autres frais"

# Postes « de production » : assiette des frais exprimés en % du coût de production.
POSTES_PRODUCTION = [
    POSTE_PAPIER,
    POSTE_MATIERES,
    POSTE_CONSOMMABLES,
    POSTE_IMPRESSION,
    POSTE_FINITION,
    POSTE_DECOUPE,
    POSTE_RAINAGE,
]
POSTES_ORDRE = POSTES_PRODUCTION + [POSTE_EMBALLAGE, POSTE_TRANSPORT, POSTE_AUTRES]
# Postes proposés pour les machines et opérations (un nouveau poste libre reste possible).
POSTES_TECHNIQUES = [POSTE_IMPRESSION, POSTE_FINITION, POSTE_DECOUPE, POSTE_RAINAGE]


def poste_rank(poste: str) -> tuple[int, str]:
    """Ordre d'affichage : postes connus d'abord, postes libres ensuite (production)."""
    if poste in POSTES_ORDRE:
        idx = POSTES_ORDRE.index(poste)
        # Les postes libres s'intercalent avant Emballage.
        return (idx if idx < len(POSTES_PRODUCTION) else idx + 100, poste)
    return (len(POSTES_PRODUCTION) + 50, poste)


def is_production_poste(poste: str) -> bool:
    return poste not in (POSTE_EMBALLAGE, POSTE_TRANSPORT, POSTE_AUTRES)


# Unités particulières des lignes de calcul.
UNITE_HEURE = "h"  # temps machine : quantité en heures, prix unitaire = taux horaire
UNITE_ASSIETTE = "FCFA d'assiette"  # frais en % : quantité = assiette, prix unitaire = taux


# --------------------------------------------------------------------------- #
# Référentiels
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Intrant:
    """Intrant du référentiel REF_INTRANTS (matière première ou consommable)."""

    code: str
    libelle: str
    famille: str = ""
    categorie_stock: str = ""
    uom_achat: str = ""
    conditionnement: str = ""
    uom_conso: str = ""
    facteur_conversion: float = 1.0
    source: str = ""

    @property
    def is_paper_sheet(self) -> bool:
        """Intrant consommé à la feuille A0 : relève du calcul en nombre de feuilles."""
        return "a0" in normalize(self.uom_conso) and "feuille" in normalize(self.uom_conso)


@dataclass(frozen=True)
class Machine:
    """Machine du référentiel REF_MACHINES."""

    code: str
    libelle: str
    atelier: str = ""
    site: str = ""
    cadence: str = ""
    source: str = ""


@dataclass(frozen=True)
class BomLine:
    """Ligne de nomenclature : quantité d'intrant par unité d'article (UoM de consommation)."""

    code: str
    quantite: float


@dataclass(frozen=True)
class RoutingLine:
    """Ligne de gamme : temps de passage en secondes par unité d'article."""

    code: str
    secondes: float


@dataclass(frozen=True)
class Article:
    id: str
    designation: str
    nature: str
    categorie: str
    unite: str = "pièce"
    procede: str = ""
    format_fini: str = ""
    site: str = ""
    nomenclature: tuple[BomLine, ...] = ()
    gamme: tuple[RoutingLine, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.designation} — {self.nature}"

    def uses_machine(self, code: str) -> bool:
        return any(line.code == code and line.secondes > 0 for line in self.gamme)


# --------------------------------------------------------------------------- #
# Unité de l'article
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class UnitSpec:
    """Traduction de UNITE_ARTICLE en règles de saisie.

    ``divisor`` convertit la quantité saisie en unités de nomenclature :
    un article vendu « au lot de 1 000 » se saisit en exemplaires (5 000) et
    sa nomenclature est appliquée 5 fois.
    """

    raw: str
    key: str  # identifiant stable, utilisé pour mémoriser la quantité par type d'unité
    input_label: str  # libellé du champ quantité
    singular: str  # « exemplaire », « m² »…
    plural_form: str
    divisor: float = 1.0
    integer: bool = True
    default_qty: float = 100
    step: float = 1

    def per_unit_label(self) -> str:
        return f"par {self.singular}"


def unit_spec(raw_unit: str) -> UnitSpec:
    """Règles de saisie selon l'unité de l'article (pièce, lot de 1 000, m², ml, kit, paire…)."""
    raw = clean_text(raw_unit) or "pièce"
    key = normalize(raw)
    lot = re.match(r"lot de ([\d\s\u00a0\u202f.]+)", key)
    if lot:
        size = to_float(lot.group(1).replace(" ", ""), 1.0) or 1.0
        return UnitSpec(raw, f"lot{int(size)}", "Quantité (exemplaires)", "exemplaire",
                        "exemplaires", divisor=size, default_qty=size, step=size / 2 if size >= 2 else 1)
    if key in ("m2", "m²", "metre carre", "metres carres"):
        return UnitSpec(raw, "m2", "Surface (m²)", "m²", "m²", integer=False, default_qty=1, step=1)
    if key in ("ml", "metre lineaire", "metres lineaires"):
        return UnitSpec(raw, "ml", "Longueur (mètres linéaires)", "mètre linéaire",
                        "mètres linéaires", integer=False, default_qty=1, step=1)
    if key == "kit":
        return UnitSpec(raw, "kit", "Quantité (kits)", "kit", "kits", default_qty=10)
    if key == "paire":
        return UnitSpec(raw, "paire", "Quantité (paires)", "paire", "paires", default_qty=10)
    if key in ("piece", "pieces", "unite", "u"):
        return UnitSpec(raw, "piece", "Quantité (exemplaires)", "exemplaire", "exemplaires")
    return UnitSpec(raw, key or "piece", f"Quantité ({raw})", raw, raw)


# --------------------------------------------------------------------------- #
# Calcul
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Estimate:
    """Valeur proposée automatiquement, avec son explication lisible."""

    value: float
    explication: str


@dataclass(frozen=True)
class SheetPlan:
    """Besoin en feuilles pour un papier de la nomenclature."""

    code: str
    libelle: str
    format_code: str
    format_libelle: str
    feuilles_par_a0: float
    quantite_a0: float  # feuilles A0 consommées (nomenclature × quantité)
    feuilles_calculees: float  # feuilles de tirage calculées (avant arrondi)
    feuilles_auto: float  # après arrondi éventuel
    feuilles: float  # retenues (auto ou saisie)
    saisie_manuelle: bool
    poses: int | None
    gache_pct: float


@dataclass
class CostLine:
    """Une ligne du détail de calcul."""

    poste: str
    code: str
    libelle: str
    quantite: float
    unite: str
    prix_unitaire: float
    montant: float
    formule: str
    origine: str  # nomenclature | gamme | estimation | saisie | paramètre | frais
    prix_valide: bool = True
    prix_manquant: bool = False
    assiette: str | None = None  # frais en % : « production » ou « hors_frais »

    @property
    def est_pourcentage(self) -> bool:
        return self.unite == UNITE_ASSIETTE

    def quantite_txt(self) -> str:
        """Quantité lisible : ``25 feuilles SRA3``, ``4 min 10 s``, ``3 554 FCFA``."""
        if self.unite == UNITE_HEURE:
            return fmt_duration(self.quantite * 3600)
        if self.est_pourcentage:
            return fmt_money(self.quantite)
        return f"{fmt_smart(self.quantite)}\u00a0{unit_plural(self.quantite, self.unite)}".strip()

    def prix_txt(self) -> str:
        """Prix unitaire lisible : ``87,5 FCFA``, ``60 000 FCFA/h``, ``3 %``."""
        if self.prix_manquant:
            return "non renseigné"
        if self.unite == UNITE_HEURE:
            return f"{fmt_money(self.prix_unitaire)}/h"
        if self.est_pourcentage:
            return f"{fmt_smart(self.prix_unitaire * 100)}\u00a0%"
        return fmt_money(self.prix_unitaire)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CostLine":
        known = {f: data.get(f) for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        known["prix_valide"] = True if known.get("prix_valide") is None else bool(known["prix_valide"])
        known["prix_manquant"] = bool(known.get("prix_manquant"))
        for name in ("quantite", "prix_unitaire", "montant"):
            known[name] = float(to_float(known.get(name), 0.0) or 0.0)
        for name in ("poste", "code", "libelle", "unite", "formule", "origine"):
            known[name] = clean_text(known.get(name))
        return cls(**known)


@dataclass
class PricingRequest:
    """Saisie de l'utilisateur pour un calcul."""

    article_id: str
    quantite: float
    feuilles: dict[str, float | None] = field(default_factory=dict)  # code papier → feuilles saisies
    operations: dict[str, float | None] = field(default_factory=dict)  # code opération → nombre saisi
    emballage: str | None = None  # code emballage (None = sans emballage)
    emballage_cout_unitaire: float | None = None  # None = tarif paramétré
    emballage_nombre: float = 0
    livraison: bool = False
    transport: str | None = None
    distance_km: float = 0  # distance aller
    frais_ponctuels: list[dict[str, Any]] = field(default_factory=list)  # {libelle, montant}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PricingRequest":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}  # type: ignore[attr-defined]
        return cls(**known)


@dataclass
class PricingResult:
    article: Article
    request: PricingRequest
    unit: UnitSpec
    lines: list[CostLine]
    total: float
    par_poste: dict[str, float]
    nb_exemplaires: float
    quantite_nomenclature: float
    feuilles: list[SheetPlan]
    estimations: dict[str, Estimate]
    alertes: list[str]
    prix_indicatifs: list[str]  # libellés des prix non validés utilisés
    parametres_version: str

    @property
    def cout_unitaire(self) -> float:
        return self.total / self.nb_exemplaires if self.nb_exemplaires else 0.0

    @property
    def cout_nomenclature(self) -> float:
        """Coût par unité de nomenclature (ex. par lot de 1 000)."""
        return self.total / self.quantite_nomenclature if self.quantite_nomenclature else 0.0
