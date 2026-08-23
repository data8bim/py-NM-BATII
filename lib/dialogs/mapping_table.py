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
Tableau de mappages partagé par les scripts « MAPP_ » du panel 06_Donnees.

Présente les lignes de mappage (paramètre source -> paramètre cible, sur des
catégories d'objets) sous forme de tableau, sur le modèle du tableau
« NM-BATII — Sélection des vues à traiter »
(05_Pieces.panel/04_PIECES_Etiquettes.pulldown/01_PIECES_Etiquette-Masse) :

  - en-tête par colonne avec tri (A-Z / Z-A), filtre (▼) et réinitialisation (X)
  - barre d'outils : Tout sélectionner / Tout désélectionner / Inverser /
    Réinitialiser tous les filtres, et compteur de mappages actifs
  - colonne « Actif » : case à cocher activant ou désactivant le mappage
    (Maj+Clic pour cocher une plage de lignes)

Pourquoi un empilement de Border plutôt qu'un DataGrid : les cellules
contiennent des contrôles vivants (deux ComboBox filtrables, un bouton de
sélection de catégories, un bouton de suppression) construits ligne par ligne
côté Python. Un DataGrid régénère ses conteneurs à chaque re-filtrage, ce qui
reparente ces contrôles (« Specified element is already the logical child of
another element »). L'empilement Clear()/Add() de Border déjà utilisé par ces
scripts n'a pas ce défaut : on garde ce mécanisme et on lui donne l'apparence
et les fonctions d'un tableau.

La fenêtre hôte (XAML) doit exposer :
    headerHost          Border recevant la ligne d'en-tête
    mappingsPanel       StackPanel recevant les lignes
    btnSelectAll, btnDeselectAll, btnInvert, btnResetAllFilters
    txtCount            TextBlock du compteur
"""

import os

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import (
    Thickness, GridLength, GridUnitType, FontWeights, TextWrapping,
    TextAlignment, HorizontalAlignment, VerticalAlignment, Visibility,
    FrameworkElement, SystemParameters
)
from System.Windows.Controls import (
    Border, Button, CheckBox, ColumnDefinition, Grid, Orientation,
    RowDefinition, StackPanel, TextBlock
)
from System.Windows.Input import Keyboard, Key as WpfKey
from System.Windows.Media import Brushes

from pyrevit import forms


_FILTER_XAML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            u'MappingColumnFilterDialog.xaml')

# Valeurs de substitution affichées dans le dialogue de filtre.
VIDE = u'(vide)'
AUCUNE_CATEGORIE = u'(aucune catégorie)'

# Colonnes du tableau : (clé, largeur). La clé '*' signale une largeur
# proportionnelle. Ces définitions sont partagées par la ligne d'en-tête et par
# chaque ligne de mappage : c'est ce qui garantit leur alignement.
COLUMNS = [
    # 92 px : largeur minimale pour loger les trois boutons d'en-tete
    # (trier / filtrer / reinitialiser), comme la colonne a cocher du tableau
    # de reference.
    (u'actif',        92),
    (u'source_param', u'*'),
    (u'__arrow__',    30),
    (u'target_param', u'*'),
    (u'categories',   150),
    (u'__delete__',   32),
]

# Marge interne identique pour l'en-tête et pour les lignes (alignement).
CELL_PADDING = Thickness(6, 5, 6, 5)


# ─── Modèle de données ───────────────────────────────────────────────────────
class MappingRow(object):
    u"""Une ligne de mappage : paramètre source -> paramètre cible, sur une
    liste de catégories. « actif » (coché par défaut) permet de désactiver le
    mappage sans le supprimer : il reste affiché et enregistré, mais n'est pas
    appliqué."""

    def __init__(self, source=u'', target=u'', categories=None, actif=True):
        self.source_param = source
        self.target_param = target
        self.categories   = list(categories) if categories else []
        self.actif        = bool(actif)
        self.border       = None   # Border WPF de la ligne
        self.check_actif  = None   # CheckBox de la colonne « Actif »
        # Etat d'affichage seulement (jamais enregistre) : voir
        # MappingTableView.exempt_from_filters().
        self.exempt_filtre = False

    def est_vierge(self):
        u"""Ligne encore vide : ni source, ni cible, ni catégorie."""
        return not (self.source_param or self.target_param or self.categories)


# ─── Helpers ─────────────────────────────────────────────────────────────────
_ACCENTS = {
    u'é': u'e', u'è': u'e', u'ê': u'e', u'ë': u'e',
    u'à': u'a', u'â': u'a',
    u'î': u'i', u'ï': u'i',
    u'ô': u'o',
    u'û': u'u', u'ù': u'u', u'ü': u'u',
    u'ç': u'c',
}


def _normalize(s):
    s = (s or u'').strip().lower()
    for accent, plain in _ACCENTS.items():
        s = s.replace(accent, plain)
    return s


def _escape_access_text(s):
    u"""Échappe les « _ » d'une chaîne affichée en Content d'un CheckBox : WPF
    (AccessText) interprète un « _ » simple comme marqueur de touche d'accès
    (le caractère suivant est souligné et le « _ » disparaît). Doubler le « _ »
    restitue un underscore littéral."""
    return (s or u'').replace(u'_', u'__')


def _apply_style(element, key):
    u"""Applique un style partagé (dialogs_styles.xaml) sans échouer si les
    styles ne sont pas chargés."""
    try:
        element.SetResourceReference(FrameworkElement.StyleProperty, key)
    except Exception:
        pass


def add_column_definitions(grid):
    u"""Applique les colonnes du tableau à un Grid (en-tête comme lignes)."""
    for key, width in COLUMNS:
        cd = ColumnDefinition()
        if width == u'*':
            cd.Width = GridLength(1, GridUnitType.Star)
        else:
            cd.Width = GridLength(width)
        grid.ColumnDefinitions.Add(cd)
    return grid


def add_cell_separators(grid):
    u"""Ajoute les traits verticaux entre cellules (lignes de grille du
    tableau). Les marges négatives les font courir sur toute la hauteur de la
    ligne, par-dessus la marge interne du Border."""
    for i in range(len(COLUMNS) - 1):
        sep = Border()
        sep.Width               = 1
        sep.Background          = Brushes.Gainsboro
        sep.HorizontalAlignment = HorizontalAlignment.Right
        sep.VerticalAlignment   = VerticalAlignment.Stretch
        sep.Margin              = Thickness(0, -5, -3, -5)
        Grid.SetColumn(sep, i)
        grid.Children.Add(sep)


def style_row_border(border):
    u"""Donne à une ligne de mappage l'apparence d'une ligne de tableau :
    contiguë à la précédente, sans coins arrondis ni marge."""
    border.Margin              = Thickness(0)
    border.Padding             = CELL_PADDING
    border.BorderThickness     = Thickness(1, 0, 1, 1)
    border.BorderBrush         = Brushes.Gainsboro
    border.HorizontalAlignment = HorizontalAlignment.Stretch
    return border


# ─── Dialogue de filtre par colonne ──────────────────────────────────────────
def show_column_filter_dialog(label, all_values, current_allowed, owner=None):
    u"""Liste des valeurs uniques (triées) d'une colonne, à cocher (Maj+Clic
    pour une plage), pour filtrer le tableau. Retourne l'ensemble des valeurs
    retenues, ou None si l'utilisateur annule."""
    # set_owner=False : forms.WPFWindow fixe par défaut l'owner Win32 natif
    # directement sur la fenêtre de Revit (WindowInteropHelper), ce qui
    # court-circuite l'owner WPF ci-dessous. Résultat : Windows ne redemande
    # jamais le repaint de la fenêtre masquée sous ce dialogue à sa fermeture,
    # seulement celui de Revit — d'où un filtre qui ne s'affiche qu'à l'action
    # suivante.
    dlg = forms.WPFWindow(_FILTER_XAML, set_owner=False)
    dlg.Title = u"Filtrer — {}".format(label)
    if owner is not None:
        dlg.Owner = owner

    selected_set = set(current_allowed)
    checks = []
    last_idx = [-1]

    for idx, val in enumerate(all_values):
        cb = CheckBox()
        cb.Content   = _escape_access_text(val) if val else VIDE
        cb.IsChecked = val in selected_set
        cb.Margin    = Thickness(2, 2, 2, 2)

        def _mk(i, v, checkbox):
            def on_click(s, e):
                ns = bool(checkbox.IsChecked)
                shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                         Keyboard.IsKeyDown(WpfKey.RightShift))
                if shift and last_idx[0] >= 0:
                    lo, hi = min(last_idx[0], i), max(last_idx[0], i)
                    for j in range(lo, hi + 1):
                        cb_j, v_j = checks[j]
                        cb_j.IsChecked = ns
                        if ns: selected_set.add(v_j)
                        else:  selected_set.discard(v_j)
                else:
                    if ns: selected_set.add(v)
                    else:  selected_set.discard(v)
                last_idx[0] = i
            return on_click

        cb.Click += _mk(idx, val, cb)
        dlg.valuesPanel.Children.Add(cb)
        checks.append((cb, val))

    def _is_visible(cb):
        return cb.Visibility == Visibility.Visible

    def on_all(s, e):
        for cb, val in checks:
            if not _is_visible(cb):
                continue
            cb.IsChecked = True
            selected_set.add(val)

    def on_none(s, e):
        for cb, val in checks:
            if not _is_visible(cb):
                continue
            cb.IsChecked = False
            selected_set.discard(val)

    def on_invert(s, e):
        for cb, val in checks:
            if not _is_visible(cb):
                continue
            ns = not bool(cb.IsChecked)
            cb.IsChecked = ns
            if ns: selected_set.add(val)
            else:  selected_set.discard(val)

    def on_search_changed(s, e):
        query         = _normalize(dlg.txtSearch.Text)
        query_exclude = _normalize(dlg.txtSearchExclude.Text)
        for cb, val in checks:
            hay = _normalize(val if val else VIDE)
            show = ((not query or query in hay) and
                    (not query_exclude or query_exclude not in hay))
            cb.Visibility = Visibility.Visible if show else Visibility.Collapsed

    dlg.txtSearch.TextChanged        += on_search_changed
    dlg.txtSearchExclude.TextChanged += on_search_changed
    dlg.btnSelectAll.Click   += on_all
    dlg.btnDeselectAll.Click += on_none
    dlg.btnInvert.Click      += on_invert
    dlg.btnOk.Click          += lambda s, e: setattr(dlg, 'DialogResult', True)
    dlg.btnCancel.Click      += lambda s, e: setattr(dlg, 'DialogResult', False)

    if dlg.show_dialog():
        return selected_set
    return None


