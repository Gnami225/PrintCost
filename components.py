"""Composants d'affichage (HTML échappé, sans logique de calcul)."""

from __future__ import annotations

from html import escape

import streamlit as st

from digiprint.catalogue import Catalogue
from digiprint.models import Article, CostLine, UnitSpec, is_production_poste, poste_rank
from digiprint.utils import fmt_money, fmt_number, fmt_smart, plural, unit_plural


def e(value: object) -> str:
    return escape(str(value), quote=True)


def entete(titre: str, sous_titre: str = "") -> None:
    sous = f"<p>{e(sous_titre)}</p>" if sous_titre else ""
    st.html(f'<div class="dp-entete"><h1>{e(titre)}</h1>{sous}</div>')


def section(titre: str, aide: str = "", premiere: bool = False) -> None:
    cls = "dp-section premiere" if premiere else "dp-section"
    extra = f"<span>{e(aide)}</span>" if aide else ""
    st.html(f'<div class="{cls}"><h3>{e(titre)}</h3>{extra}</div>')


def note(texte_html: str) -> None:
    """Petit texte explicatif (``texte_html`` doit déjà être échappé)."""
    st.html(f'<div class="dp-note">{texte_html}</div>')


def vide(titre: str, texte: str) -> None:
    st.html(f'<div class="dp-vide"><b>{e(titre)}</b>{e(texte)}</div>')


# --------------------------------------------------------------------------- #
# Fiche article
# --------------------------------------------------------------------------- #
def faits(paires: list[tuple[str, str]]) -> None:
    items = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v or '–')}</dd></div>" for k, v in paires)
    st.html(f'<dl class="dp-faits">{items}</dl>')


def nomenclature(article: Article, catalogue: Catalogue, unit: UnitSpec) -> None:
    par = f"par lot de {fmt_number(unit.divisor)}" if unit.divisor != 1 else f"par {unit.singular}"
    rows = []
    for line in article.nomenclature:
        intr = catalogue.intrant(line.code)
        uom = intr.uom_conso or "unité"
        rows.append(f"<tr><td><code>{e(line.code)}</code></td><td>{e(intr.libelle)}</td>"
                    f"<td class='num'>{e(fmt_smart(line.quantite, 4))} {e(unit_plural(line.quantite, uom))}</td></tr>")
    intrants = ("<table class='dp-mini'><thead><tr><th>Code</th><th>Intrant</th>"
                f"<th class='num'>Quantité {e(par)}</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
                if rows else "<p class='dp-note'>Aucun intrant dans la nomenclature.</p>")
    rows = []
    for line in article.gamme:
        mach = catalogue.machine(line.code)
        rows.append(f"<tr><td><code>{e(line.code)}</code></td><td>{e(mach.libelle)}</td>"
                    f"<td class='num'>{e(fmt_smart(line.secondes, 3))} s</td></tr>")
    machines = ("<table class='dp-mini'><thead><tr><th>Code</th><th>Machine</th>"
                f"<th class='num'>Temps {e(par)}</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
                if rows else "<p class='dp-note'>Aucune machine dans la gamme.</p>")
    st.html(f"<div class='dp-table-scroll'>{intrants}</div><div style='height:.9rem'></div>"
            f"<div class='dp-table-scroll'>{machines}</div>")


# --------------------------------------------------------------------------- #
# Épreuve (résultat)
# --------------------------------------------------------------------------- #
def epreuve_vide() -> None:
    st.html('<div class="dp-epreuve"><div class="dp-ep-vide"><b>Le prix apparaît ici</b>'
            'Choisissez une désignation puis une nature : le prix de revient se calcule à chaque saisie, '
            'poste par poste.</div></div>')


