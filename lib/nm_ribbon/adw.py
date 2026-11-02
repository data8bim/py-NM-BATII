# -*- coding: utf-8 -*-

# Copyright (C) 2026 data8bim (d8b)
#
# This file is part of py-NM-BATII.
#
# py-NM-BATII is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# py-NM-BATII is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with py-NM-BATII. If not, see <https://www.gnu.org/licenses/>.

"""
NM-BATII — Onglets ruban personnalises, couche Autodesk.Windows (AdWindows.dll)

AdWindows n'est pas une API officiellement documentee par Autodesk : elle
decrit le ruban WPF reellement affiche (Autodesk.Windows.ComponentManager),
alors que l'API Revit (DB/UI) ne permet ni de lire ni de deplacer des
RibbonPanel existants. C'est la seule voie pour reproduire le comportement
de "AG Custom Ribbon Tab Builder" sans dupliquer les boutons d'origine.

A retester a chaque nouvelle version majeure de Revit (cible actuelle :
2025 a 2027+, tous en .NET 8 — la forme de l'assembly peut changer avec le
runtime .NET d'une future version).

Principe : un RibbonPanel est DEPLACE (Remove de son onglet d'origine, Add
dans l'onglet personnalise), jamais clone — il ne peut de toute facon
appartenir qu'a une seule collection Panels a la fois (element WPF). C'est
ce qui le fait disparaitre de son onglet d'origine sans dupliquer ses
boutons.

Pour rester idempotent (reappliquable a volonte sans redemarrer Revit) sans
perdre la position d'origine des panneaux non repris, un inventaire figeant
l'etat "pristine" du ruban est capture au tout premier appel de la session
(_rafraichir_inventaire) et sert de reference a chaque reconstruction :
chaque appliquer() repart de cet inventaire, jamais de l'etat courant du
ruban (deja modifie par nos soins).
"""

import clr

# AdWindows.dll est deja chargee dans le process Revit (le ruban natif
# l'utilise) : la resolution par nom simple suffit, inutile de pointer vers
# un chemin sur disque.
clr.AddReference('AdWindows')
clr.AddReference('RevitAPIUI')

import Autodesk.Windows as AdWindows


# Prefixe des Id de RibbonTab crees par NM-BATII pour les onglets perso
# (un par profil). Sert a les reconnaitre pour les retirer avant
# reconstruction, et a les exclure de l'inventaire des onglets source.
PREFIXE_ID_PROFIL = u"NM_BATII_Custom_"

# Id du tab NM-BATII lui-meme (extension.json > tab.id). Exclu de
# l'inventaire : embarquer ses propres panneaux dans un onglet perso n'a
# pas de sens et risquerait une reentrance au rechargement pyRevit.
ID_ONGLET_NM_BATII = u"NM-BATII"


# Inventaire "pristine" du ruban, construit au premier appel de la session
# et jamais reconstruit ensuite pour un onglet deja connu (cf. docstring
# module). Forme :
#   { tab_id: {
#         "tab": RibbonTab,
#         "title": unicode,
#         "panels": { panel_id: {"panel": RibbonPanel, "title": unicode,
#                                 "ordre_origine": int} }
#     } }
_INVENTAIRE = {}

# Onglets source dont on a deja retire au moins un panneau lors du dernier
# appliquer() — donc pas dans leur etat d'origine. Permet de ne reconstruire
# (Panels.Clear + re-Add) QUE les onglets reellement concernes par NM-BATII,
# jamais un onglet natif jamais touche (ex. "Modifier") : le reconstruire a
# vide-pour-rien a produit en test un doublon visuel de l'onglet dans Revit —
# vraisemblablement un artefact du rendu AdWindows face a un Panels.Clear()
# suivi d'un re-Add() identique, inutile ici.
_TABS_TOUCHES = set()

