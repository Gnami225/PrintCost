"""Stockage des données : Neon PostgreSQL en hébergement, SQLite en local.

Un seul code pour les deux moteurs : SQLAlchemy traduit les requêtes.

Adresse de la base, par ordre de priorité :

1. adresse transmise par l'application (secret Streamlit ``[neon] url``) ;
2. variables d'environnement ``NEON_URL``, ``DIGIPRINT_DATABASE_URL``, ``DATABASE_URL`` ;
3. à défaut, fichier SQLite ``data/digiprint.sqlite`` (aucune configuration requise).

Les tables sont créées au premier lancement si elles n'existent pas, et
préfixées ``digiprint_`` pour cohabiter avec les tables d'autres applications
dans une même base Neon. Neon suspend la base après une période d'inactivité :
les connexions sont vérifiées avant usage (``pool_pre_ping``) et renouvelées
toutes les cinq minutes, ce qui évite les erreurs de connexion au réveil.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from . import config

P = config.TABLE_PREFIX
metadata = MetaData()

# Paramètres de tarification : un document JSON (ligne « courant »).
t_parametres = Table(
    f"{P}parametres", metadata,
    Column("cle", String(40), primary_key=True),
    Column("donnees", Text, nullable=False),
    Column("empreinte", String(40), nullable=False),
    Column("mis_a_jour_le", DateTime, nullable=False),
)

# Versions précédentes des paramètres (restaurables depuis l'application).
t_sauvegardes = Table(
    f"{P}parametres_sauvegardes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cree_le", DateTime, nullable=False),
    Column("motif", String(200), nullable=False),
    Column("empreinte", String(40), nullable=False),
    Column("donnees", Text, nullable=False),
)

# Historique des calculs enregistrés.
t_calculs = Table(
    f"{P}calculs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cree_le", DateTime, nullable=False, index=True),
    Column("reference", String(200), nullable=False),
    Column("article_id", String(60), nullable=False, index=True),
    Column("designation", String(300), nullable=False),
    Column("nature", String(500), nullable=False),
    Column("categorie", String(300), nullable=False),
    Column("quantite", Float, nullable=False),
    Column("unite", String(80), nullable=False),
    Column("total", Float, nullable=False),
    Column("cout_unitaire", Float, nullable=False),
    Column("parametres_version", String(40), nullable=False),
    Column("requete_json", Text, nullable=False),
    Column("lignes_json", Text, nullable=False),
    Column("postes_json", Text, nullable=False),
    Column("alertes_json", Text, nullable=False),
)

# Fichiers importés depuis l'application (versions de la base articles).
t_fichiers = Table(
    f"{P}fichiers", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("type", String(40), nullable=False, index=True),
    Column("nom", String(300), nullable=False),
    Column("taille", Integer, nullable=False),
    Column("empreinte", String(64), nullable=False),
    Column("cree_le", DateTime, nullable=False),
    Column("contenu", LargeBinary, nullable=False),
)

TABLES = (t_parametres, t_sauvegardes, t_calculs, t_fichiers)
BASE_ARTICLES = "base_articles"


class StockageError(Exception):
    """Base de données inaccessible ou adresse invalide."""


def maintenant() -> datetime:
    """Horodatage UTC sans fuseau (UTC = heure d'Abidjan), à la seconde."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# --------------------------------------------------------------------------- #
# Adresse et connexion
# --------------------------------------------------------------------------- #
def local_url(path: Path | None = None) -> str:
    return f"sqlite:///{Path(path or config.LOCAL_DB_FILE).resolve().as_posix()}"


def normalize_url(url: str) -> str:
    """Adresse SQLAlchemy exploitable.

    Accepte la chaîne copiée depuis la console Neon (``postgresql://…`` ou
    ``postgres://…``) et la convertit pour le pilote psycopg2 ; ajoute
    ``sslmode=require`` pour un hôte Neon qui ne le précise pas.
    """
    url = url.strip().strip('"').strip("'")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg2://" + url[len(prefix):]
            break
    try:
        parsed = make_url(url)
    except ArgumentError as exc:
        raise StockageError(f"Adresse de base de données invalide : {exc}") from exc
    if parsed.get_backend_name() == "postgresql" and "sslmode" not in parsed.query:
        if (parsed.host or "").endswith(".neon.tech"):
            parsed = parsed.update_query_dict({"sslmode": "require"})
    return parsed.render_as_string(hide_password=False)


def resolve_url(explicit: str | None = None) -> str:
    """Adresse retenue : explicite, sinon variables d'environnement, sinon SQLite local."""
    candidates = [explicit] + [os.environ.get(name) for name in config.DATABASE_ENV_VARS]
    for candidate in candidates:
        if candidate and str(candidate).strip():
            return normalize_url(str(candidate))
    return local_url()


def _make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        return engine
    return create_engine(
        url,
        pool_pre_ping=True,       # Neon suspend la base : vérifie la connexion avant usage
        pool_recycle=300,         # renouvelle les connexions toutes les 5 minutes
        pool_size=3,
        max_overflow=3,
        connect_args={"connect_timeout": 20} if parsed.get_backend_name() == "postgresql" else {},
    )


class Database:
    """Accès à la base (moteur SQLAlchemy) et informations d'affichage."""

    def __init__(self, engine: Engine):
        self.engine = engine

    @property
    def est_postgres(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    @property
    def est_neon(self) -> bool:
        return self.est_postgres and (self.engine.url.host or "").endswith(".neon.tech")

    @property
    def libelle(self) -> str:
        """« Neon PostgreSQL », « PostgreSQL » ou « SQLite local »."""
        if self.est_neon:
            return "Neon PostgreSQL"
        return "PostgreSQL" if self.est_postgres else "SQLite local"

    @property
    def cible(self) -> str:
        """Emplacement lisible, sans mot de passe."""
        url = self.engine.url
        if self.est_postgres:
            return f"{url.host or 'localhost'} / {url.database}"
        return str(url.database or "mémoire")

    def initialiser(self) -> None:
        """Crée les tables manquantes (sans toucher aux tables existantes)."""
        metadata.create_all(self.engine, checkfirst=True)

    def verifier(self) -> None:
        """Lève ``StockageError`` si la base ne répond pas."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise StockageError(_message_erreur(exc, self)) from exc


def ouvrir_base(url: str | None = None, initialiser: bool = True) -> Database:
    """Ouvre la base (Neon si configurée, SQLite local sinon) et crée les tables si besoin."""
    resolved = resolve_url(url)
    db = Database(_make_engine(resolved))
    if initialiser:
        try:
            db.initialiser()
        except SQLAlchemyError as exc:
            raise StockageError(_message_erreur(exc, db)) from exc
    return db


def _message_erreur(exc: Exception, db: Database) -> str:
    detail = str(getattr(exc, "orig", exc)).strip().splitlines()[0] if str(exc) else exc.__class__.__name__
    return f"Connexion impossible à la base {db.libelle} ({db.cible}) : {detail}"


# --------------------------------------------------------------------------- #
# Fichiers importés (base articles)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FichierStocke:
    id: int
    type: str
    nom: str
    taille: int
    empreinte: str
    cree_le: datetime
    contenu: bytes | None = None


class FichiersStore:
    """Versions successives d'un fichier importé (les plus récentes sont conservées)."""

    def __init__(self, db: Database, max_versions: int = config.MAX_BASE_VERSIONS):
        self.db = db
        self.max_versions = max_versions

    def dernier(self, type_: str = BASE_ARTICLES, avec_contenu: bool = True) -> FichierStocke | None:
        return self._premier(select(*self._colonnes(avec_contenu))
                             .where(t_fichiers.c.type == type_)
                             .order_by(t_fichiers.c.id.desc()).limit(1))

    def obtenir(self, id_: int) -> FichierStocke | None:
        return self._premier(select(*self._colonnes(True)).where(t_fichiers.c.id == int(id_)))

    def versions(self, type_: str = BASE_ARTICLES) -> list[FichierStocke]:
        query = (select(*self._colonnes(False)).where(t_fichiers.c.type == type_)
                 .order_by(t_fichiers.c.id.desc()))
        with self.db.engine.connect() as conn:
            return [self._to_obj(row) for row in conn.execute(query)]

    def enregistrer(self, contenu: bytes, nom: str, type_: str = BASE_ARTICLES) -> FichierStocke:
        empreinte = hashlib.sha256(contenu).hexdigest()
        valeurs = dict(type=type_, nom=nom, taille=len(contenu), empreinte=empreinte,
                       cree_le=maintenant(), contenu=contenu)
        with self.db.engine.begin() as conn:
            new_id = conn.execute(insert(t_fichiers).values(**valeurs)).inserted_primary_key[0]
            garder = (select(t_fichiers.c.id).where(t_fichiers.c.type == type_)
                      .order_by(t_fichiers.c.id.desc()).limit(self.max_versions))
            conn.execute(delete(t_fichiers).where(t_fichiers.c.type == type_,
                                                  t_fichiers.c.id.not_in(garder)))
        return FichierStocke(id=int(new_id), **valeurs)

    def supprimer_tout(self, type_: str = BASE_ARTICLES) -> int:
        """Revient au fichier livré avec l'application (supprime les versions importées)."""
        with self.db.engine.begin() as conn:
            return conn.execute(delete(t_fichiers).where(t_fichiers.c.type == type_)).rowcount or 0

    # ------------------------------------------------------------------ #
    @staticmethod
    def _colonnes(avec_contenu: bool) -> list:
        cols = [t_fichiers.c.id, t_fichiers.c.type, t_fichiers.c.nom, t_fichiers.c.taille,
                t_fichiers.c.empreinte, t_fichiers.c.cree_le]
        return cols + ([t_fichiers.c.contenu] if avec_contenu else [])

    def _premier(self, query) -> FichierStocke | None:
        with self.db.engine.connect() as conn:
            row = conn.execute(query).first()
        return self._to_obj(row) if row is not None else None

    @staticmethod
    def _to_obj(row) -> FichierStocke:
        data = row._mapping
        contenu = data.get("contenu")
        return FichierStocke(
            id=int(data["id"]), type=data["type"], nom=data["nom"], taille=int(data["taille"]),
            empreinte=data["empreinte"], cree_le=data["cree_le"],
            contenu=bytes(contenu) if contenu is not None else None,
        )
