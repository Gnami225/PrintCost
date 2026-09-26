"""Moteur de calcul du prix de revient (sans marge commerciale).

Le calcul part de la base articles et des paramètres, puis applique les saisies
de l'utilisateur. Chaque coût produit une ``CostLine`` dont le montant vaut
toujours ``quantité × prix unitaire`` : le détail affiché (et exporté vers
Excel) se vérifie ligne à ligne.

Ordre de calcul
---------------
1. **Papier** : feuilles de tirage déduites de la nomenclature (feuilles A0 ×
   feuilles par A0 du format de tirage du procédé), arrondies à l'unité
   supérieure ; nombre modifiable par l'utilisateur.
2. **Autres intrants** (matières premières, encres, consommables) : quantité de
   nomenclature × prix d'achat ramené à l'unité de consommation.
3. **Machines** (gamme) : temps de passage × taux horaire. Une machine rattachée
   à une opération active (le massicot pour la découpe) n'est pas comptée au
   temps : son coût est porté par l'opération, sans double comptage.
4. **Opérations** paramétrées (découpe, rainage, et toute opération ajoutée) :
   nombre estimé ou saisi × coût unitaire, éventuellement selon le papier.
5. **Emballage**, **transport** (distance aller × 2 × coût au km), **frais
   ponctuels** saisis.
6. **Frais paramétrés** : montant fixe, par exemplaire ou pourcentage d'une
   assiette (coût de production ou coût total avant frais).
"""

from __future__ import annotations

from typing import Any

from . import defaults
from .catalogue import Catalogue
from .estimation import ESTIMATORS, EstimationContext, infer_poses, reference_paper
from .models import (
    POSTE_AUTRES,
    POSTE_EMBALLAGE,
    POSTE_PAPIER,
    POSTE_TRANSPORT,
    UNITE_ASSIETTE,
    UNITE_HEURE,
    Article,
    CostLine,
    Estimate,
    PricingRequest,
    PricingResult,
    SheetPlan,
    UnitSpec,
    is_production_poste,
    poste_rank,
    unit_spec,
)
from .parametres import Parametres
from .utils import (
    NBSP,
    ceil_clean,
    clean_text,
    fmt_duration,
    fmt_money,
    fmt_number,
    fmt_smart,
    plural,
    to_float,
    unit_plural,
)


class CalculError(Exception):
    """Calcul impossible (article inconnu…)."""


# --------------------------------------------------------------------------- #
# Quantités
# --------------------------------------------------------------------------- #
def quantites(article: Article, quantite: Any) -> tuple[UnitSpec, float, float]:
    """Unité de saisie, quantité saisie (≥ 0) et quantité en unités de nomenclature."""
    unit = unit_spec(article.unite)
    qty = max(0.0, float(to_float(quantite, 0.0) or 0.0))
    return unit, qty, qty / unit.divisor


def fmt_qty(value: float, singular: str, plural_form: str | None = None) -> str:
    """``25`` + ``feuille`` → ``'25 feuilles'`` (espace insécable)."""
    label = plural(value, singular, plural_form) if plural_form else unit_plural(value, singular)
    return f"{fmt_smart(value)}{NBSP}{label}"


def fmt_saisie(unit: UnitSpec, value: float) -> str:
    """Quantité saisie avec son unité : ``500 exemplaires``, ``12 m²``."""
    return fmt_qty(value, unit.singular, unit.plural_form)


def fmt_nomenclature(unit: UnitSpec, qn: float) -> str:
    """Quantité en unités de nomenclature : ``500 exemplaires`` ou ``5 lots de 1 000``."""
    if unit.divisor != 1:
        return f"{fmt_qty(qn, 'lot')} de {fmt_number(unit.divisor)}"
    return fmt_saisie(unit, qn)


def _par_unite(unit: UnitSpec) -> str:
    return f"par lot de {fmt_number(unit.divisor)}" if unit.divisor != 1 else f"par {unit.singular}"


