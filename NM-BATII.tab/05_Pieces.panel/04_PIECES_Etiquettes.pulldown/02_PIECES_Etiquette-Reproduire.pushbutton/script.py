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


#__title__ = 'Reproduire\nles étiquettes'
#__author__ = 'data8bim (d8b)'

import os
import System
from pyrevit import revit, DB, forms
from Autodesk.Revit.DB import Element
from System.Windows import (
    Thickness, GridLength, GridUnitType, FontWeights, TextWrapping,
    TextAlignment, HorizontalAlignment, VerticalAlignment, DataTemplate,
    FrameworkElementFactory, RoutedEventHandler, Visibility
)
from System.Windows.Controls import (
    CheckBox, Grid, ColumnDefinition, RowDefinition, TextBlock, Button,
    StackPanel, Orientation,
    DataGridTextColumn, DataGridTemplateColumn, DataGridLength
)
from System.Windows.Data import Binding, BindingMode
from System.Windows.Input import Keyboard, Key as WpfKey
from System.Windows.Media import Brushes
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Collections.ObjectModel import ObservableCollection
import System.Windows.Threading as Threading

from dialogs.dialogs_styles_loader import load as _load_styles, show_alert
_load_styles()

doc   = revit.doc
uidoc = revit.uidoc
view  = doc.ActiveView


# ─── Vues : collecte ────────────────────────────────────────────────────────
_PLAN_VIEW_TYPES = (
    DB.ViewType.FloorPlan,       # Plan d'étage
    DB.ViewType.CeilingPlan,     # Plan de faux-plafond
    DB.ViewType.EngineeringPlan, # Vue en plan
    DB.ViewType.AreaPlan,        # Plan de surface
)
_ELEVATION_SECTION_TYPES = (
    DB.ViewType.Section,    # Coupe
    DB.ViewType.Elevation,  # Élévation
)

# Colonnes à placer en tête de tableau (après la case à cocher et les
# colonnes fixes "Nom de la vue"/"Niveau associé"/"Echelle de la
# vue"/"Famille"/"Type", cf. _BIP_* ci-dessous), dans cet ordre, lorsque le
# paramètre correspondant existe sur les vues du projet.
_PINNED_COLUMN_ORDER = [
    u'Gabarit de vue',
    u'Référencement de la feuille',
    u'Référencement du détail',
    u'Titre sur la feuille',
]

# Colonnes fixes (toujours affichées, dans cet ordre, quelle que soit la
# langue de Revit) : résolues par BuiltInParameter plutôt que par nom de
# paramètre affiché (celui-ci est localisé et ne correspondrait plus sous un
# Revit en anglais).
def _safe_bip(attr_name):
    return getattr(DB.BuiltInParameter, attr_name, None)

_BIP_VIEW_NAME   = _safe_bip('VIEW_NAME')
_BIP_ASSOC_LEVEL = _safe_bip('PLAN_VIEW_LEVEL')
_BIP_VIEW_SCALE  = _safe_bip('VIEW_SCALE')
_BIP_FAMILY      = _safe_bip('ELEM_FAMILY_PARAM')
_BIP_TYPE        = _safe_bip('ELEM_TYPE_PARAM')


def _bip_label(bip, fallback):
    if bip is None:
        return fallback
    try:
        return DB.LabelUtils.GetLabelFor(bip) or fallback
    except Exception:
        return fallback


def _builtin_param_value_str(view, bip):
    if bip is None:
        return u''
    try:
        p = view.get_Parameter(bip)
    except Exception:
        p = None
    if p is None:
        return u''
    st = p.StorageType
    if st == DB.StorageType.String:
        return p.AsString() or u''
    elif st == DB.StorageType.Integer:
        return p.AsValueString() or str(p.AsInteger())
    elif st == DB.StorageType.Double:
        return p.AsValueString() or str(p.AsDouble())
    else:
        return p.AsValueString() or u''


def _view_family_and_type(view):
    """Famille/Type de la vue elle-même (ex. 'Plan d'étage' / '1:50 Bâti'),
    lus sur le ViewFamilyType plutôt que via LookupParameter : indépendant de
    la langue de Revit et toujours disponible (pas un paramètre standard)."""
    try:
        vft = doc.GetElement(view.GetTypeId())
    except Exception:
        vft = None
    if vft is None:
        return u'', u''
    try:
        family = vft.FamilyName or u''
    except Exception:
        family = u''
    try:
        type_name = Element.Name.__get__(vft) or u''
    except Exception:
        type_name = u''
    return family, type_name