def epreuve(article_label: tuple[str, str], quantite_txt: str, total: float, unitaires: list[tuple[str, str]],
            postes: dict[str, float], alertes: list[str]) -> None:
    designation, nature = article_label
    ordered = sorted(postes.items(), key=lambda kv: poste_rank(kv[0]))
    rows, prod_done, production = [], False, sum(v for k, v in postes.items() if is_production_poste(k))
    has_logistique = any(not is_production_poste(k) for k in postes)
    for poste, montant in ordered:
        if not is_production_poste(poste) and not prod_done and production > 0 and has_logistique:
            rows.append(f'<div class="dp-sous-total"><span>Coût de production</span>'
                        f'<b>{e(fmt_money(production))}</b></div>')
            prod_done = True
        part = (montant / total * 100) if total else 0
        rows.append(
            f'<div class="dp-poste"><span class="nom">{e(poste)}</span>'
            f'<span class="montant">{e(fmt_money(montant))}</span>'
            f'<span class="part">{e(fmt_smart(part, 0) if part >= 1 or part == 0 else "< 1")} %</span>'
            f'<div class="barre"><i style="width:{min(100.0, max(0.0, part)):.2f}%"></i></div></div>'
        )
    entier, _, devise = fmt_money(total, decimals=0).rpartition("\u00a0")
    unit_html = "".join(f"<span><strong>{e(v)}</strong> {e(k)}</span>" for k, v in unitaires)
    alerte = "".join(
        f'<div class="dp-alerte {"erreur" if texte.startswith("Prix manquant") else "info"}">{e(texte)}</div>'
        for texte in alertes
    )
    st.html(
        '<div class="dp-epreuve">'
        f'<div class="dp-ep-article">{e(designation)}</div>'
        f'<div class="dp-ep-nature">{e(nature)}</div>'
        f'<div class="dp-ep-qte">{e(quantite_txt)}</div>'
        f'<div class="dp-ep-total">{e(entier)}<small>{e(devise)}</small></div>'
        '<div class="dp-ep-sous">Prix de revient hors marge</div>'
        f'<div class="dp-ep-unitaire">{unit_html}</div>'
        f'<div class="dp-postes">{"".join(rows)}</div>'
        f'{alerte}'
        '</div>'
    )


def alerte_info(texte: str) -> None:
    st.html(f'<div class="dp-alerte info">{e(texte)}</div>')


# --------------------------------------------------------------------------- #
# Détail du calcul
# --------------------------------------------------------------------------- #
def detail(lines: list[CostLine], total: float) -> None:
    by_poste: dict[str, list[CostLine]] = {}
    for line in lines:
        by_poste.setdefault(line.poste, []).append(line)
    body = []
    for poste in sorted(by_poste, key=poste_rank):
        items = by_poste[poste]
        subtotal = sum(line.montant for line in items)
        body.append(f'<tr class="poste"><td colspan="3">{e(poste)}</td>'
                    f'<td class="num montant">{e(fmt_money(subtotal))}</td></tr>')
        for line in items:
            tag = ""
            if line.prix_manquant:
                tag = '<span class="tag manque">manquant</span>'
            elif not line.prix_valide:
                tag = '<span class="tag" title="Prix par défaut, à valider dans Paramètres">indicatif</span>'
            body.append(
                "<tr>"
                f'<td><div class="lib">{e(line.libelle)}</div><div class="calc">{e(line.formule)}</div></td>'
                f'<td class="num">{e(line.quantite_txt())}</td>'
                f'<td class="num">{e(line.prix_txt())}{tag}</td>'
                f'<td class="num montant">{e(fmt_money(line.montant))}</td>'
                "</tr>"
            )
    if not body:
        body.append('<tr><td colspan="4" class="calc">Aucun coût pour cette saisie.</td></tr>')
    st.html(
        '<div class="dp-table-scroll"><table class="dp-detail">'
        '<thead><tr><th>Élément et calcul</th><th class="num">Quantité</th>'
        '<th class="num">Prix unitaire</th><th class="num">Montant</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody>'
        f'<tfoot><tr><td colspan="3">Prix de revient total</td><td class="num">{e(fmt_money(total))}</td></tr></tfoot>'
        '</table></div>'
    )


def quantite_txt(unit: UnitSpec, quantite: float) -> str:
    return f"{fmt_smart(quantite)}\u00a0{plural(quantite, unit.singular, unit.plural_form)}"
