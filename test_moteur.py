import copy

import pytest

from digiprint.models import PricingRequest
from digiprint.moteur import calculer, compute
from digiprint.parametres import Parametres


def _lines(result, code):
    return [l for l in result.lines if l.code == code]


def test_invariant_montant(catalogue, params):
    for art_id in ["ART-0001", "ART-0077", "ART-0144", "ART-0161", "ART-0268", "ART-0200"]:
        r = calculer(catalogue, params, PricingRequest(art_id, 300, livraison=True, transport="MOTO", distance_km=5))
        for l in r.lines:
            assert l.montant == pytest.approx(l.quantite * l.prix_unitaire)
        assert r.total == pytest.approx(sum(l.montant for l in r.lines))
        assert r.total == pytest.approx(sum(r.par_poste.values()))


def test_carte_de_visite(catalogue, params):
    r = calculer(catalogue, params, PricingRequest("ART-0001", 500))
    plan = r.feuilles[0]
    assert (plan.feuilles, plan.format_code, plan.poses) == (25, "SRA3", 21)
    assert r.estimations["DECOUPE"].value == 20
    papier = _lines(r, "IMPUT4")[0]
    assert papier.prix_unitaire == pytest.approx(35000 / 100 / 4)
    # Massicot valorisé à la coupe : pas de ligne machine MACH11.
    assert not _lines(r, "MACH11")
    assert _lines(r, "DECOUPE")[0].montant == pytest.approx(20 * 25)


def test_saisie_remplace_estimation(catalogue, params):
    r = calculer(catalogue, params, PricingRequest("ART-0001", 500, feuilles={"IMPUT4": 30}, operations={"DECOUPE": 8}))
    assert _lines(r, "IMPUT4")[0].quantite == 30
    assert _lines(r, "DECOUPE")[0].quantite == 8
    r0 = calculer(catalogue, params, PricingRequest("ART-0001", 500, operations={"DECOUPE": 0}))
    assert not _lines(r0, "DECOUPE")


def test_offset_au_lot(catalogue, params):
    r = calculer(catalogue, params, PricingRequest("ART-0144", 5000))
    assert r.quantite_nomenclature == 5
    assert r.feuilles[0].format_code == "A1" and r.feuilles[0].feuilles == 900
    assert r.cout_nomenclature == pytest.approx(r.total / 5)


def test_bache_au_m2(catalogue, params):
    r = calculer(catalogue, params, PricingRequest("ART-0161", 12.5))
    assert r.feuilles == []
    assert _lines(r, "IMPUT10")[0].quantite == pytest.approx(0.3472 * 12.5)


def test_rainage_selon_papier_et_grammage(catalogue, params):
    r170 = calculer(catalogue, params, PricingRequest("ART-0044", 1000))
    assert r170.estimations["RAINAGE"].value == 2
    ligne = _lines(r170, "RAINAGE")[0]
    assert ligne.quantite == 2000 and ligne.prix_unitaire == params.tarif_papier("RAINAGE", "IMPUT2")
    r130 = calculer(catalogue, params, PricingRequest("ART-0043", 1000))
    assert r130.estimations["RAINAGE"].value == 0 and not _lines(r130, "RAINAGE")


def test_transport_aller_retour(catalogue, params):
    r = calculer(catalogue, params, PricingRequest("ART-0001", 100, livraison=True, transport="MOTO", distance_km=12))
    t = _lines(r, "MOTO")[0]
    assert t.quantite == 24 and t.montant == pytest.approx(24 * 150)
    r2 = calculer(catalogue, params, PricingRequest("ART-0001", 100, livraison=True, transport="MOTO"))
    assert not _lines(r2, "MOTO") and r2.alertes


def test_emballage_et_frais_ponctuels(catalogue, params):
    r = calculer(catalogue, params, PricingRequest(
        "ART-0001", 100, emballage="CARTON_M", emballage_nombre=3, emballage_cout_unitaire=700,
        frais_ponctuels=[{"libelle": "Création", "montant": 10000}, {"libelle": "Remise", "montant": -5}]))
    assert _lines(r, "CARTON_M")[0].montant == 2100
    assert _lines(r, "PONCTUEL_1")[0].montant == 10000
    assert not _lines(r, "PONCTUEL_2") and any("négatif" in a for a in r.alertes)


def test_frais_pourcentage(catalogue, params):
    data = copy.deepcopy(params.data)
    data["frais"].append({"code": "STRUCT", "libelle": "Structure", "mode": "pourcentage", "valeur": 10,
                          "assiette": "hors_frais", "actif": True})
    p = Parametres(data)
    r = calculer(catalogue, p, PricingRequest("ART-0001", 100, emballage="CARTON_M", emballage_nombre=1))
    avant = sum(l.montant for l in r.lines if l.origine != "frais")
    assert _lines(r, "STRUCT")[0].montant == pytest.approx(avant * 0.10)
    production = sum(l.montant for l in r.lines if l.poste not in ("Emballage", "Transport", "Autres frais"))
    assert _lines(r, "ATELIER")[0].montant == pytest.approx(production * 0.03)


def test_prix_manquant(catalogue, params):
    data = copy.deepcopy(params.data)
    next(r for r in data["intrants"] if r["code"] == "IMPUT39")["prix_achat"] = None
    r = calculer(catalogue, Parametres(data), PricingRequest("ART-0001", 100))
    assert _lines(r, "IMPUT39")[0].prix_manquant
    assert any(a.startswith("Prix manquant") for a in r.alertes)


def test_operation_desactivee_rend_le_temps_machine(catalogue, params):
    data = copy.deepcopy(params.data)
    next(o for o in data["operations"] if o["code"] == "DECOUPE")["actif"] = False
    r = calculer(catalogue, Parametres(data), PricingRequest("ART-0001", 500))
    assert _lines(r, "MACH11") and not _lines(r, "DECOUPE")


def test_quantite_nulle(catalogue, params):
    r = calculer(catalogue, params, PricingRequest("ART-0001", 0))
    assert r.cout_unitaire == 0 and r.alertes
