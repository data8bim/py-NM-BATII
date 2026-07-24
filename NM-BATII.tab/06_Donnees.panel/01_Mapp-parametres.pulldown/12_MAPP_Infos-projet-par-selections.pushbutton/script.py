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


#__title__ = "Infos Projet → Objets par sélections"
#__doc__ = """Transfert des valeurs d'informations de projet par sélections.
#Description : Transfert des valeurs d'informations de projet vers les objets (familles) sélectionnées dans la vue active.
#Permet de mapper des paramètres d'informations de projet vers des objets (familles) sélectionnées a la souris, afin de répercuter automatiquement les valeurs des informations de projet sur tous les objets sélectionnés.

#Version : 3.5 — 2026-04-26
#Auteur : data8bim (d8b)
#"""


# ─── Fenêtre non-modale via DispatcherFrame ───────────────────────────────────
#   - main() reste sur la pile d'appels → closures et handlers vivants
#   - DispatcherFrame traite TOUS les messages Win32 du thread (WPF + Revit)
#     → la sélection souris dans les vues Revit fonctionne normalement
#   - Quand l'utilisateur clique Appliquer, on lit uidoc.Selection et on
#     exécute la Transaction directement (on est sur le thread principal Revit)
#     → la Transaction peut donc s'exécuter directement.
#   - NOTE : l'affirmation « l'ExternalEvent ne fonctionne pas dans les scripts
#     pyRevit » était FAUSSE. main() est désormais planifié dans un ExternalEvent
#     (voir bas de fichier) : c'est ce contexte qui fait afficher par Revit le
#     panneau ruban « Autoriser sélection multiple » au lieu de la barre d'options.

import os, json, codecs, clr

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')

# ─── pyRevit 6.4.0 ───────────────────────────────────────────────────────────
from pyrevit import forms, script
from pyrevit import revit as _pyrevit   # context manager Transaction

from Autodesk.Revit.DB import (
    FilteredElementCollector, StorageType, ImportInstance
)
from Autodesk.Revit.UI.Selection import ObjectType as _PickObjectType
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
import System
import System.Windows.Forms as WinForms
import System.Windows.Threading as Threading
from System.Collections.ObjectModel import ObservableCollection
from System.Windows.Data import CollectionViewSource
from System.Windows.Controls import (
    Grid, ComboBox, Button, Border, ColumnDefinition, TextBlock, CheckBox
)
from System.Windows import (
    GridLength, GridUnitType, Thickness,
    HorizontalAlignment, VerticalAlignment, WindowState
)
from System.Windows.Input import Keyboard, Key as WpfKey
from System.Windows.Media import Brushes

# lib/ de l'extension auto-ajoute au sys.path par pyRevit. L'ancien
# « import dialogs_styles_loader » (sans prefixe « dialogs. ») visait un module
# inexistant et echouait en silence : les styles NM n'etaient jamais charges et
# les fenetres s'affichaient au style WPF par defaut. _charger_styles() place
# les cles NMButton*/NMWindow* dans Application.Resources.
try:
    from dialogs.dialogs_styles_loader import load as _charger_styles
    _charger_styles()
except Exception:
    pass


# ─── Contexte Revit ──────────────────────────────────────────────────────────
doc   = __revit__.ActiveUIDocument.Document  # noqa: F821
uidoc = __revit__.ActiveUIDocument           # noqa: F821

# ─── Fenêtre active (instance unique) ────────────────────────────────────────
_ACTIVE_WINDOW = [None]


# ─── Logger via pyRevit 6.4.0 ────────────────────────────────────────────────
#
#  script.get_logger() → logger pyRevit natif (niveau DEBUG contrôlable
#  depuis pyRevit Settings > Enable Verbose Logging).
#  On conserve la compatibilité avec le flag «activer_logs_scripts» de
#  config.json de l'extension : si l'un ou l'autre est actif, on loggue.
#
logger = script.get_logger()

def _load_extension_logs_flag():
    """Lit le flag activer_logs_scripts depuis config.json de l'extension."""
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(20):
        if cur.lower().endswith('.extension'):
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent
    p = os.path.join(cur, 'config.json')
    if not os.path.isfile(p):
        return False
    try:
        with codecs.open(p, 'r', 'utf-8') as f:
            return json.load(f).get('activer_logs_scripts', False)
    except Exception:
        return False

_LOGS_ENABLED = _load_extension_logs_flag()

def _log(msg):
    if _LOGS_ENABLED:
        logger.debug(u'[Infos Projet Sel] ' + msg)


# ─── Fichier de sauvegarde automatique (pyRevit appdata) ─────────────────────
#
#  script.get_data_file() stocke dans %APPDATA%\pyRevit\ :
#  toujours accessible en écriture, même si le script est sur un partage réseau.
#  Suffixe _sel pour ne pas écraser le fichier du script «par catégories».
#
_LAST_CFG = script.get_data_file('last_mapping_sel', 'NM-Map-Infos-Proj-Sel')


