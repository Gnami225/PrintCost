"""Chargement et contrôle de la base articles (classeur Excel DIGIPRINT).

Feuilles exploitées :

- ``BASE_ARTICLE``       (obligatoire) ID, désignation, nature, catégorie, IMPUTn, MACHn ;
- ``ATTRIBUTS_ARTICLE``  unité, procédé, format fini, site ;
- ``REF_INTRANTS``       libellés, unités d'achat/consommation, facteur de conversion ;
- ``REF_MACHINES``       libellés, ateliers, cadences.

Le chargement est tolérant : en-têtes normalisés (espaces, accents, casse),
nombres au format texte acceptés, lignes incomplètes écartées. Chaque anomalie
est consignée dans ``Catalogue.anomalies`` pour affichage dans l'application.
Le nombre de colonnes IMPUTn / MACHn n'est pas figé : une colonne IMPUT51 ou
MACH21 ajoutée au classeur est prise en compte automatiquement.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .models import Article, BomLine, Intrant, Machine, RoutingLine
from .utils import clean_text, normalize, to_float


class CatalogueError(Exception):
    """Base articles illisible ou incomplète : le calcul est impossible."""


IMPUT_RE = re.compile(r"^IMPUT[_\s]*(\d+)$")
MACH_RE = re.compile(r"^MACH[_\s]*(\d+)$")


def _norm_header(value: object) -> str:
    """En-tête comparable : ``'DESIGNATION '`` → ``'DESIGNATION'`` ; ``'Désignation'`` → ``'DESIGNATION'``."""
    return re.sub(r"[\s\-]+", "_", normalize(value)).upper().strip("_")


def _find_sheet(sheets: dict[str, pd.DataFrame], *names: str) -> pd.DataFrame | None:
    wanted = {_norm_header(n) for n in names}
    for name, df in sheets.items():
        if _norm_header(name) in wanted:
            return df
    return None


def _find_col(df: pd.DataFrame, *aliases: str) -> str | None:
    wanted = [_norm_header(a) for a in aliases]
    lookup = {_norm_header(c): c for c in df.columns}
    for alias in wanted:
        if alias in lookup:
            return lookup[alias]
    return None


def _code(prefix: str, number: str) -> str:
    return f"{prefix}{int(number)}"


@dataclass
class Catalogue:
    articles: dict[str, Article]
    intrants: dict[str, Intrant]
    machines: dict[str, Machine]
    anomalies: list[str] = field(default_factory=list)
    source: str = ""
    source_mtime: float = 0.0

    # ------------------------------------------------------------------ #
    # Accès
    # ------------------------------------------------------------------ #
    def get(self, article_id: str | None) -> Article | None:
        return self.articles.get(article_id) if article_id else None

    def designations(self) -> list[str]:
        """Désignations distinctes (regroupement insensible à la casse), triées."""
        seen: dict[str, str] = {}
        for art in self.articles.values():
            seen.setdefault(normalize(art.designation), art.designation)
        return sorted(seen.values(), key=normalize)

    def articles_for(self, designation: str | None) -> list[Article]:
        """Articles (natures) d'une désignation, dans l'ordre de la base."""
        if not designation:
            return []
        key = normalize(designation)
        return [a for a in self.articles.values() if normalize(a.designation) == key]

    @property
    def procedes(self) -> list[str]:
        return sorted({a.procede for a in self.articles.values() if a.procede}, key=normalize)

    @property
    def categories(self) -> list[str]:
        return sorted({a.categorie for a in self.articles.values() if a.categorie}, key=normalize)

    def intrant(self, code: str) -> Intrant:
        return self.intrants.get(code) or Intrant(code=code, libelle=code)

    def machine(self, code: str) -> Machine:
        return self.machines.get(code) or Machine(code=code, libelle=code)

    def dataframe(self) -> pd.DataFrame:
        """Vue tabulaire des articles (consultation, contrôle)."""
        rows = [
            {
                "ID": a.id,
                "Désignation": a.designation,
                "Nature": a.nature,
                "Catégorie": a.categorie,
                "Unité": a.unite,
                "Procédé": a.procede,
                "Site": a.site,
                "Intrants": len(a.nomenclature),
                "Machines": len(a.gamme),
            }
            for a in self.articles.values()
        ]
        return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Chargement
# --------------------------------------------------------------------------- #
def load_catalogue(path: str | Path) -> Catalogue:
    """Lit le classeur et construit le catalogue. Lève ``CatalogueError`` si inutilisable."""
    path = Path(path)
    if not path.exists():
        raise CatalogueError(f"Base articles introuvable : {path}")
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=object)
    except Exception as exc:  # fichier corrompu, mauvais format…
        raise CatalogueError(f"Lecture impossible du classeur « {path.name} » : {exc}") from exc
    return build_catalogue(sheets, source=path.name, mtime=path.stat().st_mtime)


def load_catalogue_bytes(content: bytes, source: str = "", mtime: float = 0.0) -> Catalogue:
    """Construit le catalogue à partir du contenu d'un classeur (fichier importé, base de données)."""
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=object)
    except Exception as exc:
        raise CatalogueError(f"Lecture impossible du classeur « {source or 'importé'} » : {exc}") from exc
    return build_catalogue(sheets, source=source, mtime=mtime)