def _price(value: Any) -> float | None:
    number = to_float(value, None)
    return None if number is None or number < 0 else number


# --------------------------------------------------------------------------- #
# Papier
# --------------------------------------------------------------------------- #
def sheet_plan(
    article: Article,
    catalogue: Catalogue,
    params: Parametres,
    quantite: Any,
    overrides: dict[str, Any] | None = None,
) -> list[SheetPlan]:
    """Besoin en feuilles de tirage, papier par papier.

    ``overrides`` : nombre de feuilles saisi par l'utilisateur (code papier →
    nombre). Une valeur ``None`` ou absente laisse le calcul automatique.
    """
    unit, _, qn = quantites(article, quantite)
    fmt, gache = params.format_tirage(article.procede)
    per_a0 = float(to_float(fmt.get("feuilles_par_a0"), 4.0) or 4.0)
    arrondir = bool(params.general.get("arrondir_feuilles", True))
    overrides = overrides or {}

    plans: list[SheetPlan] = []
    for line in article.nomenclature:
        intrant = catalogue.intrant(line.code)
        if not intrant.is_paper_sheet:
            continue
        quantite_a0 = line.quantite * qn
        calculees = quantite_a0 * per_a0
        auto = float(ceil_clean(calculees)) if arrondir else round(calculees, 4)
        saisie = to_float(overrides.get(line.code), None) if overrides.get(line.code) is not None else None
        manuelle = saisie is not None and saisie >= 0
        plans.append(
            SheetPlan(
                code=line.code,
                libelle=intrant.libelle,
                format_code=str(fmt.get("code", "")),
                format_libelle=str(fmt.get("libelle", fmt.get("code", ""))),
                feuilles_par_a0=per_a0,
                quantite_a0=quantite_a0,
                feuilles_calculees=calculees,
                feuilles_auto=auto,
                feuilles=float(saisie) if manuelle else auto,
                saisie_manuelle=manuelle,
                poses=infer_poses(line.quantite / unit.divisor, per_a0, gache),
                gache_pct=gache,
            )
        )
    return plans


def explain_sheets(plan: SheetPlan, unit: UnitSpec, qn: float) -> str:
    """Explication du nombre de feuilles calculé automatiquement."""
    parts = [
        f"{fmt_smart(plan.quantite_a0)} A0 pour {fmt_nomenclature(unit, qn)}",
        f"× {fmt_smart(plan.feuilles_par_a0)} feuilles {plan.format_code} par A0",
        f"= {fmt_smart(plan.feuilles_calculees)}",
    ]
    text = " ".join(parts)
    if plan.feuilles_auto != plan.feuilles_calculees:
        text += f", arrondi à {fmt_smart(plan.feuilles_auto)}"
    if plan.poses:
        text += f". {plan.poses} {plural(plan.poses, 'pose')} par feuille, gâche de {fmt_smart(plan.gache_pct)} % comprise"
    return text + "."


# --------------------------------------------------------------------------- #
# Opérations
# --------------------------------------------------------------------------- #
def estimate_operations(
    article: Article,
    catalogue: Catalogue,
    params: Parametres,
    quantite: Any,
    plans: list[SheetPlan],
) -> dict[str, Estimate]:
    """Nombre proposé pour chaque opération active (valeur + explication)."""
    _, nb, _ = quantites(article, quantite)
    papier = reference_paper(article, catalogue)
    result: dict[str, Estimate] = {}
    for op in params.operations_actives():
        rule = ESTIMATORS.get(op.get("estimation") or "aucune")
        if rule is None:
            result[op["code"]] = Estimate(0, "Pas d'estimation automatique : saisissez le nombre.")
            continue
        ctx = EstimationContext(article, op, nb, plans, params.general, papier)
        try:
            result[op["code"]] = rule(ctx)
        except Exception as exc:  # une règle défaillante ne doit jamais bloquer le calcul
            result[op["code"]] = Estimate(0, f"Estimation impossible ({exc}) : saisissez le nombre.")
    return result