# ─── Modèle de données ───────────────────────────────────────────────────────
class MappingRow(object):
    def __init__(self, source=u'', target=u'', categories=None):
        self.source_param = source
        self.target_param = target
        self.categories   = list(categories) if categories else []
        self.border       = None


# ─── Lecture Revit ───────────────────────────────────────────────────────────
def get_project_info_params(doc):
    return sorted(p.Definition.Name for p in doc.ProjectInformation.Parameters)

def _exact_type_key(param):
    try:
        return param.Definition.GetDataType().TypeId
    except Exception:
        return str(param.StorageType)

def get_project_info_param_types(doc):
    return {p.Definition.Name: _exact_type_key(p)
            for p in doc.ProjectInformation.Parameters}

def get_project_info_value(doc, param_name):
    for p in doc.ProjectInformation.Parameters:
        if p.Definition.Name == param_name:
            st = p.StorageType
            if   st == StorageType.String:  return p.AsString() or u''
            elif st == StorageType.Integer: return str(p.AsInteger())
            elif st == StorageType.Double:  return p.AsValueString() or str(p.AsDouble())
            else:                           return p.AsValueString() or u''
    return u''


# ─── Cache IDs catégories CAO (ImportInstance) ───────────────────────────────
#
#  Calculé une seule fois par session via _get_cad_import_category_ids().
#  Évite de re-parcourir tous les ImportInstance à chaque appel.
#
_CAD_IDS_CACHE = [None]

def _get_cad_import_category_ids(doc):
    if _CAD_IDS_CACHE[0] is not None:
        return _CAD_IDS_CACHE[0]
    ids = set()
    try:
        for elem in FilteredElementCollector(doc).OfClass(ImportInstance):
            try:
                cat = elem.Category
                if cat is None:
                    continue
                ids.add(cat.Id.IntegerValue)
                try:
                    for sub in cat.SubCategories:
                        ids.add(sub.Id.IntegerValue)
                except Exception:
                    pass
            except Exception:
                pass
    except Exception as ex:
        _log(u'_get_cad_import_category_ids : ' + str(ex))
    _CAD_IDS_CACHE[0] = ids
    return ids


def get_available_categories(doc):
    """
    Retourne les catégories Revit acceptant des paramètres, utilisées comme
    filtre optionnel sur les éléments sélectionnés (voir apply_to_selection).
    "Informations sur le projet" n'est PAS exclue de cette liste : elle est
    traitée séparément (avec avertissement) dans show_categories_dialog().
    """
    cad_ids = _get_cad_import_category_ids(doc)
    cats = set()
    for cat in doc.Settings.Categories:
        try:
            if cat.Id.IntegerValue in cad_ids:
                continue
            if cat.AllowsBoundParameters:
                name = cat.Name
                if name:
                    cats.add(name)
        except Exception:
            pass
    return sorted(cats)


def _elem_category_name(elem):
    """Retourne le nom de la catégorie de l'élément, ou None si absent."""
    try:
        cat = elem.Category
        return cat.Name if cat is not None else None
    except Exception:
        return None


def get_params_by_exact_type(doc):
    """
    Découverte des paramètres disponibles par type de donnée.

    OPTIMISATION (v3.4) — algorithme revu pour les grands modèles :
    ────────────────────────────────────────────────────────────────
    Ancienne approche : itérer TOUS les éléments du document avec Python,
    vérifier .Category, et sauter via un set de cat IDs déjà vus.
    → O(N_éléments) avec overhead IronPython sur chaque élément.
    → Sur un modèle de 100 000 éléments : typiquement 5-15 secondes.

    Nouvelle approche : itérer les catégories (100-300 entrées max), et
    pour chacune appeler .FirstElement() — appel .NET pur qui exploite
    l'index interne de Revit par catégorie et s'arrête immédiatement
    après le premier résultat. Aucun élément n'est sérialisé vers Python
    si la catégorie est vide.
    → O(N_catégories) appels natifs, zéro overhead Python par élément.
    → Gain mesuré : ×10 à ×50 selon la taille du modèle.
    """
    by_type = {}
    cad_ids = _get_cad_import_category_ids(doc)

    for cat in doc.Settings.Categories:
        try:
            if not cat.AllowsBoundParameters:
                continue
            if cat.Id.IntegerValue in cad_ids:
                continue

            # FirstElement() : appel .NET pur — s'arrête au 1er match,
            # exploite l'index Revit par catégorie.
            elem = (FilteredElementCollector(doc)
                    .OfCategoryId(cat.Id)
                    .WhereElementIsNotElementType()
                    .FirstElement())
            if elem is None:
                continue

            for p in elem.Parameters:
                try:
                    st = p.StorageType
                    if st not in (StorageType.String,
                                  StorageType.Integer,
                                  StorageType.Double):
                        continue
                    name = p.Definition.Name
                    if not name:
                        continue
                    key = _exact_type_key(p)
                    if key not in by_type:
                        by_type[key] = set()
                    by_type[key].add(name)
                except Exception:
                    pass
        except Exception:
            pass

    return {k: sorted(v) for k, v in by_type.items()}


