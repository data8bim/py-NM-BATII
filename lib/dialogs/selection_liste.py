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
Selecteur generique d'un element dans une liste, au style NM-BATII.

Sert partout ou l'utilisateur doit designer un element du projet Revit par son
nom : gabarit de vue, type de vue, schema de surface. Une seule implementation
partagee — deux versions du meme rapprochement de nom finissent par se
contredire (cf. le gabarit de « Pièces 3D » qui divergeait de « Vues + »).

Utilisation :

    from dialogs.selection_liste import choisir_dans_liste

    nom = choisir_dans_liste(
        titre=u"Choisir un gabarit",
        description=u"...",
        entete_nom=u"Gabarit de vue",
        entete_info=u"Type de vue",
        items_tous=[(u"Mon gabarit", u"ThreeD"), ...],
        items_compat=None,          # ou une sous-liste filtree
        libelle_compat=u"",
        valeur_courante=u"")
    # -> nom choisi, ou None si l'utilisateur annule

La feuille de styles NM-BATII doit avoir ete chargee par le script appelant
(dialogs.dialogs_styles_loader.load()) : le pied de dialogue utilise les cles
NMButtonAppliquer / NMButtonAnnuler.
"""

import os

import clr
# System.Data n'est PAS charge par defaut dans le moteur IronPython de pyRevit :
# sans cette reference, `from System.Data import DataTable` echoue sur
# « No module named Data ». Le script appelant ne peut pas s'en charger — ce
# module doit etre autonome, il est importe depuis plusieurs bundles.
clr.AddReference('System.Data')
# Types System.Windows.* utilises plus bas (Visibility) : charges en pratique
# par pyrevit.forms, references ici explicitement pour ne pas en dependre.
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')

from pyrevit import forms

from dialogs.filtres_colonnes import FiltresColonnes, normaliser


def choisir_dans_liste(titre, description, entete_nom, entete_info,
                       items_tous, items_compat=None, libelle_compat=u"",
                       valeur_courante=u"", note=u""):
    """
    Ouvre le selecteur et retourne le nom choisi, ou None si annulation.

    items_tous   : liste [(nom, info)] — tout ce que le projet contient
    items_compat : sous-liste applicable au contexte, ou None si la notion n'a
                   pas de sens ici. La case « compatibles » est alors masquee.
    note         : avertissement affiche sous la description, ou '' pour rien.

    Trois moyens de reduire la liste, cumulables :
      - recherche libre sur la 1re colonne (insensible casse et accents) ;
      - tri sur les deux colonnes ;
      - filtre par valeurs sur la 2e colonne uniquement.
    Tri et filtres sont portes par les EN-TETES DE COLONNES, au standard
    NM-BATII (dialogs/filtres_colonnes.py) : meme ergonomie que la table de
    08_Modifier > « Sélectionner / Épingler les éléments ».
    « Réinitialiser tous les filtres » vide aussi le champ de recherche.

    Quand items_compat est fourni, la case peut TOUJOURS etre decochee : si la
    correspondance avec le type Revit se revelait fausse sur un cas,
    l'utilisateur ne serait pas bloque. Un filtre trop strict qui masque le bon
    element est pire qu'une liste trop longue.
    """
    from System.Data import DataTable
    from System.Windows import Visibility

    _xaml = os.path.join(os.path.dirname(__file__), 'SelectionListeDialog.xaml')
    _dlg = forms.WPFWindow(_xaml)
    _dlg.Title = titre
    _dlg.txtDescription.Text = (
        u"{}\n\n{}".format(note, description) if note else description)
    _dlg.dgElements.Columns[0].Header = entete_nom
    _dlg.dgElements.Columns[1].Header = entete_info
    _dlg.chkCompatibles.Content = libelle_compat
    if items_compat is None:
        _dlg.chkCompatibles.IsChecked  = False
        _dlg.chkCompatibles.IsEnabled  = False
        _dlg.chkCompatibles.Visibility = Visibility.Collapsed

    _dt = DataTable()
    _dt.Columns.Add('nom')
    _dt.Columns.Add('info')

    def _base_courante():
        u"""Lignes avant tri/filtres de colonnes : tient compte de la case
        « compatibles », qui est un filtre d'un autre ordre (contexte metier)."""
        return (items_compat
                if (items_compat is not None and _dlg.chkCompatibles.IsChecked)
                else items_tous)

    # (nom, info) est un tuple : le lecteur mappe les cles de colonne dessus.
    _CLES = {u'nom': 0, u'info': 1}

    def _apres_recherche():
        u"""Base restreinte par la recherche libre sur le nom."""
        _q = normaliser(_dlg.txtFiltre.Text)
        if not _q:
            return _base_courante()
        return [_it for _it in _base_courante()
                if _q in normaliser(_it[0])]

    def _remplir(sender=None, e=None):
        _dt.Rows.Clear()
        for _nom, _info in _filtres.appliquer(_apres_recherche()):
            _r = _dt.NewRow()
            _r['nom']  = _nom
            _r['info'] = _info
            _dt.Rows.Add(_r)
        # Preselectionner la valeur en cours, sinon la premiere ligne.
        _idx = 0
        for _i, _row in enumerate(_dt.Rows):
            if str(_row['nom']) == (valeur_courante or u''):
                _idx = _i
                break
        if _dt.Rows.Count:
            _dlg.dgElements.SelectedIndex = _idx
            _dlg.dgElements.ScrollIntoView(_dlg.dgElements.SelectedItem)

    # lignes_source = base AVANT recherche : la liste a cocher d'un filtre de
    # colonne doit proposer toutes les valeurs, pas seulement celles qui
    # survivent a la recherche en cours.
    _filtres = FiltresColonnes(
        lignes_source=_base_courante,
        on_change=_remplir,
        lecteur=lambda _ligne, _cle: _ligne[_CLES[_cle]],
        owner=_dlg)
    # 1re colonne : tri seul. Ses valeurs sont toutes distinctes (un nom), une
    # liste a cocher n'y aurait aucun interet — c'est le champ de recherche.
    _dlg.dgElements.Columns[0].Header = _filtres.entete(entete_nom,  u'nom',
                                                       filtrable=False)
    _dlg.dgElements.Columns[1].Header = _filtres.entete(entete_info, u'info')
    _dlg.lblFiltre.Text = u"{} :".format(entete_nom)

    def _reset_tout(s, e):
        # Vider le champ declenche TextChanged, donc _remplir ; reinitialiser
        # les filtres declenche on_change s'il y en avait. Si rien n'etait
        # pose, aucun des deux ne se declenche : il n'y a rien a rafraichir.
        _dlg.txtFiltre.Text = u''
        _filtres.reinitialiser_tout()

    _dlg.btnResetAllFilters.Click += _reset_tout

    _dlg.dgElements.ItemsSource = _dt.DefaultView
    _remplir()
    _dlg.txtFiltre.TextChanged    += _remplir
    _dlg.chkCompatibles.Checked   += _remplir
    _dlg.chkCompatibles.Unchecked += _remplir

    def _valider(s, e):
        setattr(_dlg, 'DialogResult', True)

    _dlg.dgElements.MouseDoubleClick += _valider
    _dlg.btnOK.Click     += _valider
    _dlg.btnCancel.Click += lambda s, e: setattr(_dlg, 'DialogResult', False)

    if not _dlg.show_dialog():
        return None
    _choix = _dlg.dgElements.SelectedItem
    if _choix is None:
        return None
    return str(_choix['nom'])
