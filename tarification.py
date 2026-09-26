"""Page Tarification : choix de l'article, saisies, prix de revient en direct.

Les champs conservent leur valeur pendant toute la session, y compris en
passant d'une page à l'autre (``persist_state="session"``). Les nombres
estimés automatiquement (feuilles, coupes, rainages) s'affichent en indication
dans le champ vide : il suffit de saisir un nombre pour les remplacer.
"""

from __future__ import annotations

import uuid

import streamlit as st

from digiprint.catalogue import Catalogue
from digiprint.export import fiche_depuis_resultat, fiche_excel, nom_fichier_fiche
from digiprint.models import Article, PricingRequest, PricingResult, UnitSpec, unit_spec
from digiprint.moteur import (
    compute,
    estimate_operations,
    explain_sheets,
    operation_unit_cost,
    sheet_plan,
)
from digiprint.parametres import Parametres
from digiprint.utils import fmt_money, fmt_number, fmt_smart, plural, slugify_code, to_float
from ui import components as ui
from ui import data, nav

PERSIST = "session"
SANS = "__SANS__"  # option « Sans emballage »

# --------------------------------------------------------------------------- #
# Clés d'état (utilisées aussi pour recharger un calcul depuis l'historique)
# --------------------------------------------------------------------------- #
K_DESIGNATION = "tarif_designation"
K_EMB_TYPE = "tarif_emb_type"
K_EMB_NB = "tarif_emb_nb"
K_LIVRAISON = "tarif_livraison"
K_TRANSPORT = "tarif_transport"
K_DISTANCE = "tarif_distance"
K_PONCTUELS = "tarif_ponctuels"
K_REFERENCE = "tarif_reference"
K_DERNIER = "tarif_dernier_enregistrement"


def k_article(designation: str) -> str:
    return f"tarif_article_{slugify_code(designation)}"


def k_quantite(unit: UnitSpec) -> str:
    return f"tarif_qte_{unit.key}"


def k_feuilles(article_id: str, code: str) -> str:
    return f"tarif_feuilles_{article_id}_{code}"


def k_operation(article_id: str, code: str) -> str:
    return f"tarif_op_{article_id}_{code}"


def k_emb_cout(code: str) -> str:
    return f"tarif_emb_cout_{code}"


def k_ponctuel(row_id: str, champ: str) -> str:
    return f"tarif_ponctuel_{row_id}_{champ}"


def _init(key: str, value) -> None:
    """Valeur initiale posée avant la création du widget (aucun avertissement Streamlit)."""
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
def render() -> None:
    catalogue = data.get_catalogue()
    params = data.get_parametres()

    ui.entete("Tarification", "Prix de revient d'un article, sans marge, détaillé poste par poste.")
    gauche, droite = st.columns([7, 5], gap="large")

    with gauche:
        article = _choix_article(catalogue)
        if article is None:
            with droite:
                with st.container(key="epreuve"):
                    ui.epreuve_vide()
            return
        unit = unit_spec(article.unite)
        quantite = _quantite(unit)
        _fiche_article(article, catalogue, unit)

        overrides = _feuilles_saisies(article)
        plans = sheet_plan(article, catalogue, params, quantite, overrides)
        ui.section("Papier", "feuilles de tirage")
        overrides = _saisie_feuilles(article, plans, unit, quantite)
        plans = sheet_plan(article, catalogue, params, quantite, overrides)

        estimations = estimate_operations(article, catalogue, params, quantite, plans)
        ui.section("Façonnage", "découpe, rainage et autres opérations")
        operations = _saisie_operations(article, catalogue, params, estimations, unit)

        ui.section("Emballage")
        emb_code, emb_cout, emb_nb = _saisie_emballage(params)
        ui.section("Livraison")
        livraison, transport, distance = _saisie_livraison(params)
        ui.section("Frais ponctuels", "propres à cette commande")
        ponctuels = _saisie_ponctuels()

    request = PricingRequest(
        article_id=article.id, quantite=quantite, feuilles=overrides, operations=operations,
        emballage=emb_code, emballage_cout_unitaire=emb_cout, emballage_nombre=emb_nb,
        livraison=livraison, transport=transport, distance_km=distance, frais_ponctuels=ponctuels,
    )
    result = compute(article, request, catalogue, params)

    with droite:
        _epreuve(result, params)

    ui.section("Détail du calcul", "chaque montant = quantité × prix unitaire")
    ui.detail(result.lines, result.total)