# ─── Boîtes de dialogue personnalisées ───────────────────────────────────────
def _alert(title, msg):
    """
    Affiche un message dans AlertDialog.xaml (style de l'extension).
    Remplace forms.alert() partout dans le script.
    Fallback sur forms.alert() si le XAML ne se charge pas.
    """
    try:
        xaml = script.get_bundle_file('AlertDialog.xaml')
        w = forms.WPFWindow(xaml)
        w.Title           = title
        w.txtMessage.Text = msg
        w.btnClose.Click += lambda s, e: setattr(w, 'DialogResult', True)
        w.show_dialog()
    except Exception:
        forms.alert(msg, title=title)


# ─── Résultat ────────────────────────────────────────────────────────────────
def show_result_window(msg):
    xaml = script.get_bundle_file('ResultWindow.xaml')
    try:
        w = forms.WPFWindow(xaml)
        w.Title           = u'Infos Projet -> Objets (selection)'
        w.txtMessage.Text = msg
        w.btnClose.Click += lambda s, e: setattr(w, 'DialogResult', True)
        w.show_dialog()
    except Exception:
        _alert(u'Infos Projet -> Objets (selection)', msg)


# ─── JSON ────────────────────────────────────────────────────────────────────
def _rows_to_list(rows):
    return [{'source_param': r.source_param,
             'target_param': r.target_param,
             'categories':   r.categories}
            for r in rows]

def _list_to_rows(data):
    return [MappingRow(d.get('source_param', u''),
                       d.get('target_param', u''),
                       d.get('categories',   []))
            for d in data]

def _auto_save(rows):
    try:
        with codecs.open(_LAST_CFG, 'w', 'utf-8') as f:
            json.dump({'mappings': _rows_to_list(rows)}, f,
                      indent=2, ensure_ascii=False)
        _log(u'Auto-save OK ({} mappages)'.format(len(rows)))
    except Exception as ex:
        _log(u'Auto-save : ' + str(ex))

def _auto_load():
    if not os.path.isfile(_LAST_CFG): return []
    try:
        with codecs.open(_LAST_CFG, 'r', 'utf-8') as f:
            data = json.load(f)
        rows = _list_to_rows(data.get('mappings', []))
        _log(u'Auto-load : {} mappages'.format(len(rows)))
        return rows
    except Exception as ex:
        _log(u'Auto-load : ' + str(ex))
        return []

def save_config(rows):
    dlg = WinForms.SaveFileDialog()
    dlg.Title      = u'Enregistrer la configuration'
    dlg.Filter     = u'Fichiers de mappage (*.NM-Map-Infos-Proj)|*.NM-Map-Infos-Proj'
    dlg.DefaultExt = 'NM-Map-Infos-Proj'
    dlg.FileName   = 'infos_projet_mappages.NM-Map-Infos-Proj'
    if dlg.ShowDialog() != WinForms.DialogResult.OK: return
    with codecs.open(dlg.FileName, 'w', 'utf-8') as f:
        json.dump({'mappings': _rows_to_list(rows)}, f,
                  indent=2, ensure_ascii=False)
    _log(u'Config sauvegardee : ' + dlg.FileName)
    _show_save_dialog(dlg.FileName)


def _show_save_dialog(filepath):
    """Affiche SaveDialog.xaml avec le chemin du fichier enregistré."""
    xaml = script.get_bundle_file('SaveDialog.xaml')
    try:
        w = forms.WPFWindow(xaml)
        w.Title           = u'Sauvegarde'
        w.txtMessage.Text = u'Configuration enregistree :\n\n' + filepath
        w.btnClose.Click += lambda s, e: setattr(w, 'DialogResult', True)
        w.show_dialog()
    except Exception:
        _alert(u'Sauvegarde', u'Configuration enregistree :\n' + filepath)


