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
Liste deroulante a CASES A COCHER (standard NM-BATII).

Meme role que `combo_recherche.ComboCherchable`, mais pour un choix MULTIPLE :
la liste deroulee porte une case par valeur, la zone de saisie du ComboBox sert
de champ de recherche (comme partout ailleurs dans l'extension) et affiche, hors
frappe, le resume de ce qui est coche.

    from dialogs.combo_multi_cases import ComboMultiCases

    _cmb = ComboMultiCases(win.cmbPhases, texte_vide=u"(aucune phase)")
    _cmb.definir([(ph, nom_de(ph)) for ph in phases], coches=[phases[-1]])
    _cmb.valeurs()      # -> [cle, ...] dans l'ordre de definir()

Selection multiple a la souris, identique au dialogue de cases a cocher de
01_Parametres (_open_checklist_dialog) :

    Ctrl+Clic       ajoute / retire une ligne du surlignage
    Maj+Clic        surligne la plage depuis la derniere ligne cliquee
    Ctrl+Maj+Clic   ajoute cette plage au surlignage existant

Cocher une ligne surlignee applique son nouvel etat a TOUTE la selection.

TROIS POINTS QUI NE SE DEVINENT PAS :

1. L'etat coche vit sur l'objet ligne (INotifyPropertyChanged), jamais sur
   IsSelected d'un conteneur : la recherche remplace l'ItemsSource, ce qui
   detruirait toute selection portee par les conteneurs.
2. Le surlignage est calcule ici et rendu par un DataTrigger sur la ligne. Un
   ComboBox est mono-selection : il n'a pas de SelectedItems ou l'inscrire.
3. Le clic est traite au tunnel puis marque Handled. Sans cela le ComboBoxItem
   refermerait la liste des la premiere case cochee. C'est aussi pourquoi la
   case a cocher du gabarit est IsHitTestVisible="False" : si elle prenait le
   clic, elle capturerait la souris sans jamais recevoir le relachement.
"""

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

import System
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import (INotifyPropertyChanged,
                                   PropertyChangedEventArgs)
from System.Windows import UIElement
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Controls.Primitives import TextBoxBase
from System.Windows.Input import (Keyboard, Key as WpfKey,
                                  MouseButtonEventHandler)
from System.Windows.Markup import XamlReader
from System.Windows.Media import VisualTreeHelper

from dialogs.filtres_colonnes import normaliser


AIDE_SELECTION_MULTIPLE = (
    u"Tapez pour filtrer la liste.\n"
    u"Ctrl+Clic : ajoute ou retire une ligne du surlignage.\n"
    u"Maj+Clic : surligne toute la plage depuis la dernière ligne cliquée.\n"
    u"Ctrl+Maj+Clic : ajoute la plage au surlignage existant.\n"
    u"Cocher une ligne surlignée applique son état à toute la sélection.")


# Gabarits construits ici et non dans le XAML de chaque appelant : la mecanique
# de surlignage depend des proprietes de _Ligne, elle ne doit pas etre a
# recopier — ni a maintenir — dans chaque fenetre.
_XAML_GABARIT = u"""
<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
  <Border Padding="4,2" HorizontalAlignment="Stretch">
    <Border.Style>
      <Style TargetType="Border">
        <Setter Property="Background" Value="Transparent"/>
        <Style.Triggers>
          <DataTrigger Binding="{Binding surligne}" Value="True">
            <Setter Property="Background" Value="#CCE4F7"/>
          </DataTrigger>
        </Style.Triggers>
      </Style>
    </Border.Style>
    <CheckBox IsChecked="{Binding coche, Mode=OneWay}"
              IsHitTestVisible="False" Focusable="False"
              VerticalContentAlignment="Center">
      <TextBlock Text="{Binding libelle}" Margin="2,0,0,0"
                 TextWrapping="NoWrap"/>
    </CheckBox>
  </Border>
</DataTemplate>
"""

_XAML_CONTENEUR = u"""
<Style xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
       TargetType="ComboBoxItem">
  <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
  <Setter Property="Padding" Value="0"/>
</Style>
"""


class _Ligne(object, INotifyPropertyChanged):
    u"""
    Une valeur de la liste. `coche` et `surligne` notifient leurs changements :
    le cochage en masse et le surlignage modifient des lignes que la souris n'a
    pas touchees, rien d'autre ne rafraichirait leur affichage.
    """

    def __init__(self, cle, libelle, coche):
        self.cle      = cle
        self.libelle  = libelle
        self._coche   = bool(coche)
        self._surligne = False
        self._PropertyChanged = None

    def add_PropertyChanged(self, value):
        self._PropertyChanged = System.Delegate.Combine(
            self._PropertyChanged, value)

    def remove_PropertyChanged(self, value):
        self._PropertyChanged = System.Delegate.Remove(
            self._PropertyChanged, value)

    def _notifier(self, nom):
        if self._PropertyChanged is not None:
            self._PropertyChanged(self, PropertyChangedEventArgs(nom))

    def _get_coche(self):
        return self._coche

    def _set_coche(self, value):
        value = bool(value)
        if self._coche != value:
            self._coche = value
            self._notifier(u'coche')

    coche = property(_get_coche, _set_coche)

    def _get_surligne(self):
        return self._surligne

    def _set_surligne(self, value):
        value = bool(value)
        if self._surligne != value:
            self._surligne = value
            self._notifier(u'surligne')

    surligne = property(_get_surligne, _set_surligne)


class ComboMultiCases(object):
    u"""
    Enveloppe un ComboBox du XAML pour en faire une liste a cocher.

    combo      : le ComboBox, declare vide dans le XAML.
    on_change  : appele apres chaque changement de cochage.
    texte_vide : resume affiche quand rien n'est coche.
    resume     : fonction [libelles coches] -> texte affiche. Par defaut les
                 libelles colles par « , » — lisible tant que les valeurs sont
                 peu nombreuses (phases, disciplines...).
    """

    def __init__(self, combo, on_change=None,
                 texte_vide=u"(aucune sélection)", resume=None):
        self.combo       = combo
        self._on_change  = on_change
        self._texte_vide = texte_vide
        self._resume     = resume
        self._lignes     = []    # toutes les lignes, ordre de definir()
        self._visibles   = []    # sous-ensemble affiche (recherche)
        self._selection  = []    # lignes surlignees
        self._ancre      = [-1]  # indice d'ancrage des plages Maj+Clic
        self._interne    = False # garde de reentrance sur le texte

        combo.IsEditable          = True
        # Sans cela WPF completerait la frappe avec la 1re valeur qui commence
        # pareil : impossible de chercher un fragment situe au milieu.
        combo.IsTextSearchEnabled = False
        combo.StaysOpenOnEdit     = True
        combo.IsReadOnly          = False
        combo.ItemTemplate        = XamlReader.Parse(_XAML_GABARIT)
        combo.ItemContainerStyle  = XamlReader.Parse(_XAML_CONTENEUR)
        if combo.ToolTip is None:
            combo.ToolTip = AIDE_SELECTION_MULTIPLE

        combo.AddHandler(UIElement.PreviewMouseLeftButtonDownEvent,
                         MouseButtonEventHandler(self._avant_clic), True)
        combo.AddHandler(UIElement.PreviewMouseLeftButtonUpEvent,
                         MouseButtonEventHandler(self._sur_clic), True)
        # AddHandler sur l'evenement de la zone de saisie interne : le
        # TextChanged du ComboBox lui-meme n'est pas expose.
        combo.AddHandler(TextBoxBase.TextChangedEvent,
                         TextChangedEventHandler(self._on_texte))
        combo.DropDownClosed += self._on_fermeture

    # -- API ----------------------------------------------------------------
    def definir(self, items, coches=None):
        u"""
        Remplace la liste. `items` est une suite de (cle, libelle), ou de
        libelles seuls si la cle et le libelle se confondent. `coches` est la
        suite des cles cochees au depart.
        """
        _coches = list(coches or [])
        self._lignes = []
        for _it in items or []:
            if isinstance(_it, tuple) or isinstance(_it, list):
                _cle, _lbl = _it[0], _it[1]
            else:
                _cle, _lbl = _it, _it
            self._lignes.append(
                _Ligne(_cle, _lbl, any(_c is _cle or _c == _cle
                                       for _c in _coches)))
        self._afficher(self._lignes)
        self._maj_texte()

    def valeurs(self):
        u"""Cles cochees, dans l'ordre de definir()."""
        return [l.cle for l in self._lignes if l.coche]

    def libelles(self):
        u"""Libelles coches, dans l'ordre de definir()."""
        return [l.libelle for l in self._lignes if l.coche]

    def cocher(self, cles):
        u"""Coche exactement ces cles, decoche le reste."""
        _cles = list(cles or [])
        for _l in self._lignes:
            _l.coche = any(_c is _l.cle or _c == _l.cle for _c in _cles)
        self._maj_texte()

    def vide(self):
        return not self._lignes

    # -- affichage ----------------------------------------------------------
    def _afficher(self, lignes):
        u"""
        Pose la liste visible. Le surlignage et l'ancre sont des indices DANS
        cette liste : ils ne veulent plus rien dire des qu'elle change de
        forme, et sont donc remis a zero. Les cases cochees, elles, ne bougent
        pas — c'est tout l'interet de porter l'etat sur la ligne.
        """
        self._vider_selection()
        self._ancre[0] = -1
        self._visibles = list(lignes)
        _coll = ObservableCollection[object]()
        for _l in lignes:
            _coll.Add(_l)
        self._interne = True
        try:
            self.combo.ItemsSource = _coll
        finally:
            self._interne = False

    def _texte_resume(self):
        _lbls = self.libelles()
        if not _lbls:
            return self._texte_vide
        if self._resume is not None:
            return self._resume(_lbls)
        return u", ".join(_lbls)

    def _maj_texte(self):
        self._interne = True
        try:
            self.combo.Text = self._texte_resume()
        finally:
            self._interne = False

    # -- recherche ----------------------------------------------------------
    def _on_texte(self, sender, e):
        if self._interne:
            return
        _q = normaliser(self.combo.Text)
        # Le texte vaut le resume : c'est un retour d'affichage, pas une
        # recherche. Refiltrer ici viderait la liste au moindre clic.
        if _q == normaliser(self._texte_resume()):
            return
        _vis = [l for l in self._lignes if _q in normaliser(l.libelle)] \
            if _q else list(self._lignes)
        self._afficher(_vis)
        self._interne = True
        try:
            self.combo.IsDropDownOpen = True
        finally:
            self._interne = False

    def _on_fermeture(self, sender, e):
        u"""Refermer solde la recherche : le resume revient, la liste aussi."""
        if len(self._visibles) != len(self._lignes):
            self._afficher(self._lignes)
        self._maj_texte()

    # -- souris -------------------------------------------------------------
    def _ligne_depuis(self, el):
        u"""
        Remonte de l'element clique jusqu'a la ligne qu'il represente.

        PIEGE : avec AddHandler pose sur le ComboBox, `sender` est le COMBOBOX,
        pas la ligne cliquee — il faut partir de e.OriginalSource.
        """
        while el is not None:
            _dc = getattr(el, 'DataContext', None)
            if isinstance(_dc, _Ligne):
                return _dc
            _suivant = getattr(el, 'Parent', None)
            if _suivant is None:
                try:
                    _suivant = VisualTreeHelper.GetParent(el)
                except Exception:
                    _suivant = None
            el = _suivant
        return None

    def _vider_selection(self):
        for _l in self._selection:
            _l.surligne = False
        del self._selection[:]

    def _ajouter_selection(self, ligne):
        if ligne not in self._selection:
            self._selection.append(ligne)
            ligne.surligne = True

    def _avant_clic(self, sender, e):
        _row = self._ligne_depuis(e.OriginalSource)
        if _row is None or _row not in self._visibles:
            return
        _idx  = self._visibles.index(_row)
        _ctrl = (Keyboard.IsKeyDown(WpfKey.LeftCtrl) or
                 Keyboard.IsKeyDown(WpfKey.RightCtrl))
        _maj  = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                 Keyboard.IsKeyDown(WpfKey.RightShift))
        if _maj and self._ancre[0] >= 0:
            _lo = min(self._ancre[0], _idx)
            _hi = max(self._ancre[0], _idx)
            if not _ctrl:
                # Maj seul : la plage REMPLACE le surlignage.
                self._vider_selection()
            # Ctrl+Maj : la plage s'AJOUTE a ce qui est deja surligne.
            for _l in self._visibles[_lo:_hi + 1]:
                self._ajouter_selection(_l)
        elif _ctrl:
            if _row in self._selection:
                self._selection.remove(_row)
                _row.surligne = False
            else:
                self._ajouter_selection(_row)
            self._ancre[0] = _idx
        else:
            self._vider_selection()
            self._ajouter_selection(_row)
            self._ancre[0] = _idx

    def _sur_clic(self, sender, e):
        _row = self._ligne_depuis(e.OriginalSource)
        if _row is None or _row not in self._visibles:
            return
        _etat = not _row.coche
        # Toute la selection prend l'etat de la ligne cliquee — c'est le
        # cochage en masse. Hors selection multiple, la ligne cliquee seule.
        _cibles = (self._selection
                   if (_row in self._selection and len(self._selection) > 1)
                   else [_row])
        for _l in _cibles:
            _l.coche = _etat
        # Le resume ecraserait une recherche en cours dans la zone de saisie :
        # tant qu'un filtre est pose, il attend la fermeture de la liste.
        if len(self._visibles) == len(self._lignes):
            self._maj_texte()
        # Sans Handled, le ComboBoxItem refermerait la liste a chaque case.
        e.Handled = True
        if self._on_change is not None:
            self._on_change()