# --------------------------------------------------------------------------- #
# Article et quantité
# --------------------------------------------------------------------------- #
def _choix_article(catalogue: Catalogue) -> Article | None:
    designations = catalogue.designations()
    if st.session_state.get(K_DESIGNATION) not in designations:
        st.session_state[K_DESIGNATION] = None  # base articles remplacée entre-temps
    col1, col2 = st.columns([2, 3])
    with col1:
        designation = st.selectbox(
            "Désignation", designations, index=None, key=K_DESIGNATION, persist_state=PERSIST,
            placeholder="Rechercher une désignation", filter_mode="contains",
            help="Tapez une partie du nom : la recherche ignore les majuscules. "
                 "Seules les désignations de la base articles sont proposées.",
        )
    articles = catalogue.articles_for(designation)
    ids = [a.id for a in articles]
    with col2:
        if not designation:
            st.selectbox("Nature", [], index=None, disabled=True, placeholder="Choisissez d'abord une désignation")
            return None
        key = k_article(designation)
        if st.session_state.get(key) not in ids:
            st.session_state[key] = ids[0] if len(ids) == 1 else None
        natures = {a.id: a.nature for a in articles}
        article_id = st.selectbox(
            f"Nature ({len(ids)} {plural(len(ids), 'choix', 'choix')})", ids, index=None, key=key,
            format_func=lambda i: natures.get(i, i), persist_state=PERSIST,
            placeholder="Rechercher une nature", filter_mode="contains",
            help="Format, support, impression et finition. Tapez une partie du texte pour filtrer.",
        )
    return catalogue.get(article_id)


def _quantite(unit: UnitSpec) -> float:
    key = k_quantite(unit)
    _init(key, int(unit.default_qty) if unit.integer else float(unit.default_qty))
    col1, col2 = st.columns([2, 3])
    with col1:
        if unit.integer:
            value = st.number_input(unit.input_label, min_value=0, step=int(max(1, unit.step)),
                                    key=key, persist_state=PERSIST)
        else:
            value = st.number_input(unit.input_label, min_value=0.0, step=float(unit.step),
                                    format="%.2f", key=key, persist_state=PERSIST)
    with col2:
        if unit.divisor != 1:
            lots = (value or 0) / unit.divisor
            ui.note(f"Article vendu au lot de {fmt_number(unit.divisor)} : la nomenclature de la base "
                    f"est appliquée <strong>{fmt_smart(lots)} {plural(lots, 'fois', 'fois')}</strong>.")
    return float(value or 0)


def _fiche_article(article: Article, catalogue: Catalogue, unit: UnitSpec) -> None:
    ui.faits([
        ("Article", article.id),
        ("Catégorie", article.categorie),
        ("Unité", article.unite),
        ("Procédé", article.procede),
        ("Format fini", article.format_fini),
        ("Site de production", article.site),
    ])
    with st.expander("Nomenclature et gamme de la base articles"):
        ui.nomenclature(article, catalogue, unit)


# --------------------------------------------------------------------------- #
# Production
# --------------------------------------------------------------------------- #
def _feuilles_saisies(article: Article) -> dict:
    """Saisies en cours (état de session), lues avant l'affichage des champs."""
    return {line.code: st.session_state.get(k_feuilles(article.id, line.code))
            for line in article.nomenclature}