def build_catalogue(sheets: dict[str, pd.DataFrame], source: str = "", mtime: float = 0.0) -> Catalogue:
    anomalies: list[str] = []

    base = _find_sheet(sheets, "BASE_ARTICLE", "BASE_ARTICLES", "ARTICLES")
    if base is None:
        raise CatalogueError("La feuille « BASE_ARTICLE » est absente du classeur.")

    col_id = _find_col(base, "ID_ARTICLES", "ID_ARTICLE", "ID", "CODE_ARTICLE", "CODE")
    col_des = _find_col(base, "DESIGNATION", "DESIGNATION_ARTICLE", "LIBELLE")
    col_nat = _find_col(base, "NATURE")
    col_cat = _find_col(base, "CATEGORIE", "CATEGORIE_ARTICLE", "FAMILLE")
    missing = [n for n, c in (("ID", col_id), ("DESIGNATION", col_des), ("NATURE", col_nat)) if c is None]
    if missing:
        raise CatalogueError("Colonnes obligatoires absentes de BASE_ARTICLE : " + ", ".join(missing))

    imput_cols: dict[str, str] = {}
    mach_cols: dict[str, str] = {}
    for col in base.columns:
        header = _norm_header(col)
        if m := IMPUT_RE.match(header):
            imput_cols[col] = _code("IMPUT", m.group(1))
        elif m := MACH_RE.match(header):
            mach_cols[col] = _code("MACH", m.group(1))

    attributs = _read_attributs(sheets, anomalies)
    intrants = _read_ref_intrants(sheets, anomalies)
    machines = _read_ref_machines(sheets, anomalies)

    articles: dict[str, Article] = {}
    for idx, row in base.iterrows():
        excel_row = int(idx) + 2  # ligne Excel (en-tête en ligne 1)
        art_id = clean_text(row.get(col_id))
        designation = clean_text(row.get(col_des))
        nature = clean_text(row.get(col_nat))
        if not art_id and not designation and not nature:
            continue  # ligne vide
        if not art_id:
            anomalies.append(f"Ligne {excel_row} ignorée : identifiant article manquant.")
            continue
        if not designation or not nature:
            anomalies.append(f"{art_id} ignoré : désignation ou nature manquante (ligne {excel_row}).")
            continue
        if art_id in articles:
            anomalies.append(f"{art_id} en double (ligne {excel_row}) : seule la première occurrence est retenue.")
            continue

        bom: list[BomLine] = []
        for col, code in imput_cols.items():
            qty = _quantity(row.get(col), art_id, code, anomalies)
            if qty:
                bom.append(BomLine(code, qty))
        routing: list[RoutingLine] = []
        for col, code in mach_cols.items():
            secs = _quantity(row.get(col), art_id, code, anomalies)
            if secs:
                routing.append(RoutingLine(code, secs))

        attr = attributs.get(art_id, {})
        if attributs and not attr:
            anomalies.append(f"{art_id} absent de ATTRIBUTS_ARTICLE : unité « pièce » retenue par défaut.")
        if not bom and not routing:
            anomalies.append(f"{art_id} ({designation}) n'a ni intrant ni machine : son coût de production sera nul.")

        articles[art_id] = Article(
            id=art_id,
            designation=designation,
            nature=nature,
            categorie=clean_text(row.get(col_cat)) if col_cat else "",
            unite=attr.get("unite") or "pièce",
            procede=attr.get("procede", ""),
            format_fini=attr.get("format_fini", ""),
            site=attr.get("site", ""),
            nomenclature=tuple(bom),
            gamme=tuple(routing),
        )

    if not articles:
        raise CatalogueError("Aucun article exploitable dans la feuille BASE_ARTICLE.")

    # Codes utilisés dans la base mais absents des référentiels.
    used_imput = {line.code for a in articles.values() for line in a.nomenclature}
    used_mach = {line.code for a in articles.values() for line in a.gamme}
    for code in sorted(used_imput - intrants.keys(), key=_code_sort):
        anomalies.append(f"{code} utilisé par des articles mais absent de REF_INTRANTS.")
        intrants[code] = Intrant(code=code, libelle=code)
    for code in sorted(used_mach - machines.keys(), key=_code_sort):
        anomalies.append(f"{code} utilisé par des articles mais absent de REF_MACHINES.")
        machines[code] = Machine(code=code, libelle=code)

    intrants = dict(sorted(intrants.items(), key=lambda kv: _code_sort(kv[0])))
    machines = dict(sorted(machines.items(), key=lambda kv: _code_sort(kv[0])))
    return Catalogue(articles, intrants, machines, anomalies, source, mtime)


def _code_sort(code: str) -> tuple[str, int]:
    m = re.match(r"([A-Z]+)(\d+)$", code)
    return (m.group(1), int(m.group(2))) if m else (code, 0)


