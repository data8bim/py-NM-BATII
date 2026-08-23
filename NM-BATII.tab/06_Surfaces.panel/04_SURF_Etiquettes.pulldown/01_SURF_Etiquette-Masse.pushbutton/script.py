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


#__title__ = 'Étiqueter\nen masse'
#__author__ = 'data8bim (d8b)'

import os
import json
import codecs
import System
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import Element, LocationPoint
from Autodesk.Revit.DB import Area as AreaClass
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType as PickObjectType
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from System.Windows import (
    Thickness, WindowState, GridLength, GridUnitType, FontWeights, TextWrapping,
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

from utils.config_loader import load_config

doc   = revit.doc
uidoc = revit.uidoc
view  = doc.ActiveView


# ─── Logs pyRevit ──────────────────────────────────────────────────────────────
# Convention de l'extension : rien ne s'affiche si « Activer les logs des
# scripts » est décoché dans 01_Parametres (clé activer_logs_scripts de
# config.json). Résolu ICI, au niveau module : le gestionnaire d'ExternalEvent
# prend un instantané des globals et le restaure avant main(), donc tout ce qui
# est défini avant lui reste disponible dans le fil Revit.
try:
    _LOG_ACTIF = bool(load_config().get('activer_logs_scripts', False))
except Exception:
    _LOG_ACTIF = False

_output = script.get_output()
if not _LOG_ACTIF:
    try:
        _output.close()
    except Exception:
        pass


def _log(message):
    if not _LOG_ACTIF or not message:
        return
    try:
        _output.print_md(message)
    except Exception:
        pass


class _AreaSelectionFilter(object, ISelectionFilter):
    """Restreint la sélection Revit aux seules surfaces."""
    def AllowElement(self, element):
        return isinstance(element, AreaClass)
    def AllowReference(self, reference, point):
        return False

CONFIG_KEY = 'etiquette_masse_surfaces'


# ─── Config (types cochés par défaut) ──────────────────────────────────────────
def _config_path():
    cur = os.path.dirname(os.path.abspath(__file__))
    while not cur.lower().endswith('.extension'):
        parent = os.path.dirname(cur)
        if parent == cur:
            raise IOError("Dossier .extension introuvable depuis : " + cur)
        cur = parent
    return os.path.join(cur, 'config.json')


def _save_default_tag_types(labels):
    """Enregistre les types d'étiquette cochés comme réglages par défaut."""
    try:
        path = _config_path()
        with codecs.open(path, 'r', 'utf-8') as f:
            cfg = json.load(f)
        cfg.setdefault(CONFIG_KEY, {})['types_selectionnes'] = labels
        with codecs.open(path, 'w', 'utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _elem_name(e):
    """
    Contournement IronPython : Element.Name est implémenté en interface
    explicite sur certains types (FamilySymbol, ElementType...), ce qui fait
    échouer l'accès direct `e.Name` (AttributeError: Name).
    """
    return Element.Name.__get__(e)


# ─── Collecte ─────────────────────────────────────────────────────────────────
def get_area_tag_types():
    """Retourne les FamilySymbol de la catégorie 'Étiquette de surface', triés."""
    types = list(
        DB.FilteredElementCollector(doc)
        .OfCategory(DB.BuiltInCategory.OST_AreaTags)
        .WhereElementIsElementType()
        .ToElements()
    )
    types.sort(key=lambda t: (_elem_name(t.Family), _elem_name(t)))
    return types


def _is_placed_area(area):
    """Une surface non placée n'a pas de point d'insertion : rien où accrocher
    une étiquette. Le test porte sur LocationPoint, et pas seulement sur la
    présence d'une Location, comme dans lib/utils/surfaces_etiquettes.py."""
    try:
        return isinstance(area.Location, LocationPoint)
    except Exception:
        return False


def _point_pose(area):
    """Point où poser l'étiquette : le POINT D'INSERTION de la surface.

    C'est là que Revit pose l'étiquette avec « Tout étiqueter », et c'est
    l'ancrage de l'étiquette : y placer la tête est ce qui rend la ligne de
    repère inutile.

    Une version antérieure visait le centre du rectangle englobant, c'est-à-dire
    le croisement des diagonales de la référence de surface. Le calcul était
    juste, mais la cible était fausse : Revit n'étiquette pas là, et chaque
    étiquette se retrouvait décalée de son point d'ancrage.
    """
    pt = area.Location.Point
    return DB.UV(pt.X, pt.Y)


def _tag_area(tag):
    """Surface portée par une étiquette, ou None.

    Area est la propriété spécialisée d'AreaTag, SpatialElement celle de sa
    classe de base : l'une ou l'autre peut échouer selon l'état de l'étiquette
    (orpheline, liée...). Renoncer trop tôt reviendrait à croire la surface non
    étiquetée, donc à lui en poser une seconde."""
    for nom in ('Area', 'SpatialElement'):
        try:
            surf = getattr(tag, nom, None)
        except Exception:
            surf = None
        if surf is not None:
            return surf
    return None


def get_view_areas(active_view):
    areas = DB.FilteredElementCollector(doc, active_view.Id)\
        .OfCategory(DB.BuiltInCategory.OST_Areas)\
        .WhereElementIsNotElementType()\
        .ToElements()
    return [a for a in areas if _is_placed_area(a)]


def get_tagged_area_ids_by_view():
    """Dict {view_id.IntegerValue: set(area_id.IntegerValue)} des surfaces déjà
    étiquetées, par vue (une surface peut être étiquetée dans une vue et pas
    dans une autre : l'absence d'étiquette s'apprécie vue par vue)."""
    result = {}
    tags = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_AreaTags)\
        .WhereElementIsNotElementType()\
        .ToElements()
    for tag in tags:
        try:
            area = _tag_area(tag)
            if area is None:
                continue
            result.setdefault(tag.OwnerViewId.IntegerValue, set()).add(area.Id.IntegerValue)
        except Exception:
            pass
    return result


# ─── Vues sélectionnées : collecte, tableau de choix ───────────────────────────
# Les surfaces (Area) n'existent QUE dans les plans de surface : ni un plan
# d'étage, ni une coupe, ni une élévation ne peut en afficher une — donc encore
# moins en porter l'étiquette. La liste des vues proposées s'y limite, là où
# l'équivalent « pièces » de 05_Pieces.panel accepte aussi coupes et élévations.
_AREA_PLAN_VIEW_TYPES = (
    DB.ViewType.AreaPlan,        # Plan de surface
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


def order_column_names(names):
    """Place les colonnes de _PINNED_COLUMN_ORDER en tête (si présentes parmi
    les paramètres découverts), puis les autres colonnes par ordre alphabétique."""
    by_normalized = {}
    for name in names:
        by_normalized.setdefault(_normalize(name), name)
    pinned = []
    used = set()
    for target in _PINNED_COLUMN_ORDER:
        actual = by_normalized.get(_normalize(target))
        if actual is not None and actual not in used:
            pinned.append(actual)
            used.add(actual)
    rest = [n for n in names if n not in used]
    return pinned + rest


def get_selectable_views():
    """Plans de surface (hors gabarits) proposés au choix."""
    views = DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan).WhereElementIsNotElementType().ToElements()
    result = []
    for v in views:
        try:
            if v.IsTemplate:
                continue
            if v.ViewType in _AREA_PLAN_VIEW_TYPES:
                result.append(v)
        except Exception:
            pass
    return result


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


class _ViewRow(object, INotifyPropertyChanged):
    """Ligne du tableau de choix des vues. 'Selected' notifie ses changements
    (INotifyPropertyChanged) pour que la case à cocher reste synchrone avec le
    modèle lors des sélections en masse (Tout sélectionner, Maj+Clic...)."""

    def __init__(self, view):
        self.view = view
        self._selected = False
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
    multiple Maj+Clic supportée), pour filtrer le tableau de vues."""
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


def show_views_picker_dialog(all_views, current_selected_ids):
    """Tableur de choix des vues à traiter : une colonne par paramètre de vue
    (paramètres usuels épinglés en tête, puis les autres par ordre
    alphabétique), avec filtres et tri par colonne, sélection multiple
    (Maj+Clic pour une plage)."""
    xaml_path = os.path.join(os.path.dirname(__file__), 'ViewsPickerDialog.xaml')
    wpf = forms.WPFWindow(xaml_path)

    # "Nom de la vue"/"Niveau associé"/"Echelle de la vue" sont déjà couverts
    # par les colonnes fixes ViewName/AssociatedLevel/ViewScale (résolues par
    # BuiltInParameter) : on les retire des colonnes dynamiques pour éviter
    # un doublon.
    _fixed_labels = set([
        _bip_label(_BIP_VIEW_NAME, u'Nom de la vue'),
        _bip_label(_BIP_ASSOC_LEVEL, u'Niveau associé'),
        _bip_label(_BIP_VIEW_SCALE, u'Echelle de la vue'),
    ])
    raw_names = [n for n in get_dynamic_param_names(all_views) if n not in _fixed_labels]
    ordered_names = order_column_names(raw_names)
    all_rows = build_view_rows(all_views, ordered_names)
    for r in all_rows:
        r.Selected = r.view.Id.IntegerValue in current_selected_ids

    last_idx = [-1]
    header_widgets = {}
    view_state = {'filters': {}, 'sort': None}

    # Le filtre/tri est recalculé côté Python puis appliqué en réaffectant
    # ItemsSource à une collection neuve : plus robuste que ICollectionView
    # (Filter + Refresh()), dont le rendu s'est révélé décalé d'une action
    # dans cet hôte WPF (l'effet d'un filtre n'apparaissait qu'au filtre ou
    # au tri suivant).
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

    # Colonnes fixes, toujours dans cet ordre et à la même position quelle
    # que soit la langue de Revit (résolues par BuiltInParameter, cf. plus
    # haut) : Nom de la vue, Niveau associé, Echelle de la vue, Famille, Type.
    _fixed_columns = [
        (_bip_label(_BIP_VIEW_NAME, u'Nom de la vue'), u'ViewName'),
        (_bip_label(_BIP_ASSOC_LEVEL, u'Niveau associé'), u'AssociatedLevel'),
        (_bip_label(_BIP_VIEW_SCALE, u'Echelle de la vue'), u'ViewScale'),
        (_bip_label(_BIP_FAMILY, u'Famille'), u'Family'),
        (_bip_label(_BIP_TYPE, u'Type'), u'TypeName'),
    ]
    for label, key in _fixed_columns:
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
        dialog_result['ok'] = True
        wpf.Close()

    wpf.btnOk.Click     += _on_ok
    wpf.btnCancel.Click += lambda s, e: wpf.Close()

    frame = Threading.DispatcherFrame()
    wpf.Closed += lambda s, e: setattr(frame, 'Continue', False)
    wpf.Show()
    Threading.Dispatcher.PushFrame(frame)

    if not dialog_result['ok']:
        return None
    return set(r.view.Id.IntegerValue for r in all_rows if r.Selected)


# ─── Étiquetage ────────────────────────────────────────────────────────────────
def tag_area(area, tag_type, target_view):
    """Pose une étiquette sur la surface, dans la vue donnée.

    NewAreaTag prend directement (vue, surface, point) : pas de LinkElementId
    comme pour les pièces, et la vue est passée en objet, pas en ElementId.
    Aucun cas coupe/élévation à traiter ici — une surface ne s'y affiche pas
    (voir _AREA_PLAN_VIEW_TYPES).

    HasLeader est mis à False EXPLICITEMENT, et ce n'est pas superflu : sans
    cette écriture l'étiquette hérite du dernier réglage de l'outil natif, d'où
    des lignes de repère posées sans que personne ne les ait demandées. C'était
    la cause des repères systématiques, la position n'y était pour rien.

    Pas de repère du tout, et donc pas de réglage : l'étiquette est posée sur
    le point d'insertion, c'est-à-dire pile sur son ancrage — un repère n'y
    aurait rien à relier.
    """
    point = _point_pose(area)
    tag = doc.Create.NewAreaTag(target_view, area, point)
    if tag is None:
        return False
    if tag_type is not None:
        if not tag_type.IsActive:
            tag_type.Activate()
        tag.AreaTagType = tag_type
    try:
        tag.HasLeader = False
    except Exception:
        pass
    return True


# ─── Interface ─────────────────────────────────────────────────────────────────
def main():
    tag_types = get_area_tag_types()
    if not tag_types:
        show_alert(
            u"Étiqueter en masse",
            u"Aucun type d'étiquette de surface disponible dans ce projet.\n"
            u"Chargez une famille d'étiquette de surfaces avant de continuer."
        )
        return

    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    default_selected = set(cfg.get(CONFIG_KEY, {}).get('types_selectionnes', []))

    xaml_path = os.path.join(os.path.dirname(__file__), 'MainWindow.xaml')
    wpf = forms.WPFWindow(xaml_path)

    checkbox_items = []
    for t in tag_types:
        label = u"{} : {}".format(_elem_name(t.Family), _elem_name(t))
        cb = CheckBox()
        cb.Content = label
        cb.Margin = Thickness(0, 3, 0, 3)
        cb.IsChecked = label in default_selected
        wpf.spTagTypes.Children.Add(cb)
        checkbox_items.append((cb, t, label))

    selection_state = {'areas': []}
    views_state = {'selected_view_ids': set(), 'candidate_views': None}
    dialog_result = {'ok': False}

    def _on_deselect_all(s, e):
        for cb, t, label in checkbox_items:
            cb.IsChecked = False

    def _on_select_areas(s, e):
        """Minimise la fenêtre pour permettre la sélection de surfaces dans la
        vue, puis restaure la fenêtre. Nécessite une fenêtre non modale (Show)."""
        wpf.WindowState = WindowState.Minimized
        try:
            refs = uidoc.Selection.PickObjects(
                PickObjectType.Element, _AreaSelectionFilter(),
                u"Sélectionnez les surfaces puis cliquez sur Terminer"
            )
            areas = [doc.GetElement(r.ElementId) for r in refs]
            selection_state['areas'] = [a for a in areas if a is not None and _is_placed_area(a)]
        except Exception:
            pass
        wpf.WindowState = WindowState.Normal
        wpf.Activate()
        wpf.txtSelectionCount.Text = u"({} surface(s) sélectionnée(s))".format(len(selection_state['areas']))
        wpf.rbVueSelection.IsChecked = True

    def _mk_select_views_handler(target_radio):
        def handler(s, e):
            if views_state['candidate_views'] is None:
                views_state['candidate_views'] = get_selectable_views()
            candidates = views_state['candidate_views']
            if not candidates:
                show_alert(u"Étiqueter en masse",
                           u"Aucun plan de surface disponible dans ce projet.")
                return
            result = show_views_picker_dialog(candidates, views_state['selected_view_ids'])
            if result is not None:
                views_state['selected_view_ids'] = result
                count_text = u"({} vue(s) sélectionnée(s))".format(len(result))
                wpf.txtViewsCount.Text = count_text
                wpf.txtViewsCount2.Text = count_text
                if not (wpf.rbVuesSelectionneesToutes.IsChecked or
                        wpf.rbVuesSelectionneesSansEtiquette.IsChecked):
                    target_radio.IsChecked = True
        return handler

    def _on_ok(s, e):
        if not any(cb.IsChecked for cb, t, label in checkbox_items):
            show_alert(u"Étiqueter en masse", u"Sélectionnez au moins un type d'étiquette.")
            return
        if wpf.rbVueSelection.IsChecked and not selection_state['areas']:
            show_alert(u"Étiqueter en masse",
                       u"Aucune surface sélectionnée. Cliquez sur \"Sélectionner\".")
            return
        if ((wpf.rbVuesSelectionneesToutes.IsChecked or wpf.rbVuesSelectionneesSansEtiquette.IsChecked)
                and not views_state['selected_view_ids']):
            show_alert(u"Étiqueter en masse",
                       u"Aucune vue sélectionnée. Cliquez sur \"Choisir les vues...\".")
            return
        dialog_result['ok'] = True
        wpf.Close()

    def _update_scope_buttons(s=None, e=None):
        wpf.btnSelectViews.IsEnabled = bool(wpf.rbVuesSelectionneesToutes.IsChecked)
        wpf.btnSelectViews2.IsEnabled = bool(wpf.rbVuesSelectionneesSansEtiquette.IsChecked)
        wpf.btnSelectAreas.IsEnabled = bool(wpf.rbVueSelection.IsChecked)

    for rb_name in (u'rbProjetToutes', u'rbProjetSansEtiquette',
                    u'rbVuesSelectionneesToutes', u'rbVuesSelectionneesSansEtiquette',
                    u'rbVueToutes', u'rbVueSansEtiquette', u'rbVueSelection'):
        getattr(wpf, rb_name).Checked += _update_scope_buttons
    _update_scope_buttons()

    wpf.btnDeselectAll.Click += _on_deselect_all
    wpf.btnSelectAreas.Click += _on_select_areas
    wpf.btnSelectViews.Click += _mk_select_views_handler(wpf.rbVuesSelectionneesToutes)
    wpf.btnSelectViews2.Click += _mk_select_views_handler(wpf.rbVuesSelectionneesSansEtiquette)
    wpf.btnOK.Click += _on_ok
    wpf.btnCancel.Click += lambda s, e: wpf.Close()

    frame = Threading.DispatcherFrame()
    wpf.Closed += lambda s, e: setattr(frame, 'Continue', False)
    wpf.Show()
    Threading.Dispatcher.PushFrame(frame)

    if not dialog_result['ok']:
        return

    selected = [(t, label) for cb, t, label in checkbox_items if cb.IsChecked]
    selected_types = [t for t, label in selected]
    _save_default_tag_types([label for t, label in selected])

    if wpf.rbProjetToutes.IsChecked:
        scope = 'toutes_vues_toutes'
    elif wpf.rbProjetSansEtiquette.IsChecked:
        scope = 'toutes_vues_sans'
    elif wpf.rbVuesSelectionneesToutes.IsChecked:
        scope = 'vues_selection_toutes'
    elif wpf.rbVuesSelectionneesSansEtiquette.IsChecked:
        scope = 'vues_selection_sans'
    elif wpf.rbVueToutes.IsChecked:
        scope = 'vue_toutes'
    elif wpf.rbVueSelection.IsChecked:
        scope = 'vue_selection'
    else:
        scope = 'vue_sans'

    # Liste de couples (vue, surfaces à étiqueter dans cette vue).
    view_area_pairs = []

    if scope in ('toutes_vues_toutes', 'toutes_vues_sans'):
        tagged_by_view = get_tagged_area_ids_by_view() if scope == 'toutes_vues_sans' else {}
        for v in get_selectable_views():
            areas_in_view = get_view_areas(v)
            if scope == 'toutes_vues_sans':
                already = tagged_by_view.get(v.Id.IntegerValue, set())
                areas_in_view = [a for a in areas_in_view if a.Id.IntegerValue not in already]
            if areas_in_view:
                view_area_pairs.append((v, areas_in_view))
    elif scope in ('vues_selection_toutes', 'vues_selection_sans'):
        tagged_by_view = get_tagged_area_ids_by_view() if scope == 'vues_selection_sans' else {}
        selected_ids = views_state['selected_view_ids']
        candidates = views_state['candidate_views'] or []
        for v in candidates:
            if v.Id.IntegerValue not in selected_ids:
                continue
            areas_in_view = get_view_areas(v)
            if scope == 'vues_selection_sans':
                already = tagged_by_view.get(v.Id.IntegerValue, set())
                areas_in_view = [a for a in areas_in_view if a.Id.IntegerValue not in already]
            if areas_in_view:
                view_area_pairs.append((v, areas_in_view))
    else:
        if scope == 'vue_selection':
            areas = selection_state['areas']
        elif scope == 'vue_sans':
            tagged_by_view = get_tagged_area_ids_by_view()
            already = tagged_by_view.get(view.Id.IntegerValue, set())
            areas = [a for a in get_view_areas(view) if a.Id.IntegerValue not in already]
        else:
            areas = get_view_areas(view)
        if areas:
            view_area_pairs.append((view, areas))

    if not view_area_pairs:
        show_alert(u"Étiqueter en masse", u"Aucune surface à étiqueter selon les critères choisis.")
        return

    n_ok = 0
    n_skip = 0
    with revit.Transaction(u"Étiqueter les surfaces en masse"):
        for target_view, areas in view_area_pairs:
            for area in areas:
                for tag_type in selected_types:
                    try:
                        if tag_area(area, tag_type, target_view):
                            n_ok += 1
                        else:
                            n_skip += 1
                    except Exception:
                        n_skip += 1

    msg = u"{} étiquette(s) créée(s).".format(n_ok)
    if n_skip:
        msg += u"\n{} étiquette(s) ignorée(s) (échec de création).".format(n_skip)

    _log(u"# Étiqueter les surfaces en masse")
    _log(u"{0} étiquette(s) créée(s), {1} ignorée(s).".format(n_ok, n_skip))

    show_alert(u"Étiqueter en masse", msg)


# ── ExternalEvent : main() s'execute sur le thread Revit ──────────────────────
#
# Pourquoi : appeler PickObjects depuis un ExternalEvent fait afficher par Revit
# le panneau ruban « Autoriser selection multiple » (gros boutons Terminer /
# Annuler / Multiple) au lieu de la discrete barre d'options obtenue en appel
# direct. UI de selection uniformisee pour toute l'extension.
#
# Difficulte : apres le retour de Execute(), IronPython/pyRevit vide les globals
# du module, ce qui casserait tout le code de ce fichier. On en sauvegarde une
# COPIE au demarrage et on la restaure en tete de Execute() : le code existant
# reste utilisable tel quel, sans etre reecrit.

class _ActionHandler(IExternalEventHandler):

    def __init__(self):
        self._fn      = [None]           # mutable — pas de nonlocal en IPy 2.7
        self._globals = dict(globals())  # snapshot ICI : globals encore vivants

    def planifier(self, fn):
        self._fn[0] = fn

    def Execute(self, uiapp):
        try:
            globals().update(self._globals)
        except Exception:
            pass
        fn = self._fn[0]
        self._fn[0] = None
        if fn:
            try:
                fn()
            except Exception:
                # Ne jamais avaler en silence : remonter la cause.
                import traceback
                try:
                    import System.Windows as _SW
                    _SW.MessageBox.Show(traceback.format_exc(),
                                        u'NM-BATII — Erreur')
                except Exception:
                    pass

    def GetName(self):
        return u"NM-BATII — Etiquetage en masse des surfaces"


if __name__ == '__main__':
    # Le handler est instancie APRES toutes les definitions : c'est a cet
    # instant qu'est pris le snapshot des globals restaure par Execute().
    _action_handler = _ActionHandler()
    _ext_event      = ExternalEvent.Create(_action_handler)
    _action_handler.planifier(main)
    _ext_event.Raise()