# Onglets actuellement masques (IsVisible=False) par NM-BATII — pour ne
# reafficher que ceux-la, jamais toucher IsVisible d'un onglet qu'on n'a
# jamais masque soi-meme.
_TABS_MASQUES = set()


def _ruban():
    """Retourne le RibbonControl courant, ou None si le ruban n'est pas pret."""
    return AdWindows.ComponentManager.Ribbon


def _id_tab(tab):
    """Id non localise d'un RibbonTab, ou chaine vide si absent."""
    return tab.Id or u""


def _id_panel(panel):
    """
    Id non localise d'un RibbonPanel.

    RibbonPanel.Id peut etre vide pour certains panneaux (ressources XAML
    sans Id explicite) : on retombe alors sur Source.Title, seule valeur
    garantie non vide dans ce cas — au prix de la portee inter-langue.
    """
    source = panel.Source
    if source is None:
        return u""
    pid = getattr(source, "Id", None)
    if pid:
        return pid
    return source.Title or u""


def _est_onglet_perso(tid):
    return tid.startswith(PREFIXE_ID_PROFIL)


def _rafraichir_inventaire():
    """
    Complete _INVENTAIRE avec les onglets/panneaux pas encore connus.

    N'ecrase jamais une entree existante : un onglet deja inventorie a pu
    etre vide par appliquer() depuis, son contenu live n'est alors plus la
    reference. Un onglet apparu apres coup (add-in charge tardivement) est
    en revanche capture a son tour, panneaux dans leur ordre d'affichage
    courant.
    """
    ruban = _ruban()
    if ruban is None:
        return

    exclus = (ID_ONGLET_NM_BATII,)
    for tab in ruban.Tabs:
        if getattr(tab, "IsContextualTab", False):
            continue
        tid = _id_tab(tab)
        if not tid or tid in exclus or _est_onglet_perso(tid):
            continue
        if tid in _INVENTAIRE:
            continue

        panels = {}
        for idx, panel in enumerate(tab.Panels):
            pid = _id_panel(panel)
            if not pid:
                continue
            titre = panel.Source.Title if panel.Source else pid
            panels[pid] = {"panel": panel, "title": titre or pid, "ordre_origine": idx}

        _INVENTAIRE[tid] = {"tab": tab, "title": tab.Title or tid, "panels": panels}


def list_tabs():
    """
    Retourne les onglets source disponibles : [{"id": ..., "title": ...}, ...],
    tries par titre affiche.

    Base sur l'inventaire pristine : un onglet reste liste meme si tous ses
    panneaux sont actuellement dans un onglet perso (pour pouvoir les en
    retirer plus tard).
    """
    _rafraichir_inventaire()
    resultat = [{"id": tid, "title": e["title"]} for tid, e in _INVENTAIRE.items()]
    resultat.sort(key=lambda t: t["title"])
    return resultat


def list_panels(tab_id):
    """
    Retourne les panneaux d'origine d'un onglet source (ordre d'origine) :
    [{"id": ..., "title": ...}, ...].
    """
    _rafraichir_inventaire()
    entry = _INVENTAIRE.get(tab_id)
    if not entry:
        return []
    panels = sorted(entry["panels"].items(), key=lambda kv: kv[1]["ordre_origine"])
    return [{"id": pid, "title": p["title"]} for pid, p in panels]


def _vider_panels(tab):
    """Detache tous les RibbonPanel d'un RibbonTab (sans les detruire)."""
    while tab.Panels.Count > 0:
        tab.Panels.RemoveAt(0)


def _retirer_onglets_perso(ruban):
    """Retire et vide tous les onglets perso NM-BATII precedemment construits."""
    existants = [t for t in ruban.Tabs if _est_onglet_perso(_id_tab(t))]
    for tab in existants:
        _vider_panels(tab)  # libere les RibbonPanel avant de les reattribuer
        ruban.Tabs.Remove(tab)