def _fixed_columns_spec():
    """Libellé (localisé) + clé de binding des colonnes fixes, dans l'ordre
    Nom de la vue / Niveau associé / Echelle de la vue / Famille / Type."""
    return [
        (_bip_label(_BIP_VIEW_NAME, u'Nom de la vue'), u'ViewName'),
        (_bip_label(_BIP_ASSOC_LEVEL, u'Niveau associé'), u'AssociatedLevel'),
        (_bip_label(_BIP_VIEW_SCALE, u'Echelle de la vue'), u'ViewScale'),
        (_bip_label(_BIP_FAMILY, u'Famille'), u'Family'),
        (_bip_label(_BIP_TYPE, u'Type'), u'TypeName'),
    ]


def _fixed_column_labels():
    return set(label for label, key in _fixed_columns_spec())

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
    """Échappe les "_" d'une chaîne affichée en Content d'un CheckBox/Button :
    WPF (AccessText) interprète un "_" simple comme marqueur de touche
    d'accès (le caractère suivant est souligné et le "_" disparaît). Doubler
    le "_" restitue un underscore littéral."""
    return (s or u'').replace(u'_', u'__')


def order_column_names(names, pinned_order=None):
    """Place les colonnes de pinned_order (ou _PINNED_COLUMN_ORDER par défaut)
    en tête (si présentes parmi les paramètres découverts), puis les autres
    colonnes par ordre alphabétique."""
    if pinned_order is None:
        pinned_order = _PINNED_COLUMN_ORDER
    by_normalized = {}
    for name in names:
        by_normalized.setdefault(_normalize(name), name)
    pinned = []
    used = set()
    for target in pinned_order:
        actual = by_normalized.get(_normalize(target))
        if actual is not None and actual not in used:
            pinned.append(actual)
            used.add(actual)
    rest = [n for n in names if n not in used]
    return pinned + rest


def get_selectable_views():
    """Vues en plan, coupe et élévation (hors gabarits) du projet."""
    views = DB.FilteredElementCollector(doc).OfClass(DB.View).WhereElementIsNotElementType().ToElements()
    result = []
    for v in views:
        try:
            if v.IsTemplate:
                continue
            if v.ViewType in _PLAN_VIEW_TYPES or v.ViewType in _ELEVATION_SECTION_TYPES:
                result.append(v)
        except Exception:
            pass
    return result


def get_view_room_tags(v):
    return list(
        DB.FilteredElementCollector(doc, v.Id)
        .OfCategory(DB.BuiltInCategory.OST_RoomTags)
        .WhereElementIsNotElementType()
        .ToElements()
    )


