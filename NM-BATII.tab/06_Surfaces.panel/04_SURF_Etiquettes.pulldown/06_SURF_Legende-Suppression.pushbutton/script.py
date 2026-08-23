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


#__title__ = 'Supprimer\nles légendes'
#__author__ = 'data8bim (d8b)'

"""
NM-BATII — Suppression en masse des légendes de motif/couleur des surfaces.

Pendant de 04_SURF_Legende-Couleurs, dont il reprend les portées (tous les
plans de surface, par schéma, par vues choisies) et, de
05_SURF_Etiquette-Suppression, la liste des types RÉELLEMENT UTILISÉS : offrir
un type qu'aucune légende ne porte n'aiderait à rien supprimer.

Portée bornée aux PLANS DE SURFACE. Une légende de motif/couleur posée sur un
plan d'étage — pour les pièces, par exemple — n'est jamais énumérée, donc
jamais supprimée : ce bouton vit dans la palette Surfaces, il n'a pas à faire
le ménage ailleurs.
"""

import os
import json
import codecs
import System
from pyrevit import revit, DB, forms, script
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

from utils.config_loader import load_config

doc   = revit.doc
uidoc = revit.uidoc
view  = doc.ActiveView

CONFIG_KEY = 'suppression_masse_legendes_surfaces'


# ─── Logs pyRevit ──────────────────────────────────────────────────────────────
# Convention de l'extension : rien ne s'affiche si « Activer les logs des
# scripts » est décoché dans 01_Parametres (clé activer_logs_scripts de
# config.json).
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


def _elem_name(e):
    """
    Contournement IronPython : Element.Name est implémenté en interface
    explicite sur certains types (FamilySymbol, ElementType...), ce qui fait
    échouer l'accès direct `e.Name` (AttributeError: Name).
    """
    return Element.Name.__get__(e)


# ─── Config (types cochés par défaut) ──────────────────────────────────────────
def _config_path():
    cur = os.path.dirname(os.path.abspath(__file__))
    while not cur.lower().endswith('.extension'):
        parent = os.path.dirname(cur)
        if parent == cur:
            raise IOError("Dossier .extension introuvable depuis : " + cur)
        cur = parent
    return os.path.join(cur, 'config.json')