def _saisie_feuilles(article: Article, plans, unit: UnitSpec, quantite: float) -> dict[str, float | None]:
    if not plans:
        ui.note("Pas de papier en feuilles dans la nomenclature : les supports (rouleaux, textiles, objets) "
                "sont comptés avec les matières premières.")
        return {}
    qn = quantite / unit.divisor
    overrides: dict[str, float | None] = {}
    for plan in plans:
        key = k_feuilles(article.id, plan.code)
        _init(key, None)
        col1, col2 = st.columns([2, 3])
        with col1:
            value = st.number_input(
                f"{plan.libelle}, feuilles {plan.format_code}", min_value=0, step=1, key=key,
                placeholder=f"Auto : {fmt_number(plan.feuilles_auto)}", persist_state=PERSIST,
                help="Laissez vide pour garder le calcul automatique. Un nombre saisi le remplace.",
            )
        with col2:
            prefix = "<strong>Nombre saisi.</strong> Calcul automatique : " if value is not None else ""
            ui.note(prefix + ui.e(explain_sheets(plan, unit, qn)))
        overrides[plan.code] = value
    return overrides


def _saisie_operations(article: Article, catalogue: Catalogue, params: Parametres, estimations,
                       unit: UnitSpec) -> dict[str, float | None]:
    ops = params.operations_actives()
    if not ops:
        ui.note("Aucune opération active dans les paramètres.")
        return {}
    saisies: dict[str, float | None] = {}
    for op in ops:
        code = op["code"]
        estimate = estimations.get(code)
        unite = op.get("unite") or "opération"
        if op.get("base") == "exemplaire":
            label = f"{op.get('libelle', code)}, {plural(2, unite)} par {unit.singular}"
        else:
            label = f"{op.get('libelle', code)}, {plural(2, unite)} pour la commande"
        key = k_operation(article.id, code)
        _init(key, None)
        pu, source = operation_unit_cost(op, article, catalogue, params)
        col1, col2 = st.columns([2, 3])
        with col1:
            value = st.number_input(
                label, min_value=0, step=1, key=key, persist_state=PERSIST,
                placeholder=f"Auto : {fmt_smart(estimate.value if estimate else 0)}",
                help="Laissez vide pour garder l'estimation. Un nombre saisi la remplace (0 pour aucune).",
            )
        with col2:
            texte = ui.e(estimate.explication if estimate else "")
            cout = (f" Coût unitaire : <strong>{ui.e(fmt_money(pu))}</strong> ({ui.e(source)})."
                    if pu is not None else " <strong>Coût unitaire non renseigné.</strong>")
            prefix = "<strong>Nombre saisi.</strong> Estimation : " if value is not None else ""
            ui.note(prefix + texte + cout)
        saisies[code] = value
    return saisies


# --------------------------------------------------------------------------- #
# Emballage, livraison, frais ponctuels
# --------------------------------------------------------------------------- #
def _saisie_emballage(params: Parametres) -> tuple[str | None, float | None, float]:
    emballages = {row["code"]: row for row in params.emballages}
    options = [SANS] + list(emballages)
    defaut = params.general.get("emballage_defaut")
    if st.session_state.get(K_EMB_TYPE) not in options:
        st.session_state[K_EMB_TYPE] = defaut if defaut in emballages else SANS
    col1, col2, col3 = st.columns([5, 3, 3])
    with col1:
        code = st.selectbox(
            "Type d'emballage", options, key=K_EMB_TYPE, persist_state=PERSIST, filter_mode="contains",
            format_func=lambda c: "Sans emballage" if c == SANS else emballages[c].get("libelle", c),
        )
    if code == SANS:
        return None, None, 0
    tarif = to_float(emballages[code].get("cout_unitaire"), None)
    cout_key = k_emb_cout(code)
    _init(cout_key, None)
    _init(K_EMB_NB, 0)
    with col2:
        cout = st.number_input(
            "Coût unitaire (FCFA)", min_value=0.0, step=50.0, format="%.0f", key=cout_key,
            placeholder=f"Tarif : {fmt_number(tarif) if tarif is not None else 'non renseigné'}",
            persist_state=PERSIST, help="Laissez vide pour appliquer le tarif des paramètres.",
        )
    with col3:
        nombre = st.number_input("Nombre de cartons", min_value=0, step=1, key=K_EMB_NB, persist_state=PERSIST)
    return code, cout, float(nombre or 0)


