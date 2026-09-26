"""Tests de l'interface (exécution réelle des pages Streamlit)."""

import os
import shutil

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import BASE, ROOT


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGIPRINT_DATA_DIR", str(tmp_path))
    for var in ("NEON_URL", "DIGIPRINT_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    shutil.copy(BASE, tmp_path / BASE.name)
    monkeypatch.chdir(ROOT)
    import digiprint.config as config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "BASE_ARTICLES_FILE", tmp_path / BASE.name)
    monkeypatch.setattr(config, "LOCAL_DB_FILE", tmp_path / "digiprint.sqlite")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    return at


def test_parcours_tarification(app):
    assert not app.exception
    app.selectbox(key="tarif_designation").set_value("Dépliant").run()
    app.selectbox(key="tarif_article_DEPLIANT").set_value("ART-0044").run()
    app.number_input(key="tarif_qte_piece").set_value(1000).run()
    app.number_input(key="tarif_distance").set_value(12).run()
    assert not app.exception and not app.warning
    corps = " ".join(h.proto.body for h in app.get("html"))
    assert "dp-ep-total" in corps and "Rainage" in corps
    app.button(key="tarif_enregistrer").click().run()
    assert not app.exception
    assert "sous le n°" in " ".join(h.proto.body for h in app.get("html"))
