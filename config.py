"""Configuration centrale : chemins, constantes et paramètres d'hébergement.

Stockage des données
--------------------
L'application enregistre ses paramètres, l'historique des calculs et les
versions importées de la base articles dans une base de données :

- **Neon PostgreSQL** lorsqu'une adresse est configurée (hébergement sur
  Streamlit Community Cloud) : secret ``[neon] url`` ou variable
  d'environnement ``NEON_URL`` ;
- **SQLite local** (``data/digiprint.sqlite``) sinon, pour un usage sur poste
  sans aucune configuration.

Variables d'environnement reconnues (toutes facultatives) :

- ``NEON_URL``                 adresse PostgreSQL (prioritaire sur les deux suivantes)
- ``DIGIPRINT_DATABASE_URL``   adresse de base de données, tout moteur SQLAlchemy
- ``DATABASE_URL``             idem (convention de nombreux hébergeurs)
- ``DIGIPRINT_DATA_DIR``       dossier des données locales (SQLite, base articles)
- ``DIGIPRINT_BASE_ARTICLES``  chemin du classeur de la base articles livré avec l'application
- ``DIGIPRINT_ADMIN_PASSWORD`` mot de passe protégeant la page Paramètres
"""

from __future__ import annotations

import os
from pathlib import Path

APP_TITLE = "DIGIPRINT Tarification"
DEVISE = "FCFA"

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DIGIPRINT_DATA_DIR", ROOT_DIR / "data"))

# Classeur livré avec l'application (utilisé tant qu'aucune version n'a été importée).
BASE_ARTICLES_FILE = Path(
    os.environ.get("DIGIPRINT_BASE_ARTICLES", DATA_DIR / "BASE_ARTICLE_DIGIPRINT.xlsx")
)
# Base locale utilisée quand aucune adresse Neon / PostgreSQL n'est configurée.
LOCAL_DB_FILE = DATA_DIR / "digiprint.sqlite"

# Préfixe des tables : l'application peut partager une base Neon avec d'autres applications.
TABLE_PREFIX = "digiprint_"

# Nombre de sauvegardes conservées (paramètres) et de versions de la base articles.
MAX_BACKUPS = 30
MAX_BASE_VERSIONS = 10

# Variables d'environnement lues, par ordre de priorité, pour l'adresse de la base.
DATABASE_ENV_VARS = ("NEON_URL", "DIGIPRINT_DATABASE_URL", "DATABASE_URL")


def admin_password() -> str | None:
    """Mot de passe administrateur facultatif (variable d'environnement)."""
    value = os.environ.get("DIGIPRINT_ADMIN_PASSWORD", "").strip()
    return value or None