def _quantity(value: object, art_id: str, code: str, anomalies: list[str]) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)) or clean_text(value) == "":
        return 0.0
    qty = to_float(value, None)
    if qty is None:
        anomalies.append(f"{art_id} / {code} : valeur « {clean_text(value)} » illisible, ignorée.")
        return 0.0
    if qty < 0:
        anomalies.append(f"{art_id} / {code} : valeur négative ({qty}) ignorée.")
        return 0.0
    return qty


def _read_attributs(sheets: dict[str, pd.DataFrame], anomalies: list[str]) -> dict[str, dict[str, str]]:
    df = _find_sheet(sheets, "ATTRIBUTS_ARTICLE", "ATTRIBUTS_ARTICLES", "ATTRIBUTS")
    if df is None:
        anomalies.append("Feuille ATTRIBUTS_ARTICLE absente : unités et procédés non renseignés.")
        return {}
    col_id = _find_col(df, "ID_ARTICLES", "ID_ARTICLE", "ID")
    if col_id is None:
        anomalies.append("ATTRIBUTS_ARTICLE sans colonne ID_ARTICLES : feuille ignorée.")
        return {}
    cols = {
        "unite": _find_col(df, "UNITE_ARTICLE", "UNITE"),
        "procede": _find_col(df, "PROCEDE_PRINCIPAL", "PROCEDE"),
        "format_fini": _find_col(df, "FORMAT_FINI", "FORMAT"),
        "site": _find_col(df, "SITE_PRODUCTION", "SITE"),
    }
    result: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        art_id = clean_text(row.get(col_id))
        if art_id:
            result[art_id] = {k: clean_text(row.get(c)) if c else "" for k, c in cols.items()}
    return result


def _read_ref_intrants(sheets: dict[str, pd.DataFrame], anomalies: list[str]) -> dict[str, Intrant]:
    df = _find_sheet(sheets, "REF_INTRANTS", "REF_INTRANT", "INTRANTS")
    if df is None:
        anomalies.append("Feuille REF_INTRANTS absente : libellés et conversions d'unités indisponibles.")
        return {}
    col_code = _find_col(df, "CODE", "CODE_INTRANT") or df.columns[0]
    get = lambda *a: _find_col(df, *a)  # noqa: E731
    c_lib, c_fam, c_cat = get("LIBELLE", "DESIGNATION"), get("FAMILLE"), get("CATEGORIE_STOCK", "CATEGORIE")
    c_ua, c_cond, c_uc = get("UOM_ACHAT"), get("CONDITIONNEMENT"), get("UOM_CONSO")
    c_fact, c_src = get("FACTEUR_CONVERSION", "FACTEUR"), get("SOURCE")
    result: dict[str, Intrant] = {}
    for _, row in df.iterrows():
        raw = _norm_header(row.get(col_code))
        m = IMPUT_RE.match(raw)
        if not m:
            continue
        code = _code("IMPUT", m.group(1))
        facteur = to_float(row.get(c_fact), None) if c_fact else None
        if not facteur or facteur <= 0:
            anomalies.append(f"{code} : facteur de conversion absent ou nul, 1 retenu.")
            facteur = 1.0
        result[code] = Intrant(
            code=code,
            libelle=clean_text(row.get(c_lib)) if c_lib else code,
            famille=clean_text(row.get(c_fam)) if c_fam else "",
            categorie_stock=clean_text(row.get(c_cat)) if c_cat else "",
            uom_achat=clean_text(row.get(c_ua)) if c_ua else "",
            conditionnement=clean_text(row.get(c_cond)) if c_cond else "",
            uom_conso=clean_text(row.get(c_uc)) if c_uc else "",
            facteur_conversion=float(facteur),
            source=clean_text(row.get(c_src)) if c_src else "",
        )
    return result


def _read_ref_machines(sheets: dict[str, pd.DataFrame], anomalies: list[str]) -> dict[str, Machine]:
    df = _find_sheet(sheets, "REF_MACHINES", "REF_MACHINE", "MACHINES")
    if df is None:
        anomalies.append("Feuille REF_MACHINES absente : libellés machines indisponibles.")
        return {}
    # La première colonne porte le code (en-tête parfois mal saisi dans le classeur).
    col_code = _find_col(df, "CODE", "CODE_MACHINE") or df.columns[0]
    get = lambda *a: _find_col(df, *a)  # noqa: E731
    c_lib, c_at, c_site = get("MACHINE", "LIBELLE"), get("ATELIER"), get("SITE")
    c_cad, c_src = get("CADENCE_REFERENCE", "CADENCE"), get("SOURCE")
    result: dict[str, Machine] = {}
    for _, row in df.iterrows():
        m = MACH_RE.match(_norm_header(row.get(col_code)))
        if not m:
            continue
        code = _code("MACH", m.group(1))
        result[code] = Machine(
            code=code,
            libelle=clean_text(row.get(c_lib)) if c_lib else code,
            atelier=clean_text(row.get(c_at)) if c_at else "",
            site=clean_text(row.get(c_site)) if c_site else "",
            cadence=clean_text(row.get(c_cad)) if c_cad else "",
            source=clean_text(row.get(c_src)) if c_src else "",
        )
    return result
