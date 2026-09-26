"""Styles de l'interface.

Le thème de base (couleurs, police, rayons) est défini dans
``.streamlit/config.toml`` ; ce module ajoute les composants propres à
l'application, au premier rang desquels l'« épreuve » : le panneau de résultat,
traité comme une épreuve d'imprimerie avec ses traits de coupe.
"""

from __future__ import annotations

import streamlit as st

ROSE = "#C8236A"
ROSE_FONCE = "#9E1B54"
ROSE_VOILE = "#FCF1F6"
ENCRE = "#2B2D33"
GRIS = "#5E6169"
GRIS_CLAIR = "#8E9098"
FILET = "#E7E7EB"
SURFACE = "#F6F6F8"

CSS = f"""
<style>
:root {{
  --dp-rose: {ROSE};
  --dp-rose-fonce: {ROSE_FONCE};
  --dp-rose-voile: {ROSE_VOILE};
  --dp-encre: {ENCRE};
  --dp-gris: {GRIS};
  --dp-gris-clair: {GRIS_CLAIR};
  --dp-filet: {FILET};
  --dp-surface: {SURFACE};
}}

/* Largeur de lecture confortable. */
.block-container {{ padding-top: 4.6rem; padding-bottom: 4rem; max-width: 1320px; }}

/* Chiffres proportionnels : les formes tabulaires de la police élargissent aussi la virgule. */

/* En-tête de page */
.dp-entete {{ margin: 0 0 1.4rem 0; }}
.dp-entete h1 {{
  font-size: 2.05rem; line-height: 1.15; font-weight: 750; letter-spacing: -0.015em;
  margin: 0; padding: 0; color: var(--dp-encre);
}}
.dp-entete p {{ margin: .35rem 0 0 0; color: var(--dp-gris); font-size: .98rem; max-width: 68ch; }}

/* Titres de section dans la colonne de saisie */
.dp-section {{
  display: flex; align-items: baseline; gap: .6rem;
  margin: 1.5rem 0 .35rem 0; padding-top: 1rem; border-top: 1px solid var(--dp-filet);
}}
.dp-section h3 {{ font-size: 1.08rem; font-weight: 700; margin: 0; padding: 0; color: var(--dp-encre); }}
.dp-section span {{ color: var(--dp-gris-clair); font-size: .88rem; }}
.dp-section.premiere {{ border-top: 0; padding-top: 0; margin-top: .2rem; }}

.dp-note {{ color: var(--dp-gris); font-size: .86rem; line-height: 1.45; margin: .1rem 0 .5rem 0; }}
.dp-note strong {{ color: var(--dp-encre); font-weight: 600; }}

/* Fiche article : grille de faits */
.dp-faits {{
  display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: .7rem 1.4rem; margin: .6rem 0 .4rem 0;
}}
.dp-faits div {{ min-width: 0; }}
.dp-faits dt {{ color: var(--dp-gris-clair); font-size: .78rem; margin: 0; }}
.dp-faits dd {{ margin: .1rem 0 0 0; font-size: .93rem; color: var(--dp-encre); font-weight: 550; overflow-wrap: anywhere; }}

/* Tableaux compacts (nomenclature, détail) */
.dp-table-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
.dp-mini {{ width: 100%; border-collapse: collapse; font-size: .86rem; }}
.dp-mini th {{ text-align: left; font-weight: 600; color: var(--dp-gris); padding: .35rem .5rem .35rem 0;
  border-bottom: 1px solid var(--dp-filet); white-space: nowrap; }}
.dp-mini td {{ padding: .35rem .5rem .35rem 0; border-bottom: 1px solid #F1F1F4; vertical-align: top; }}
.dp-mini td.num, .dp-mini th.num {{ text-align: right; white-space: nowrap; }}
.dp-mini code {{ font-size: .78rem; color: var(--dp-gris); background: none; padding: 0; }}

/* Épreuve : panneau de résultat, collant à droite sur grand écran */
@media (min-width: 900px) {{
  [data-testid="stColumn"]:has([class*="st-key-epreuve"]) {{ position: sticky; top: 4.2rem; align-self: flex-start; }}
}}
[class*="st-key-epreuve"] {{
  position: relative; background: #FFFFFF; border: 1px solid var(--dp-filet);
  padding: 1.5rem 1.5rem 1.2rem 1.5rem; margin: 16px;
}}
/* Traits de coupe aux quatre coins, hors du format fini, comme sur une épreuve. */
[class*="st-key-epreuve"]::before {{
  content: ""; position: absolute; inset: -16px; pointer-events: none;
  --t: var(--dp-gris-clair);
  background-image:
    linear-gradient(var(--t), var(--t)), linear-gradient(var(--t), var(--t)),
    linear-gradient(var(--t), var(--t)), linear-gradient(var(--t), var(--t)),
    linear-gradient(var(--t), var(--t)), linear-gradient(var(--t), var(--t)),
    linear-gradient(var(--t), var(--t)), linear-gradient(var(--t), var(--t));
  background-repeat: no-repeat;
  background-size: 11px 1px, 1px 11px, 11px 1px, 1px 11px, 11px 1px, 1px 11px, 11px 1px, 1px 11px;
  background-position:
    left 0 top 15px, left 15px top 0,
    right 0 top 15px, right 15px top 0,
    left 0 bottom 15px, left 15px bottom 0,
    right 0 bottom 15px, right 15px bottom 0;
}}
.dp-ep-article {{ font-size: 1.02rem; font-weight: 700; color: var(--dp-encre); line-height: 1.3; }}
.dp-ep-nature {{ color: var(--dp-gris); font-size: .9rem; line-height: 1.35; margin-top: .15rem; }}
.dp-ep-qte {{ color: var(--dp-gris); font-size: .9rem; margin-top: .55rem; }}
.dp-ep-total {{
  font-size: 2.9rem; line-height: 1; font-weight: 800; letter-spacing: -0.025em;
  color: var(--dp-rose); margin: 1.1rem 0 .25rem 0; white-space: nowrap;
}}
.dp-ep-total small {{ font-size: 1.05rem; font-weight: 700; letter-spacing: 0; margin-left: .3rem; }}
.dp-ep-sous {{ color: var(--dp-gris); font-size: .88rem; }}
.dp-ep-unitaire {{
  display: flex; flex-wrap: wrap; gap: .2rem 1.2rem; margin: .8rem 0 1.1rem 0;
  padding: .7rem 0; border-top: 1px solid var(--dp-filet); border-bottom: 1px solid var(--dp-filet);
  font-size: .92rem; color: var(--dp-gris);
}}
.dp-ep-unitaire strong {{ color: var(--dp-encre); font-size: 1.05rem; font-weight: 700; }}
.dp-postes {{ display: flex; flex-direction: column; gap: .55rem; }}
.dp-poste {{ display: grid; grid-template-columns: 1fr auto 3.2rem; gap: .1rem .7rem; align-items: baseline; font-size: .9rem; }}
.dp-poste .nom {{ color: var(--dp-encre); }}
.dp-poste .montant {{ color: var(--dp-encre); font-weight: 600; text-align: right; white-space: nowrap; }}
.dp-poste .part {{ color: var(--dp-gris-clair); text-align: right; font-size: .82rem; }}
.dp-poste .barre {{ grid-column: 1 / -1; height: 3px; background: #F0F0F3; }}
.dp-poste .barre i {{ display: block; height: 3px; background: var(--dp-rose); }}
.dp-sous-total {{
  display: flex; justify-content: space-between; font-size: .86rem; color: var(--dp-gris);
  padding: .45rem 0 .1rem 0; margin: .1rem 0 .25rem 0; border-top: 1px dashed #D9D9DF;
}}
.dp-sous-total b {{ color: var(--dp-encre); font-weight: 650; }}
.dp-ep-vide {{ color: var(--dp-gris); font-size: .95rem; line-height: 1.5; padding: .4rem 0 .6rem 0; }}
.dp-ep-vide b {{ display: block; color: var(--dp-encre); font-size: 1.05rem; margin-bottom: .3rem; }}
.dp-alerte {{ margin-top: 1rem; padding: .6rem .75rem; font-size: .85rem; line-height: 1.45; border-left: 3px solid; }}
.dp-alerte.erreur {{ border-color: #B42318; background: #FEF3F2; color: #7A271A; }}
.dp-alerte.info {{ border-color: var(--dp-rose); background: var(--dp-rose-voile); color: #6E1F42; }}

/* Détail du calcul */
.dp-detail {{ width: 100%; border-collapse: collapse; font-size: .9rem; margin-top: .3rem; }}
.dp-detail th {{ text-align: left; font-weight: 600; color: var(--dp-gris); font-size: .82rem;
  padding: .5rem .8rem .5rem 0; border-bottom: 1px solid var(--dp-encre); white-space: nowrap; }}
.dp-detail th.num, .dp-detail td.num {{ text-align: right; }}
.dp-detail td {{ padding: .55rem .8rem .55rem 0; border-bottom: 1px solid #EFEFF2; vertical-align: top; }}
.dp-detail td.num {{ white-space: nowrap; }}
.dp-detail tr.poste td {{ padding-top: 1.1rem; border-bottom: 1px solid var(--dp-filet); font-weight: 700; color: var(--dp-encre); }}
.dp-detail tr.poste td.num {{ color: var(--dp-encre); }}
.dp-detail .lib {{ color: var(--dp-encre); }}
.dp-detail .calc {{ color: var(--dp-gris-clair); font-size: .8rem; line-height: 1.4; margin-top: .15rem; max-width: 70ch; }}
.dp-detail .tag {{ display: inline-block; margin-left: .35rem; font-size: .72rem; color: var(--dp-rose-fonce);
  border: 1px solid #F0C6D8; padding: 0 .3rem; border-radius: 3px; vertical-align: 1px; }}
.dp-detail .tag.manque {{ color: #B42318; border-color: #F5C2BC; }}
.dp-detail tfoot td {{ border-top: 1px solid var(--dp-encre); border-bottom: 0; padding-top: .7rem;
  font-weight: 800; font-size: 1.02rem; }}
.dp-detail tfoot td.num {{ color: var(--dp-rose); }}

/* Messages d'état vides */
.dp-vide {{ padding: 2.2rem 0; color: var(--dp-gris); max-width: 60ch; }}
.dp-vide b {{ color: var(--dp-encre); display: block; font-size: 1.05rem; margin-bottom: .3rem; }}

/* Indicateur de modifications non enregistrées (Paramètres) */
.dp-brouillon {{
  display: flex; gap: .6rem; align-items: center; padding: .55rem .8rem; margin-bottom: .6rem;
  background: var(--dp-rose-voile); border-left: 3px solid var(--dp-rose); color: #6E1F42; font-size: .9rem;
}}

@media (max-width: 640px) {{
  .dp-entete h1 {{ font-size: 1.6rem; }}
  .dp-ep-total {{ font-size: 2.3rem; }}
  [class*="st-key-epreuve"] {{ margin: 16px 14px; padding: 1.1rem; }}
}}
@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
</style>
"""


def inject() -> None:
    st.html(CSS)
