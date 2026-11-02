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
NM-BATII — Onglets ruban personnalises, fenetre WPF

Garde la logique hors de script.py (cf. conventions du projet : script.py
reste l'entree mince, la logique vit dans lib/). ouvrir() construit la
fenetre a partir de WPFWindow.xaml, situe a cote du script.py appelant.

Plusieurs profils (= plusieurs onglets ruban personnalises) peuvent
coexister ; l'ordre de cfg["profils"] est l'ordre d'affichage des onglets
dans Revit, et l'ordre de panneaux[...] est l'ordre des panneaux dans
chaque onglet — pas de champ "ordre" separe a tenir synchronise, les
boutons Monter/Descendre deplacent directement les elements de liste.
"""

import os

from pyrevit import forms

from . import adw
from . import config as nm_config

try:
    from dialogs.dialogs_styles_loader import load as _charger_styles
    from dialogs.dialogs_styles_loader import show_alert as _show_alert
    from dialogs.dialogs_styles_loader import show_confirm as _show_confirm
except Exception:
    # Styles cosmetiques : l'ouverture de la fenetre ne doit pas en dependre
    # (meme tolerance que 02_Mises_a_jour, cf. son commentaire d'import).
    _charger_styles = None
    _show_alert = None
    _show_confirm = None


_SANS_SOURCE = u" (introuvable)"


def _alerte(titre, message):
    if _show_alert:
        _show_alert(titre, message)
    else:
        forms.alert(message)


def _confirmer(titre, message):
    if _show_confirm:
        return _show_confirm(titre, message)
    return forms.alert(message, ok=False, yes=True, no=True)


def ouvrir(xaml_path):
    """Ouvre la fenetre de configuration des onglets personnalises."""
    if _charger_styles:
        try:
            _charger_styles()
        except Exception:
            pass

    dlg = forms.WPFWindow(xaml_path)
    dlg.Title = u"NM-BATII — Onglet personnalisé"

    tabs_dispo = adw.list_tabs()
    index_titre_tab = dict((t["id"], t["title"]) for t in tabs_dispo)
    cache_panels = {}  # tab_id -> adw.list_panels(tab_id), memoise

    def _panneaux_du_tab(tab_id):
        if tab_id not in cache_panels:
            cache_panels[tab_id] = adw.list_panels(tab_id)
        return cache_panels[tab_id]

    def _titre_panel(tab_id, panel_id):
        for p in _panneaux_du_tab(tab_id):
            if p["id"] == panel_id:
                return p["title"]
        return panel_id + _SANS_SOURCE

    def _titre_tab(tab_id):
        return index_titre_tab.get(tab_id, tab_id + _SANS_SOURCE)

    # --- Etat ---------------------------------------------------------
    cfg = nm_config.charger()
    etat = {"cfg": cfg, "profil_idx": 0 if cfg["profils"] else -1}

    # --- Rafraichissements ---------------------------------------------

    def _profil_courant():
        idx = etat["profil_idx"]
        profils = etat["cfg"]["profils"]
        if 0 <= idx < len(profils):
            return profils[idx]
        return None

    def _ids_deja_utilises():
        """(tab_id, panel_id) deja affectes a un profil, tous confondus."""
        utilises = set()
        for p in etat["cfg"]["profils"]:
            for tab_id, panel_id in p["panneaux"]:
                utilises.add((tab_id, panel_id))
        return utilises

    def _rafraichir_profils(garder_selection=True):
        # Verrou anti-recursion : reassigner ItemsSource/SelectedIndex
        # declenche SelectionChanged, qui sans ce verrou reecrirait
        # txtNomOnglet.Text pendant que l'utilisateur est en train d'y taper
        # (cf. _on_nom_onglet_change) et deplacerait son curseur a chaque
        # frappe.
        etat["ignorer_selection_profil"] = True
        try:
            noms = [p["nom_onglet"] for p in etat["cfg"]["profils"]]
            dlg.lstProfils.ItemsSource = noms
            idx = etat["profil_idx"]
            if garder_selection and 0 <= idx < len(noms):
                dlg.lstProfils.SelectedIndex = idx
            elif noms:
                dlg.lstProfils.SelectedIndex = 0
            else:
                dlg.lstProfils.SelectedIndex = -1
        finally:
            etat["ignorer_selection_profil"] = False

    def _rafraichir_nom_onglet():
        profil = _profil_courant()
        dlg.txtNomOnglet.Text = profil["nom_onglet"] if profil else u""
        dlg.txtNomOnglet.IsEnabled = profil is not None

    def _rafraichir_transferes():
        profil = _profil_courant()
        if not profil:
            dlg.lstTransferes.ItemsSource = []
            return
        dlg.lstTransferes.ItemsSource = [
            u"{0} → {1}".format(_titre_tab(t), _titre_panel(t, p))
            for t, p in profil["panneaux"]
        ]

    def _rafraichir_panneaux_dispo():
        idx_tab = dlg.lstOngletsDispo.SelectedIndex
        if idx_tab < 0 or idx_tab >= len(tabs_dispo):
            dlg.lstPanneauxDispo.ItemsSource = []
            return
        tab_id = tabs_dispo[idx_tab]["id"]
        utilises = _ids_deja_utilises()
        panneaux = [p for p in _panneaux_du_tab(tab_id) if (tab_id, p["id"]) not in utilises]
        dlg.lstPanneauxDispo.ItemsSource = [p["title"] for p in panneaux]

    def _rafraichir_onglets_masques():
        dlg.lstOngletsMasques.ItemsSource = [
            _titre_tab(t) for t in etat["cfg"]["onglets_masques"]
        ]

    def _rafraichir_tout():
        _rafraichir_profils()
        _rafraichir_nom_onglet()
        _rafraichir_transferes()
        _rafraichir_panneaux_dispo()
        _rafraichir_onglets_masques()

    dlg.lstOngletsDispo.ItemsSource = [t["title"] for t in tabs_dispo]
    _rafraichir_tout()

    # --- Profils ---------------------------------------------------------

    def _on_select_profil(sender, args):
        if etat.get("ignorer_selection_profil"):
            return
        etat["profil_idx"] = dlg.lstProfils.SelectedIndex
        _rafraichir_nom_onglet()
        _rafraichir_transferes()
        _rafraichir_panneaux_dispo()

    def _on_nouveau_profil(sender, args):
        profil = {"id": nm_config.nouvel_id_profil(), "nom_onglet": u"Nouvel onglet",
                  "panneaux": []}
        etat["cfg"]["profils"].append(profil)
        etat["profil_idx"] = len(etat["cfg"]["profils"]) - 1
        _rafraichir_tout()

    def _on_supprimer_profil(sender, args):
        profil = _profil_courant()
        if not profil:
            return
        if not _confirmer(u"Supprimer l'onglet",
                           u"Supprimer l'onglet personnalisé « {0} » ?".format(profil["nom_onglet"])):
            return
        del etat["cfg"]["profils"][etat["profil_idx"]]
        if etat["profil_idx"] >= len(etat["cfg"]["profils"]):
            etat["profil_idx"] = len(etat["cfg"]["profils"]) - 1
        _rafraichir_tout()

    def _on_profil_deplacer(delta):
        profils = etat["cfg"]["profils"]
        idx = etat["profil_idx"]
        nouvel_idx = idx + delta
        if idx < 0 or not (0 <= nouvel_idx < len(profils)):
            return
        profils[idx], profils[nouvel_idx] = profils[nouvel_idx], profils[idx]
        etat["profil_idx"] = nouvel_idx
        _rafraichir_profils()

    def _on_profil_monter(sender, args):
        _on_profil_deplacer(-1)

    def _on_profil_descendre(sender, args):
        _on_profil_deplacer(1)

    def _on_nom_onglet_change(sender, args):
        profil = _profil_courant()
        if not profil:
            return
        profil["nom_onglet"] = dlg.txtNomOnglet.Text.strip() or u"Custom Tab"
        _rafraichir_profils()  # garde la liste des profils synchro avec le nom tape

    # --- Panneaux du profil courant --------------------------------------

    def _on_select_onglet_dispo(sender, args):
        _rafraichir_panneaux_dispo()

    def _on_ajouter_panneau(sender, args):
        profil = _profil_courant()
        if not profil:
            _alerte(u"Onglet personnalisé", u"Créez ou sélectionnez d'abord un onglet personnalisé.")
            return
        idx_tab = dlg.lstOngletsDispo.SelectedIndex
        if idx_tab < 0 or idx_tab >= len(tabs_dispo):
            return
        tab_id = tabs_dispo[idx_tab]["id"]
        titres_selectionnes = [unicode(s) for s in dlg.lstPanneauxDispo.SelectedItems]
        if not titres_selectionnes:
            return
        for p in _panneaux_du_tab(tab_id):
            if p["title"] in titres_selectionnes:
                profil["panneaux"].append([tab_id, p["id"]])
        _rafraichir_transferes()
        _rafraichir_panneaux_dispo()

    def _on_supprimer_panneau(sender, args):
        profil = _profil_courant()
        if not profil:
            return
        libelles_a_retirer = [unicode(s) for s in dlg.lstTransferes.SelectedItems]
        restants = []
        for t, p in profil["panneaux"]:
            lib = u"{0} → {1}".format(_titre_tab(t), _titre_panel(t, p))
            if lib in libelles_a_retirer:
                libelles_a_retirer.remove(lib)
                continue
            restants.append([t, p])
        profil["panneaux"] = restants
        _rafraichir_transferes()
        _rafraichir_panneaux_dispo()

    def _on_panneau_deplacer(delta):
        profil = _profil_courant()
        if not profil:
            return
        idx = dlg.lstTransferes.SelectedIndex
        nouvel_idx = idx + delta
        liste = profil["panneaux"]
        if idx < 0 or not (0 <= nouvel_idx < len(liste)):
            return
        liste[idx], liste[nouvel_idx] = liste[nouvel_idx], liste[idx]
        _rafraichir_transferes()
        dlg.lstTransferes.SelectedIndex = nouvel_idx

    def _on_panneau_monter(sender, args):
        _on_panneau_deplacer(-1)

    def _on_panneau_descendre(sender, args):
        _on_panneau_deplacer(1)

    # --- Onglets masques (manuel) -----------------------------------------

    def _on_masquer_onglet(sender, args):
        idx_tab = dlg.lstOngletsDispo.SelectedIndex
        if idx_tab < 0 or idx_tab >= len(tabs_dispo):
            return
        tab_id = tabs_dispo[idx_tab]["id"]
        if tab_id not in etat["cfg"]["onglets_masques"]:
            etat["cfg"]["onglets_masques"].append(tab_id)
            _rafraichir_onglets_masques()

    def _on_demasquer_onglet(sender, args):
        titres_a_retirer = [unicode(s) for s in dlg.lstOngletsMasques.SelectedItems]
        restants = []
        for tid in etat["cfg"]["onglets_masques"]:
            if _titre_tab(tid) in titres_a_retirer:
                titres_a_retirer.remove(_titre_tab(tid))
                continue
            restants.append(tid)
        etat["cfg"]["onglets_masques"] = restants
        _rafraichir_onglets_masques()

    # --- Pied de fenetre ---------------------------------------------------

    def _on_enregistrer(sender, args):
        ok = nm_config.enregistrer(etat["cfg"])
        adw.appliquer(etat["cfg"])
        msg = (u"Onglet(s) appliqué(s) immédiatement."
               if ok else
               u"Échec de l'écriture de la configuration — les onglets ont tout de "
               u"même été appliqués pour cette session Revit.")
        _alerte(u"Onglet personnalisé", msg)

    def _on_reinitialiser(sender, args):
        if not _confirmer(u"Réinitialiser",
                           u"Effacer tous les onglets personnalisés et les onglets masqués ?"):
            return
        etat["cfg"] = nm_config.reinitialiser()
        adw.appliquer(etat["cfg"])
        etat["profil_idx"] = -1
        _rafraichir_tout()

    def _on_exporter(sender, args):
        chemin = forms.save_file(file_ext=u"txt")
        if not chemin:
            return
        try:
            nm_config.exporter_txt(chemin, etat["cfg"])
            _alerte(u"Export", u"Configuration exportée :\n{0}".format(chemin))
        except Exception as e:
            forms.alert(u"Échec de l'export :\n{0}".format(str(e)))

    def _on_importer(sender, args):
        chemin = forms.pick_file(file_ext=u"txt")
        if not chemin:
            return
        try:
            etat["cfg"] = nm_config.importer_txt(chemin)
        except Exception as e:
            forms.alert(u"Échec de l'import :\n{0}".format(str(e)))
            return
        etat["profil_idx"] = 0 if etat["cfg"]["profils"] else -1
        _rafraichir_tout()

    def _on_fermer(sender, args):
        dlg.Close()

    # --- Cablage -------------------------------------------------------

    dlg.lstProfils.SelectionChanged += _on_select_profil
    dlg.btnNouveauProfil.Click += _on_nouveau_profil
    dlg.btnSupprimerProfil.Click += _on_supprimer_profil
    dlg.btnProfilMonter.Click += _on_profil_monter
    dlg.btnProfilDescendre.Click += _on_profil_descendre
    dlg.txtNomOnglet.TextChanged += _on_nom_onglet_change

    dlg.lstOngletsDispo.SelectionChanged += _on_select_onglet_dispo
    dlg.btnAjouterPanneau.Click += _on_ajouter_panneau
    dlg.btnSupprimerPanneau.Click += _on_supprimer_panneau
    dlg.btnPanneauMonter.Click += _on_panneau_monter
    dlg.btnPanneauDescendre.Click += _on_panneau_descendre

    dlg.btnMasquerOnglet.Click += _on_masquer_onglet
    dlg.btnDemasquerOnglet.Click += _on_demasquer_onglet

    dlg.btnEnregistrerAppliquer.Click += _on_enregistrer
    dlg.btnReinitialiser.Click += _on_reinitialiser
    dlg.btnExporter.Click += _on_exporter
    dlg.btnImporter.Click += _on_importer
    dlg.btnFermer.Click += _on_fermer

    dlg.show_dialog()