def _save_default_types(labels):
    """Enregistre les types de légende cochés comme réglages par défaut."""
    try:
        path = _config_path()
        with codecs.open(path, 'r', 'utf-8') as f:
            cfg = json.load(f)
        cfg.setdefault(CONFIG_KEY, {})['types_selectionnes'] = labels
        with codecs.open(path, 'w', 'utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ─── Schémas de surface ────────────────────────────────────────────────────────
def _schema_de_vue(v):
    """AreaScheme du plan de surface, ou None."""
    try:
        return v.AreaScheme
    except Exception:
        return None


def nom_schema(v):
    """Nom du schéma de surface de la vue, ou u'' s'il est illisible."""
    schema = _schema_de_vue(v)
    if schema is None:
        return u''
    try:
        return _elem_name(schema) or u''
    except Exception:
        return u''


def schemas_disponibles(views):
    """Noms des schémas de surface rencontrés, triés, sans doublon."""
    noms = set()
    for v in views:
        nom = nom_schema(v)
        if nom:
            noms.add(nom)
    return sorted(noms, key=lambda n: n.lower())


# ─── Légendes de motif/couleur ─────────────────────────────────────────────────
def legendes_du_projet():
    """Toutes les légendes de motif/couleur du document."""
    try:
        return list(DB.FilteredElementCollector(doc)
                    .OfClass(DB.ColorFillLegend)
                    .WhereElementIsNotElementType()
                    .ToElements())
    except Exception:
        return []


def legendes_par_vue():
    """{ view_id.IntegerValue : [ColorFillLegend, ...] } pour tout le document.

    Collecteur sur le DOCUMENT puis filtre sur OwnerViewId, et NON collecteur
    borné à la vue : ce dernier ne rend que ce qui y est visible, et une
    légende masquée par un gabarit ou un « Masquer dans la vue » échapperait à
    la suppression tout en restant bien présente. Même piège que
    lib/utils/surfaces_etiquettes.etiquettes_de_la_vue.
    """
    par_vue = {}
    for legende in legendes_du_projet():
        try:
            cle = legende.OwnerViewId.IntegerValue
        except Exception:
            continue
        par_vue.setdefault(cle, []).append(legende)
    return par_vue


def _nom_type(type_id):
    """Nom d'un type de légende, ou u'' s'il est illisible."""
    try:
        t = doc.GetElement(type_id)
    except Exception:
        return u''
    if t is None:
        return u''
    try:
        return _elem_name(t) or u''
    except Exception:
        return u''


def types_legende_utilises():
    """[(nom, ElementId)] des types portés par au moins une légende du projet.

    Même parti pris que 05_SURF_Etiquette-Suppression : proposer un type
    qu'aucune légende n'utilise n'aide à rien supprimer et allonge la liste
    pour rien. Les types sont lus SUR LES LÉGENDES existantes, pas dans le
    catalogue de la catégorie.
    """
    vus = {}
    for legende in legendes_du_projet():
        try:
            tid = legende.GetTypeId()
        except Exception:
            continue
        if tid is None:
            continue
        cle = tid.IntegerValue
        if cle not in vus:
            vus[cle] = tid
    trouves = []
    for cle, tid in vus.items():
        nom = _nom_type(tid)
        if nom:
            trouves.append((nom, tid))
    trouves.sort(key=lambda couple: couple[0].lower())
    return trouves


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


# ─── Schémas de surface : tableau de choix ─────────────────────────────────────
def show_schemas_picker_dialog(tous_les_noms, deja_choisis, owner=None):
    """Liste des schémas de surface du projet, à cocher (Maj+Clic pour une
    plage). Retourne l'ensemble des noms retenus, ou None si annulé.

    Réutilise ColumnFilterDialog.xaml : la disposition demandée est exactement
    la sienne — recherche, tout sélectionner / désélectionner / inverser, puis
    une pile de cases à cocher.
    """
    xaml_path = os.path.join(os.path.dirname(__file__), 'ColumnFilterDialog.xaml')
    # set_owner=False : forms.WPFWindow fixe sinon l'owner Win32 sur la fenêtre
    # de Revit, ce qui court-circuite l'owner WPF ci-dessous et laisse la
    # fenêtre appelante sans repaint à la fermeture.
    dlg = forms.WPFWindow(xaml_path, set_owner=False)
    dlg.Title = u"Schémas de surface à traiter"
    if owner is not None:
        dlg.Owner = owner

    retenus = set(deja_choisis)
    cases = []
    dernier = [-1]

    for idx, nom in enumerate(tous_les_noms):
        cb = CheckBox()
        cb.Content = _escape_access_text(nom)
        cb.IsChecked = nom in retenus
        cb.Margin = Thickness(2, 2, 2, 2)

        def _mk(i, valeur, case):
            def on_click(s, e):
                coche = bool(case.IsChecked)
                maj = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                       Keyboard.IsKeyDown(WpfKey.RightShift))
                if maj and dernier[0] >= 0:
                    lo, hi = min(dernier[0], i), max(dernier[0], i)
                    for j in range(lo, hi + 1):
                        case_j, valeur_j = cases[j]
                        case_j.IsChecked = coche
                        if coche: retenus.add(valeur_j)
                        else:     retenus.discard(valeur_j)
                else:
                    if coche: retenus.add(valeur)
                    else:     retenus.discard(valeur)
                dernier[0] = i
            return on_click

        cb.Click += _mk(idx, nom, cb)
        dlg.valuesPanel.Children.Add(cb)
        cases.append((cb, nom))

    def _visible(cb):
        return cb.Visibility == Visibility.Visible

    def on_all(s, e):
        for cb, nom in cases:
            if not _visible(cb):
                continue
            cb.IsChecked = True
            retenus.add(nom)

    def on_none(s, e):
        for cb, nom in cases:
            if not _visible(cb):
                continue
            cb.IsChecked = False
            retenus.discard(nom)

    def on_invert(s, e):
        for cb, nom in cases:
            if not _visible(cb):
                continue
            coche = not bool(cb.IsChecked)
            cb.IsChecked = coche
            if coche: retenus.add(nom)
            else:     retenus.discard(nom)

    def on_search_changed(s, e):
        inclut = _normalize(dlg.txtSearch.Text)
        exclut = _normalize(dlg.txtSearchExclude.Text)
        for cb, nom in cases:
            botte = _normalize(nom)
            montrer = ((not inclut or inclut in botte) and
                       (not exclut or exclut not in botte))
            cb.Visibility = Visibility.Visible if montrer else Visibility.Collapsed

    dlg.txtSearch.TextChanged        += on_search_changed
    dlg.txtSearchExclude.TextChanged += on_search_changed
    dlg.btnSelectAll.Click   += on_all
    dlg.btnDeselectAll.Click += on_none
    dlg.btnInvert.Click      += on_invert
    dlg.btnOk.Click          += lambda s, e: setattr(dlg, 'DialogResult', True)
    dlg.btnCancel.Click      += lambda s, e: setattr(dlg, 'DialogResult', False)

    if dlg.show_dialog():
        return retenus
    return None


