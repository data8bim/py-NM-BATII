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
Filtres et tri en EN-TETE DE COLONNE, standard NM-BATII.

Reprend a l'identique l'ergonomie de la table de
08_Modifier > « Sélectionner / Épingler les éléments » : chaque en-tete porte
le libelle de la colonne surmontant trois petits boutons —

    [A-Z ↕]  trier (asc → desc → aucun) — retirable par `avec_tri=False`
    [▼]      filtrer par valeurs (liste a cocher, rouge si un filtre est actif)
    [X]      reinitialiser le filtre de cette colonne

Le dialogue de filtre (ColumnFilterDialog.xaml) propose « Contient » / « Ne
contient pas », Tout selectionner / deselectionner / Inverser, et Maj+Clic pour
cocher une plage.

Utilisation :

    from dialogs.filtres_colonnes import FiltresColonnes

    _fc = FiltresColonnes(lambda: mes_lignes, on_change=_rafraichir, owner=dlg)
    grille.Columns[0].Header = _fc.entete(u"Nom", u'nom')
    grille.Columns[1].Header = _fc.entete(u"Type", u'info')
    ...
    lignes_affichees = _fc.appliquer(mes_lignes)

Les « lignes » sont des tuples/objets dont les valeurs sont lues par
`lecteur(ligne, cle)` — par defaut un dict-like ou un objet a attributs.
"""

import os

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')

from pyrevit import forms

from System.Windows import (
    Thickness, GridLength, GridUnitType, HorizontalAlignment,
    VerticalAlignment, TextAlignment, TextWrapping, FontWeights, Visibility)
from System.Windows.Controls import (
    Grid, RowDefinition, TextBlock, Button, StackPanel, Orientation, CheckBox)
from System.Windows.Input import Keyboard, Key as WpfKey
from System.Windows.Media import Brushes


# ─── Utilitaires ─────────────────────────────────────────────────────────────
_ACCENTS = {
    u'é': u'e', u'è': u'e', u'ê': u'e', u'ë': u'e',
    u'à': u'a', u'â': u'a',
    u'î': u'i', u'ï': u'i',
    u'ô': u'o',
    u'û': u'u', u'ù': u'u', u'ü': u'u',
    u'ç': u'c',
}


def normaliser(s):
    u"""Minuscules, sans accents ni espaces de bord : base des comparaisons."""
    s = (s or u'').strip().lower()
    for accent, plain in _ACCENTS.items():
        s = s.replace(accent, plain)
    return s


def _echapper_acces(s):
    u"""
    Double les « _ » d'un texte affiche en Content d'un CheckBox : WPF
    (AccessText) traite un « _ » simple comme marqueur de touche d'acces — le
    caractere suivant est souligne et le « _ » disparait.
    """
    return (s or u'').replace(u'_', u'__')


# ─── Dialogue de filtre d'une colonne ────────────────────────────────────────
def show_column_filter_dialog(label, valeurs, autorisees, owner=None):
    u"""
    Liste a cocher des valeurs uniques d'une colonne.
    Retourne l'ensemble des valeurs cochees, ou None si annulation.
    """
    _xaml = os.path.join(os.path.dirname(__file__), 'ColumnFilterDialog.xaml')
    # set_owner=False : forms.WPFWindow fixe sinon l'owner Win32 natif sur la
    # fenetre de Revit, ce qui court-circuite l'owner WPF passe ici — la
    # fenetre masquee sous ce dialogue n'est alors repeinte qu'a l'action
    # suivante.
    dlg = forms.WPFWindow(_xaml, set_owner=False)
    dlg.Title = u"Filtrer — {}".format(label)
    if owner is not None:
        dlg.Owner = owner

    coches      = set(autorisees or [])
    checks      = []      # [(CheckBox, valeur)]
    dernier_idx = [-1]

    for valeur in valeurs:
        cb = CheckBox()
        cb.Content = _echapper_acces(valeur) if valeur else u'(vide)'
        cb.IsChecked = valeur in coches
        cb.Margin = Thickness(2, 2, 2, 2)

        def _mk(idx, val, checkbox):
            def on_click(s, e):
                _etat = bool(checkbox.IsChecked)
                _maj = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                        Keyboard.IsKeyDown(WpfKey.RightShift))
                if _maj and dernier_idx[0] >= 0:
                    lo, hi = min(dernier_idx[0], idx), max(dernier_idx[0], idx)
                    for j in range(lo, hi + 1):
                        cb_j, val_j = checks[j]
                        cb_j.IsChecked = _etat
                        if _etat:
                            coches.add(val_j)
                        else:
                            coches.discard(val_j)
                else:
                    if _etat:
                        coches.add(val)
                    else:
                        coches.discard(val)
                dernier_idx[0] = idx
            return on_click

        cb.Click += _mk(len(checks), valeur, cb)
        dlg.valuesPanel.Children.Add(cb)
        checks.append((cb, valeur))

    def _visible(cb):
        return cb.Visibility == Visibility.Visible

    def on_search_changed(s, e):
        contient = normaliser(dlg.txtSearch.Text)
        exclut   = normaliser(dlg.txtSearchExclude.Text)
        for cb, val in checks:
            texte = normaliser(cb.Content)
            montrer = ((not contient or contient in texte) and
                       (not exclut or exclut not in texte))
            cb.Visibility = Visibility.Visible if montrer else Visibility.Collapsed

    def on_all(s, e):
        for cb, val in checks:
            if _visible(cb):
                cb.IsChecked = True
                coches.add(val)

    def on_none(s, e):
        for cb, val in checks:
            if _visible(cb):
                cb.IsChecked = False
                coches.discard(val)

    def on_invert(s, e):
        for cb, val in checks:
            if not _visible(cb):
                continue
            _etat = not bool(cb.IsChecked)
            cb.IsChecked = _etat
            if _etat:
                coches.add(val)
            else:
                coches.discard(val)

    dlg.txtSearch.TextChanged        += on_search_changed
    dlg.txtSearchExclude.TextChanged += on_search_changed
    dlg.btnSelectAll.Click   += on_all
    dlg.btnDeselectAll.Click += on_none
    dlg.btnInvert.Click      += on_invert
    dlg.btnOk.Click          += lambda s, e: setattr(dlg, 'DialogResult', True)
    dlg.btnCancel.Click      += lambda s, e: setattr(dlg, 'DialogResult', False)

    if dlg.show_dialog():
        return coches
    return None


# ─── Gestionnaire tri + filtres pour un DataGrid ─────────────────────────────
class FiltresColonnes(object):
    u"""
    Tri et filtres par valeurs, poses sur les en-tetes d'un DataGrid.

    lignes_source : fonction sans argument retournant TOUTES les lignes (avant
                    filtrage). Rappelee a chaque ouverture d'un filtre, pour
                    que la liste des valeurs proposees suive la source.
    on_change     : fonction sans argument, appelee apres tout changement de
                    tri ou de filtre — c'est a l'appelant de reafficher.
    lecteur       : fonction (ligne, cle) -> valeur affichee. Par defaut,
                    ligne[cle] si indexable, sinon getattr(ligne, cle).
    owner         : fenetre proprietaire des dialogues de filtre.
    """

    def __init__(self, lignes_source, on_change, lecteur=None, owner=None):
        self._lignes_source = lignes_source
        self._on_change     = on_change
        self._owner         = owner
        self._lecteur       = lecteur or self._lecteur_defaut
        self.tri            = None    # (cle, 'asc'|'desc') ou None
        self.filtres        = {}      # cle -> set(valeurs gardees) | None
        self._entetes       = {}      # cle -> {'tri':Button, 'filtre':Button}
        self._separateurs   = {}      # cle -> separateur, colonnes MULTI-VALEURS

    # -- lecture d'une valeur ------------------------------------------------
    @staticmethod
    def _lecteur_defaut(ligne, cle):
        try:
            return ligne[cle]
        except Exception:
            return getattr(ligne, cle, u'')

    def valeur(self, ligne, cle):
        v = self._lecteur(ligne, cle)
        return u'' if v is None else v

    def valeurs(self, ligne, cle):
        u"""
        Les valeurs d'une cellule, TOUJOURS sous forme de liste.

        Une colonne declaree multi-valeurs (voir `separateur` dans entete())
        porte plusieurs valeurs dans une meme cellule : « Plan d'etage » ET
        « Vue 3D ». Le filtre doit alors proposer chaque valeur separement et
        garder la ligne des qu'UNE d'elles est cochee — sinon l'utilisateur ne
        pourrait filtrer que sur des combinaisons entieres, ce qui n'a aucun
        sens des que deux lignes ne portent pas exactement le meme jeu.

        Une cellule vide rend [u''] et non [] : elle reste ainsi filtrable,
        comme dans une colonne ordinaire.
        """
        _sep = self._separateurs.get(cle)
        _v = self.valeur(ligne, cle)
        if not _sep:
            return [_v]
        _parts = [p.strip() for p in unicode(_v).split(_sep)]
        _parts = [p for p in _parts if p]
        return _parts or [u'']

    # -- application ---------------------------------------------------------
    def _ligne_visible(self, ligne):
        for cle, gardees in self.filtres.items():
            if gardees is None:
                continue
            if self._separateurs.get(cle):
                # Multi-valeurs : la ligne passe des qu'UNE de ses valeurs est
                # gardee.
                if not any(v in gardees for v in self.valeurs(ligne, cle)):
                    return False
            elif self.valeur(ligne, cle) not in gardees:
                return False
        return True

    def ligne_visible(self, ligne):
        u"""
        True si la ligne passe tous les filtres de colonne.

        Public : une table dont l'ordre est impose (un DataView trie par code,
        par exemple) n'a que faire de `appliquer`, qui trie aussi — il lui faut
        seulement savoir montrer ou masquer chaque ligne.
        """
        return self._ligne_visible(ligne)

    def appliquer(self, lignes):
        u"""Retourne les lignes filtrees puis triees."""
        _res = [l for l in lignes if self._ligne_visible(l)]
        if self.tri:
            cle, sens = self.tri
            _res.sort(key=lambda l: normaliser(self.valeur(l, cle)),
                      reverse=(sens == 'desc'))
        return _res

    def actif(self):
        u"""True si au moins un filtre de colonne est pose."""
        return any(v is not None for v in self.filtres.values())

    def reinitialiser_tout(self):
        _change = False
        for cle in list(self.filtres.keys()):
            if self.filtres[cle] is not None:
                self.filtres[cle] = None
                self._maj_bouton_filtre(cle)
                _change = True
        if _change:
            self._on_change()

    # -- en-tetes ------------------------------------------------------------
    def _maj_boutons_tri(self):
        for cle, widgets in self._entetes.items():
            # Colonne posee avec avec_tri=False : pas de bouton a rafraichir.
            if widgets.get('tri') is None:
                continue
            if self.tri and self.tri[0] == cle:
                widgets['tri'].Content = u'A→Z' if self.tri[1] == 'asc' else u'Z→A'
            else:
                widgets['tri'].Content = u'A-Z ↕'

    def _maj_bouton_filtre(self, cle):
        widgets = self._entetes.get(cle)
        # Colonne non filtrable : pas de bouton ▼ a colorer.
        if not widgets or widgets.get('filtre') is None:
            return
        _actif = self.filtres.get(cle) is not None
        widgets['filtre'].Foreground = (Brushes.OrangeRed if _actif
                                        else Brushes.Black)

    def entete(self, label, cle, filtrable=True, avec_tri=True,
               infobulle=None, separateur=None):
        u"""
        Construit l'en-tete (libelle + boutons) a poser en Header.

        filtrable=False : seul le bouton de tri est pose. Pour une colonne dont
        les valeurs sont toutes distinctes (un nom, un identifiant), une liste
        a cocher n'aurait aucun interet — la recherche libre y repond mieux.

        avec_tri=False : pas de bouton de tri. Pour une table dont l'ordre PORTE
        du sens et ne doit pas se reorganiser — un referentiel hierarchique
        trie par code, ou le rang d'une ligne dit de qui elle depend.

        infobulle : texte de l'infobulle quand le libelle ne se suffit pas.
        Par defaut elle reprend le libelle, ce qui n'aide que si la colonne est
        trop etroite pour l'afficher en entier ; sur un en-tete ABREGE, repeter
        « Niv. » au survol de « Niv. » n'apprend rien. Y developper
        l'abreviation, ou dire ce que la colonne contient.

        separateur : declare la colonne MULTI-VALEURS. La cellule porte alors
        plusieurs valeurs collees par ce separateur ; le filtre les propose
        une par une et garde la ligne des qu'UNE est cochee. Sans lui (defaut),
        la cellule reste une valeur unique — comportement d'origine, inchange
        pour toutes les tables qui ne le passent pas.
        """
        if filtrable:
            self.filtres.setdefault(cle, None)
        if separateur:
            self._separateurs[cle] = separateur

        g = Grid()
        for _ in range(2):
            _r = RowDefinition()
            _r.Height = GridLength(1, GridUnitType.Auto)
            g.RowDefinitions.Add(_r)

        tb = TextBlock()
        tb.Text = label
        tb.TextWrapping = TextWrapping.Wrap
        tb.HorizontalAlignment = HorizontalAlignment.Center
        tb.TextAlignment = TextAlignment.Center
        tb.FontWeight = FontWeights.Bold
        tb.Margin = Thickness(0, 0, 0, 4)
        tb.ToolTip = infobulle or label
        Grid.SetRow(tb, 0)

        panneau = Grid()
        panneau.HorizontalAlignment = HorizontalAlignment.Center
        Grid.SetRow(panneau, 1)

        def _mk_bouton(contenu, infobulle, largeur=22, taille=10):
            b = Button()
            b.Content = contenu
            b.Width = largeur
            b.Height = 20
            b.Margin = Thickness(2, 0, 2, 0)
            b.Padding = Thickness(0)
            b.FontSize = taille
            b.HorizontalContentAlignment = HorizontalAlignment.Center
            b.VerticalContentAlignment = VerticalAlignment.Center
            b.ToolTip = infobulle
            return b

        btn_tri = None
        if avec_tri:
            btn_tri = _mk_bouton(u'A-Z ↕', u'Trier', largeur=34, taille=9)
        btn_filtre = btn_reset = None
        if filtrable:
            btn_filtre = _mk_bouton(u'▼', u'Filtrer')
            btn_reset  = _mk_bouton(
                u'X', u'Réinitialiser le filtre de cette colonne')

        ligne = StackPanel()
        ligne.Orientation = Orientation.Horizontal
        ligne.HorizontalAlignment = HorizontalAlignment.Center
        if avec_tri:
            ligne.Children.Add(btn_tri)
        if filtrable:
            ligne.Children.Add(btn_filtre)
            ligne.Children.Add(btn_reset)
        panneau.Children.Add(ligne)

        g.Children.Add(tb)
        g.Children.Add(panneau)

        def _on_tri(s, e):
            if self.tri == (cle, 'asc'):
                self.tri = (cle, 'desc')
            elif self.tri == (cle, 'desc'):
                self.tri = None
            else:
                self.tri = (cle, 'asc')
            self._maj_boutons_tri()
            self._on_change()

        def _on_filtre(s, e):
            # Union des valeurs et non ensemble des cellules : sur une colonne
            # multi-valeurs, c'est ce qui fait apparaitre « Plan d'etage » et
            # « Vue 3D » comme deux entrees plutot qu'une seule ligne
            # « Plan d'etage, Vue 3D » que personne ne saurait recomposer.
            _vus = set()
            for _l in self._lignes_source():
                _vus.update(self.valeurs(_l, cle))
            _valeurs = sorted(_vus, key=normaliser)
            _gardees = self.filtres.get(cle)
            if _gardees is None:
                # Aucun filtre pose : on ouvre tout decoche, l'utilisateur
                # coche les seules valeurs qu'il veut garder. Un filtre deja
                # actif, lui, se rouvre sur les valeurs gardees.
                _gardees = set()
            _res = show_column_filter_dialog(label, _valeurs, _gardees,
                                             owner=self._owner)
            if _res is not None:
                _tout = (_res == set(_valeurs))
                self.filtres[cle] = None if _tout else _res
                self._maj_bouton_filtre(cle)
                self._on_change()

        def _on_reset(s, e):
            if self.filtres.get(cle) is not None:
                self.filtres[cle] = None
                self._maj_bouton_filtre(cle)
                self._on_change()

        if avec_tri:
            btn_tri.Click += _on_tri
        if filtrable:
            btn_filtre.Click += _on_filtre
            btn_reset.Click  += _on_reset

        self._entetes[cle] = {'tri': btn_tri, 'filtre': btn_filtre,
                              'reset': btn_reset}
        return g
