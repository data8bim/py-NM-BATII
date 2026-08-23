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


#__title__ = 'Légendes\nde couleurs'
#__author__ = 'data8bim (d8b)'

"""
NM-BATII — Pose en masse des légendes de motif/couleur sur les plans de surface.

La position vient d'une VUE DE RÉFÉRENCE que l'utilisateur désigne, et dont la
légende sert de modèle. Son schéma de surface n'a pas d'importance : on ne
reprend qu'un emplacement, il vaut aussi bien pour un autre type de calcul.

Le repérage est PUREMENT PLANIMÉTRIQUE. La référence ne transmet que (x, y) —
position_legende ne rend d'ailleurs rien d'autre, pour que le Z ne puisse pas
voyager par inadvertance. Chaque légende reçoit ensuite le Z que Revit a retenu
pour SA vue, si bien que le niveau n'intervient à aucun moment.

Une version antérieure calculait la position depuis la zone de cadrage. Elle a
été abandonnée : le cadrage est inexploitable quand il n'est pas actif (Revit y
conserve une boîte par défaut sans rapport avec le dessin), et quand il l'est,
son coin haut-droit tombe sur le plan.
"""

import os
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
    StackPanel, Orientation, ListBoxItem, ComboBoxItem,
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
def categorie_surfaces():
    """ElementId de la catégorie « Surfaces », celle que légende la vue.

    Résolue par Category.GetCategory plutôt que construite depuis
    BuiltInCategory : c'est la seule voie qui rende l'ElementId réellement
    présent dans CE document.
    """
    try:
        cat = DB.Category.GetCategory(doc, DB.BuiltInCategory.OST_Areas)
    except Exception:
        cat = None
    return cat.Id if cat is not None else None


def types_legende():
    """Types de légende de motif/couleur du projet : [(nom, ElementId)].

    Ce sont les ElementType de la catégorie OST_ColorFillLegends, ceux que
    propose le sélecteur de type de Revit quand une légende est sélectionnée.
    Triés par nom, pour que la liste déroulante soit parcourable.
    """
    trouves = []
    try:
        collecteur = (DB.FilteredElementCollector(doc)
                      .OfCategory(DB.BuiltInCategory.OST_ColorFillLegends)
                      .WhereElementIsElementType())
    except Exception:
        return []
    for t in collecteur:
        try:
            nom = _elem_name(t) or u''
        except Exception:
            nom = u''
        if nom:
            trouves.append((nom, t.Id))
    trouves.sort(key=lambda couple: couple[0].lower())
    return trouves


def legendes_par_vue():
    """{ view_id.IntegerValue : [ColorFillLegend, ...] } pour tout le document.

    Collecteur sur le DOCUMENT puis filtre sur OwnerViewId, et NON collecteur
    borné à la vue : ce dernier ne rend que ce qui y est visible, et une
    légende masquée par un gabarit ou un « Masquer dans la vue » reviendrait
    en double. Même piège que lib/utils/surfaces_etiquettes.etiquettes_de_la_vue.
    """
    par_vue = {}
    collecteur = (DB.FilteredElementCollector(doc)
                  .OfClass(DB.ColorFillLegend)
                  .WhereElementIsNotElementType())
    for legende in collecteur:
        try:
            cle = legende.OwnerViewId.IntegerValue
        except Exception:
            continue
        par_vue.setdefault(cle, []).append(legende)
    return par_vue


def position_legende(legende):
    """Position EN PLAN d'une légende : (x, y), ou None si illisible.

    Un couple et non un XYZ, volontairement : la référence ne doit transmettre
    que des coordonnées de plan. Rendre le point complet laissait le Z — donc
    l'altitude du niveau de la vue de référence — voyager jusqu'aux autres
    vues, alors que le repérage demandé est purement planimétrique. Ici
    l'information n'existe tout simplement pas.
    """
    try:
        origine = legende.Origin
    except Exception:
        return None
    if origine is None:
        return None
    try:
        return (origine.X, origine.Y)
    except Exception:
        return None


