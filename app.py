"""DIGIPRINT Tarification : point d'entrée de l'application Streamlit.

Lancement en local :   streamlit run app.py
Hébergement :          Streamlit Community Cloud + base Neon PostgreSQL (voir README.md).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from digiprint import config
from digiprint.catalogue import CatalogueError
from digiprint.stockage import StockageError
from ui import components as ui
from ui import data, nav, theme
from ui.pages import historique, parametres, tarification

STATIC = Path(__file__).resolve().parent / "static"

st.set_page_config(
    page_title=config.APP_TITLE,
    page_icon=str(STATIC / "favicon.png"),
    layout="wide",
    initial_sidebar_state="collapsed",
)
theme.inject()
st.logo(str(STATIC / "logo.svg"), size="large")

PAGES = {
    "tarification": st.Page(tarification.render, title="Tarification", icon=":material/request_quote:",
                            url_path="tarification", default=True),
    "parametres": st.Page(parametres.render, title="Paramètres", icon=":material/tune:", url_path="parametres"),
    "historique": st.Page(historique.render, title="Historique", icon=":material/history:", url_path="historique"),
}
nav.PAGES.update(PAGES)
page = st.navigation(list(PAGES.values()), position="top")

try:
    data.get_db()
    data.get_catalogue()
    data.get_parametres()
except StockageError as exc:
    ui.entete("Base de données inaccessible")
    st.error(str(exc))
    st.markdown(
        "Vérifiez l'adresse de la base dans les secrets de l'application (section `[neon]`, clé `url`) "
        "et que le projet Neon est actif. Sans adresse configurée, l'application utilise une base SQLite locale."
    )
    st.stop()
except CatalogueError as exc:
    ui.entete("Base articles illisible")
    st.error(str(exc))
    st.markdown(
        "Le classeur de la base articles doit contenir la feuille `BASE_ARTICLE` avec les colonnes "
        "`ID_ARTICLES`, `DESIGNATION`, `NATURE`, `IMPUT1…` et `MACH1…`. "
        f"Fichier attendu : `{config.BASE_ARTICLES_FILE.name}` dans le dossier `data`."
    )
    st.stop()

page.run()
