"""Accès aux données depuis l'interface, avec mise en cache Streamlit.

Adresse de la base (même convention que les autres applications hébergées) :
secret Streamlit ``[neon] url``. Formats également acceptés : ``[connections.neon]
url``, clés de premier niveau ``NEON_URL`` ou ``DATABASE_URL``, variables
d'environnement du même nom. Sans adresse, l'application utilise un fichier
SQLite local et fonctionne sans configuration.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import streamlit as st

from digiprint import config
from digiprint.catalogue import Catalogue, load_catalogue, load_catalogue_bytes
from digiprint.historique import Enregistrement, HistoriqueStore
from digiprint.parametres import Parametres, ParametresStore
from digiprint.stockage import BASE_ARTICLES, Database, FichiersStore, ouvrir_base


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #
def _secret(*path: str) -> Any:
    """Lecture tolérante d'un secret (absence de fichier secrets.toml comprise)."""
    try:
        node: Any = st.secrets
        for part in path:
            node = node[part]
        return node
    except Exception:
        return None


def neon_url() -> str | None:
    """Adresse de la base Neon / PostgreSQL configurée, ou ``None`` (SQLite local)."""
    for path in (("neon", "url"), ("connections", "neon", "url"), ("NEON_URL",), ("DATABASE_URL",)):
        value = _secret(*path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None  # les variables d'environnement sont lues par stockage.resolve_url


def _admin_secret() -> tuple[str | None, str | None]:
    clair = _secret("admin", "mot_de_passe") or config.admin_password()
    empreinte = _secret("admin", "mot_de_passe_sha256")
    return (str(clair) if clair else None, str(empreinte).lower() if empreinte else None)


def admin_requis() -> bool:
    clair, empreinte = _admin_secret()
    return bool(clair or empreinte)


def admin_verifier(saisie: str) -> bool:
    clair, empreinte = _admin_secret()
    if empreinte:
        return hmac.compare_digest(hashlib.sha256(saisie.encode("utf-8")).hexdigest(), empreinte)
    return bool(clair) and hmac.compare_digest(saisie, clair)


# --------------------------------------------------------------------------- #
# Base de données
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner="Connexion à la base de données…")
def get_db() -> Database:
    return ouvrir_base(neon_url())


# --------------------------------------------------------------------------- #
# Base articles
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BaseInfo:
    """Provenance de la base articles utilisée."""

    origine: str  # « import » ou « fichier »
    nom: str
    date: datetime | None
    fichier_id: int | None
    empreinte: str


@st.cache_data(ttl=60, show_spinner=False)
def base_info() -> BaseInfo:
    stored = FichiersStore(get_db()).dernier(BASE_ARTICLES, avec_contenu=False)
    if stored is not None:
        return BaseInfo("import", stored.nom, stored.cree_le, stored.id, stored.empreinte)
    path = config.BASE_ARTICLES_FILE
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return BaseInfo("fichier", path.name, datetime.fromtimestamp(mtime) if mtime else None, None,
                    f"{path}:{mtime}")


@st.cache_resource(show_spinner="Chargement de la base articles…", max_entries=3)
def _catalogue(origine: str, fichier_id: int | None, empreinte: str) -> Catalogue:
    if origine == "import" and fichier_id is not None:
        stored = FichiersStore(get_db()).obtenir(fichier_id)
        if stored is not None and stored.contenu is not None:
            return load_catalogue_bytes(stored.contenu, source=stored.nom,
                                        mtime=stored.cree_le.timestamp())
    return load_catalogue(config.BASE_ARTICLES_FILE)


def _cle(info: BaseInfo) -> tuple[str, int | None, str]:
    return info.origine, info.fichier_id, info.empreinte


def get_catalogue() -> Catalogue:
    return _catalogue(*_cle(base_info()))


def invalider_base() -> None:
    base_info.clear()
    _parametres.clear()


# --------------------------------------------------------------------------- #
# Paramètres
# --------------------------------------------------------------------------- #
@st.cache_resource(ttl=60, show_spinner=False, max_entries=3)
def _parametres(origine: str, fichier_id: int | None, empreinte: str) -> Parametres:
    return ParametresStore(get_db()).load(_catalogue(origine, fichier_id, empreinte))


def get_parametres() -> Parametres:
    return _parametres(*_cle(base_info()))


def parametres_store() -> ParametresStore:
    return ParametresStore(get_db())


def invalider_parametres() -> None:
    _parametres.clear()


# --------------------------------------------------------------------------- #
# Historique
# --------------------------------------------------------------------------- #
def historique_store() -> HistoriqueStore:
    return HistoriqueStore(get_db())


@st.cache_data(ttl=30, show_spinner=False)
def lister_historique(recherche: str, debut: date | None, fin: date | None) -> list[Enregistrement]:
    return historique_store().lister(recherche=recherche, debut=debut, fin=fin)


def invalider_historique() -> None:
    lister_historique.clear()


def environnement() -> dict[str, str]:
    """Informations d'exploitation affichées dans la page Paramètres."""
    db = get_db()
    return {
        "stockage": db.libelle,
        "cible": db.cible,
        "configuration": "secret Streamlit [neon]" if neon_url() else (
            "variable d'environnement" if any(os.environ.get(v) for v in config.DATABASE_ENV_VARS)
            else "aucune (fichier local)"),
    }