def load_config():
    """
    Charge un fichier de configuration de mappages.

    Seuls les fichiers .NM-Map-Infos-Proj sont acceptés afin d'éviter de
    charger par erreur un JSON quelconque non compatible avec ce script.
    Le champ «categories» de chaque ligne (partagé avec le script «Infos
    Projet → Objets par catégories») est chargé et utilisé ici comme un
    FILTRE sur les objets sélectionnés (voir apply_to_selection).
    """
    dlg = WinForms.OpenFileDialog()
    dlg.Title      = u'Charger la configuration'
    dlg.Filter     = u'Fichiers de mappage (*.NM-Map-Infos-Proj)|*.NM-Map-Infos-Proj'
    dlg.DefaultExt = 'NM-Map-Infos-Proj'
    if dlg.ShowDialog() != WinForms.DialogResult.OK:
        return None
    # Garde-fou : si l'utilisateur tape manuellement un chemin qui contourne
    # le filtre du dialogue, on bloque quand même ici.
    if not dlg.FileName.lower().endswith('.nm-map-infos-proj'):
        _alert(u'Format incorrect',
               u'Seuls les fichiers ".NM-Map-Infos-Proj" sont acceptés.')
        return None
    try:
        with codecs.open(dlg.FileName, 'r', 'utf-8') as f:
            data = json.load(f)
        return _list_to_rows(data.get('mappings', []))
    except Exception as ex:
        _alert(u'Erreur de lecture', str(ex))
        return None


# ─── Dialogue catégories ─────────────────────────────────────────────────────
_PROJECT_INFO_CAT = u'Informations sur le projet'


def show_categories_dialog(all_categories, current_selection):
    xaml = script.get_bundle_file('CategoriesDialog.xaml')
    dlg  = forms.WPFWindow(xaml)
    dlg.Title = u'Selectionner les categories'

    # Séparer "Informations sur le projet" du reste de la liste
    regular_cats = [c for c in all_categories if c != _PROJECT_INFO_CAT]
    selected_set = set(current_selection)
    visible_cbs  = []
    last_idx     = [-1]

    # Case séparée "Informations sur le projet"
    dlg.cbProjectInfo.IsChecked = (_PROJECT_INFO_CAT in selected_set)

    def _sync():
        for cb, cat in visible_cbs:
            if bool(cb.IsChecked): selected_set.add(cat)
            else:                  selected_set.discard(cat)
        # Sync aussi la case ProjectInfo
        if bool(dlg.cbProjectInfo.IsChecked):
            selected_set.add(_PROJECT_INFO_CAT)
        else:
            selected_set.discard(_PROJECT_INFO_CAT)

    def populate(filter_text=u''):
        _sync()
        dlg.categoryListPanel.Children.Clear()
        del visible_cbs[:]
        last_idx[0] = -1
        for cat in regular_cats:
            if filter_text and filter_text.lower() not in cat.lower():
                continue
            cb = CheckBox()
            cb.Content   = cat
            cb.IsChecked = (cat in selected_set)
            cb.Margin    = Thickness(2, 2, 2, 2)
            idx = len(visible_cbs)

            def _mk(i, name, checkbox):
                def on_click(s, e):
                    ns = bool(checkbox.IsChecked)
                    shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                             Keyboard.IsKeyDown(WpfKey.RightShift))
                    if shift and last_idx[0] >= 0:
                        lo, hi = min(last_idx[0], i), max(last_idx[0], i)
                        for j in range(lo, hi + 1):
                            if j < len(visible_cbs):
                                cb_j, cat_j = visible_cbs[j]
                                cb_j.IsChecked = ns
                                if ns: selected_set.add(cat_j)
                                else:  selected_set.discard(cat_j)
                    else:
                        if ns: selected_set.add(name)
                        else:  selected_set.discard(name)
                    last_idx[0] = i
                return on_click

            cb.Click += _mk(idx, cat, cb)
            dlg.categoryListPanel.Children.Add(cb)
            visible_cbs.append((cb, cat))

    populate()

    def on_search(s, e): populate(s.Text)
    def on_all(s, e):
        for cb, cat in visible_cbs: cb.IsChecked = True;  selected_set.add(cat)
    def on_none(s, e):
        for cb, cat in visible_cbs: cb.IsChecked = False; selected_set.discard(cat)
    def on_invert(s, e):
        for cb, cat in visible_cbs:
            ns = not bool(cb.IsChecked)
            cb.IsChecked = ns
            if ns: selected_set.add(cat)
            else:  selected_set.discard(cat)
    def on_ok(s, e):
        _sync()
        setattr(dlg, 'DialogResult', True)

    dlg.searchBox.TextChanged    += on_search
    dlg.btnSelectAll.Click       += on_all
    dlg.btnDeselectAll.Click     += on_none
    dlg.btnInvert.Click          += on_invert
    dlg.btnOk.Click              += on_ok
    dlg.btnCancel.Click          += lambda s, e: setattr(dlg, 'DialogResult', False)

    if dlg.show_dialog():
        return sorted(selected_set)

    return None