# ─── Interface ─────────────────────────────────────────────────────────────────
def main():
    types = types_legende_utilises()
    if not types:
        show_alert(u"Supprimer les légendes",
                   u"Aucune légende de motif/couleur n'est présente dans ce "
                   u"projet.")
        return

    toutes_les_vues = get_selectable_views()
    if not toutes_les_vues:
        show_alert(u"Supprimer les légendes",
                   u"Aucun plan de surface disponible dans ce projet.")
        return

    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    deja_coches = set(cfg.get(CONFIG_KEY, {}).get('types_selectionnes', []))

    xaml_path = os.path.join(os.path.dirname(__file__), 'MainWindow.xaml')
    wpf = forms.WPFWindow(xaml_path)

    cases = []
    for nom_type, id_type in types:
        cb = CheckBox()
        cb.Content = _escape_access_text(nom_type)
        cb.Margin = Thickness(0, 3, 0, 3)
        cb.IsChecked = nom_type in deja_coches
        wpf.spTypes.Children.Add(cb)
        cases.append((cb, id_type, nom_type))

    etat = {'schemas': set(), 'vues': set()}
    dialog_result = {'ok': False}

    def _maj_boutons(s=None, e=None):
        wpf.btnSelectSchemas.IsEnabled = bool(wpf.rbSchemas.IsChecked)
        wpf.btnSelectViews.IsEnabled   = bool(wpf.rbVues.IsChecked)

    def _on_deselect_all(s, e):
        for cb, id_type, nom_type in cases:
            cb.IsChecked = False

    def _on_select_schemas(s, e):
        disponibles = schemas_disponibles(toutes_les_vues)
        if not disponibles:
            show_alert(u"Supprimer les légendes",
                       u"Aucun schéma de surface n'a pu être lu sur les plans "
                       u"de surface de ce projet.")
            return
        resultat = show_schemas_picker_dialog(disponibles, etat['schemas'],
                                              owner=wpf)
        wpf.Activate()
        if resultat is not None:
            etat['schemas'] = resultat
            wpf.txtSchemasCount.Text = u"({} schéma(s))".format(len(resultat))
            wpf.rbSchemas.IsChecked = True

    def _on_select_views(s, e):
        resultat = show_views_picker_dialog(toutes_les_vues, etat['vues'])
        wpf.Activate()
        if resultat is not None:
            etat['vues'] = resultat
            wpf.txtViewsCount.Text = u"({} vue(s))".format(len(resultat))
            wpf.rbVues.IsChecked = True

    def _on_ok(s, e):
        if not any(cb.IsChecked for cb, id_type, nom_type in cases):
            show_alert(u"Supprimer les légendes",
                       u"Sélectionnez au moins un type de légende.")
            return
        if wpf.rbSchemas.IsChecked and not etat['schemas']:
            show_alert(u"Supprimer les légendes",
                       u"Aucun schéma sélectionné. Cliquez sur "
                       u"\"Choisir les schémas...\".")
            return
        if wpf.rbVues.IsChecked and not etat['vues']:
            show_alert(u"Supprimer les légendes",
                       u"Aucune vue sélectionnée. Cliquez sur "
                       u"\"Choisir les vues...\".")
            return
        dialog_result['ok'] = True
        wpf.Close()

    for nom_rb in (u'rbToutes', u'rbSchemas', u'rbVues'):
        getattr(wpf, nom_rb).Checked += _maj_boutons
    _maj_boutons()

    wpf.btnDeselectAll.Click   += _on_deselect_all
    wpf.btnSelectSchemas.Click += _on_select_schemas
    wpf.btnSelectViews.Click   += _on_select_views
    wpf.btnOK.Click            += _on_ok
    wpf.btnCancel.Click        += lambda s, e: wpf.Close()

    frame = Threading.DispatcherFrame()
    wpf.Closed += lambda s, e: setattr(frame, 'Continue', False)
    wpf.Show()
    Threading.Dispatcher.PushFrame(frame)

    if not dialog_result['ok']:
        return

    retenus = [(id_type, nom_type) for cb, id_type, nom_type in cases
               if cb.IsChecked]
    ids_types = set(id_type.IntegerValue for id_type, nom_type in retenus)
    _save_default_types([nom_type for id_type, nom_type in retenus])

    # « Tous les plans de surface » en dernier, donc en repli : c'est l'option
    # cochée par défaut, et la seule qui ne dépende d'aucune sélection.
    if wpf.rbSchemas.IsChecked:
        cibles = [v for v in toutes_les_vues if nom_schema(v) in etat['schemas']]
    elif wpf.rbVues.IsChecked:
        cibles = [v for v in toutes_les_vues
                  if v.Id.IntegerValue in etat['vues']]
    else:
        cibles = list(toutes_les_vues)

    if not cibles:
        show_alert(u"Supprimer les légendes",
                   u"Aucun plan de surface ne correspond aux critères choisis.")
        return

    existantes = legendes_par_vue()

    # Le tri est fait AVANT d'ouvrir la transaction : rien n'est modifié tant
    # qu'on ne sait pas s'il y a quelque chose à supprimer, et le message
    # « rien à faire » n'ouvre alors aucune transaction vide.
    a_supprimer = []
    for v in cibles:
        for legende in (existantes.get(v.Id.IntegerValue) or []):
            try:
                tid = legende.GetTypeId()
            except Exception:
                continue
            if tid is not None and tid.IntegerValue in ids_types:
                a_supprimer.append((v, legende))

    if not a_supprimer:
        show_alert(u"Supprimer les légendes",
                   u"Aucune légende à supprimer selon les critères choisis.")
        return

    n_ok = 0
    n_skip = 0
    journal = []

    with revit.Transaction(u"Supprimer les légendes de couleurs des surfaces"):
        for v, legende in a_supprimer:
            try:
                doc.Delete(legende.Id)
                n_ok += 1
                journal.append((v, True, None))
            except Exception as ex:
                n_skip += 1
                journal.append((v, False, str(ex)))

    lignes = [u"{0} légende(s) de motif/couleur supprimée(s).".format(n_ok)]
    if n_skip:
        lignes.append(u"{0} légende(s) conservée(s) (échec de suppression)."
                      .format(n_skip))

    def _nom(v):
        try:
            return _elem_name(v) or u"(vue {0})".format(v.Id.IntegerValue)
        except Exception:
            return u"(vue {0})".format(v.Id.IntegerValue)

    _log(u"# Suppression des légendes de motif/couleur des surfaces")
    _log(u"Types retenus : {0}".format(
        u", ".join(nom_type for id_type, nom_type in retenus) or u"(aucun)"))
    _log(u"{0} plan(s) de surface dans le projet, {1} retenu(s) par la portée "
         u"choisie.".format(len(toutes_les_vues), len(cibles)))
    _log(u"{0} supprimée(s), {1} en échec.".format(n_ok, n_skip))
    if journal:
        _log(u"**Détail par vue :**")
        for v, ok, cause in journal:
            _log(u"- {0} {1} [{2}]{3}".format(
                u"✔" if ok else u"✖", _nom(v),
                nom_schema(v) or u"schéma inconnu",
                u" — " + cause if cause else u""))

    show_alert(u"Supprimer les légendes", u"\n".join(lignes))


# Pas d'ExternalEvent ici, contrairement à 01_SURF_Etiquette-Masse : celui-ci
# n'existe que pour obtenir la barre d'options discrète de PickObjects. Aucune
# sélection dans la vue n'est demandée par ce bouton, et le script pyRevit
# s'exécute déjà dans un contexte API valide — la transaction passe directement.
if __name__ == '__main__':
    main()