def get_view_ids_with_room_tags():
    """Ids des vues contenant au moins une étiquette de pièce, calculés en un
    seul FilteredElementCollector projet (au lieu d'un collecteur par vue
    candidate, beaucoup trop lent sur les gros projets)."""
    all_tags = (
        DB.FilteredElementCollector(doc)
        .OfCategory(DB.BuiltInCategory.OST_RoomTags)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    ids = set()
    for t in all_tags:
        try:
            ids.add(t.OwnerViewId.IntegerValue)
        except Exception:
            pass
    return ids


def _param_value_str(elem, param_name):
    p = elem.LookupParameter(param_name)
    if p is None:
        return u''
    st = p.StorageType
    if st == DB.StorageType.String:
        return p.AsString() or u''
    elif st == DB.StorageType.Integer:
        return p.AsValueString() or str(p.AsInteger())
    elif st == DB.StorageType.Double:
        return p.AsValueString() or str(p.AsDouble())
    else:
        return p.AsValueString() or u''


def get_dynamic_param_names(views):
    """Union, en ordre alphabétique, de tous les noms de paramètres des vues
    (y compris les paramètres de projet)."""
    names = set()
    for v in views:
        try:
            for p in v.Parameters:
                try:
                    nm = p.Definition.Name
                    if not nm:
                        continue
                    names.add(nm)
                except Exception:
                    pass
        except Exception:
            pass
    return sorted(names)


def _matching_type_level_views(all_candidates, source_view):
    """Vues de même type et même niveau associé que source_view, à
    l'exclusion de source_view elle-même. Le filtre "même échelle" (option)
    est appliqué séparément, en direct, dans la boîte de dialogue de
    sélection des vues cibles."""
    src_level = _builtin_param_value_str(source_view, _BIP_ASSOC_LEVEL)
    result = []
    for v in all_candidates:
        if v.Id.IntegerValue == source_view.Id.IntegerValue:
            continue
        if v.ViewType != source_view.ViewType:
            continue
        if _builtin_param_value_str(v, _BIP_ASSOC_LEVEL) != src_level:
            continue
        result.append(v)
    return result


class _ViewRow(object, INotifyPropertyChanged):
    """Ligne du tableau de choix des vues. 'Selected' notifie ses changements
    (INotifyPropertyChanged) pour que la case à cocher reste synchrone avec le
    modèle lors des sélections en masse (Tout sélectionner, Maj+Clic...).
    'TargetsLabel' notifie de même le libellé du bouton "Vers vues" pour que
    celui-ci reste correct après regénération du conteneur (tri/filtre)."""

    def __init__(self, view):
        self.view = view
        self._selected = False
        self._targets = set()
        self._PropertyChanged = None
        self.ViewName = _builtin_param_value_str(view, _BIP_VIEW_NAME)
        self.AssociatedLevel = _builtin_param_value_str(view, _BIP_ASSOC_LEVEL)
        self.ViewScale = _builtin_param_value_str(view, _BIP_VIEW_SCALE)
        self.Family, self.TypeName = _view_family_and_type(view)

    def add_PropertyChanged(self, value):
        self._PropertyChanged = System.Delegate.Combine(self._PropertyChanged, value)

    def remove_PropertyChanged(self, value):
        self._PropertyChanged = System.Delegate.Remove(self._PropertyChanged, value)

    def _get_Selected(self):
        return self._selected

    def _set_Selected(self, value):
        if self._selected != value:
            self._selected = value
            if self._PropertyChanged is not None:
                self._PropertyChanged(self, PropertyChangedEventArgs(u'Selected'))

    Selected = property(_get_Selected, _set_Selected)

    def _get_SelectedLabel(self):
        return u'Sélectionné' if self._selected else u'Non sélectionné'

    SelectedLabel = property(_get_SelectedLabel)

    def get_targets(self):
        return self._targets

    def set_targets(self, ids):
        self._targets = set(ids)
        if self._PropertyChanged is not None:
            self._PropertyChanged(self, PropertyChangedEventArgs(u'TargetsLabel'))

    def _get_TargetsLabel(self):
        n = len(self._targets)
        return u"Sélectionner ({})".format(n) if n else u"Sélectionner"

    TargetsLabel = property(_get_TargetsLabel)


def build_view_rows(views, ordered_names):
    rows = []
    for v in views:
        row = _ViewRow(v)
        for i, name in enumerate(ordered_names):
            setattr(row, 'P{}'.format(i), _param_value_str(v, name))
        rows.append(row)
    return rows


def show_column_filter_dialog(label, all_values, current_allowed, owner=None):
    """Liste des valeurs uniques (triées) d'une colonne, à cocher (sélection
    multiple Maj+Clic supportée), avec recherche "Contient"/"Ne contient
    pas", pour filtrer le tableau de vues."""
    xaml_path = os.path.join(os.path.dirname(__file__), 'ColumnFilterDialog.xaml')
    # set_owner=False : forms.WPFWindow fixe par défaut l'owner Win32 natif
    # directement sur la fenêtre de Revit (WindowInteropHelper), ce qui
    # court-circuite l'owner WPF vers "wpf" ci-dessous. Résultat : Windows ne
    # redemande jamais le repaint de "wpf" (masquée sous ce dialogue) à la
    # fermeture, seulement celui de Revit — d'où le filtre qui ne s'affichait
    # qu'à l'action suivante.
    dlg = forms.WPFWindow(xaml_path, set_owner=False)
    dlg.Title = u"Filtrer — {}".format(label)
    if owner is not None:
        dlg.Owner = owner

    selected_set = set(current_allowed)
    checks = []
    last_idx = [-1]

    for idx, val in enumerate(all_values):
        cb = CheckBox()
        cb.Content = _escape_access_text(val) if val else u'(vide)'
        cb.IsChecked = val in selected_set
        cb.Margin = Thickness(2, 2, 2, 2)

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
        query = _normalize(dlg.txtSearch.Text)
        query_exclude = _normalize(dlg.txtSearchExclude.Text)
        for cb, val in checks:
            hay = _normalize(val if val else u'(vide)')
            show = (not query or query in hay) and (not query_exclude or query_exclude not in hay)
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


def show_target_views_picker_dialog(xaml_path, title, all_views, current_selected_ids,
                                     source_view, default_same_scale):
    """Tableur de choix des vues cibles : une colonne par paramètre de vue
    (paramètres usuels épinglés en tête, puis les autres par ordre
    alphabétique), avec filtres et tri par colonne, sélection multiple
    (Maj+Clic pour une plage). L'option "Même échelle" filtre en direct les
    vues affichées (même échelle que source_view)."""
    wpf = forms.WPFWindow(xaml_path)
    wpf.Title = title
    wpf.chkMemeEchelle.IsChecked = default_same_scale
    src_scale = _builtin_param_value_str(source_view, _BIP_VIEW_SCALE)

    raw_names = [n for n in get_dynamic_param_names(all_views) if n not in _fixed_column_labels()]
    ordered_names = order_column_names(raw_names)
    all_rows = build_view_rows(all_views, ordered_names)
    for r in all_rows:
        r.Selected = r.view.Id.IntegerValue in current_selected_ids

    last_idx = [-1]
    header_widgets = {}
    view_state = {'filters': {}, 'sort': None}
    visible_state = [list(all_rows)]

    def _row_visible(row_obj):
        if bool(wpf.chkMemeEchelle.IsChecked):
            if row_obj.ViewScale != src_scale:
                return False
        for key, allowed in view_state['filters'].items():
            if allowed is not None and getattr(row_obj, key, u'') not in allowed:
                return False
        return True

    def _visible_rows():
        return visible_state[0]

    def _update_count():
        n = sum(1 for r in all_rows if r.Selected)
        wpf.txtCount.Text = u"({} vue(s) sélectionnée(s))".format(n)

    def apply_filter():
        rows = [r for r in all_rows if _row_visible(r)]
        if view_state['sort']:
            skey, sdirection = view_state['sort']
            rows.sort(key=lambda r: (getattr(r, skey, u'') or u'').lower(),
                      reverse=(sdirection == 'desc'))
        visible_state[0] = rows
        new_coll = ObservableCollection[object]()
        for r in rows:
            new_coll.Add(r)
        wpf.dataGrid.ItemsSource = new_coll
        _update_count()

    def _update_sort_buttons():
        cur = view_state['sort']
        for key, widgets in header_widgets.items():
            if cur and cur[0] == key:
                widgets['sort_btn'].Content = u'A\u2192Z' if cur[1] == 'asc' else u'Z\u2192A'
            else:
                widgets['sort_btn'].Content = u'A-Z \u2195'

    def _update_filter_btn(key):
        active = view_state['filters'].get(key) is not None
        header_widgets[key]['filter_btn'].Foreground = Brushes.OrangeRed if active else Brushes.Black

    def _mk_sort_handler(key):
        def handler(s, e):
            cur = view_state['sort']
            if cur == (key, 'asc'):
                view_state['sort'] = (key, 'desc')
            elif cur == (key, 'desc'):
                view_state['sort'] = None
            else:
                view_state['sort'] = (key, 'asc')
            _update_sort_buttons()
            apply_filter()
        return handler

    def _mk_filter_handler(key, label):
        def handler(s, e):
            all_values = sorted(set(getattr(r, key) for r in all_rows))
            current_allowed = view_state['filters'].get(key)
            if current_allowed is None:
                current_allowed = set()
            result = show_column_filter_dialog(label, all_values, current_allowed, owner=wpf)
            wpf.Activate()
            if result is not None:
                is_all = (result == set(all_values))
                view_state['filters'][key] = None if is_all else result
                _update_filter_btn(key)
                apply_filter()
        return handler

    def _mk_reset_column_handler(key):
        def handler(s, e):
            if view_state['filters'].get(key) is not None:
                view_state['filters'][key] = None
                _update_filter_btn(key)
                apply_filter()
        return handler

    def _on_reset_all_filters(s, e):
        changed = False
        for key in view_state['filters'].keys():
            if view_state['filters'][key] is not None:
                view_state['filters'][key] = None
                _update_filter_btn(key)
                changed = True
        if changed:
            apply_filter()

    def _make_header(label, key):
        g = Grid()
        r1 = RowDefinition(); r1.Height = GridLength(1, GridUnitType.Auto)
        r2 = RowDefinition(); r2.Height = GridLength(1, GridUnitType.Auto)
        g.RowDefinitions.Add(r1)
        g.RowDefinitions.Add(r2)

        tb = TextBlock()
        tb.Text = label
        tb.TextWrapping = TextWrapping.Wrap
        tb.HorizontalAlignment = HorizontalAlignment.Center
        tb.TextAlignment = TextAlignment.Center
        tb.FontWeight = FontWeights.Bold
        tb.Margin = Thickness(0, 0, 0, 4)
        Grid.SetRow(tb, 0)

        buttons_panel = Grid()
        buttons_panel.HorizontalAlignment = HorizontalAlignment.Center
        Grid.SetRow(buttons_panel, 1)

        def _mk_header_button(content, tooltip, width=22, font_size=10):
            b = Button()
            b.Content = content
            b.Width = width; b.Height = 20
            b.Margin = Thickness(2, 0, 2, 0)
            b.Padding = Thickness(0)
            b.FontSize = font_size
            b.HorizontalContentAlignment = HorizontalAlignment.Center
            b.VerticalContentAlignment = VerticalAlignment.Center
            b.ToolTip = tooltip
            return b

        btn_sort = _mk_header_button(u'A-Z \u2195', u'Trier', width=34, font_size=9)
        btn_filter = _mk_header_button(u'\u25bc', u'Filtrer')
        btn_reset = _mk_header_button(u'X', u'Réinitialiser le filtre de cette colonne')

        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        row.HorizontalAlignment = HorizontalAlignment.Center
        row.Children.Add(btn_sort)
        row.Children.Add(btn_filter)
        row.Children.Add(btn_reset)
        buttons_panel.Children.Add(row)

        g.Children.Add(tb)
        g.Children.Add(buttons_panel)

        btn_sort.Click   += _mk_sort_handler(key)
        btn_filter.Click += _mk_filter_handler(key, label)
        btn_reset.Click  += _mk_reset_column_handler(key)

        header_widgets[key] = {'sort_btn': btn_sort, 'filter_btn': btn_filter, 'reset_btn': btn_reset}
        return g

    def _on_row_checkbox_click(sender, e):
        row_obj = sender.DataContext
        visible_rows = _visible_rows()
        if row_obj is None or row_obj not in visible_rows:
            return
        idx = visible_rows.index(row_obj)
        ns = bool(sender.IsChecked)
        shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                 Keyboard.IsKeyDown(WpfKey.RightShift))
        if shift and last_idx[0] >= 0:
            lo, hi = min(last_idx[0], idx), max(last_idx[0], idx)
            for j in range(lo, hi + 1):
                visible_rows[j].Selected = ns
        else:
            row_obj.Selected = ns
        last_idx[0] = idx
        _update_count()

    def _make_checkbox_column():
        col = DataGridTemplateColumn()
        col.Header = _make_header(u'Sélection', 'SelectedLabel')
        col.Width = DataGridLength(90)
        factory = FrameworkElementFactory(CheckBox)
        factory.SetValue(CheckBox.HorizontalAlignmentProperty, HorizontalAlignment.Center)
        binding = Binding('Selected')
        binding.Mode = BindingMode.TwoWay
        factory.SetBinding(CheckBox.IsCheckedProperty, binding)
        factory.AddHandler(CheckBox.ClickEvent, RoutedEventHandler(_on_row_checkbox_click))
        tmpl = DataTemplate()
        tmpl.VisualTree = factory
        col.CellTemplate = tmpl
        return col

    wpf.dataGrid.Columns.Add(_make_checkbox_column())
    view_state['filters']['SelectedLabel'] = None

    for label, key in _fixed_columns_spec():
        col = DataGridTextColumn()
        col.Header = _make_header(label, key)
        col.Binding = Binding(key)
        col.IsReadOnly = True
        col.Width = DataGridLength(160)
        wpf.dataGrid.Columns.Add(col)
        view_state['filters'][key] = None

    for i, name in enumerate(ordered_names):
        key = 'P{}'.format(i)
        col = DataGridTextColumn()
        col.Header = _make_header(name, key)
        col.Binding = Binding(key)
        col.IsReadOnly = True
        col.Width = DataGridLength(160)
        wpf.dataGrid.Columns.Add(col)
        view_state['filters'][key] = None

    apply_filter()

    def _on_select_all(s, e):
        for r in _visible_rows():
            r.Selected = True
        _update_count()

    def _on_deselect_all(s, e):
        for r in _visible_rows():
            r.Selected = False
        _update_count()

    def _on_invert(s, e):
        for r in _visible_rows():
            r.Selected = not r.Selected
        _update_count()

    wpf.btnSelectAll.Click     += _on_select_all
    wpf.btnDeselectAll.Click   += _on_deselect_all
    wpf.btnInvert.Click        += _on_invert
    wpf.btnResetAllFilters.Click += _on_reset_all_filters

    def _on_same_scale_changed(s, e):
        apply_filter()

    wpf.chkMemeEchelle.Checked   += _on_same_scale_changed
    wpf.chkMemeEchelle.Unchecked += _on_same_scale_changed

    dialog_result = {'ok': False}

    def _on_ok(s, e):
        dialog_result['ok'] = True
        wpf.Close()

    wpf.btnOk.Click     += _on_ok
    wpf.btnCancel.Click += lambda s, e: wpf.Close()

    frame = Threading.DispatcherFrame()
    wpf.Closed += lambda s, e: setattr(frame, 'Continue', False)
    wpf.Show()
    Threading.Dispatcher.PushFrame(frame)

    if not dialog_result['ok']:
        return None, bool(wpf.chkMemeEchelle.IsChecked)
    return set(r.view.Id.IntegerValue for r in all_rows if r.Selected), bool(wpf.chkMemeEchelle.IsChecked)