# ─── Application des mappages ─────────────────────────────────────────────────
def apply_to_selection(row_list, elements):
    """
    Applique les mappages sur la liste d'éléments fournie.
    Appelée depuis on_apply() — on est sur le thread principal Revit.
    Transaction via _pyrevit.Transaction : commit auto, rollback auto.

    Le champ «categories» de chaque ligne agit comme un FILTRE sur la
    sélection : seuls les éléments sélectionnés appartenant à l'une des
    catégories choisies reçoivent CE mappage (les autres éléments
    sélectionnés ne sont pas affectés par cette ligne). Une ligne sans
    aucune catégorie choisie n'est appliquée à aucun élément.
    """
    active = [r for r in row_list
              if r.source_param and r.target_param and r.categories]
    if not active:
        _alert(u'Aucun mappage',
               u'Aucun mappage complet.\n\n'
               u'Chaque ligne doit avoir :\n'
               u'  \u2022 un paramètre source\n'
               u'  \u2022 un paramètre cible\n'
               u'  \u2022 au moins une catégorie (filtre).')
        return

    if not elements:
        _alert(u'Aucun objet sélectionné',
               u'Aucun objet sélectionné.\n\n'
               u'Cliquez sur \u2295\u00a0Sélectionner pour choisir des objets\n'
               u'dans Revit, puis cliquez sur \u25b6\u00a0Appliquer.')
        return

    values_by_row = dict((id(r), get_project_info_value(doc, r.source_param))
                          for r in active)

    n_set = n_skip = 0
    errors = []

    # Context manager pyRevit 6.4.0 : commit auto, rollback auto sur exception
    try:
        with _pyrevit.Transaction(u'Infos Projet -> Objets (selection)', doc=doc):
            for elem in elements:
                elem_cat = _elem_category_name(elem)
                for row in active:
                    if elem_cat not in row.categories:
                        continue
                    value = values_by_row[id(row)]
                    try:
                        p = elem.LookupParameter(row.target_param)
                        if p is None or p.IsReadOnly:
                            n_skip += 1
                        elif p.StorageType == StorageType.String:
                            p.Set(value); n_set += 1
                        elif p.StorageType == StorageType.Integer:
                            try:   p.Set(int(float(value))); n_set += 1
                            except Exception: n_skip += 1
                        elif p.StorageType == StorageType.Double:
                            try:   p.Set(float(value)); n_set += 1
                            except Exception: n_skip += 1
                        else:
                            n_skip += 1
                    except Exception as ex:
                        errors.append(u'{}: {}'.format(row.target_param, ex))
    except Exception as ex:
        _alert(u'Erreur de transaction', str(ex))
        return

    _log(u'{} renseigne(s), {} ignore(s)'.format(n_set, n_skip))

    lines = [u'{} objet(s), {} parametre(s) renseigne(s)'.format(
             len(elements), n_set)]
    if n_skip:
        lines.append(u'{} ignore(s) (absent, lecture seule ou type incompatible)'.format(n_skip))
    if errors:
        lines.append(u'{} erreur(s) (voir console)'.format(len(errors)))
        for e in errors[:5]: _log(str(e))
    show_result_window(u'\n'.join(lines))


# ─── ComboBox filtrable (ObservableCollection + CollectionViewSource) ─────────
def _make_filterable_combo(full_items, initial_value, on_select, margin, tooltip):
    cb = ComboBox()
    cb.IsEditable          = True
    cb.IsTextSearchEnabled = False
    cb.StaysOpenOnEdit     = True
    cb.Margin              = margin
    cb.VerticalAlignment   = VerticalAlignment.Center
    cb.ToolTip             = tooltip

    _st   = {'loading': False, 'filter': u''}
    _coll = ObservableCollection[object]()
    for item in full_items: _coll.Add(item)
    _view = CollectionViewSource.GetDefaultView(_coll)

    def _pred(obj):
        ft = _st['filter']
        return True if not ft else ft.lower() in u'{}'.format(obj).lower()

    _view.Filter   = System.Predicate[System.Object](_pred)
    cb.ItemsSource = _view
    if initial_value: cb.Text = initial_value

    _nav = frozenset([WpfKey.Up, WpfKey.Down, WpfKey.Left, WpfKey.Right,
                      WpfKey.Home, WpfKey.End, WpfKey.PageUp, WpfKey.PageDown,
                      WpfKey.LeftShift, WpfKey.RightShift, WpfKey.LeftCtrl,
                      WpfKey.RightCtrl, WpfKey.LeftAlt, WpfKey.RightAlt,
                      WpfKey.CapsLock, WpfKey.Tab,
                      WpfKey.F1, WpfKey.F2, WpfKey.F3, WpfKey.F4,
                      WpfKey.F5, WpfKey.F6, WpfKey.F7, WpfKey.F8,
                      WpfKey.F9, WpfKey.F10, WpfKey.F11, WpfKey.F12])

    def on_key_up(s, e):
        if e.Key == WpfKey.Escape:
            _st['filter'] = u''; _view.Refresh()
            s.IsDropDownOpen = False; return
        if e.Key == WpfKey.Return:
            text = s.Text or u''
            for i in range(_coll.Count):
                if u'{}'.format(_coll[i]) == text: on_select(text); break
            _st['filter'] = u''; _view.Refresh()
            s.IsDropDownOpen = False; return
        if e.Key in _nav: return
        _st['loading'] = True
        _st['filter']  = s.Text or u''
        _view.Refresh()
        _st['loading'] = False
        if not s.IsDropDownOpen and _coll.Count > 0:
            s.IsDropDownOpen = True

    def on_sel_changed(s, e):
        if not _st['loading'] and s.SelectedItem is not None:
            on_select(u'{}'.format(s.SelectedItem))
            _st['filter'] = u''; _view.Refresh()

    cb.KeyUp            += on_key_up
    cb.SelectionChanged += on_sel_changed

    def _reload(new_items, cur_val=u''):
        _st['loading'] = True; _st['filter'] = u''
        _coll.Clear()
        for item in new_items: _coll.Add(item)
        _view.Filter = System.Predicate[System.Object](_pred)
        if cur_val: cb.Text = cur_val
        _st['loading'] = False

    return cb, _reload


