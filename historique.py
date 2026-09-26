"""Page Historique : calculs enregistrés, consultables, rechargeables et exportables."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from digiprint.export import fiche_depuis_enregistrement, fiche_excel, historique_excel, nom_fichier_fiche
from digiprint.utils import fmt_money, fmt_smart, plural, unit_plural
from ui import components as ui
from ui import data, nav
from ui.pages import tarification

K_GEN = "hist_gen"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render() -> None:
    ui.entete("Historique", "Calculs enregistrés : consultez le détail, rechargez-les dans la tarification "
                            "ou exportez-les vers Excel.")
    ss = st.session_state
    ss.setdefault(K_GEN, 0)

    col1, col2, col3 = st.columns([4, 3, 2], vertical_alignment="bottom")
    with col1:
        recherche = st.text_input("Rechercher", key="hist_recherche", persist_state="session",
                                  placeholder="Référence, désignation, nature, identifiant article")
    with col2:
        if "hist_periode" not in ss:
            ss["hist_periode"] = (date.today() - timedelta(days=90), date.today())
        periode = st.date_input("Période", key="hist_periode", format="DD/MM/YYYY", persist_state="session")
    debut, fin = _bornes(periode)
    records = data.lister_historique(recherche or "", debut, fin)
    with col3:
        st.download_button("Exporter (Excel)", data=lambda: historique_excel(records),
                           file_name=f"Historique_tarification_{date.today():%Y%m%d}.xlsx", mime=XLSX,
                           icon=":material/download:", width="stretch", on_click="ignore",
                           disabled=not records, key="hist_export")

    if not records:
        if data.historique_store().compter() == 0:
            ui.vide("Aucun calcul enregistré",
                    "Dans la page Tarification, le bouton « Enregistrer » conserve ici le prix, sa saisie "
                    "et son détail.")
        else:
            ui.vide("Aucun calcul pour ces critères", "Élargissez la période ou modifiez la recherche.")
        return

    ui.note(f"<strong>{len(records)}</strong> {plural(len(records), 'calcul')}. "
            "Sélectionnez une ligne pour afficher son détail.")
    df = pd.DataFrame([{
        "N°": r.id, "Date": r.cree_le, "Référence": r.reference, "Désignation": r.designation,
        "Nature": r.nature, "Quantité": f"{fmt_smart(r.quantite)} {unit_plural(r.quantite, r.unite)}",
        "Prix de revient (FCFA)": round(r.total), "Coût unitaire (FCFA)": r.cout_unitaire,
    } for r in records])
    event = st.dataframe(
        df, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
        key=f"hist_table_{ss[K_GEN]}", height=min(420, 38 + 35 * len(df)),
        column_config={
            "N°": st.column_config.NumberColumn(width="small", format="%d"),
            "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
            "Nature": st.column_config.TextColumn(width="large"),
            "Prix de revient (FCFA)": st.column_config.NumberColumn(format="localized"),
            "Coût unitaire (FCFA)": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    rows = list(event.selection.rows) if event and event.selection else []
    ids = [int(df.iloc[i]["N°"]) for i in rows if i < len(df)]
    if len(ids) > 1:
        col1, _ = st.columns([2, 5])
        if col1.button(f"Supprimer les {len(ids)} calculs sélectionnés", icon=":material/delete:",
                       key="hist_suppr_multi"):
            _confirmer(ids)
    elif len(ids) == 1:
        _detail(ids[0])


def _bornes(periode) -> tuple[date | None, date | None]:
    if isinstance(periode, (tuple, list)):
        if len(periode) == 2:
            return periode[0], periode[1]
        if len(periode) == 1:
            return periode[0], periode[0]
        return None, None
    return (periode, periode) if periode else (None, None)


def _detail(numero: int) -> None:
    rec = data.historique_store().obtenir(numero)
    if rec is None:
        st.warning("Ce calcul n'existe plus.")
        return
    params = data.get_parametres()
    catalogue = data.get_catalogue()
    ui.section(f"Calcul n° {rec.id}", rec.reference or "sans référence")
    gauche, droite = st.columns([7, 5], gap="large")
    with gauche:
        ui.faits([
            ("Enregistré le", f"{rec.cree_le:%d/%m/%Y à %H:%M}"),
            ("Article", rec.article_id),
            ("Catégorie", rec.categorie),
            ("Quantité", f"{fmt_smart(rec.quantite)} {unit_plural(rec.quantite, rec.unite)}"),
            ("Version des paramètres", rec.parametres_version),
        ])
        if rec.parametres_version != params.version:
            ui.note("Calculé avec une version antérieure des paramètres : le montant ci-contre est celui "
                    "enregistré. Le recharger recalcule le prix avec les paramètres actuels.")
        ui.detail(rec.lignes, rec.total)
    with droite:
        with st.container(key="epreuve_hist"):
            unitaires = [(f"par {rec.unite}", fmt_money(rec.cout_unitaire))]
            ui.epreuve((rec.designation, rec.nature), f"{fmt_smart(rec.quantite)} {unit_plural(rec.quantite, rec.unite)}",
                       rec.total, unitaires, rec.postes, rec.alertes)
            if st.button("Recharger dans la tarification", type="primary", icon=":material/replay:",
                         width="stretch", key=f"hist_recharger_{rec.id}", disabled=rec.requete is None):
                if tarification.charger(catalogue, rec.requete, rec.reference):
                    st.switch_page(nav.page("tarification"))
                st.error(f"L'article {rec.article_id} n'existe plus dans la base articles en service.")
            fiche = fiche_depuis_enregistrement(rec)
            col1, col2 = st.columns(2)
            with col1:
                st.download_button("Fiche Excel", data=lambda: fiche_excel(fiche), file_name=nom_fichier_fiche(fiche),
                                   mime=XLSX, icon=":material/download:", width="stretch", on_click="ignore",
                                   key=f"hist_fiche_{rec.id}")
            with col2:
                if st.button("Supprimer", icon=":material/delete:", width="stretch", key=f"hist_suppr_{rec.id}"):
                    _confirmer([rec.id])


@st.dialog("Supprimer de l'historique")
def _confirmer(ids: list[int]) -> None:
    n = len(ids)
    st.write(f"Supprimer définitivement {n} {plural(n, 'calcul')} (n° {', '.join(map(str, ids))}) ? "
             "Cette action ne peut pas être annulée.")
    col1, col2 = st.columns(2)
    if col1.button("Supprimer", type="primary", width="stretch"):
        data.historique_store().supprimer(ids)
        data.invalider_historique()
        st.session_state[K_GEN] = st.session_state.get(K_GEN, 0) + 1
        st.rerun()
    if col2.button("Annuler", width="stretch"):
        st.rerun()