def operation_unit_cost(op: dict[str, Any], article: Article, catalogue: Catalogue,
                        params: Parametres) -> tuple[float | None, str]:
    """Coût unitaire d'une opération et sa provenance (tarif selon le papier ou tarif général)."""
    if op.get("selon_papier"):
        papier = reference_paper(article, catalogue)
        if papier is not None:
            tarif = params.tarif_papier(op["code"], papier.code)
            if tarif is not None and tarif >= 0:
                return tarif, f"tarif {papier.libelle}"
    return _price(op.get("cout_unitaire")), "tarif général"


# --------------------------------------------------------------------------- #
# Calcul complet
# --------------------------------------------------------------------------- #
def compute(article: Article, request: PricingRequest, catalogue: Catalogue, params: Parametres) -> PricingResult:
    """Prix de revient complet d'un article pour une saisie donnée."""
    unit, nb, qn = quantites(article, request.quantite)
    lines: list[CostLine] = []
    alertes: list[str] = []

    if nb <= 0:
        alertes.append("Saisissez une quantité supérieure à zéro pour obtenir un prix.")

    plans = sheet_plan(article, catalogue, params, request.quantite, request.feuilles)
    estimations = estimate_operations(article, catalogue, params, request.quantite, plans)

    _add_paper(lines, plans, catalogue, params)
    _add_intrants(lines, article, catalogue, params, unit, qn)
    _add_machines(lines, article, catalogue, params, unit, qn)
    _add_operations(lines, article, request, catalogue, params, unit, nb, estimations)
    _add_packaging(lines, request, params, alertes)
    _add_transport(lines, request, params, alertes)
    _add_ponctuels(lines, request, alertes)
    _add_frais(lines, params, unit, nb)

    order = {id(line): i for i, line in enumerate(lines)}
    lines.sort(key=lambda line: (poste_rank(line.poste), order[id(line)]))

    par_poste: dict[str, float] = {}
    for line in lines:
        par_poste[line.poste] = par_poste.get(line.poste, 0.0) + line.montant
    total = sum(line.montant for line in lines)

    manquants = sorted({line.libelle for line in lines if line.prix_manquant})
    if manquants:
        alertes.append(
            "Prix manquant, compté à 0 : " + ", ".join(manquants)
            + ". Renseignez-le dans la page Paramètres."
        )
    indicatifs = sorted({line.libelle for line in lines
                         if not line.prix_valide and not line.prix_manquant and line.montant > 0})

    return PricingResult(
        article=article,
        request=request,
        unit=unit,
        lines=lines,
        total=total,
        par_poste=par_poste,
        nb_exemplaires=nb,
        quantite_nomenclature=qn,
        feuilles=plans,
        estimations=estimations,
        alertes=alertes,
        prix_indicatifs=indicatifs,
        parametres_version=params.version,
    )


def calculer(catalogue: Catalogue, params: Parametres, request: PricingRequest) -> PricingResult:
    """Point d'entrée à partir de l'identifiant article de la saisie."""
    article = catalogue.get(request.article_id)
    if article is None:
        raise CalculError(f"Article « {request.article_id} » introuvable dans la base articles.")
    return compute(article, request, catalogue, params)