def _saisie_livraison(params: Parametres) -> tuple[bool, str | None, float]:
    transports = {row["code"]: row for row in params.transports}
    _init(K_LIVRAISON, bool(params.general.get("livraison_defaut", True)))
    livrer = st.toggle("Livrer la commande", key=K_LIVRAISON, persist_state=PERSIST)
    if not livrer:
        return False, None, 0.0
    if not transports:
        ui.note("Aucun mode de transport paramétré : ajoutez-en un dans Paramètres.")
        return True, None, 0.0
    defaut = params.general.get("transport_defaut")
    if st.session_state.get(K_TRANSPORT) not in transports:
        st.session_state[K_TRANSPORT] = defaut if defaut in transports else next(iter(transports))
    _init(K_DISTANCE, 0.0)
    col1, col2 = st.columns([5, 3])
    with col1:
        code = st.selectbox(
            "Mode de transport", list(transports), key=K_TRANSPORT, persist_state=PERSIST,
            format_func=lambda c: f"{transports[c].get('libelle', c)}, "
                                  f"{fmt_money(to_float(transports[c].get('cout_km'), 0))} le km",
        )
    with col2:
        distance = st.number_input("Distance aller (km)", min_value=0.0, step=1.0, format="%g",
                                   key=K_DISTANCE, persist_state=PERSIST)
    row = transports[code]
    cout_km = to_float(row.get("cout_km"), 0.0) or 0.0
    fixes = to_float(row.get("frais_fixes"), 0.0) or 0.0
    if distance and distance > 0:
        texte = (f"Distance facturée : <strong>{fmt_smart(distance)} × 2 = {fmt_smart(distance * 2)} km</strong> "
                 f"(aller-retour) × {ui.e(fmt_money(cout_km))} le km = "
                 f"<strong>{ui.e(fmt_money(distance * 2 * cout_km))}</strong>")
        if fixes:
            texte += f", plus {ui.e(fmt_money(fixes))} de prise en charge"
        ui.note(texte + ".")
    else:
        ui.note("Saisissez la distance aller : l'aller-retour est facturé.")
    return True, code, float(distance or 0)


def _ajouter_ponctuel() -> None:
    st.session_state[K_PONCTUELS] = list(st.session_state.get(K_PONCTUELS, [])) + [uuid.uuid4().hex[:8]]


def _retirer_ponctuel(row_id: str) -> None:
    st.session_state[K_PONCTUELS] = [r for r in st.session_state.get(K_PONCTUELS, []) if r != row_id]


def _saisie_ponctuels() -> list[dict]:
    lignes = []
    for row_id in list(st.session_state.get(K_PONCTUELS, [])):
        k_lib, k_mt = k_ponctuel(row_id, "libelle"), k_ponctuel(row_id, "montant")
        _init(k_lib, "")
        _init(k_mt, None)
        col1, col2, col3 = st.columns([6, 3, 1], vertical_alignment="bottom")
        with col1:
            libelle = st.text_input("Libellé", key=k_lib, persist_state=PERSIST,
                                    placeholder="Création graphique, sous-traitance…")
        with col2:
            montant = st.number_input("Montant (FCFA)", min_value=0.0, step=500.0, format="%.0f",
                                      key=k_mt, persist_state=PERSIST)
        with col3:
            st.button("", key=f"tarif_ponctuel_{row_id}_suppr", icon=":material/close:",
                      help="Retirer ce frais", on_click=_retirer_ponctuel, args=(row_id,))
        lignes.append({"libelle": libelle, "montant": montant})
    st.button("Ajouter un frais", icon=":material/add:", on_click=_ajouter_ponctuel, key="tarif_ponctuel_ajout")
    return lignes


