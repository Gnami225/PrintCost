"""Fixtures communes : base articles réelle, base de données jetable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from digiprint.catalogue import load_catalogue  # noqa: E402
from digiprint.parametres import ParametresStore  # noqa: E402
from digiprint.stockage import ouvrir_base  # noqa: E402

BASE = ROOT / "data" / "BASE_ARTICLE_DIGIPRINT.xlsx"


@pytest.fixture(scope="session")
def catalogue():
    return load_catalogue(BASE)


def _urls():
    urls = ["sqlite"]
    if os.environ.get("DIGIPRINT_TEST_PG"):
        urls.append("postgresql")
    return urls


@pytest.fixture(params=_urls())
def db(request, tmp_path):
    """Base SQLite temporaire ; PostgreSQL aussi si DIGIPRINT_TEST_PG contient une adresse."""
    if request.param == "sqlite":
        return ouvrir_base(f"sqlite:///{tmp_path / 'test.sqlite'}")
    base = ouvrir_base(os.environ["DIGIPRINT_TEST_PG"])
    from digiprint.stockage import metadata
    metadata.drop_all(base.engine)
    base.initialiser()
    return base


@pytest.fixture
def params(db, catalogue):
    return ParametresStore(db).load(catalogue)