# --------------------------------------------------------------------------- #
# Postes de coût
# --------------------------------------------------------------------------- #
def _add_paper(lines: list[CostLine], plans: list[SheetPlan], catalogue: Catalogue, params: Parametres) -> None:
    for plan in plans:
        intrant = catalogue.intrant(plan.code)
        row = params.intrant(plan.code)
        poste = clean_text(row.get("poste")) or POSTE_PAPIER
        fixe = params.prix_format(plan.code, plan.format_code)
        if fixe is not None:
            pu = float(_price(fixe.get("prix_feuille")) or 0.0)
            valide, manquant = bool(fixe.get("valide")), False
            detail = f"prix fixé pour la feuille {plan.format_code}"
        else:
            prix = _price(row.get("prix_achat"))
            manquant = prix is None
            valide = bool(row.get("valide"))
            pu = (prix or 0.0) / intrant.facteur_conversion / plan.feuilles_par_a0
            conditionnement = intrant.conditionnement or f"{fmt_smart(intrant.facteur_conversion)} A0"
            achat = intrant.uom_achat.lower() or "paquet"
            detail = (
                f"{fmt_money(prix)} par {achat} de {conditionnement}, "
                f"{fmt_smart(plan.feuilles_par_a0)} feuilles {plan.format_code} par A0"
                if not manquant else "prix d'achat non renseigné"
            )
        unite = f"feuille {plan.format_code}"
        saisie = " (nombre saisi)" if plan.saisie_manuelle else ""
        lines.append(CostLine(
            poste=poste,
            code=plan.code,
            libelle=intrant.libelle,
            quantite=plan.feuilles,
            unite=unite,
            prix_unitaire=pu,
            montant=plan.feuilles * pu,
            formule=f"{fmt_qty(plan.feuilles, 'feuille')} {plan.format_code}{saisie} × {fmt_money(pu)} ({detail})",
            origine="saisie" if plan.saisie_manuelle else "nomenclature",
            prix_valide=valide,
            prix_manquant=manquant,
        ))


def _add_intrants(lines: list[CostLine], article: Article, catalogue: Catalogue, params: Parametres,
                  unit: UnitSpec, qn: float) -> None:
    for bom in article.nomenclature:
        intrant = catalogue.intrant(bom.code)
        if intrant.is_paper_sheet:
            continue
        row = params.intrant(bom.code)
        poste = clean_text(row.get("poste")) or defaults.default_poste_intrant(intrant)
        prix = _price(row.get("prix_achat"))
        pu = (prix or 0.0) / intrant.facteur_conversion
        quantite = bom.quantite * qn
        uom = intrant.uom_conso or "unité"
        achat = intrant.uom_achat.lower() or "conditionnement"
        if prix is None:
            detail = "prix d'achat non renseigné"
        elif intrant.facteur_conversion != 1 and intrant.conditionnement:
            detail = f"{fmt_money(prix)} par {achat} de {intrant.conditionnement}"
        else:
            detail = f"{fmt_money(prix)} par {achat}"
        lines.append(CostLine(
            poste=poste,
            code=bom.code,
            libelle=intrant.libelle,
            quantite=quantite,
            unite=uom,
            prix_unitaire=pu,
            montant=quantite * pu,
            formule=(
                f"{fmt_qty(bom.quantite, uom)} {_par_unite(unit)} × {fmt_nomenclature(unit, qn)} "
                f"= {fmt_qty(quantite, uom)} × {fmt_money(pu)} ({detail})"
            ),
            origine="nomenclature",
            prix_valide=bool(row.get("valide")),
            prix_manquant=prix is None,
        ))


def _add_machines(lines: list[CostLine], article: Article, catalogue: Catalogue, params: Parametres,
                  unit: UnitSpec, qn: float) -> None:
    portees = params.machines_valorisees_par_operation()
    for routing in article.gamme:
        if routing.code in portees:
            continue  # coût porté par l'opération rattachée (pas de double comptage)
        machine = catalogue.machine(routing.code)
        row = params.machine(routing.code)
        poste = clean_text(row.get("poste")) or defaults.default_poste_machine(machine)
        taux = _price(row.get("taux_horaire"))
        secondes = routing.secondes * qn
        heures = secondes / 3600
        lines.append(CostLine(
            poste=poste,
            code=routing.code,
            libelle=machine.libelle,
            quantite=heures,
            unite=UNITE_HEURE,
            prix_unitaire=taux or 0.0,
            montant=heures * (taux or 0.0),
            formule=(
                f"{fmt_smart(routing.secondes)} s {_par_unite(unit)} × {fmt_nomenclature(unit, qn)} "
                f"= {fmt_duration(secondes)} × {fmt_money(taux) if taux is not None else 'taux non renseigné'} de l'heure"
            ),
            origine="gamme",
            prix_valide=bool(row.get("valide")),
            prix_manquant=taux is None,
        ))