# --------------------------------------------------------------------------- #
# Épreuve
# --------------------------------------------------------------------------- #
def _epreuve(result: PricingResult, params: Parametres) -> None:
    unit = result.unit
    unitaires = [(f"par {unit.singular}", fmt_money(result.cout_unitaire))]
    if unit.divisor != 1:
        unitaires.append((f"le lot de {fmt_number(unit.divisor)}", fmt_money(result.cout_nomenclature)))
    with st.container(key="epreuve"):
        ui.epreuve(
            (result.article.designation, result.article.nature),
            ui.quantite_txt(unit, result.nb_exemplaires),
            result.total, unitaires, result.par_poste, result.alertes,
        )
        if result.prix_indicatifs:
            n = len(result.prix_indicatifs)
            st.page_link(
                nav.page("parametres"), icon=":material/rule:",
                label=f"{n} {plural(n, 'prix indicatif')} à valider dans Paramètres",
                help="Prix par défaut non encore confirmés : " + ", ".join(result.prix_indicatifs),
            )
        st.text_input("Référence", key=K_REFERENCE, persist_state=PERSIST,
                      placeholder="Client, numéro de devis…",
                      help="Facultatif : retrouvez ce calcul par cette référence dans l'historique.")
        col1, col2 = st.columns(2)
        with col1:
            st.button("Enregistrer", type="primary", icon=":material/bookmark_add:", width="stretch",
                      disabled=result.nb_exemplaires <= 0, on_click=_enregistrer, args=(result,),
                      key="tarif_enregistrer")
        fiche = fiche_depuis_resultat(result, st.session_state.get(K_REFERENCE, "") or "")
        with col2:
            st.download_button(
                "Fiche Excel", data=lambda: fiche_excel(fiche), file_name=nom_fichier_fiche(fiche),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                icon=":material/download:", width="stretch", on_click="ignore", key="tarif_fiche",
                disabled=result.nb_exemplaires <= 0,
            )
        dernier = st.session_state.get(K_DERNIER)
        if dernier:
            ui.note(f"Enregistré dans l'historique sous le n° <strong>{dernier}</strong>.")


def _enregistrer(result: PricingResult) -> None:
    reference = st.session_state.get(K_REFERENCE, "") or ""
    numero = data.historique_store().ajouter(result, reference)
    data.invalider_historique()
    st.session_state[K_DERNIER] = numero
    st.toast(f"Calcul enregistré sous le n° {numero}.", icon=":material/check_circle:")


# --------------------------------------------------------------------------- #
# Rechargement d'un calcul enregistré
# --------------------------------------------------------------------------- #
def charger(catalogue: Catalogue, request: PricingRequest, reference: str = "") -> bool:
    """Replace une saisie enregistrée dans les champs de la page. ``False`` si l'article n'existe plus."""
    article = catalogue.get(request.article_id)
    if article is None:
        return False
    ss = st.session_state
    unit = unit_spec(article.unite)
    ss[K_DESIGNATION] = next((d for d in catalogue.designations()
                              if d.casefold() == article.designation.casefold()), article.designation)
    ss[k_article(ss[K_DESIGNATION])] = article.id
    q = request.quantite or 0
    ss[k_quantite(unit)] = int(q) if unit.integer else float(q)
    for line in article.nomenclature:
        value = request.feuilles.get(line.code)
        ss[k_feuilles(article.id, line.code)] = int(value) if value is not None else None
    for code, value in request.operations.items():
        ss[k_operation(article.id, code)] = int(value) if value is not None else None
    ss[K_EMB_TYPE] = request.emballage or SANS
    if request.emballage:
        ss[k_emb_cout(request.emballage)] = request.emballage_cout_unitaire
    ss[K_EMB_NB] = int(request.emballage_nombre or 0)
    ss[K_LIVRAISON] = bool(request.livraison)
    if request.transport:
        ss[K_TRANSPORT] = request.transport
    ss[K_DISTANCE] = float(request.distance_km or 0)
    ids = []
    for frais in request.frais_ponctuels or []:
        row_id = uuid.uuid4().hex[:8]
        ids.append(row_id)
        ss[k_ponctuel(row_id, "libelle")] = str(frais.get("libelle") or "")
        ss[k_ponctuel(row_id, "montant")] = to_float(frais.get("montant"), None)
    ss[K_PONCTUELS] = ids
    ss[K_REFERENCE] = reference
    ss.pop(K_DERNIER, None)
    return True
