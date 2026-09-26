"""Fonctions utilitaires sans dépendance à Streamlit.

- normalisation de texte (recherche insensible à la casse et aux accents) ;
- conversion robuste des nombres saisis ou lus dans Excel ;
- formatage des montants à la française (espace insécable, virgule décimale).
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

NBSP = "\u00a0"  # espace insécable : séparateur de milliers


# --------------------------------------------------------------------------- #
# Texte
# --------------------------------------------------------------------------- #
def clean_text(value: Any) -> str:
    """Convertit en texte, supprime les espaces superflus. ``None``/NaN → ''."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    return re.sub(r"\s+", " ", text)


def normalize(value: Any) -> str:
    """Clé de comparaison : minuscules, sans accents, espaces réduits."""
    text = unicodedata.normalize("NFKD", clean_text(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace("œ", "oe").replace("æ", "ae")


def matches(query: str, *fields: Any) -> bool:
    """Recherche partielle multi-mots, insensible à la casse et aux accents.

    Tous les mots de ``query`` doivent apparaître dans l'un des champs.
    """
    tokens = normalize(query).split()
    if not tokens:
        return True
    haystack = " ".join(normalize(f) for f in fields)
    return all(tok in haystack for tok in tokens)


def slugify_code(label: str, prefix: str = "") -> str:
    """Code technique en majuscules à partir d'un libellé (``'Coins ronds'`` → ``'COINS_RONDS'``)."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", normalize(label)).strip("_").upper()
    return f"{prefix}{base}" if base else prefix.rstrip("_") or "CODE"


GRAMMAGE_RE = re.compile(r"(\d{2,3})\s*g\b", re.IGNORECASE)


def parse_grammage(label: str) -> int | None:
    """Grammage (g/m²) lu dans un libellé : ``'Papier couché mat 300 g'`` → 300."""
    found = GRAMMAGE_RE.findall(clean_text(label))
    return int(found[-1]) if found else None


# --------------------------------------------------------------------------- #
# Nombres
# --------------------------------------------------------------------------- #
def to_float(value: Any, default: float | None = 0.0) -> float | None:
    """Conversion tolérante : ``'1 250,5'`` → 1250.5 ; vide/NaN/illisible → ``default``."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return default if math.isnan(float(value)) or math.isinf(float(value)) else float(value)
    text = str(value).strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if not text:
        return default
    text = text.replace(",", ".")
    try:
        result = float(text)
    except ValueError:
        return default
    return default if math.isnan(result) or math.isinf(result) else result


def ceil_clean(value: float) -> int:
    """Arrondi supérieur tolérant aux erreurs d'arrondi flottant (25.0000000001 → 25)."""
    return int(math.ceil(round(value, 6)))


# --------------------------------------------------------------------------- #
# Formatage français
# --------------------------------------------------------------------------- #
def fmt_number(value: float | None, decimals: int = 0) -> str:
    """``1234567.891`` → ``'1 234 567,89'`` (espace insécable, virgule décimale)."""
    if value is None:
        return "–"
    if isinstance(value, float) and math.isnan(value):
        return "–"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", NBSP).replace(".", ",")


def fmt_smart(value: float | None, max_decimals: int = 2) -> str:
    """Nombre avec décimales seulement si utiles : 25 → '25' ; 6.25 → '6,25' ; 0.0125 → '0,0125'."""
    if value is None:
        return "–"
    if abs(value - round(value)) < 1e-9:
        return fmt_number(round(value), 0)
    decimals = max_decimals
    # Petites valeurs : on garde assez de chiffres significatifs.
    if 0 < abs(value) < 1:
        decimals = max(max_decimals, min(6, -int(math.floor(math.log10(abs(value)))) + 2))
    text = fmt_number(value, decimals)
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def fmt_money(value: float | None, devise: str = "FCFA", decimals: int | None = None) -> str:
    """Montant en devise. Par défaut : entier au-delà de 100, deux décimales en dessous."""
    if value is None:
        return "–"
    if decimals is None:
        decimals = 0 if abs(value) >= 100 else 2
    text = fmt_number(value, decimals)
    if decimals and "," in text:
        text = text.rstrip("0").rstrip(",")
    return f"{text}{NBSP}{devise}"


def plural(count: float, singular: str, plural_form: str | None = None) -> str:
    """Accord simple : 1 feuille, 2 feuilles (règle française : < 2 → singulier)."""
    if abs(count) < 2:
        return singular
    return plural_form or (singular if singular.endswith(("s", "x", "z")) else singular + "s")


def fmt_duration(seconds: float | None) -> str:
    """Durée lisible : 25 → '25 s' ; 250 → '4 min 10 s' ; 5400 → '1 h 30 min'."""
    if seconds is None:
        return "–"
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{fmt_smart(seconds, 1)}{NBSP}s"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}{NBSP}h{NBSP}{minutes:02d}{NBSP}min" if minutes else f"{hours}{NBSP}h"
    return f"{minutes}{NBSP}min{NBSP}{secs:02d}{NBSP}s" if secs else f"{minutes}{NBSP}min"


_ABBREVIATIONS = {"ml", "g", "kg", "l", "m²", "m2", "km", "h", "cm", "mm", "fcfa", "%"}


def unit_plural(count: float, unit: str) -> str:
    """Accorde une unité : (2, 'feuille SRA3') → 'feuilles SRA3' ; (3, 'ml') → 'ml'."""
    if not unit or abs(count) < 2:
        return unit
    if unit == "mètre linéaire":
        return "mètres linéaires"
    words = unit.split(" ")
    head = words[0]
    if head.lower() in _ABBREVIATIONS or not head.isalpha() or len(head) < 3:
        return unit
    words[0] = plural(count, head)
    return " ".join(words)