def _add_operations(lines: list[CostLine], article: Article, request: PricingRequest, catalogue: Catalogue,
                    params: Parametres, unit: UnitSpec, nb: float, estimations: dict[str, Estimate]) -> None:
    for op in params.operations_actives():
        code = op["code"]
        estimate = estimations.get(code, Estimate(0, ""))
        raw = request.operations.get(code)
        saisi = to_float(raw, None) if raw is not None else None
        manuel = saisi is not None and saisi >= 0
        nombre = float(saisi) if manuel else float(estimate.value)
        if nombre <= 0 or nb <= 0:
            continue
        unite = clean_text(op.get("unite")) or "opération"
        par_exemplaire = op.get("base") == "exemplaire"
        quantite = nombre * nb if par_exemplaire else nombre
        pu, source = operation_unit_cost(op, article, catalogue, params)
        if par_exemplaire:
            quantite_txt = (f"{fmt_qty(nombre, unite)} par {unit.singular} × {fmt_saisie(unit, nb)} "
                            f"= {fmt_qty(quantite, unite)}")
        else:
            quantite_txt = fmt_qty(quantite, unite)
        origine_txt = "nombre saisi" if manuel else "nombre estimé"
        note = ""
        machine = clean_text(op.get("machine"))
        if machine and article.uses_machine(machine):
            note = f" ; temps {catalogue.machine(machine).libelle.lower()} de la gamme non compté"
        lines.append(CostLine(
            poste=clean_text(op.get("poste")) or POSTE_AUTRES,
            code=code,
            libelle=clean_text(op.get("libelle")) or code,
            quantite=quantite,
            unite=unite,
            prix_unitaire=pu or 0.0,
            montant=quantite * (pu or 0.0),
            formule=f"{quantite_txt} ({origine_txt}) × {fmt_money(pu)} ({source}){note}",
            origine="saisie" if manuel else "estimation",
            prix_valide=bool(op.get("valide")),
            prix_manquant=pu is None,
        ))


def _add_packaging(lines: list[CostLine], request: PricingRequest, params: Parametres, alertes: list[str]) -> None:
    nombre = to_float(request.emballage_nombre, 0.0) or 0.0
    if nombre <= 0:
        return
    emballage = params.emballage(request.emballage)
    saisi = _price(request.emballage_cout_unitaire) if request.emballage_cout_unitaire is not None else None
    pu = saisi if saisi is not None else (_price(emballage.get("cout_unitaire")) if emballage else None)
    libelle = clean_text(emballage.get("libelle")) if emballage else "Emballage"
    if pu is None:
        alertes.append("Coût unitaire de l'emballage non renseigné : emballage compté à 0.")
    lines.append(CostLine(
        poste=POSTE_EMBALLAGE,
        code=request.emballage or "EMBALLAGE",
        libelle=libelle,
        quantite=nombre,
        unite="carton",
        prix_unitaire=pu or 0.0,
        montant=nombre * (pu or 0.0),
        formule=(f"{fmt_qty(nombre, 'carton')} × {fmt_money(pu)} "
                 f"({'coût saisi' if saisi is not None else 'coût paramétré'})"),
        origine="saisie" if saisi is not None else "paramètre",
        prix_valide=True if saisi is not None else bool(emballage and emballage.get("valide")),
        prix_manquant=pu is None,
    ))