def vues_avec_legende(views, par_vue):
    """Sous-ensemble des vues portant déjà au moins une légende lisible.

    Ce sont les seules qui peuvent servir de référence de position. Le schéma
    de surface n'entre pas en compte : on ne reprend qu'un emplacement, et il
    vaut aussi bien pour un autre type de calcul.
    """
    retenues = []
    for v in views:
        legendes = par_vue.get(v.Id.IntegerValue) or []
        for legende in legendes:
            if position_legende(legende) is not None:
                retenues.append(v)
                break
    return retenues


# Refus connus de Revit, ramenés à une phrase actionnable. Le message brut est
# en anglais et comporte même une faute de frappe côté Revit (« catetoryId ») :
# on repère donc un fragment stable plutôt que la chaîne entière.
_SANS_SCHEMA = u"aucun jeu de couleurs appliqué aux surfaces dans cette vue"


def cause_lisible(message):
    """Traduit un refus de Revit, ou rend le message brut s'il est inconnu."""
    brut = message or u""
    if u"color fill scheme" in brut:
        return _SANS_SCHEMA
    if u"not on the view plane" in brut:
        return u"le point de pose ne tombe pas sur le plan de la vue"
    return brut


def z_du_plan_de_vue(v):
    """Altitude du plan de la vue, exigée par ColorFillLegend.Create.

    Create rejette tout point dont le Z ne tombe pas sur le plan de la vue :
    « The origin is not on the view plane ». Un Z fixe ne convenait donc qu'aux
    vues du niveau situé à l'altitude 0, et échouait sur tous les autres.

    Ce Z n'est PAS une donnée de la vue de référence : il est relu sur la vue
    de destination. Le repérage reste planimétrique, seule l'altitude du plan
    de dessin est propre à chaque vue — sans quoi Revit refuse la création.
    """
    for lecture in (lambda: v.Origin.Z,
                    lambda: v.CropBox.Transform.Origin.Z,
                    lambda: v.GenLevel.Elevation):
        try:
            z = lecture()
        except Exception:
            continue
        if z is not None:
            return z
    return 0.0


def poser_legende(v, categorie_id, position_plan, type_id=None):
    """Crée la légende de la vue à la position EN PLAN donnée : (x, y).

    Seuls X et Y viennent de la vue de référence. Le Z est celui du plan de la
    vue de destination (voir z_du_plan_de_vue) : aucune altitude ne circule
    d'une vue à l'autre, quel que soit leur niveau.

    Origin est réécrite après création parce que Create prend bien un point
    mais ne garantit pas de le conserver — c'est déjà ce qu'on avait constaté
    sur les étiquettes de surface, où NewAreaTag replaçait l'objet à sa guise.
    La propriété fait foi, on l'écrit.

    type_id : type de légende à appliquer, ou None pour laisser celui que Revit
    retient par défaut. Le changement de type est tenté APRÈS la création —
    Create ne prend pas de type — et son échec n'annule pas la pose : mieux
    vaut une légende au mauvais type qu'aucune légende.
    """
    x, y = position_plan
    legende = DB.ColorFillLegend.Create(doc, v.Id, categorie_id,
                                        DB.XYZ(x, y, z_du_plan_de_vue(v)))
    if legende is None:
        return None
    if type_id is not None:
        try:
            legende.ChangeTypeId(type_id)
        except Exception:
            pass
    try:
        actuelle = legende.Origin
        legende.Origin = DB.XYZ(x, y, actuelle.Z)
    except Exception:
        pass
    return legende


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


