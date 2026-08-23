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

u"""
Liste deroulante avec champ de recherche integre (standard NM-BATII).

Le ComboBox devient editable : la frappe filtre les valeurs proposees, sans
tenir compte de la casse ni des accents (meme `normaliser()` que les filtres de
colonnes). Vider le champ rend la liste complete.

    from dialogs.combo_recherche import ComboCherchable

    _cmb = ComboCherchable(win.cmbDiscipline, on_change=_maj_suite)
    _cmb.definir(items, selection=u"ARCHITECTURE")
    _cmb.valeur()        # -> valeur retenue, ou None

POURQUOI UNE CLASSE plutot que deux fonctions : l'etat (liste complete,
selection courante, garde de reentrance) doit survivre entre les evenements
WPF, et une cascade de menus reaffecte les ItemsSource en permanence. Sans cet
etat, filtrer reviendrait a perdre la liste d'origine des la premiere frappe.
"""

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')

from System.Windows.Controls import ComboBox, TextBox
from System.Windows.Controls.Primitives import TextBoxBase

from dialogs.filtres_colonnes import normaliser


class ComboCherchable(object):
    u"""
    Enveloppe un ComboBox existant pour y ajouter la recherche.

    combo     : le ComboBox du XAML
    on_change : appele quand la SELECTION change reellement (pas a chaque
                frappe) — c'est lui qui relance une cascade eventuelle.
    marqueur_vide : texte affiche quand la liste est vide ; `valeur()` rend
                alors None.
    """

    def __init__(self, combo, on_change=None, marqueur_vide=None):
        self.combo = combo
        self._on_change = on_change
        self._marqueur = marqueur_vide
        self._tous = []          # liste complete, avant recherche
        self._selection = None   # valeur retenue
        self._interne = False    # garde de reentrance

        combo.IsEditable = True
        # Sans cela WPF completerait la frappe avec la 1re valeur qui commence
        # pareil, ce qui empeche de chercher un fragment situe au milieu.
        combo.IsTextSearchEnabled = False
        combo.StaysOpenOnEdit = True
        combo.IsReadOnly = False

        combo.SelectionChanged += self._on_selection_changed
        # AddHandler sur l'evenement de la zone de saisie interne : le
        # TextChanged du ComboBox lui-meme n'est pas expose.
        combo.AddHandler(TextBoxBase.TextChangedEvent,
                         _handler_texte(self._on_texte))
        combo.DropDownOpened += self._on_ouverture

    # -- API ----------------------------------------------------------------
    def definir(self, items, selection=None):
        u"""
        Remplace la liste complete. `selection` est conservee si elle y figure,
        sinon la premiere valeur est retenue.
        """
        self._tous = list(items or [])
        if self._tous:
            _sel = selection if selection in self._tous else self._tous[0]
        else:
            _sel = None
        self._selection = _sel
        self._appliquer(self._tous, _sel)

    def valeur(self):
        u"""Valeur retenue, ou None si la liste est vide."""
        if self._selection is None or self._selection == self._marqueur:
            return None
        return self._selection

    def selectionner(self, valeur):
        u"""
        Retient `valeur` si elle figure dans la liste, et declenche on_change.
        Sans effet sinon. Retourne True si la selection a change.

        Sert au rappel d'un profil enregistre : il faut que la cascade se
        rejoue, contrairement a definir() qui pose une liste sans rien
        declencher.
        """
        if valeur is None or valeur not in self._tous:
            return False
        if valeur == self._selection:
            return False
        self._selection = valeur
        self._appliquer(self._tous, valeur)
        if self._on_change is not None:
            self._on_change()
        return True

    def vide(self):
        return not self._tous

    def items(self):
        u"""Liste complete actuelle (avant recherche)."""
        return list(self._tous)

    # -- interne ------------------------------------------------------------
    def _appliquer(self, visibles, selection):
        u"""Reaffecte les items sans declencher on_change."""
        self._interne = True
        try:
            _aff = list(visibles) if visibles else (
                [self._marqueur] if self._marqueur else [])
            self.combo.ItemsSource = _aff
            if selection is not None and selection in _aff:
                self.combo.SelectedItem = selection
            elif _aff:
                self.combo.SelectedIndex = 0
            self.combo.Text = (selection if selection is not None
                               else (_aff[0] if _aff else u''))
        finally:
            self._interne = False

    def _on_texte(self, sender, e):
        if self._interne:
            return
        _q = normaliser(self.combo.Text)
        # Le texte vaut la selection : c'est le retour d'un choix, pas une
        # recherche. Refiltrer ici viderait la liste au moindre clic.
        if self._selection is not None and _q == normaliser(self._selection):
            return
        _visibles = [v for v in self._tous if _q in normaliser(v)] if _q \
            else list(self._tous)
        self._interne = True
        try:
            self.combo.ItemsSource = _visibles
            self.combo.IsDropDownOpen = True
        finally:
            self._interne = False

    def _on_ouverture(self, sender, e):
        u"""Rouvrir sans avoir tape doit remontrer toute la liste."""
        if self._interne:
            return
        if self.combo.ItemsSource is not None and \
                len(list(self.combo.ItemsSource)) == len(self._tous):
            return
        if normaliser(self.combo.Text) == normaliser(self._selection or u''):
            self._interne = True
            try:
                self.combo.ItemsSource = list(self._tous)
                if self._selection in self._tous:
                    self.combo.SelectedItem = self._selection
            finally:
                self._interne = False

    def _on_selection_changed(self, sender, e):
        if self._interne:
            return
        _v = self.combo.SelectedItem
        if _v is None or _v == self._selection:
            return
        self._selection = _v
        # Recaler le texte sur la valeur choisie, sinon un reste de recherche
        # y subsisterait et _on_texte le relirait comme une nouvelle requete.
        self._interne = True
        try:
            self.combo.Text = _v
        finally:
            self._interne = False
        if self._on_change is not None:
            self._on_change()


def _handler_texte(fn):
    u"""RoutedEventHandler pour TextChangedEvent, en IronPython."""
    from System.Windows.Controls import TextChangedEventHandler
    return TextChangedEventHandler(fn)
