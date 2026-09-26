"""Page Paramètres : tous les coûts de la tarification, modifiables sans toucher au code.

Les tableaux modifient un brouillon ; rien n'est enregistré avant « Enregistrer
les paramètres ». Le brouillon survit à un changement de page. Chaque
enregistrement conserve la version remplacée (onglet Sauvegardes) et refuse
d'écraser une modification faite entre-temps par un autre utilisateur.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import pandas as pd
import streamlit as st

from digiprint import config
from digiprint.catalogue import Catalogue, CatalogueError, load_catalogue_bytes
from digiprint.models import POSTE_CONSOMMABLES, POSTE_MATIERES, POSTE_PAPIER, POSTES_TECHNIQUES
from digiprint.parametres import (
    ASSIETTES_FRAIS,
    BASES_OPERATION,
    ESTIMATIONS,
    MODES_FRAIS,
    Parametres,
    ParametresConflit,
    ParametresError,
    clean_for_json,
    postes_disponibles,
    sync_with_catalogue,
)
from digiprint.stockage import FichiersStore
from digiprint.utils import clean_text, fmt_money, fmt_number, matches, slugify_code, to_float
from ui import components as ui
from ui import data

K_ORIGINE = "param_origine"
K_BASE = "param_base"
K_GEN = "param_gen"
K_BROUILLON = "param_brouillon"
K_RENDU = "param_rendu"
K_ADMIN = "param_admin_ok"
K_MESSAGE = "param_message"

ONGLETS = ["Papiers", "Matières et consommables", "Machines", "Opérations", "Emballage et transport",
           "Frais additionnels", "Réglages", "Base articles", "Sauvegardes"]


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
def render() -> None:
    ui.entete("Paramètres", "Tous les coûts utilisés par la tarification. Modifiez les tableaux, "
                            "puis enregistrez : les calculs suivants en tiennent compte.")
    if data.admin_requis() and not st.session_state.get(K_ADMIN):
        _connexion()
        return

    catalogue = data.get_catalogue()
    params = data.get_parametres()
    origine_version, base, gen = _etat(params)

    message = st.session_state.pop(K_MESSAGE, None)
    if message:
        st.success(message, icon=":material/check_circle:")
    if params.data.get("_alerte"):
        st.warning(params.data["_alerte"])

    barre = st.container()
    brouillon = copy.deepcopy(base)
    tabs = st.tabs(ONGLETS, key="param_onglets")
    with tabs[0]:
        _onglet_papiers(brouillon, base, catalogue, gen)
    with tabs[1]:
        _onglet_matieres(brouillon, base, catalogue, gen)
    with tabs[2]:
        _onglet_machines(brouillon, base, catalogue, gen)
    with tabs[3]:
        _onglet_operations(brouillon, base, catalogue, gen)
    with tabs[4]:
        _onglet_logistique(brouillon, base, gen)
    with tabs[5]:
        _onglet_frais(brouillon, base, gen)
    with tabs[6]:
        _onglet_reglages(brouillon, base, gen)
    with tabs[7]:
        _onglet_base(catalogue, params)
    with tabs[8]:
        _onglet_sauvegardes(catalogue, params)

    st.session_state[K_BROUILLON] = brouillon
    st.session_state[K_RENDU] = gen
    with barre:
        _barre_enregistrement(brouillon, params, origine_version)


def _connexion() -> None:
    ui.note("Cette page est protégée. Saisissez le mot de passe administrateur.")
    with st.form("param_connexion", border=False):
        mdp = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Accéder aux paramètres", type="primary"):
            if data.admin_verifier(mdp):
                st.session_state[K_ADMIN] = True
                st.rerun()
            st.error("Mot de passe incorrect.")


# --------------------------------------------------------------------------- #
# État d'édition
# --------------------------------------------------------------------------- #
def _etat(params: Parametres) -> tuple[str, dict, int]:
    """Version d'origine, données d'entrée des tableaux et génération des clés."""
    ss = st.session_state
    if K_ORIGINE not in ss:
        _repartir(params)
    origine_version, origine = ss[K_ORIGINE]
    gen = ss[K_GEN]
    # Retour sur la page après l'avoir quittée : les tableaux ont perdu leur état,
    # on repart du dernier brouillon pour ne perdre aucune modification.
    if ss.get(K_RENDU) == gen and f"pe{gen}_papiers" not in ss and K_BROUILLON in ss:
        ss[K_BASE] = copy.deepcopy(ss[K_BROUILLON])
        ss[K_GEN] = gen = gen + 1
    # Paramètres enregistrés ailleurs et aucune modification locale : on suit la nouvelle version.
    if params.version != origine_version and not _modifie(ss.get(K_BROUILLON, ss[K_BASE]), origine):
        _repartir(params)
        origine_version, gen = ss[K_ORIGINE][0], ss[K_GEN]
    return origine_version, ss[K_BASE], gen


def _repartir(params: Parametres) -> None:
    ss = st.session_state
    donnees = copy.deepcopy({k: v for k, v in params.data.items() if not k.startswith("_")})
    ss[K_ORIGINE] = (params.version, donnees)
    ss[K_BASE] = copy.deepcopy(donnees)
    ss[K_BROUILLON] = copy.deepcopy(donnees)
    ss[K_GEN] = ss.get(K_GEN, 0) + 1


def _normal(value: Any) -> Any:
    """Forme comparable : 20000.0 et 20000 sont égaux, None et NaN aussi."""
    if isinstance(value, dict):
        return {k: _normal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normal(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _canon(d: dict) -> str:
    d = {k: v for k, v in d.items() if k != "mis_a_jour_le" and not k.startswith("_")}
    return json.dumps(_normal(clean_for_json(d)), sort_keys=True, ensure_ascii=False, default=str)


def _modifie(a: dict, b: dict) -> bool:
    return _canon(a) != _canon(b)


def _barre_enregistrement(brouillon: dict, params: Parametres, origine_version: str) -> None:
    origine = st.session_state[K_ORIGINE][1]
    if not _modifie(brouillon, origine):
        a_valider = Parametres(brouillon).prix_a_valider()
        date = params.mis_a_jour_le.replace("T", " à ")[:19] if params.mis_a_jour_le else "–"
        ui.note(f"Dernier enregistrement le <strong>{ui.e(date)}</strong> (GMT). "
                + (f"<strong>{a_valider}</strong> prix encore indicatifs : cochez « Validé » une fois "
                   "chaque prix vérifié." if a_valider else "Tous les prix sont validés."))
        return
    st.html('<div class="dp-brouillon">Modifications non enregistrées : elles ne s\'appliquent '
            'aux calculs qu\'après enregistrement.</div>')
    col1, col2, _ = st.columns([2, 2, 4])
    with col1:
        enregistrer = st.button("Enregistrer les paramètres", type="primary", icon=":material/save:",
                                width="stretch", key="param_enregistrer")
    with col2:
        if st.button("Annuler les modifications", icon=":material/undo:", width="stretch", key="param_annuler"):
            ss = st.session_state
            ss[K_BASE] = copy.deepcopy(ss[K_ORIGINE][1])
            ss[K_BROUILLON] = copy.deepcopy(ss[K_ORIGINE][1])
            ss[K_GEN] += 1
            st.rerun()
    if enregistrer:
        _enregistrer(brouillon, origine_version, "Modification des paramètres")


def _enregistrer(donnees: dict, origine_version: str | None, motif: str) -> None:
    try:
        nouveau = data.parametres_store().save(donnees, motif=motif, version_attendue=origine_version)
    except ParametresError as exc:
        st.error("Enregistrement refusé :\n\n" + "\n".join(f"- {err}" for err in exc.erreurs))
        return
    except ParametresConflit as exc:
        st.error(str(exc))
        if st.button("Recharger la dernière version (mes modifications seront perdues)", key="param_conflit"):
            data.invalider_parametres()
            st.session_state.pop(K_ORIGINE, None)
            st.rerun()
        return
    data.invalider_parametres()
    _repartir(nouveau)
    st.session_state[K_MESSAGE] = "Paramètres enregistrés. Les prochains calculs les utilisent."
    st.rerun()


# --------------------------------------------------------------------------- #
# Outils de tableaux
# --------------------------------------------------------------------------- #
def _vide(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA


def _num(value: Any) -> float | None:
    return None if _vide(value) else to_float(value, None)


def _bool(value: Any) -> bool:
    return False if _vide(value) else bool(value)


def _txt(value: Any) -> str:
    return "" if _vide(value) else clean_text(value)


def _editor(df: pd.DataFrame, key: str, colonnes: dict, dynamic: bool = False,
            disabled: list[str] | None = None) -> pd.DataFrame:
    return st.data_editor(df, key=key, hide_index=True, column_config=colonnes, width="stretch",
                          num_rows="dynamic" if dynamic else "fixed", disabled=disabled or False)


def _code(r: dict, pris: set[str]) -> str:
    code = _txt(r.get("code")).upper().replace(" ", "_")
    if not code:
        base = slugify_code(_txt(r.get("libelle")) or "NOUVEAU")
        code, i = base, 2
        while code in pris:
            code, i = f"{base}_{i}", i + 1
    pris.add(code)
    return code


def _par_code(rows: list[dict]) -> dict[str, dict]:
    return {r.get("code"): r for r in rows}


def _maj(brouillon: dict, table: str, code: str) -> dict:
    row = _par_code(brouillon[table]).get(code)
    if row is None:
        row = {"code": code}
        brouillon[table].append(row)
    return row


# --------------------------------------------------------------------------- #
# Papiers
# --------------------------------------------------------------------------- #
def _papiers(catalogue: Catalogue) -> list[str]:
    return [code for code, intr in catalogue.intrants.items() if intr.is_paper_sheet]


def _achat(catalogue: Catalogue, code: str) -> str:
    intr = catalogue.intrant(code)
    return f"{intr.uom_achat} de {intr.conditionnement}" if intr.conditionnement else intr.uom_achat


def _onglet_papiers(brouillon: dict, base: dict, catalogue: Catalogue, gen: int) -> None:
    codes = _papiers(catalogue)
    rows = _par_code(base["intrants"])
    ui.note("Prix d'achat du paquet tel que facturé par le fournisseur. Le prix d'une feuille de tirage en est "
            "déduit selon le format (tableau plus bas) ; un prix fixé pour un format le remplace.")
    df = pd.DataFrame([{
        "code": c, "papier": catalogue.intrant(c).libelle, "achat": _achat(catalogue, c),
        "prix_achat": _num(rows.get(c, {}).get("prix_achat")), "valide": _bool(rows.get(c, {}).get("valide")),
    } for c in codes], columns=["code", "papier", "achat", "prix_achat", "valide"])
    out = _editor(df, f"pe{gen}_papiers", {
        "code": st.column_config.TextColumn("Code", width="small"),
        "papier": st.column_config.TextColumn("Papier", width="large"),
        "achat": st.column_config.TextColumn("Achat"),
        "prix_achat": st.column_config.NumberColumn("Prix d'achat (FCFA)", min_value=0, step=100, format="localized"),
        "valide": st.column_config.CheckboxColumn("Validé", help="Cochez une fois le prix confirmé."),
    }, disabled=["code", "papier", "achat"])
    for rec in out.to_dict("records"):
        row = _maj(brouillon, "intrants", rec["code"])
        row.setdefault("poste", POSTE_PAPIER)
        row["prix_achat"] = _num(rec["prix_achat"])
        row["valide"] = _bool(rec["valide"])

    formats = list(brouillon.get("formats", []))
    fmt_codes = [f["code"] for f in formats]

    ui.section("Prix fixés pour un format", "facultatif")
    ui.note("Pour un papier acheté directement au format de tirage (SRA3 prédécoupé, par exemple) : "
            "le prix saisi par feuille remplace le prix déduit du paquet.")
    df = pd.DataFrame([{"intrant": r.get("intrant"), "format": r.get("format"),
                        "prix_feuille": _num(r.get("prix_feuille")), "valide": _bool(r.get("valide"))}
                       for r in base.get("prix_formats", [])],
                      columns=["intrant", "format", "prix_feuille", "valide"])
    out = _editor(df, f"pe{gen}_prix_formats", {
        "intrant": st.column_config.SelectboxColumn(
            "Papier", options=codes, required=True, width="large",
            format_func=lambda c: f"{c} {catalogue.intrant(c).libelle}"),
        "format": st.column_config.SelectboxColumn("Format", options=fmt_codes, required=True),
        "prix_feuille": st.column_config.NumberColumn("Prix par feuille (FCFA)", min_value=0, step=1,
                                                      format="localized", required=True),
        "valide": st.column_config.CheckboxColumn("Validé", default=False),
    }, dynamic=True)
    brouillon["prix_formats"] = [
        {"intrant": _txt(r["intrant"]), "format": _txt(r["format"]),
         "prix_feuille": _num(r["prix_feuille"]), "valide": _bool(r["valide"])}
        for r in out.to_dict("records") if _txt(r["intrant"]) or _txt(r["format"]) or _num(r["prix_feuille"])
    ]

    ui.section("Prix d'une feuille selon le format", "modifications en cours comprises")
    p = Parametres(brouillon)
    lignes = []
    for c in codes:
        intr = catalogue.intrant(c)
        prix = _num(p.intrant(c).get("prix_achat"))
        ligne = {"Papier": f"{c} {intr.libelle}"}
        for f in formats:
            fixe = p.prix_format(c, f["code"])
            per = to_float(f.get("feuilles_par_a0"), 0) or 0
            if fixe is not None:
                ligne[f["code"]] = f"{fmt_money(to_float(fixe['prix_feuille'], 0))} (fixé)"
            elif prix is not None and per > 0:
                ligne[f["code"]] = fmt_money(prix / intr.facteur_conversion / per)
            else:
                ligne[f["code"]] = "non renseigné"
        lignes.append(ligne)
    st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")

    tarifs = {(t.get("operation"), t.get("intrant")): t.get("cout_unitaire") for t in base.get("tarifs_papier", [])}
    for op in brouillon.get("operations", []):
        if not op.get("selon_papier"):
            continue
        code_op = op.get("code")
        unite = op.get("unite") or "opération"
        ui.section(f"{op.get('libelle', code_op)} selon le papier", f"coût par {unite}")
        ui.note(f"Laissez vide pour appliquer le tarif général de l'opération "
                f"({ui.e(fmt_money(to_float(op.get('cout_unitaire'), 0)))}). Le papier retenu est le plus épais "
                "de l'article (la couverture d'une brochure, par exemple).")
        df = pd.DataFrame([{"code": c, "papier": catalogue.intrant(c).libelle,
                            "cout": _num(tarifs.get((code_op, c)))} for c in codes],
                          columns=["code", "papier", "cout"])
        out = _editor(df, f"pe{gen}_tarifs_{slugify_code(str(code_op))}", {
            "code": st.column_config.TextColumn("Code", width="small"),
            "papier": st.column_config.TextColumn("Papier", width="large"),
            "cout": st.column_config.NumberColumn(f"Coût par {unite} (FCFA)", min_value=0, step=0.5, format="%g"),
        }, disabled=["code", "papier"])
        autres = [t for t in brouillon.get("tarifs_papier", []) if t.get("operation") != code_op]
        brouillon["tarifs_papier"] = autres + [
            {"operation": code_op, "intrant": r["code"], "cout_unitaire": _num(r["cout"])}
            for r in out.to_dict("records") if _num(r["cout"]) is not None
        ]


# --------------------------------------------------------------------------- #
# Matières, machines
# --------------------------------------------------------------------------- #
def _onglet_matieres(brouillon: dict, base: dict, catalogue: Catalogue, gen: int) -> None:
    papiers = set(_papiers(catalogue))
    codes = [c for c in catalogue.intrants if c not in papiers]
    rows = _par_code(base["intrants"])
    ui.note("Prix d'achat par unité d'achat (rouleau, bidon, carton…). Le coût consommé est ramené à l'unité "
            "de la nomenclature par le facteur de conversion de la base articles.")
    postes = [POSTE_MATIERES, POSTE_CONSOMMABLES, POSTE_PAPIER]
    df = pd.DataFrame([{
        "code": c, "intrant": catalogue.intrant(c).libelle, "famille": catalogue.intrant(c).categorie_stock,
        "achat": _achat(catalogue, c), "prix_achat": _num(rows.get(c, {}).get("prix_achat")),
        "poste": rows.get(c, {}).get("poste") or POSTE_MATIERES, "valide": _bool(rows.get(c, {}).get("valide")),
    } for c in codes], columns=["code", "intrant", "famille", "achat", "prix_achat", "poste", "valide"])
    out = _editor(df, f"pe{gen}_matieres", {
        "code": st.column_config.TextColumn("Code", width="small"),
        "intrant": st.column_config.TextColumn("Intrant", width="large"),
        "famille": st.column_config.TextColumn("Famille"),
        "achat": st.column_config.TextColumn("Achat"),
        "prix_achat": st.column_config.NumberColumn("Prix d'achat (FCFA)", min_value=0, step=100, format="localized"),
        "poste": st.column_config.SelectboxColumn("Poste de coût", options=postes, required=True),
        "valide": st.column_config.CheckboxColumn("Validé"),
    }, disabled=["code", "intrant", "famille", "achat"])
    for rec in out.to_dict("records"):
        row = _maj(brouillon, "intrants", rec["code"])
        row["prix_achat"] = _num(rec["prix_achat"])
        row["poste"] = _txt(rec["poste"]) or POSTE_MATIERES
        row["valide"] = _bool(rec["valide"])

    with st.expander("Prix par unité consommée"):
        p = Parametres(brouillon)
        lignes = []
        for c in codes:
            intr = catalogue.intrant(c)
            prix = _num(p.intrant(c).get("prix_achat"))
            lignes.append({"Intrant": f"{c} {intr.libelle}",
                           "Prix": fmt_money(prix / intr.facteur_conversion) if prix is not None else "non renseigné",
                           "Unité consommée": intr.uom_conso})
        st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")


def _onglet_machines(brouillon: dict, base: dict, catalogue: Catalogue, gen: int) -> None:
    rows = _par_code(base["machines"])
    portees = Parametres(base).machines_valorisees_par_operation()
    ui.note("Taux horaire complet (amortissement, énergie, main-d'œuvre, maintenance). Le temps de passage "
            "vient de la gamme de chaque article.")
    if portees:
        ui.note("Valorisées par une opération, donc temps de gamme non compté : "
                + ", ".join(f"<strong>{ui.e(catalogue.machine(m).libelle)}</strong> (opération {ui.e(o)})"
                            for m, o in portees.items()) + ".")
    df = pd.DataFrame([{
        "code": c, "machine": m.libelle, "atelier": m.atelier, "cadence": m.cadence,
        "taux_horaire": _num(rows.get(c, {}).get("taux_horaire")),
        "poste": rows.get(c, {}).get("poste") or POSTES_TECHNIQUES[0], "valide": _bool(rows.get(c, {}).get("valide")),
    } for c, m in catalogue.machines.items()],
        columns=["code", "machine", "atelier", "cadence", "taux_horaire", "poste", "valide"])
    out = _editor(df, f"pe{gen}_machines", {
        "code": st.column_config.TextColumn("Code", width="small"),
        "machine": st.column_config.TextColumn("Machine", width="large"),
        "atelier": st.column_config.TextColumn("Atelier"),
        "cadence": st.column_config.TextColumn("Cadence de référence"),
        "taux_horaire": st.column_config.NumberColumn("Taux horaire (FCFA)", min_value=0, step=500, format="localized"),
        "poste": st.column_config.SelectboxColumn("Poste de coût", options=postes_disponibles(base), required=True),
        "valide": st.column_config.CheckboxColumn("Validé"),
    }, disabled=["code", "machine", "atelier", "cadence"])
    for rec in out.to_dict("records"):
        row = _maj(brouillon, "machines", rec["code"])
        row["taux_horaire"] = _num(rec["taux_horaire"])
        row["poste"] = _txt(rec["poste"]) or POSTES_TECHNIQUES[0]
        row["valide"] = _bool(rec["valide"])


# --------------------------------------------------------------------------- #
# Opérations
# --------------------------------------------------------------------------- #
def _onglet_operations(brouillon: dict, base: dict, catalogue: Catalogue, gen: int) -> None:
    ui.note("Opérations comptées à l'unité : nombre (estimé ou saisi dans la tarification) × coût unitaire. "
            "Ajoutez une ligne pour une nouvelle opération (pose d'œillets, coins ronds, perforation…). "
            "Rattacher une machine remplace son temps de gamme par l'opération, sans double comptage.")
    machines = [""] + list(catalogue.machines)
    cols = ["code", "libelle", "poste", "unite", "base", "cout_unitaire", "selon_papier", "machine",
            "estimation", "actif", "valide"]
    df = pd.DataFrame([{
        "code": op.get("code"), "libelle": op.get("libelle"), "poste": op.get("poste"), "unite": op.get("unite"),
        "base": op.get("base", "commande"), "cout_unitaire": _num(op.get("cout_unitaire")),
        "selon_papier": _bool(op.get("selon_papier")), "machine": op.get("machine") or "",
        "estimation": op.get("estimation") or "aucune", "actif": _bool(op.get("actif")),
        "valide": _bool(op.get("valide")),
    } for op in base.get("operations", [])], columns=cols)
    out = _editor(df, f"pe{gen}_operations", {
        "code": st.column_config.TextColumn("Code", width="small", help="Laissé vide : déduit du libellé."),
        "libelle": st.column_config.TextColumn("Libellé", width="medium", required=True),
        "poste": st.column_config.SelectboxColumn("Poste", options=postes_disponibles(base), required=True,
                                                  default=POSTES_TECHNIQUES[1]),
        "unite": st.column_config.TextColumn("Unité", default="opération", help="coupe, rainage, œillet…"),
        "base": st.column_config.SelectboxColumn("Nombre saisi", options=list(BASES_OPERATION),
                                                 format_func=BASES_OPERATION.get, required=True, default="commande"),
        "cout_unitaire": st.column_config.NumberColumn("Coût unitaire (FCFA)", min_value=0, step=1, format="%g",
                                                       required=True, default=0),
        "selon_papier": st.column_config.CheckboxColumn("Selon le papier", default=False,
                                                        help="Tarifs par papier dans l'onglet Papiers."),
        "machine": st.column_config.SelectboxColumn(
            "Machine rattachée", options=machines,
            format_func=lambda c: f"{c} {catalogue.machine(c).libelle}" if c else "Aucune"),
        "estimation": st.column_config.SelectboxColumn("Estimation", options=list(ESTIMATIONS),
                                                       format_func=ESTIMATIONS.get, default="aucune"),
        "actif": st.column_config.CheckboxColumn("Active", default=True),
        "valide": st.column_config.CheckboxColumn("Validé", default=False),
    }, dynamic=True)
    pris: set[str] = set()
    ops = []
    for r in out.to_dict("records"):
        if not _txt(r["libelle"]) and not _txt(r["code"]):
            continue
        code = _code(r, pris)
        cout = _num(r["cout_unitaire"])
        ops.append({
            "code": code, "libelle": _txt(r["libelle"]) or code, "poste": _txt(r["poste"]) or POSTES_TECHNIQUES[1],
            "unite": _txt(r["unite"]) or "opération", "base": _txt(r["base"]) or "commande",
            "cout_unitaire": cout if cout is not None else 0, "selon_papier": _bool(r["selon_papier"]),
            "machine": _txt(r["machine"]), "estimation": _txt(r["estimation"]) or "aucune",
            "actif": _bool(r["actif"]), "valide": _bool(r["valide"]),
        })
    brouillon["operations"] = ops
    ui.note("Les tarifs selon le papier se renseignent dans l'onglet <strong>Papiers</strong> "
            "dès que « Selon le papier » est coché.")


# --------------------------------------------------------------------------- #
# Emballage, transport, frais
# --------------------------------------------------------------------------- #
def _onglet_logistique(brouillon: dict, base: dict, gen: int) -> None:
    ui.section("Emballages", "coût unitaire par carton ou colis", premiere=True)
    df = pd.DataFrame([{"code": r.get("code"), "libelle": r.get("libelle"),
                        "cout_unitaire": _num(r.get("cout_unitaire")), "valide": _bool(r.get("valide"))}
                       for r in base.get("emballages", [])], columns=["code", "libelle", "cout_unitaire", "valide"])
    out = _editor(df, f"pe{gen}_emballages", {
        "code": st.column_config.TextColumn("Code", width="small", help="Laissé vide : déduit du libellé."),
        "libelle": st.column_config.TextColumn("Libellé", width="large", required=True),
        "cout_unitaire": st.column_config.NumberColumn("Coût unitaire (FCFA)", min_value=0, step=50,
                                                       format="localized", required=True, default=0),
        "valide": st.column_config.CheckboxColumn("Validé", default=False),
    }, dynamic=True)
    pris: set[str] = set()
    brouillon["emballages"] = [
        {"code": _code(r, pris), "libelle": _txt(r["libelle"]) or _txt(r["code"]),
         "cout_unitaire": _num(r["cout_unitaire"]) or 0, "valide": _bool(r["valide"])}
        for r in out.to_dict("records") if _txt(r["libelle"]) or _txt(r["code"])
    ]

    ui.section("Transports", "distance facturée = distance aller × 2")
    df = pd.DataFrame([{"code": r.get("code"), "libelle": r.get("libelle"), "cout_km": _num(r.get("cout_km")),
                        "frais_fixes": _num(r.get("frais_fixes")), "valide": _bool(r.get("valide"))}
                       for r in base.get("transports", [])],
                      columns=["code", "libelle", "cout_km", "frais_fixes", "valide"])
    out = _editor(df, f"pe{gen}_transports", {
        "code": st.column_config.TextColumn("Code", width="small", help="Laissé vide : déduit du libellé."),
        "libelle": st.column_config.TextColumn("Libellé", width="large", required=True),
        "cout_km": st.column_config.NumberColumn("Coût au km (FCFA)", min_value=0, step=10, format="localized",
                                                 required=True, default=0),
        "frais_fixes": st.column_config.NumberColumn("Prise en charge par livraison (FCFA)", min_value=0,
                                                     step=100, format="localized", default=0),
        "valide": st.column_config.CheckboxColumn("Validé", default=False),
    }, dynamic=True)
    pris = set()
    brouillon["transports"] = [
        {"code": _code(r, pris), "libelle": _txt(r["libelle"]) or _txt(r["code"]),
         "cout_km": _num(r["cout_km"]) or 0, "frais_fixes": _num(r["frais_fixes"]) or 0,
         "valide": _bool(r["valide"])}
        for r in out.to_dict("records") if _txt(r["libelle"]) or _txt(r["code"])
    ]

    ui.section("Valeurs proposées dans la tarification")
    g = base.get("general", {})
    emb = {r["code"]: r["libelle"] for r in brouillon["emballages"]}
    tr = {r["code"]: r["libelle"] for r in brouillon["transports"]}
    col1, col2, col3 = st.columns(3, vertical_alignment="bottom")
    with col1:
        opts = [""] + list(emb)
        cur = g.get("emballage_defaut") if g.get("emballage_defaut") in emb else ""
        brouillon["general"]["emballage_defaut"] = st.selectbox(
            "Emballage proposé", opts, index=opts.index(cur), key=f"pe{gen}_emb_defaut",
            format_func=lambda c: emb.get(c, "Sans emballage")) or None
    with col2:
        opts = list(tr) or [""]
        cur = g.get("transport_defaut") if g.get("transport_defaut") in tr else opts[0]
        brouillon["general"]["transport_defaut"] = st.selectbox(
            "Transport proposé", opts, index=opts.index(cur), key=f"pe{gen}_tr_defaut",
            format_func=lambda c: tr.get(c, "Aucun")) or None
    with col3:
        brouillon["general"]["livraison_defaut"] = st.toggle(
            "Livraison activée d'office", value=bool(g.get("livraison_defaut", True)), key=f"pe{gen}_liv_defaut")


def _onglet_frais(brouillon: dict, base: dict, gen: int) -> None:
    ui.note("Frais ajoutés à chaque calcul lorsqu'ils sont actifs : montant fixe par commande, montant par "
            "exemplaire, ou pourcentage du coût de production (ou du coût total avant frais). Les frais propres "
            "à une commande se saisissent dans la tarification.")
    cols = ["code", "libelle", "mode", "valeur", "assiette", "actif", "valide"]
    df = pd.DataFrame([{"code": r.get("code"), "libelle": r.get("libelle"), "mode": r.get("mode", "fixe"),
                        "valeur": _num(r.get("valeur")), "assiette": r.get("assiette", "production"),
                        "actif": _bool(r.get("actif")), "valide": _bool(r.get("valide"))}
                       for r in base.get("frais", [])], columns=cols)
    out = _editor(df, f"pe{gen}_frais", {
        "code": st.column_config.TextColumn("Code", width="small", help="Laissé vide : déduit du libellé."),
        "libelle": st.column_config.TextColumn("Libellé", width="large", required=True),
        "mode": st.column_config.SelectboxColumn("Calcul", options=list(MODES_FRAIS), format_func=MODES_FRAIS.get,
                                                 required=True, default="fixe"),
        "valeur": st.column_config.NumberColumn("Valeur (FCFA ou %)", min_value=0, step=1, format="%g",
                                                required=True, default=0),
        "assiette": st.column_config.SelectboxColumn("Assiette du %", options=list(ASSIETTES_FRAIS),
                                                     format_func=ASSIETTES_FRAIS.get, default="production"),
        "actif": st.column_config.CheckboxColumn("Actif", default=True),
        "valide": st.column_config.CheckboxColumn("Validé", default=False),
    }, dynamic=True)
    pris: set[str] = set()
    brouillon["frais"] = [
        {"code": _code(r, pris), "libelle": _txt(r["libelle"]) or _txt(r["code"]), "mode": _txt(r["mode"]) or "fixe",
         "valeur": _num(r["valeur"]) or 0, "assiette": _txt(r["assiette"]) or "production",
         "actif": _bool(r["actif"]), "valide": _bool(r["valide"])}
        for r in out.to_dict("records") if _txt(r["libelle"]) or _txt(r["code"])
    ]


# --------------------------------------------------------------------------- #
# Réglages
# --------------------------------------------------------------------------- #
def _onglet_reglages(brouillon: dict, base: dict, gen: int) -> None:
    g = base.get("general", {})
    ui.section("Feuilles et estimations", premiere=True)
    col1, col2, col3 = st.columns(3, vertical_alignment="bottom")
    with col1:
        brouillon["general"]["arrondir_feuilles"] = st.toggle(
            "Arrondir les feuilles à l'unité supérieure", value=bool(g.get("arrondir_feuilles", True)),
            key=f"pe{gen}_arrondi")
    with col2:
        brouillon["general"]["hauteur_levee"] = st.number_input(
            "Hauteur de levée au massicot (feuilles)", min_value=1, step=10,
            value=int(to_float(g.get("hauteur_levee"), 250) or 250), key=f"pe{gen}_levee",
            help="Feuilles coupées en une fois : sert à estimer le nombre de coupes.")
    with col3:
        brouillon["general"]["grammage_min_rainage"] = st.number_input(
            "Rainage à partir de (g/m²)", min_value=0, step=10,
            value=int(to_float(g.get("grammage_min_rainage"), 170) or 0), key=f"pe{gen}_rainage",
            help="En dessous de ce grammage, un pli se fait sans rainage.")

    ui.section("Formats de tirage", "feuilles obtenues dans une feuille A0")
    df = pd.DataFrame([{"code": f.get("code"), "libelle": f.get("libelle"),
                        "feuilles_par_a0": _num(f.get("feuilles_par_a0"))} for f in base.get("formats", [])],
                      columns=["code", "libelle", "feuilles_par_a0"])
    out = _editor(df, f"pe{gen}_formats", {
        "code": st.column_config.TextColumn("Code", width="small", required=True),
        "libelle": st.column_config.TextColumn("Libellé", width="large"),
        "feuilles_par_a0": st.column_config.NumberColumn("Feuilles par A0", min_value=0.01, step=0.5,
                                                         format="%g", required=True),
    }, dynamic=True)
    brouillon["formats"] = [
        {"code": _txt(r["code"]).upper(), "libelle": _txt(r["libelle"]) or _txt(r["code"]).upper(),
         "feuilles_par_a0": _num(r["feuilles_par_a0"])}
        for r in out.to_dict("records") if _txt(r["code"])
    ]

    ui.section("Procédés", "format de tirage et gâche de la base")
    ui.note("La gâche est déjà comprise dans les quantités de la base articles : elle sert ici à retrouver le "
            "nombre de poses par feuille (estimation des coupes), pas à majorer le papier.")
    codes = [f["code"] for f in brouillon["formats"]] or ["SRA3"]
    df = pd.DataFrame([{"procede": p.get("procede"), "format": p.get("format"), "gache_pct": _num(p.get("gache_pct"))}
                       for p in base.get("procedes", [])], columns=["procede", "format", "gache_pct"])
    out = _editor(df, f"pe{gen}_procedes", {
        "procede": st.column_config.TextColumn("Procédé", width="large"),
        "format": st.column_config.SelectboxColumn("Format de tirage", options=codes, required=True),
        "gache_pct": st.column_config.NumberColumn("Gâche (%)", min_value=0, max_value=99, step=0.5, format="%g"),
    }, disabled=["procede"])
    brouillon["procedes"] = [
        {"procede": _txt(r["procede"]), "format": _txt(r["format"]),
         "gache_pct": _num(r["gache_pct"]) if _num(r["gache_pct"]) is not None else 5}
        for r in out.to_dict("records")
    ]


# --------------------------------------------------------------------------- #
# Base articles
# --------------------------------------------------------------------------- #
def _onglet_base(catalogue: Catalogue, params: Parametres) -> None:
    info = data.base_info()
    env = data.environnement()
    ui.faits([
        ("Articles", fmt_number(len(catalogue.articles))),
        ("Désignations", fmt_number(len(catalogue.designations()))),
        ("Intrants", fmt_number(len(catalogue.intrants))),
        ("Machines", fmt_number(len(catalogue.machines))),
        ("Classeur", info.nom),
        ("Provenance", "Importé dans l'application" if info.origine == "import" else "Livré avec l'application"),
        ("Stockage des données", env["stockage"]),
        ("Emplacement", env["cible"]),
    ])
    if info.origine == "import" and info.date:
        ui.note(f"Version importée le <strong>{info.date:%d/%m/%Y à %H:%M}</strong> (GMT).")
    if catalogue.anomalies:
        with st.expander(f"Contrôle du classeur : {len(catalogue.anomalies)} point(s) à vérifier"):
            st.markdown("\n".join(f"- {a}" for a in catalogue.anomalies))
    else:
        ui.note("Contrôle du classeur : aucune anomalie (identifiants uniques, désignations et natures "
                "renseignées, codes IMPUT et MACH présents dans les référentiels).")

    ui.section("Consulter les articles")
    recherche = st.text_input("Filtrer", placeholder="Désignation, nature, catégorie, identifiant",
                              key="param_base_filtre")
    df = catalogue.dataframe()
    if recherche:
        df = df[df.apply(lambda r: matches(recherche, r["ID"], r["Désignation"], r["Nature"], r["Catégorie"]), axis=1)]
    st.dataframe(df, hide_index=True, width="stretch", height=320)

    ui.section("Remplacer la base articles")
    ui.note("Importez une nouvelle version du classeur (même structure : feuille BASE_ARTICLE, colonnes IMPUTn "
            "et MACHn, référentiels). Elle est contrôlée avant remplacement ; les nouveaux intrants et machines "
            "apparaissent dans les paramètres sans prix. Les versions précédentes restent disponibles.")
    fichier = st.file_uploader("Classeur Excel", type=["xlsx", "xlsm"], key="param_base_upload")
    if fichier is not None:
        contenu = fichier.getvalue()
        try:
            nouveau = load_catalogue_bytes(contenu, source=fichier.name)
        except CatalogueError as exc:
            st.error(f"Classeur refusé : {exc}")
        else:
            anciens, nouveaux = set(catalogue.articles), set(nouveau.articles)
            ui.note(f"<strong>{len(nouveaux)}</strong> articles ({len(nouveaux - anciens)} nouveaux, "
                    f"{len(anciens - nouveaux)} retirés), {len(nouveau.designations())} désignations, "
                    f"{len(nouveau.anomalies)} point(s) de contrôle.")
            if st.button("Remplacer la base articles", type="primary", key="param_base_remplacer"):
                FichiersStore(data.get_db()).enregistrer(contenu, fichier.name)
                _synchroniser(params, nouveau)
                data.invalider_base()
                st.session_state.pop(K_ORIGINE, None)
                st.session_state[K_MESSAGE] = f"Base articles remplacée par « {fichier.name} »."
                st.rerun()

    store = FichiersStore(data.get_db())
    versions = store.versions()
    if versions:
        ui.section("Versions importées")
        for v in versions:
            col1, col2 = st.columns([5, 2], vertical_alignment="center")
            with col1:
                actuelle = " (en service)" if info.fichier_id == v.id else ""
                ui.note(f"<strong>{ui.e(v.nom)}</strong>{actuelle}, importée le {v.cree_le:%d/%m/%Y à %H:%M}, "
                        f"{fmt_number(v.taille / 1024)} Ko")
            with col2:
                if info.fichier_id != v.id and st.button("Remettre en service", key=f"param_base_v{v.id}"):
                    ancien = store.obtenir(v.id)
                    store.enregistrer(ancien.contenu, ancien.nom)
                    data.invalider_base()
                    st.session_state.pop(K_ORIGINE, None)
                    st.rerun()
        if st.button("Revenir au classeur livré avec l'application", key="param_base_origine"):
            store.supprimer_tout()
            data.invalider_base()
            st.session_state.pop(K_ORIGINE, None)
            st.rerun()


def _synchroniser(params: Parametres, catalogue: Catalogue) -> None:
    donnees = copy.deepcopy({k: v for k, v in params.data.items() if not k.startswith("_")})
    if sync_with_catalogue(donnees, catalogue, use_default_prices=False):
        try:
            data.parametres_store().save(donnees, motif="Synchronisation avec la nouvelle base articles")
        except ParametresError:
            pass  # la synchronisation se refera au prochain chargement


# --------------------------------------------------------------------------- #
# Sauvegardes
# --------------------------------------------------------------------------- #
def _onglet_sauvegardes(catalogue: Catalogue, params: Parametres) -> None:
    store = data.parametres_store()
    ui.section("Exporter et importer", premiere=True)
    ui.note("Le fichier JSON contient tous les paramètres enregistrés : copie de sécurité, ou transfert "
            "entre l'application sur poste et l'application hébergée.")
    brut = {k: v for k, v in params.data.items() if not k.startswith("_")}
    st.download_button("Télécharger les paramètres (JSON)", icon=":material/download:",
                       data=json.dumps(brut, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name=f"parametres_digiprint_{params.version}.json", mime="application/json",
                       on_click="ignore", key="param_export")
    fichier = st.file_uploader("Importer un fichier de paramètres", type=["json"], key="param_import")
    if fichier is not None:
        try:
            donnees = json.loads(fichier.getvalue().decode("utf-8"))
            if not isinstance(donnees, dict):
                raise ValueError("document inattendu")
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(f"Fichier illisible : {exc}")
        else:
            if st.button("Remplacer les paramètres par ce fichier", type="primary", key="param_import_ok"):
                sync_with_catalogue(donnees, catalogue, use_default_prices=False)
                try:
                    nouveau = store.save(donnees, motif=f"Import du fichier {fichier.name}")
                except ParametresError as exc:
                    st.error("Import refusé :\n\n" + "\n".join(f"- {e}" for e in exc.erreurs))
                else:
                    data.invalider_parametres()
                    _repartir(nouveau)
                    st.session_state[K_MESSAGE] = f"Paramètres importés depuis « {fichier.name} »."
                    st.rerun()

    ui.section("Versions précédentes", f"les {config.MAX_BACKUPS} dernières")
    sauvegardes = store.sauvegardes()
    if not sauvegardes:
        ui.note("Aucune version précédente : chaque enregistrement conservera ici la version remplacée.")
    for s in sauvegardes:
        col1, col2 = st.columns([5, 2], vertical_alignment="center")
        with col1:
            ui.note(f"<strong>{s['cree_le']:%d/%m/%Y à %H:%M}</strong>, remplacée lors de : "
                    f"{ui.e(s['motif'][:1].lower() + s['motif'][1:])} (version {ui.e(s['empreinte'])})")
        with col2:
            if st.button("Restaurer", key=f"param_restaurer_{s['id']}", icon=":material/restore:"):
                try:
                    nouveau = store.restaurer(s["id"], catalogue)
                except ParametresError as exc:
                    st.error("Restauration refusée :\n\n" + "\n".join(f"- {e}" for e in exc.erreurs))
                else:
                    data.invalider_parametres()
                    _repartir(nouveau)
                    st.session_state[K_MESSAGE] = "Version restaurée ; la version remplacée est sauvegardée."
                    st.rerun()

    ui.section("Valeurs par défaut")
    ui.note("Remplace tous les paramètres par les valeurs indicatives d'origine. La version actuelle est "
            "sauvegardée et reste restaurable.")
    if st.button("Rétablir les valeurs par défaut", icon=":material/restart_alt:", key="param_reset"):
        _dialogue_reset(catalogue)


@st.dialog("Rétablir les valeurs par défaut")
def _dialogue_reset(catalogue: Catalogue) -> None:
    st.write("Tous les prix et réglages reviennent aux valeurs indicatives d'origine. "
             "La version actuelle est sauvegardée.")
    col1, col2 = st.columns(2)
    if col1.button("Rétablir", type="primary", width="stretch"):
        nouveau = data.parametres_store().reset(catalogue)
        data.invalider_parametres()
        _repartir(nouveau)
        st.session_state[K_MESSAGE] = "Valeurs par défaut rétablies."
        st.rerun()
    if col2.button("Annuler", width="stretch"):
        st.rerun()