# ─── Vue de référence : choix de la position ───────────────────────────────────
def show_ref_view_dialog(views, deja_choisie, owner=None):
    """Choix de LA vue dont la position de légende sera recopiée.

    Retourne la vue retenue, ou None si annulé.
    """
    xaml_path = os.path.join(os.path.dirname(__file__), 'RefViewDialog.xaml')
    # set_owner=False : forms.WPFWindow fixe sinon l'owner Win32 sur la fenêtre
    # de Revit, ce qui court-circuite l'owner WPF ci-dessous et laisse la
    # fenêtre appelante sans repaint à la fermeture.
    dlg = forms.WPFWindow(xaml_path, set_owner=False)
    if owner is not None:
        dlg.Owner = owner

    lignes = []
    for v in views:
        try:
            nom = _elem_name(v) or u''
        except Exception:
            nom = u''
        schema = nom_schema(v)
        libelle = u"{0}   —   {1}".format(nom, schema) if schema else nom
        lignes.append((libelle, v))
    lignes.sort(key=lambda couple: couple[0].lower())

    def _remplir(filtre=u''):
        dlg.lstViews.Items.Clear()
        for libelle, v in lignes:
            if filtre and filtre not in _normalize(libelle):
                continue
            item = ListBoxItem()
            item.Content = libelle
            item.Tag = v
            dlg.lstViews.Items.Add(item)
            if deja_choisie is not None and v.Id == deja_choisie.Id:
                dlg.lstViews.SelectedItem = item

    _remplir()

    def _on_search(s, e):
        _remplir(_normalize(dlg.txtSearch.Text))

    dlg.txtSearch.TextChanged += _on_search
    dlg.btnOk.Click     += lambda s, e: setattr(dlg, 'DialogResult', True)
    dlg.btnCancel.Click += lambda s, e: setattr(dlg, 'DialogResult', False)

    if not dlg.show_dialog():
        return None
    item = dlg.lstViews.SelectedItem
    return item.Tag if item is not None else None