def _remettre_un_onglet_a_son_etat_origine(entry):
    """Reconstruit UN onglet source avec tous ses panneaux, ordre d'origine."""
    tab = entry["tab"]
    _vider_panels(tab)
    panels = sorted(entry["panels"].items(), key=lambda kv: kv[1]["ordre_origine"])
    for _pid, p in panels:
        tab.Panels.Add(p["panel"])


def appliquer(config):
    """
    Applique une configuration complete (dict issu de nm_ribbon.config) :

      1. Ne reconstruit (Panels.Clear + re-Add) QUE les onglets source
         concernes — ceux qui l'etaient lors du dernier appliquer() (pour
         les remettre a plat s'ils ne le sont plus) et ceux requis par la
         config actuelle. Un onglet jamais touche par NM-BATII (ex. l'onglet
         natif "Modifier") n'est jamais manipule.
      2. Construit un RibbonTab par profil (dans l'ordre de config["profils"]),
         en DEPLACANT (pas copiant) les panneaux listes.
      3. Masque automatiquement tout onglet source devenu vide, et les
         onglets listes explicitement dans config["onglets_masques"]. Seuls
         les onglets qu'on a nous-memes masques sont reaffiches si retires
         de cette liste — IsVisible d'un onglet jamais masque par NM-BATII
         n'est jamais touche.

    Idempotent : peut etre appele a chaque modification de la config sans
    attendre un redemarrage de Revit (bouton "Enregistrer et appliquer"),
    et au demarrage via le hook Idling (startup.py).
    """
    ruban = _ruban()
    if ruban is None:
        # Ruban pas encore construit (trop tot dans le demarrage de Revit) :
        # rien a faire, l'appelant (startup.py) reessaiera au prochain Idling.
        return False

    _rafraichir_inventaire()
    _retirer_onglets_perso(ruban)

    requis = set()
    for profil in config.get(u"profils", []):
        for tab_id, _panel_id in profil.get(u"panneaux", []):
            requis.add(tab_id)

    for tab_id in (_TABS_TOUCHES | requis):
        entry = _INVENTAIRE.get(tab_id)
        if entry:
            _remettre_un_onglet_a_son_etat_origine(entry)

    for profil in config.get(u"profils", []):
        nouvel_onglet = AdWindows.RibbonTab()
        nouvel_onglet.Id = PREFIXE_ID_PROFIL + unicode(profil.get(u"id", u""))
        nouvel_onglet.Title = profil.get(u"nom_onglet") or u"Custom Tab"

        for tab_id, panel_id in profil.get(u"panneaux", []):
            entry = _INVENTAIRE.get(tab_id)
            if not entry:
                continue
            p = entry["panels"].get(panel_id)
            if not p:
                # Panneau disparu depuis l'enregistrement (add-in tiers
                # desinstalle, mise a jour...) : ignore silencieusement.
                continue
            entry["tab"].Panels.Remove(p["panel"])
            nouvel_onglet.Panels.Add(p["panel"])

        if nouvel_onglet.Panels.Count > 0:
            ruban.Tabs.Add(nouvel_onglet)

    _TABS_TOUCHES.clear()
    _TABS_TOUCHES.update(requis)

    # Onglets devenus vides (tous panneaux repris par un profil) : masques
    # automatiquement, inutile de les lister dans onglets_masques pour ca.
    masque_cible = set(
        tid for tid in requis
        if _INVENTAIRE.get(tid) and _INVENTAIRE[tid]["tab"].Panels.Count == 0
    )
    masque_cible.update(
        tid for tid in config.get(u"onglets_masques", []) if tid in _INVENTAIRE
    )

    for tab_id in (_TABS_MASQUES - masque_cible):
        entry = _INVENTAIRE.get(tab_id)
        if entry:
            entry["tab"].IsVisible = True
    for tab_id in masque_cible:
        entry = _INVENTAIRE.get(tab_id)
        if entry:
            entry["tab"].IsVisible = False

    _TABS_MASQUES.clear()
    _TABS_MASQUES.update(masque_cible)

    return True