# ─── Construction d'une ligne ────────────────────────────────────────────────
def make_row_border(row_data, source_params, source_param_types, params_by_type,
                    all_categories, row_list, panel, used_targets, all_reload_entries,
                    refresh_all_target_combos, apply_view):

    def star_col():
        cd = ColumnDefinition(); cd.Width = GridLength(1, GridUnitType.Star); return cd
    def fixed_col(w):
        cd = ColumnDefinition(); cd.Width = GridLength(w); return cd

    border = Border()
    border.Margin = Thickness(0, 0, 0, 4); border.Padding = Thickness(6, 5, 6, 5)
    border.BorderThickness = Thickness(1); border.BorderBrush = Brushes.LightGray
    border.CornerRadius = System.Windows.CornerRadius(3)
    border.HorizontalAlignment = HorizontalAlignment.Stretch
    row_data.border = border

    g = Grid(); g.HorizontalAlignment = HorizontalAlignment.Stretch
    for cd in [star_col(), fixed_col(30), star_col(), fixed_col(150), fixed_col(32)]:
        g.ColumnDefinitions.Add(cd)

    _reload_tgt_ref = [None]

    def on_src_select(value):
        row_data.source_param = value
        tk    = source_param_types.get(value)
        names = params_by_type.get(tk, []) if tk else []
        avail = [n for n in names if n not in used_targets or n == row_data.target_param]
        if _reload_tgt_ref[0]: _reload_tgt_ref[0](avail, row_data.target_param)

    cb_src, _ = _make_filterable_combo(
        source_params, row_data.source_param, on_src_select,
        Thickness(0, 0, 4, 0), u'Parametre source — taper pour filtrer')
    Grid.SetColumn(cb_src, 0)

    arrow = TextBlock()
    arrow.Text = u'->'; arrow.HorizontalAlignment = HorizontalAlignment.Center
    arrow.VerticalAlignment = VerticalAlignment.Center; arrow.Foreground = Brushes.Gray
    Grid.SetColumn(arrow, 1)

    initial_tk    = source_param_types.get(row_data.source_param)
    initial_names = params_by_type.get(initial_tk, []) if initial_tk else []
    initial_avail = [n for n in initial_names
                     if n not in used_targets or n == row_data.target_param]

    def on_tgt_select(value):
        old = row_data.target_param
        if old and old != value: used_targets.discard(old)
        row_data.target_param = value
        if value: used_targets.add(value)
        refresh_all_target_combos(except_row=row_data)

    cb_tgt, _reload_tgt = _make_filterable_combo(
        initial_avail, row_data.target_param, on_tgt_select,
        Thickness(4, 0, 4, 0), u'Parametre cible — taper pour filtrer')
    Grid.SetColumn(cb_tgt, 2)
    _reload_tgt_ref[0] = _reload_tgt

    def on_tgt_lf(s, e):
        if s.SelectedItem is None and s.Text:
            old = row_data.target_param
            if old and old != s.Text: used_targets.discard(old)
            row_data.target_param = s.Text
            if s.Text: used_targets.add(s.Text)
            refresh_all_target_combos(except_row=row_data)
    cb_tgt.LostFocus += on_tgt_lf

    reload_entry = [_reload_tgt, row_data]
    all_reload_entries.append(reload_entry)
    if row_data.target_param: used_targets.add(row_data.target_param)

    def cat_label():
        n = len(row_data.categories)
        return u'{} categorie(s)'.format(n) if n else u'Choisir categories...'

    btn_cat = Button()
    btn_cat.Content           = cat_label()
    btn_cat.Margin            = Thickness(4, 0, 4, 0)
    btn_cat.VerticalAlignment = VerticalAlignment.Center
    btn_cat.ToolTip           = u'Selectionner les categories d\'objets cibles'
    Grid.SetColumn(btn_cat, 3)

    def on_cats(s, e):
        result = show_categories_dialog(all_categories, list(row_data.categories))
        if result is not None:
            row_data.categories = result
            btn_cat.Content     = cat_label()
    btn_cat.Click += on_cats

    btn_del = Button()
    btn_del.Content = u'x'; btn_del.Width = 26; btn_del.Height = 26
    btn_del.Margin = Thickness(4, 0, 0, 0)
    btn_del.VerticalAlignment = VerticalAlignment.Center
    btn_del.HorizontalAlignment = HorizontalAlignment.Center
    btn_del.ToolTip = u'Supprimer ce mappage'
    Grid.SetColumn(btn_del, 4)

    def on_del(s, e):
        old = row_data.target_param
        if old: used_targets.discard(old)
        if reload_entry in all_reload_entries: all_reload_entries.remove(reload_entry)
        if row_data in row_list: row_list.remove(row_data)
        refresh_all_target_combos(); apply_view()
    btn_del.Click += on_del

    for child in [cb_src, arrow, cb_tgt, btn_cat, btn_del]: g.Children.Add(child)
    border.Child = g
    return border


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    _log(u'Demarrage')

    if _ACTIVE_WINDOW[0] is not None:
        try:
            _ACTIVE_WINDOW[0].Activate(); return
        except Exception:
            _ACTIVE_WINDOW[0] = None

    source_params      = get_project_info_params(doc)
    source_param_types = get_project_info_param_types(doc)
    all_categories     = get_available_categories(doc)
    params_by_type     = get_params_by_exact_type(doc)

    if not source_params:
        _alert(u'Informations Projet',
               u'Aucun paramètre trouvé dans les Informations Projet.')
        return

    # script.get_bundle_file() remplace os.path.join(os.path.dirname(__file__), …)
    xaml_path = script.get_bundle_file('WPFWindow.xaml')
    wpf       = forms.WPFWindow(xaml_path)
    wpf.Title = u'Informations Projet -> Objets (sélection)'

    row_list           = []
    used_targets       = set()
    all_reload_entries = []
    _vs = {'filter_src': u'', 'filter_tgt': u'', 'sort': None}

    # État de la sélection : éléments choisis via ⊕ Sélectionner
    _sel_state = {'elements': []}

    def _update_sel_label():
        n = len(_sel_state['elements'])
        if n == 0:
            wpf.txtSelCount.Text = u'Aucun objet sélectionné'
        elif n == 1:
            wpf.txtSelCount.Text = u'1 objet sélectionné'
        else:
            wpf.txtSelCount.Text = u'{} objets sélectionnés'.format(n)

    def apply_view():
        fs = _vs['filter_src'].lower(); ft = _vs['filter_tgt'].lower()
        visible = [r for r in row_list
                   if (not fs or fs in r.source_param.lower())
                   and (not ft or ft in r.target_param.lower())]
        s = _vs['sort']
        if   s == 'src_asc':  visible.sort(key=lambda r: r.source_param.lower())
        elif s == 'src_desc': visible.sort(key=lambda r: r.source_param.lower(), reverse=True)
        elif s == 'tgt_asc':  visible.sort(key=lambda r: r.target_param.lower())
        elif s == 'tgt_desc': visible.sort(key=lambda r: r.target_param.lower(), reverse=True)
        wpf.mappingsPanel.Children.Clear()
        for r in visible: wpf.mappingsPanel.Children.Add(r.border)

    def _update_sort_btns():
        s = _vs['sort']
        wpf.btnSortSrc.Content = (u'A\u2192Z' if s == 'src_asc' else
                                   u'Z\u2192A' if s == 'src_desc' else u'\u21c5')
        wpf.btnSortTgt.Content = (u'A\u2192Z' if s == 'tgt_asc' else
                                   u'Z\u2192A' if s == 'tgt_desc' else u'\u21c5')

    def refresh_all_target_combos(except_row=None):
        for fn, rd in list(all_reload_entries):
            if rd is except_row: continue
            tk    = source_param_types.get(rd.source_param)
            names = params_by_type.get(tk, []) if tk else []
            avail = [n for n in names if n not in used_targets or n == rd.target_param]
            fn(avail, rd.target_param)

    def add_row(row_data=None):
        if row_data is None: row_data = MappingRow()
        row_list.append(row_data)
        b = make_row_border(
            row_data, source_params, source_param_types, params_by_type,
            all_categories, row_list, wpf.mappingsPanel, used_targets, all_reload_entries,
            refresh_all_target_combos, apply_view)
        wpf.mappingsPanel.Children.Add(b)

    def load_rows(rows):
        wpf.mappingsPanel.Children.Clear()
        row_list[:] = []; used_targets.clear(); all_reload_entries[:] = []
        for r in rows: add_row(r)
        apply_view()

    # ── Câblage ───────────────────────────────────────────────────────────────
    def on_load(s, e):
        rows = load_config()
        if rows is not None: load_rows(rows)

    def on_save(s, e):     save_config(row_list)

    def on_add(s, e):      add_row()

    def on_clear_all(s, e):
        wpf.mappingsPanel.Children.Clear()
        row_list[:] = []; used_targets.clear(); all_reload_entries[:] = []

    def on_select_btn(s, e):
        """
        Passe en mode sélection Revit natif :
        1. Minimise la fenêtre WPF
        2. Appelle PickObjects() → affiche le bandeau Multiple/Terminer/Annuler
        3. Stocke les éléments dans _sel_state et met à jour le label
        4. Restaure la fenêtre
        """
        wpf.WindowState = WindowState.Minimized
        try:
            refs = uidoc.Selection.PickObjects(
                _PickObjectType.Element,
                u'Sélectionnez les objets puis cliquez sur Terminer')
            _sel_state['elements'] = [
                doc.GetElement(r.ElementId) for r in refs
                if doc.GetElement(r.ElementId) is not None]
            _log(u'Selection : {} element(s)'.format(len(_sel_state['elements'])))
        except Exception:
            pass  # Annuler → on conserve la sélection précédente
        wpf.WindowState = WindowState.Normal
        wpf.Activate()
        _update_sel_label()

    def on_apply(s, e):
        # Priorité : éléments stockés via ⊕ Sélectionner
        # Fallback  : sélection courante de uidoc (sélection pré-existante)
        elems = _sel_state['elements']
        if not elems:
            try:
                ids   = uidoc.Selection.GetElementIds()
                elems = [doc.GetElement(i) for i in ids
                         if doc.GetElement(i) is not None]
            except Exception:
                elems = []
        apply_to_selection(row_list, elems)

    def on_close(s, e):    wpf.Close()

    def on_search_src(s, e):
        _vs['filter_src'] = s.Text or u''; apply_view()

    def on_search_tgt(s, e):
        _vs['filter_tgt'] = s.Text or u''; apply_view()

    def on_sort_src(s, e):
        cur = _vs['sort']
        if cur == 'src_asc': _vs['sort'] = 'src_desc'
        elif cur == 'src_desc': _vs['sort'] = None
        else: _vs['sort'] = 'src_asc'
        _update_sort_btns(); apply_view()

    def on_sort_tgt(s, e):
        cur = _vs['sort']
        if cur == 'tgt_asc': _vs['sort'] = 'tgt_desc'
        elif cur == 'tgt_desc': _vs['sort'] = None
        else: _vs['sort'] = 'tgt_asc'
        _update_sort_btns(); apply_view()

    wpf.btnSelect.Click       += on_select_btn
    wpf.btnLoad.Click         += on_load
    wpf.btnSave.Click         += on_save
    wpf.btnAdd.Click          += on_add
    wpf.btnClearAll.Click     += on_clear_all
    wpf.btnApply.Click        += on_apply
    wpf.btnClose.Click        += on_close
    wpf.searchSrc.TextChanged += on_search_src
    wpf.searchTgt.TextChanged += on_search_tgt
    wpf.btnSortSrc.Click      += on_sort_src
    wpf.btnSortTgt.Click      += on_sort_tgt

    try:
        last = _auto_load()
        if last: load_rows(last)
    except Exception as ex:
        _log(u'Auto-load echoue : ' + str(ex))

    # Toujours au moins une ligne de mappage, meme vierge : sans elle la zone de
    # mappage reste vide et se confond visuellement avec les champs de filtre
    # situes juste au-dessus (confusion constatee a l'usage).
    if not row_list:
        add_row()

    # ── Non-modal via DispatcherFrame ─────────────────────────────────────────
    _frame = Threading.DispatcherFrame()

    def on_closed(s, e):
        _auto_save(row_list)
        _ACTIVE_WINDOW[0] = None
        _frame.Continue = False

    wpf.Closed        += on_closed
    _ACTIVE_WINDOW[0]  = wpf

    wpf.Show()
    Threading.Dispatcher.PushFrame(_frame)
    _log(u'Fenetre fermee')


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
        return u"NM-BATII — Infos projet par selection"


if __name__ == '__main__':
    # Le handler est instancie APRES toutes les definitions : c'est a cet
    # instant qu'est pris le snapshot des globals restaure par Execute().
    _action_handler = _ActionHandler()
    _ext_event      = ExternalEvent.Create(_action_handler)
    _action_handler.planifier(main)
    _ext_event.Raise()