# ─── Interface ─────────────────────────────────────────────────────────────────
def main():
    all_selectable = get_selectable_views()
    tagged_view_ids = get_view_ids_with_room_tags()
    source_candidates = [v for v in all_selectable if v.Id.IntegerValue in tagged_view_ids]
    if not source_candidates:
        show_alert(
            u"Reproduire les étiquettes",
            u"Aucune vue du projet ne contient d'étiquette de pièce à reproduire."
        )
        return

    xaml_path = os.path.join(os.path.dirname(__file__), 'MainWindow.xaml')
    wpf = forms.WPFWindow(xaml_path)

    # "Nom de la vue"/"Niveau associé"/"Echelle de la vue" (+ Famille/Type)
    # sont couvertes par les colonnes fixes ajoutées avant "Vers vues" ;
    # aucune autre colonne n'est pinglée dans le tableau principal.
    raw_names = [n for n in get_dynamic_param_names(source_candidates) if n not in _fixed_column_labels()]
    ordered_names = order_column_names(raw_names, pinned_order=[])

    all_rows = build_view_rows(source_candidates, ordered_names)

    last_idx = [-1]
    header_widgets = {}
    view_state = {'filters': {}, 'sort': None}
    visible_state = [list(all_rows)]

    def _row_visible(row_obj):
        for key, allowed in view_state['filters'].items():
            if allowed is not None and getattr(row_obj, key, u'') not in allowed:
                return False
        return True

    def _visible_rows():
        return visible_state[0]

    def _update_count():
        n = sum(1 for r in all_rows if r.Selected)
        wpf.txtCount.Text = u"({} vue(s) sélectionnée(s) comme source)".format(n)

    def apply_filter():
        rows = [r for r in all_rows if _row_visible(r)]
        if view_state['sort']:
            skey, sdirection = view_state['sort']
            rows.sort(key=lambda r: (getattr(r, skey, u'') or u'').lower(),
                      reverse=(sdirection == 'desc'))
        visible_state[0] = rows
        new_coll = ObservableCollection[object]()
        for r in rows:
            new_coll.Add(r)
        wpf.dataGrid.ItemsSource = new_coll
        _update_count()

    def _update_sort_buttons():
        cur = view_state['sort']
        for key, widgets in header_widgets.items():
            if cur and cur[0] == key:
                widgets['sort_btn'].Content = u'A\u2192Z' if cur[1] == 'asc' else u'Z\u2192A'
            else:
                widgets['sort_btn'].Content = u'A-Z \u2195'

    def _update_filter_btn(key):
        active = view_state['filters'].get(key) is not None
        header_widgets[key]['filter_btn'].Foreground = Brushes.OrangeRed if active else Brushes.Black

    def _mk_sort_handler(key):
        def handler(s, e):
            cur = view_state['sort']
            if cur == (key, 'asc'):
                view_state['sort'] = (key, 'desc')
            elif cur == (key, 'desc'):
                view_state['sort'] = None
            else:
                view_state['sort'] = (key, 'asc')
            _update_sort_buttons()
            apply_filter()
        return handler

    def _mk_filter_handler(key, label):
        def handler(s, e):
            all_values = sorted(set(getattr(r, key) for r in all_rows))
            current_allowed = view_state['filters'].get(key)
            if current_allowed is None:
                current_allowed = set()
            result = show_column_filter_dialog(label, all_values, current_allowed, owner=wpf)
            wpf.Activate()
            if result is not None:
                is_all = (result == set(all_values))
                view_state['filters'][key] = None if is_all else result
                _update_filter_btn(key)
                apply_filter()
        return handler

    def _mk_reset_column_handler(key):
        def handler(s, e):
            if view_state['filters'].get(key) is not None:
                view_state['filters'][key] = None
                _update_filter_btn(key)
                apply_filter()
        return handler

    def _on_reset_all_filters(s, e):
        changed = False
        for key in view_state['filters'].keys():
            if view_state['filters'][key] is not None:
                view_state['filters'][key] = None
                _update_filter_btn(key)
                changed = True
        if changed:
            apply_filter()

    def _make_header(label, key):
        g = Grid()
        r1 = RowDefinition(); r1.Height = GridLength(1, GridUnitType.Auto)
        r2 = RowDefinition(); r2.Height = GridLength(1, GridUnitType.Auto)
        g.RowDefinitions.Add(r1)
        g.RowDefinitions.Add(r2)

        tb = TextBlock()
        tb.Text = label
        tb.TextWrapping = TextWrapping.Wrap
        tb.HorizontalAlignment = HorizontalAlignment.Center
        tb.TextAlignment = TextAlignment.Center
        tb.FontWeight = FontWeights.Bold
        tb.Margin = Thickness(0, 0, 0, 4)
        Grid.SetRow(tb, 0)

        buttons_panel = Grid()
        buttons_panel.HorizontalAlignment = HorizontalAlignment.Center
        Grid.SetRow(buttons_panel, 1)

        def _mk_header_button(content, tooltip, width=22, font_size=10):
            b = Button()
            b.Content = content
            b.Width = width; b.Height = 20
            b.Margin = Thickness(2, 0, 2, 0)
            b.Padding = Thickness(0)
            b.FontSize = font_size
            b.HorizontalContentAlignment = HorizontalAlignment.Center
            b.VerticalContentAlignment = VerticalAlignment.Center
            b.ToolTip = tooltip
            return b

        btn_sort = _mk_header_button(u'A-Z \u2195', u'Trier', width=34, font_size=9)
        btn_filter = _mk_header_button(u'\u25bc', u'Filtrer')
        btn_reset = _mk_header_button(u'X', u'Réinitialiser le filtre de cette colonne')

        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        row.HorizontalAlignment = HorizontalAlignment.Center
        row.Children.Add(btn_sort)
        row.Children.Add(btn_filter)
        row.Children.Add(btn_reset)
        buttons_panel.Children.Add(row)

        g.Children.Add(tb)
        g.Children.Add(buttons_panel)

        btn_sort.Click   += _mk_sort_handler(key)
        btn_filter.Click += _mk_filter_handler(key, label)
        btn_reset.Click  += _mk_reset_column_handler(key)

        header_widgets[key] = {'sort_btn': btn_sort, 'filter_btn': btn_filter, 'reset_btn': btn_reset}
        return g

    def _on_row_checkbox_click(sender, e):
        row_obj = sender.DataContext
        visible_rows = _visible_rows()
        if row_obj is None or row_obj not in visible_rows:
            return
        idx = visible_rows.index(row_obj)
        ns = bool(sender.IsChecked)
        shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                 Keyboard.IsKeyDown(WpfKey.RightShift))
        if shift and last_idx[0] >= 0:
            lo, hi = min(last_idx[0], idx), max(last_idx[0], idx)
            for j in range(lo, hi + 1):
                visible_rows[j].Selected = ns
        else:
            row_obj.Selected = ns
        last_idx[0] = idx
        _update_count()

    def _make_checkbox_column():
        col = DataGridTemplateColumn()
        col.Header = _make_header(u'Sélection', 'SelectedLabel')
        col.Width = DataGridLength(90)
        factory = FrameworkElementFactory(CheckBox)
        factory.SetValue(CheckBox.HorizontalAlignmentProperty, HorizontalAlignment.Center)
        binding = Binding('Selected')
        binding.Mode = BindingMode.TwoWay
        factory.SetBinding(CheckBox.IsCheckedProperty, binding)
        factory.AddHandler(CheckBox.ClickEvent, RoutedEventHandler(_on_row_checkbox_click))
        tmpl = DataTemplate()
        tmpl.VisualTree = factory
        col.CellTemplate = tmpl
        return col

    def _on_targets_button_click(sender, e):
        row_obj = sender.DataContext
        if row_obj is None:
            return
        candidates = _matching_type_level_views(all_selectable, row_obj.view)
        if not candidates:
            show_alert(u"Reproduire les étiquettes",
                       u"Aucune vue cible correspondante (même type, même niveau).")
            return
        src_name = row_obj.ViewName
        title = u"NM-BATII — Sélection des vues cibles pour « {} »".format(src_name)
        target_xaml = os.path.join(os.path.dirname(__file__), 'TargetViewsPickerDialog.xaml')
        result, _ = show_target_views_picker_dialog(
            target_xaml, title, candidates, row_obj.get_targets(),
            row_obj.view, True
        )
        wpf.Activate()
        if result is not None:
            row_obj.set_targets(result)

    def _make_targets_column():
        col = DataGridTemplateColumn()
        col.Header = _make_header(u'Vers vues', 'TargetsLabel')
        col.Width = DataGridLength(150)
        factory = FrameworkElementFactory(Button)
        binding = Binding('TargetsLabel')
        factory.SetBinding(Button.ContentProperty, binding)
        factory.SetValue(Button.PaddingProperty, Thickness(6, 2, 6, 2))
        factory.SetValue(Button.MarginProperty, Thickness(2))
        factory.AddHandler(Button.ClickEvent, RoutedEventHandler(_on_targets_button_click))
        tmpl = DataTemplate()
        tmpl.VisualTree = factory
        col.CellTemplate = tmpl
        return col

    wpf.dataGrid.Columns.Add(_make_checkbox_column())
    view_state['filters']['SelectedLabel'] = None

    # "Vers vues" est placée juste après "Nom de la vue" et figée avec elle
    # (cf. FrozenColumnCount="3" dans MainWindow.xaml : Sélection, Nom de la
    # vue, Vers vues).
    _fixed_spec = _fixed_columns_spec()
    _view_name_col = _fixed_spec[0]
    _other_fixed_cols = _fixed_spec[1:]

    for label, key in [_view_name_col]:
        col = DataGridTextColumn()
        col.Header = _make_header(label, key)
        col.Binding = Binding(key)
        col.IsReadOnly = True
        col.Width = DataGridLength(160)
        wpf.dataGrid.Columns.Add(col)
        view_state['filters'][key] = None

    wpf.dataGrid.Columns.Add(_make_targets_column())
    view_state['filters']['TargetsLabel'] = None

    for label, key in _other_fixed_cols:
        col = DataGridTextColumn()
        col.Header = _make_header(label, key)
        col.Binding = Binding(key)
        col.IsReadOnly = True
        col.Width = DataGridLength(160)
        wpf.dataGrid.Columns.Add(col)
        view_state['filters'][key] = None

    for i, name in enumerate(ordered_names):
        key = 'P{}'.format(i)
        col = DataGridTextColumn()
        col.Header = _make_header(name, key)
        col.Binding = Binding(key)
        col.IsReadOnly = True
        col.Width = DataGridLength(160)
        wpf.dataGrid.Columns.Add(col)
        view_state['filters'][key] = None

    apply_filter()

    def _on_select_all(s, e):
        for r in _visible_rows():
            r.Selected = True
        _update_count()

    def _on_deselect_all(s, e):
        for r in _visible_rows():
            r.Selected = False
        _update_count()

    def _on_invert(s, e):
        for r in _visible_rows():
            r.Selected = not r.Selected
        _update_count()

    wpf.btnSelectAll.Click     += _on_select_all
    wpf.btnDeselectAll.Click   += _on_deselect_all
    wpf.btnInvert.Click        += _on_invert
    wpf.btnResetAllFilters.Click += _on_reset_all_filters

    dialog_result = {'ok': False}

    def _on_ok(s, e):
        selected_rows = [r for r in all_rows if r.Selected]
        if not selected_rows:
            show_alert(u"Reproduire les étiquettes",
                       u"Sélectionnez au moins une vue source (case à cocher).")
            return
        missing = [r for r in selected_rows if not r.get_targets()]
        if missing:
            names = u", ".join(r.ViewName for r in missing)
            show_alert(u"Reproduire les étiquettes",
                       u"Aucune vue cible choisie pour : {}.\n"
                       u"Cliquez sur \"Sélectionner\" (colonne \"Vers vues\")."
                       .format(names))
            return
        dialog_result['ok'] = True
        wpf.Close()

    wpf.btnOK.Click     += _on_ok
    wpf.btnCancel.Click += lambda s, e: wpf.Close()

    frame = Threading.DispatcherFrame()
    wpf.Closed += lambda s, e: setattr(frame, 'Continue', False)
    wpf.Show()
    Threading.Dispatcher.PushFrame(frame)

    if not dialog_result['ok']:
        return

    n_ok = 0
    n_skip = 0
    with revit.Transaction(u"Reproduire les étiquettes de pièces entre vues"):
        for row in all_rows:
            if not row.Selected:
                continue
            target_ids = row.get_targets()
            if not target_ids:
                continue
            source_tags = get_view_room_tags(row.view)
            for target_id in target_ids:
                target_view = doc.GetElement(DB.ElementId(target_id))
                if target_view is None:
                    continue
                existing_room_ids = set()
                for t in get_view_room_tags(target_view):
                    try:
                        r = t.Room
                        if r is not None:
                            existing_room_ids.add(r.Id.IntegerValue)
                    except Exception:
                        pass
                for tag in source_tags:
                    try:
                        room = tag.Room
                        if room is None:
                            n_skip += 1
                            continue
                        if room.Id.IntegerValue in existing_room_ids:
                            n_skip += 1
                            continue
                        pt = tag.TagHeadPosition
                        uv = DB.UV(pt.X, pt.Y)
                        new_tag = doc.Create.NewRoomTag(
                            DB.LinkElementId(room.Id), uv, target_view.Id
                        )
                        try:
                            new_tag.RoomTagType = tag.RoomTagType
                        except Exception:
                            pass
                        try:
                            new_tag.TagHeadPosition = pt
                        except Exception:
                            pass
                        try:
                            has_leader = bool(tag.HasLeader)
                            new_tag.HasLeader = has_leader
                            if has_leader:
                                try:
                                    new_tag.LeaderEndCondition = tag.LeaderEndCondition
                                except Exception:
                                    pass
                                try:
                                    if tag.LeaderEndCondition == DB.LeaderEndCondition.Free:
                                        new_tag.LeaderEnd = tag.LeaderEnd
                                except Exception:
                                    pass
                                try:
                                    new_tag.LeaderElbow = tag.LeaderElbow
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        existing_room_ids.add(room.Id.IntegerValue)
                        n_ok += 1
                    except Exception:
                        n_skip += 1

    msg = u"{} étiquette(s) créée(s).".format(n_ok)
    if n_skip:
        msg += u"\n{} étiquette(s) ignorée(s) (déjà présente ou échec).".format(n_skip)
    show_alert(u"Reproduire les étiquettes", msg)


if __name__ == '__main__':
    main()
