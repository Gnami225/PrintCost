from digiprint.catalogue import build_catalogue, load_catalogue_bytes
from digiprint.models import unit_spec
from tests.conftest import BASE
import pandas as pd


def test_base_reelle(catalogue):
    assert len(catalogue.articles) == 273
    assert len(catalogue.designations()) == 52
    assert len(catalogue.intrants) == 50 and len(catalogue.machines) == 20
    assert catalogue.anomalies == []


def test_article_carte(catalogue):
    art = catalogue.get("ART-0001")
    assert art.designation == "Carte de visite"
    assert {l.code: l.quantite for l in art.nomenclature} == {"IMPUT4": 0.0125, "IMPUT39": 0.006}
    assert art.uses_machine("MACH11")


def test_natures_par_designation_insensible_casse(catalogue):
    assert len(catalogue.articles_for("CARTE DE VISITE")) == 17


def test_chargement_depuis_octets():
    assert len(load_catalogue_bytes(BASE.read_bytes(), "x.xlsx").articles) == 273


def test_anomalies_tolerees():
    df = pd.DataFrame({"ID_ARTICLES": ["A1", "A1", None], "DESIGNATION ": ["X", "X", "Y"],
                       "NATURE": ["n", "n", "m"], "IMPUT1": ["0,5", "abc", None], "MACH1": [-1, 2, None]})
    cat = build_catalogue({"BASE_ARTICLE": df})
    assert list(cat.articles) == ["A1"]
    assert cat.get("A1").nomenclature[0].quantite == 0.5
    assert any("double" in a for a in cat.anomalies)
    assert any("négative" in a for a in cat.anomalies)


def test_unites():
    assert unit_spec("lot de 1 000").divisor == 1000
    assert not unit_spec("m²").integer
    assert unit_spec("pièce").key == "piece"