# ─── Tableau ─────────────────────────────────────────────────────────────────
class MappingTableView(object):
    u"""En-têtes de colonnes (tri / filtre / réinitialisation), barre d'outils
    et rendu des lignes de mappage.

    wpf              fenêtre hôte (voir en-tête du module pour les noms requis)
    rows             LISTE VIVANTE de MappingRow : le tableau la relit à chaque
                     apply_view(), les scripts continuent de la modifier
                     directement (ajout, suppression, chargement).
    label_*          libellés des colonnes, propres à chaque script.
    """

    def __init__(self, wpf, rows,
                 label_source=u'Paramètre source',
                 label_target=u'Paramètre cible',
                 label_categories=u'Catégories',
                 label_actif=u'Actif'):
        self.wpf   = wpf
        self.rows  = rows
        self.panel = wpf.mappingsPanel

        self._visible        = []
        self._last_idx       = -1
        self._filters        = {}     # clé -> set(valeurs autorisées) | None
        self._sort           = None   # (clé, 'asc' | 'desc') | None
        self._header_widgets = {}

        # (clé, libellé, triable/filtrable)
        self._columns = [
            (u'actif',        label_actif,      True),
            (u'source_param', label_source,     True),
            (u'__arrow__',    u'',              False),
            (u'target_param', label_target,     True),
            (u'categories',   label_categories, True),
            (u'__delete__',   u'',              False),
        ]

        self._build_header()
        self._wire_toolbar()

    # ── Valeurs d'une ligne, par colonne ─────────────────────────────────────
    def _row_values(self, row, key):
        u"""Valeurs d'une ligne pour une colonne. Une ligne peut porter
        plusieurs valeurs (colonne « Catégories ») : elle passe le filtre si
        l'une d'elles est retenue."""
        if key == u'actif':
            return [u'Actif' if row.actif else u'Inactif']
        if key == u'categories':
            return list(row.categories) if row.categories else [AUCUNE_CATEGORIE]
        val = getattr(row, key, u'') or u''
        return [val if val else VIDE]

    def _sort_key(self, row, key):
        if key == u'actif':
            return (0 if row.actif else 1, u'')
        if key == u'categories':
            return (len(row.categories),
                    u', '.join(sorted(row.categories)).lower())
        return (0, (getattr(row, key, u'') or u'').lower())

    def _row_visible(self, row):
        # Une ligne vierge porte les valeurs « (vide) » / « (aucune catégorie) »,
        # qui n'appartiennent a aucun filtre en cours : ajoutee alors qu'un
        # filtre est actif, elle serait invisible. Elle reste donc affichee,
        # ainsi qu'une ligne tout juste ajoutee que l'on est en train de
        # remplir (voir exempt_from_filters).
        if row.exempt_filtre or row.est_vierge():
            return True
        for key, allowed in self._filters.items():
            if allowed is None:
                continue
            values = self._row_values(row, key)
            if not [v for v in values if v in allowed]:
                return False
        return True

    # ── En-tête ──────────────────────────────────────────────────────────────
    def _mk_header_button(self, content, tooltip, width=22, font_size=10):
        b = Button()
        _apply_style(b, u'NMButtonStandard')
        b.Content = content
        b.Width   = width
        b.Height  = 20
        b.Margin  = Thickness(2, 0, 2, 0)
        b.Padding = Thickness(0)
        b.FontSize = font_size
        b.HorizontalContentAlignment = HorizontalAlignment.Center
        b.VerticalContentAlignment   = VerticalAlignment.Center
        b.ToolTip = tooltip
        return b

    def _make_header_cell(self, label, key, with_buttons):
        g = Grid()
        r1 = RowDefinition(); r1.Height = GridLength(1, GridUnitType.Auto)
        r2 = RowDefinition(); r2.Height = GridLength(1, GridUnitType.Auto)
        g.RowDefinitions.Add(r1)
        g.RowDefinitions.Add(r2)

        tb = TextBlock()
        tb.Text                = label
        tb.TextWrapping        = TextWrapping.Wrap
        tb.HorizontalAlignment = HorizontalAlignment.Center
        tb.TextAlignment       = TextAlignment.Center
        tb.FontWeight          = FontWeights.Bold
        tb.Margin              = Thickness(0, 0, 0, 4)
        Grid.SetRow(tb, 0)
        g.Children.Add(tb)

        if not with_buttons:
            return g

        btn_sort   = self._mk_header_button(u'A-Z ↕', u'Trier',
                                            width=34, font_size=9)
        btn_filter = self._mk_header_button(u'▼', u'Filtrer')
        btn_reset  = self._mk_header_button(
            u'X', u'Réinitialiser le filtre de cette colonne')

        row = StackPanel()
        row.Orientation        = Orientation.Horizontal
        row.HorizontalAlignment = HorizontalAlignment.Center
        row.Children.Add(btn_sort)
        row.Children.Add(btn_filter)
        row.Children.Add(btn_reset)
        Grid.SetRow(row, 1)
        g.Children.Add(row)

        btn_sort.Click   += self._mk_sort_handler(key)
        btn_filter.Click += self._mk_filter_handler(key, label)
        btn_reset.Click  += self._mk_reset_column_handler(key)

        self._header_widgets[key] = {'sort_btn': btn_sort,
                                     'filter_btn': btn_filter,
                                     'reset_btn': btn_reset}
        return g

    def _build_header(self):
        g = Grid()
        add_column_definitions(g)
        add_cell_separators(g)
        for i, (key, label, with_buttons) in enumerate(self._columns):
            cell = self._make_header_cell(label, key, with_buttons)
            Grid.SetColumn(cell, i)
            g.Children.Add(cell)
            if with_buttons:
                self._filters[key] = None
        # Les lignes sont dans un ScrollViewer à barre verticale toujours
        # visible : on réserve la même largeur à droite de l'en-tête, sinon les
        # colonnes de l'en-tête et celles des lignes ne coïncident pas.
        try:
            self.wpf.headerHost.Margin = Thickness(
                0, 0, SystemParameters.VerticalScrollBarWidth, 0)
        except Exception:
            pass

        self.wpf.headerHost.Child = g
        self._update_sort_buttons()

    # ── Tri / filtres ────────────────────────────────────────────────────────
    def _update_sort_buttons(self):
        cur = self._sort
        for key, widgets in self._header_widgets.items():
            if cur and cur[0] == key:
                widgets['sort_btn'].Content = (u'A→Z' if cur[1] == 'asc'
                                               else u'Z→A')
            else:
                widgets['sort_btn'].Content = u'A-Z ↕'

    def _update_filter_btn(self, key):
        widgets = self._header_widgets.get(key)
        if not widgets:
            return
        active = self._filters.get(key) is not None
        widgets['filter_btn'].Foreground = (Brushes.OrangeRed if active
                                            else Brushes.Black)

    def _mk_sort_handler(self, key):
        def handler(s, e):
            cur = self._sort
            if cur == (key, 'asc'):
                self._sort = (key, 'desc')
            elif cur == (key, 'desc'):
                self._sort = None
            else:
                self._sort = (key, 'asc')
            self._update_sort_buttons()
            self.apply_view()
        return handler

    def _mk_filter_handler(self, key, label):
        def handler(s, e):
            all_values = set()
            for r in self.rows:
                for v in self._row_values(r, key):
                    all_values.add(v)
            all_values = sorted(all_values)
            current_allowed = self._filters.get(key)
            if current_allowed is None:
                current_allowed = set(all_values)
            result = show_column_filter_dialog(label, all_values,
                                               current_allowed, owner=self.wpf)
            try:
                self.wpf.Activate()
            except Exception:
                pass
            if result is not None:
                is_all = (result == set(all_values))
                self._filters[key] = None if is_all else result
                self._update_filter_btn(key)
                self._clear_exemptions()
                self.apply_view()
        return handler

    def _mk_reset_column_handler(self, key):
        def handler(s, e):
            if self._filters.get(key) is not None:
                self._filters[key] = None
                self._update_filter_btn(key)
                self._clear_exemptions()
                self.apply_view()
        return handler

    def _on_reset_all_filters(self, s, e):
        changed = False
        for key in list(self._filters.keys()):
            if self._filters[key] is not None:
                self._filters[key] = None
                self._update_filter_btn(key)
                changed = True
        if changed:
            self._clear_exemptions()
            self.apply_view()

    # ── Barre d'outils ───────────────────────────────────────────────────────
    def _wire_toolbar(self):
        self.wpf.btnSelectAll.Click       += self._on_select_all
        self.wpf.btnDeselectAll.Click     += self._on_deselect_all
        self.wpf.btnInvert.Click          += self._on_invert
        self.wpf.btnResetAllFilters.Click += self._on_reset_all_filters

    def _set_actif(self, row, value):
        row.actif = bool(value)
        if row.check_actif is not None:
            row.check_actif.IsChecked = bool(value)
        if row.border is not None:
            row.border.Opacity = 1.0 if row.actif else 0.55

    def _after_actif_changed(self):
        self.update_count()
        # Un filtre sur la colonne « Actif » peut rendre la ligne invisible.
        if self._filters.get(u'actif') is not None:
            self.apply_view()

    def _on_select_all(self, s, e):
        for r in self._visible:
            self._set_actif(r, True)
        self._after_actif_changed()

    def _on_deselect_all(self, s, e):
        for r in self._visible:
            self._set_actif(r, False)
        self._after_actif_changed()

    def _on_invert(self, s, e):
        for r in self._visible:
            self._set_actif(r, not r.actif)
        self._after_actif_changed()

    # ── Colonne « Actif » ────────────────────────────────────────────────────
    def make_actif_cell(self, row_data):
        u"""CheckBox de la colonne « Actif » d'une ligne (colonne 0)."""
        cb = CheckBox()
        cb.IsChecked           = bool(row_data.actif)
        cb.HorizontalAlignment = HorizontalAlignment.Center
        cb.VerticalAlignment   = VerticalAlignment.Center
        cb.ToolTip = (u'Mappage actif : décocher pour le conserver sans '
                      u"l'appliquer (Maj+Clic : plage de lignes)")
        cb.Click += self._mk_actif_click(row_data, cb)
        row_data.check_actif = cb
        Grid.SetColumn(cb, 0)
        return cb

    def _mk_actif_click(self, row_data, checkbox):
        def on_click(s, e):
            ns = bool(checkbox.IsChecked)
            try:
                idx = self._visible.index(row_data)
            except ValueError:
                idx = -1
            shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                     Keyboard.IsKeyDown(WpfKey.RightShift))
            if shift and self._last_idx >= 0 and idx >= 0:
                lo, hi = min(self._last_idx, idx), max(self._last_idx, idx)
                for j in range(lo, hi + 1):
                    self._set_actif(self._visible[j], ns)
            else:
                self._set_actif(row_data, ns)
            if idx >= 0:
                self._last_idx = idx
            self._after_actif_changed()
        return on_click

    # ── Rendu ────────────────────────────────────────────────────────────────
    def visible_rows(self):
        return list(self._visible)

    def exempt_from_filters(self, row):
        u"""Affiche cette ligne quels que soient les filtres en cours, jusqu'à
        la prochaine modification d'un filtre. À appeler juste après avoir créé
        une ligne (« ＋ Ajouter un mappage ») : elle reste ainsi visible le
        temps d'être renseignée, alors qu'elle ne correspond encore à aucune
        valeur filtrée."""
        row.exempt_filtre = True

    def _clear_exemptions(self):
        u"""Fin du sursis : l'utilisateur reprend la main sur les filtres, les
        lignes redeviennent toutes soumises aux critères."""
        for r in self.rows:
            r.exempt_filtre = False

    def refresh_if_needed(self, key):
        u"""Reconstruit le tableau seulement si la colonne modifiée participe
        au filtre ou au tri courant : inutile de tout réafficher (et de
        remonter le défilement) sinon."""
        if (self._filters.get(key) is not None or
                (self._sort and self._sort[0] == key)):
            self.apply_view()

    def update_count(self):
        total = len(self.rows)
        n     = len([r for r in self.rows if r.actif])
        self.wpf.txtCount.Text = u'({} / {} mappage(s) actif(s))'.format(n, total)

    def apply_view(self):
        u"""Reconstruit le tableau selon les filtres et le tri actifs."""
        visible = [r for r in self.rows if self._row_visible(r)]
        if self._sort:
            key, direction = self._sort
            visible.sort(key=lambda r: self._sort_key(r, key),
                         reverse=(direction == 'desc'))
        self._visible  = visible
        self._last_idx = -1

        self.panel.Children.Clear()
        for i, r in enumerate(visible):
            if r.border is None:
                continue
            r.border.Background = (Brushes.White if i % 2 == 0
                                   else Brushes.WhiteSmoke)
            r.border.Opacity    = 1.0 if r.actif else 0.55
            self.panel.Children.Add(r.border)
        self.update_count()