def _add_transport(lines: list[CostLine], request: PricingRequest, params: Parametres, alertes: list[str]) -> None:
    if not request.livraison:
        return
    distance = to_float(request.distance_km, 0.0) or 0.0
    transport = params.transport(request.transport)
    if transport is None:
        alertes.append("Mode de transport non trouvé dans les paramètres : livraison non chiffrée.")
        return
    if distance <= 0:
        alertes.append("Livraison : distance aller non saisie, transport non chiffré.")
        return
    facturee = distance * 2
    cout_km = _price(transport.get("cout_km"))
    valide = bool(transport.get("valide"))
    libelle = clean_text(transport.get("libelle")) or transport["code"]
    lines.append(CostLine(
        poste=POSTE_TRANSPORT,
        code=transport["code"],
        libelle=f"Livraison, {libelle[:1].lower() + libelle[1:]}",
        quantite=facturee,
        unite="km",
        prix_unitaire=cout_km or 0.0,
        montant=facturee * (cout_km or 0.0),
        formule=(f"{fmt_smart(distance)} km aller × 2 = {fmt_smart(facturee)} km facturés "
                 f"× {fmt_money(cout_km)} le km"),
        origine="saisie",
        prix_valide=valide,
        prix_manquant=cout_km is None,
    ))
    fixes = _price(transport.get("frais_fixes")) or 0.0
    if fixes > 0:
        lines.append(CostLine(
            poste=POSTE_TRANSPORT,
            code=f"{transport['code']}_FIXE",
            libelle=f"Prise en charge, {libelle[:1].lower() + libelle[1:]}",
            quantite=1,
            unite="livraison",
            prix_unitaire=fixes,
            montant=fixes,
            formule="Forfait par livraison",
            origine="paramètre",
            prix_valide=valide,
        ))


def _add_ponctuels(lines: list[CostLine], request: PricingRequest, alertes: list[str]) -> None:
    for i, frais in enumerate(request.frais_ponctuels or [], start=1):
        montant = to_float((frais or {}).get("montant"), None)
        libelle = clean_text((frais or {}).get("libelle")) or f"Frais ponctuel {i}"
        if montant is None or montant == 0:
            continue
        if montant < 0:
            alertes.append(f"« {libelle} » : un montant négatif n'est pas admis dans un prix de revient, ligne ignorée.")
            continue
        lines.append(CostLine(
            poste=POSTE_AUTRES,
            code=f"PONCTUEL_{i}",
            libelle=libelle,
            quantite=1,
            unite="forfait",
            prix_unitaire=montant,
            montant=montant,
            formule="Montant saisi pour cette commande",
            origine="saisie",
        ))


def _add_frais(lines: list[CostLine], params: Parametres, unit: UnitSpec, nb: float) -> None:
    production = sum(line.montant for line in lines if is_production_poste(line.poste))
    avant_frais = sum(line.montant for line in lines)
    for frais in params.frais_actifs():
        valeur = _price(frais.get("valeur")) or 0.0
        mode = frais.get("mode")
        libelle = clean_text(frais.get("libelle")) or frais.get("code", "Frais")
        base_assiette = None
        if mode == "fixe":
            quantite, unite, pu, formule = 1.0, "commande", valeur, "Montant fixe par commande"
        elif mode == "par_exemplaire":
            quantite, unite, pu = nb, unit.singular, valeur
            formule = f"{fmt_saisie(unit, nb)} × {fmt_money(valeur)}"
        elif mode == "pourcentage":
            production_seule = frais.get("assiette", "production") == "production"
            base_assiette = "production" if production_seule else "hors_frais"
            assiette = production if production_seule else avant_frais
            quantite, unite, pu = assiette, UNITE_ASSIETTE, valeur / 100
            nom = "coût de production" if production_seule else "coût total avant frais"
            formule = f"{fmt_smart(valeur)} % du {nom} ({fmt_money(assiette)})"
        else:
            continue
        montant = quantite * pu
        if montant <= 0:
            continue
        lines.append(CostLine(
            poste=POSTE_AUTRES,
            code=clean_text(frais.get("code")) or "FRAIS",
            libelle=libelle,
            quantite=quantite,
            unite=unite,
            prix_unitaire=pu,
            montant=montant,
            formule=formule,
            origine="frais",
            prix_valide=bool(frais.get("valide")),
            assiette=base_assiette,
        ))