# ─── Interface ─────────────────────────────────────────────────────────────────
def main():
    categorie_id = categorie_surfaces()
    if categorie_id is None:
        show_alert(u"Légendes de couleurs",
                   u"La catégorie « Surfaces » est introuvable dans ce projet.")
        return

    toutes_les_vues = get_selectable_views()
    if not toutes_les_vues:
        show_alert(u"Légendes de couleurs",
                   u"Aucun plan de surface disponible dans ce projet.")
        return

    # Lu une fois ici : sert à la fois à proposer les vues de référence et,
    # plus bas, à savoir quelles légendes remplacer.
    existantes = legendes_par_vue()
    references = vues_avec_legende(toutes_les_vues, existantes)
    if not references:
        show_alert(
            u"Légendes de couleurs",
            u"Aucun plan de surface ne comporte de légende de motif/couleur.\n\n"
            u"Placez-en une à la main, à l'endroit voulu, sur une vue "
            u"quelconque : elle servira de modèle de position pour toutes les "
            u"autres."
        )
        return

    xaml_path = os.path.join(os.path.dirname(__file__), 'MainWindow.xaml')
    wpf = forms.WPFWindow(xaml_path)

    etat = {'schemas': set(), 'vues': set(), 'ref': None}
    dialog_result = {'ok': False}

    def _maj_boutons(s=None, e=None):
        wpf.btnSelectSchemas.IsEnabled = bool(wpf.rbSchemas.IsChecked)
        wpf.btnSelectViews.IsEnabled   = bool(wpf.rbVues.IsChecked)

    def _on_select_ref(s, e):
        choisie = show_ref_view_dialog(references, etat['ref'], owner=wpf)
        wpf.Activate()
        if choisie is not None:
            etat['ref'] = choisie
            try:
                nom = _elem_name(choisie) or u''
            except Exception:
                nom = u''
            wpf.txtRefView.Text = nom or u"(sans nom)"

    def _on_select_schemas(s, e):
        disponibles = schemas_disponibles(toutes_les_vues)
        if not disponibles:
            show_alert(u"Légendes de couleurs",
                       u"Aucun schéma de surface n'a pu être lu sur les plans "
                       u"de surface de ce projet.")
            return
        resultat = show_schemas_picker_dialog(disponibles, etat['schemas'],
                                              owner=wpf)
        wpf.Activate()
        if resultat is not None:
            etat['schemas'] = resultat
            # Format volontairement court : ce compteur est sur la ligne qui
            # fixe la largeur minimale du dialogue (voir MainWindow.xaml).
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
        if etat['ref'] is None:
            show_alert(u"Légendes de couleurs",
                       u"Aucune vue de référence choisie. Cliquez sur "
                       u"\"Choisir la vue de référence...\".")
            return
        if wpf.rbSchemas.IsChecked and not etat['schemas']:
            show_alert(u"Légendes de couleurs",
                       u"Aucun schéma sélectionné. Cliquez sur "
                       u"\"Choisir les schémas...\".")
            return
        if wpf.rbVues.IsChecked and not etat['vues']:
            show_alert(u"Légendes de couleurs",
                       u"Aucune vue sélectionnée. Cliquez sur "
                       u"\"Choisir les vues...\".")
            return
        dialog_result['ok'] = True
        wpf.Close()

    for nom_rb in (u'rbToutes', u'rbSchemas', u'rbVues'):
        getattr(wpf, nom_rb).Checked += _maj_boutons
    _maj_boutons()

    # Liste des types de légende. La première entrée laisse Revit décider :
    # c'est le comportement d'avant cette option, et il doit rester joignable
    # pour un projet dont les types ne seraient pas encore réglés.
    defaut = ComboBoxItem()
    defaut.Content = u"< Type par défaut de Revit >"
    defaut.Tag = None
    wpf.cboTypeLegende.Items.Add(defaut)
    for nom_type, id_type in types_legende():
        item = ComboBoxItem()
        item.Content = nom_type
        item.Tag = id_type
        wpf.cboTypeLegende.Items.Add(item)
    wpf.cboTypeLegende.SelectedItem = defaut

    wpf.btnSelectRefView.Click += _on_select_ref
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

    vue_ref = etat['ref']
    position = None
    for legende in (existantes.get(vue_ref.Id.IntegerValue) or []):
        position = position_legende(legende)
        if position is not None:
            break
    if position is None:
        show_alert(u"Légendes de couleurs",
                   u"La position de la légende de la vue de référence est "
                   u"illisible.")
        return

    # « Tous les plans de surface » en dernier, donc en repli : c'est l'option
    # cochée par défaut, et la seule qui ne dépende d'aucune sélection.
    if wpf.rbSchemas.IsChecked:
        cibles = [v for v in toutes_les_vues if nom_schema(v) in etat['schemas']]
    elif wpf.rbVues.IsChecked:
        cibles = [v for v in toutes_les_vues
                  if v.Id.IntegerValue in etat['vues']]
    else:
        cibles = list(toutes_les_vues)

    type_id = None
    try:
        item = wpf.cboTypeLegende.SelectedItem
        if item is not None:
            type_id = item.Tag
    except Exception:
        pass

    # La vue de référence est laissée telle quelle : la recréer au même endroit
    # ne changerait rien de visible, mais ferait perdre les largeurs de
    # colonnes que l'utilisateur y a réglées — et c'est justement la vue qu'il
    # a soignée.
    cibles = [v for v in cibles if v.Id != vue_ref.Id]

    if not cibles:
        show_alert(u"Légendes de couleurs",
                   u"Aucun plan de surface à traiter (hors vue de référence).")
        return

    n_posees = 0
    n_remplacees = 0
    n_echecs = 0
    n_sans_schema = 0
    journal = []

    with revit.Transaction(u"Poser les légendes de couleurs des surfaces"):
        for v in cibles:
            anciennes = existantes.get(v.Id.IntegerValue) or []

            # Suppression AVANT création, et pas l'inverse : rien ne garantit
            # que Revit accepte une seconde légende de la même catégorie dans
            # une vue, et un refus laisserait l'ancienne en place alors que
            # l'utilisateur a demandé un remplacement. Le prix est qu'un échec
            # de création laisse la vue sans légende — d'où le nom des vues
            # concernées dans le journal.
            supprimees = 0
            for ancienne in anciennes:
                try:
                    doc.Delete(ancienne.Id)
                    supprimees += 1
                except Exception:
                    pass

            cause = None
            try:
                legende = poser_legende(v, categorie_id, position, type_id)
                if legende is None:
                    cause = u"Create a rendu None"
            except Exception as ex:
                legende = None
                cause = cause_lisible(str(ex))
                if cause == _SANS_SCHEMA:
                    n_sans_schema += 1

            if legende is not None:
                if supprimees:
                    n_remplacees += 1
                else:
                    n_posees += 1
            else:
                n_echecs += 1

            # Une ligne par vue, succès compris : c'est le seul moyen de voir
            # d'un coup d'œil si une vue attendue manque à l'appel, ou si elle
            # a bien été traitée mais que Revit a refusé la création.
            journal.append((v, legende is not None, supprimees, cause))

    total = n_posees + n_remplacees
    lignes = [u"{0} légende(s) de motif/couleur posée(s).".format(total)]
    if n_remplacees:
        lignes.append(u"dont {0} en remplacement d'une légende existante."
                      .format(n_remplacees))
    if n_echecs:
        lignes.append(u"{0} vue(s) sans légende (échec de création)."
                      .format(n_echecs))
    if n_sans_schema:
        lignes.append(u"dont {0} sans jeu de couleurs appliqué aux surfaces : "
                      u"appliquez-en un à ces vues, Revit ne peut pas y créer "
                      u"de légende sans cela.".format(n_sans_schema))

    try:
        nom_ref = _elem_name(vue_ref) or u''
    except Exception:
        nom_ref = u''
    lignes.append(u"")
    lignes.append(u"Position reprise de « {0} », laissée inchangée."
                  .format(nom_ref))

    def _nom(v):
        try:
            return _elem_name(v) or u"(vue {0})".format(v.Id.IntegerValue)
        except Exception:
            return u"(vue {0})".format(v.Id.IntegerValue)

    _log(u"# Légendes de motif/couleur des surfaces")
    _log(u"Vue de référence : {0}".format(nom_ref))
    _log(u"Position en plan reprise : X={0:.3f}  Y={1:.3f} (pieds)".format(
        position[0], position[1]))
    _log(u"{0} plan(s) de surface dans le projet, {1} retenu(s) par la portée "
         u"choisie (vue de référence exclue).".format(len(toutes_les_vues),
                                                      len(cibles)))
    _log(u"{0} posée(s), {1} remplacée(s), {2} en échec.".format(
        n_posees, n_remplacees, n_echecs))

    if journal:
        _log(u"**Détail par vue :**")
        for v, ok, supprimees, cause in journal:
            etiquette = u"✔" if ok else u"✖"
            details = []
            if supprimees:
                details.append(u"{0} ancienne(s) supprimée(s)".format(supprimees))
            if cause:
                details.append(cause)
            suffixe = u" — " + u", ".join(details) if details else u""
            _log(u"- {0} {1} [{2}]{3}".format(
                etiquette, _nom(v), nom_schema(v) or u"schéma inconnu", suffixe))

    show_alert(u"Légendes de couleurs", u"\n".join(lignes))


# Pas d'ExternalEvent ici, contrairement à 01_SURF_Etiquette-Masse : celui-ci
# n'existe que pour obtenir la barre d'options discrète de PickObjects. Aucune
# sélection dans la vue n'est demandée par ce bouton, et le script pyRevit
# s'exécute déjà dans un contexte API valide — la transaction passe directement.
if __name__ == '__main__':
    main()
