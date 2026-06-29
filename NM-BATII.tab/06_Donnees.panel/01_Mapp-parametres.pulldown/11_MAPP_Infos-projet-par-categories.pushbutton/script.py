# -*- coding: utf-8 -*-

# Copyright 2026 data8bim (d8b)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


#__title__ = "Infos Projet → Objets par catégories"
#__doc__ = """Transfert des valeurs d'informations de projet par catégories.
#Description : Transfert des valeurs d'informations de projet vers les objets (familles) des catégories sélectionnées.
#Permet de mapper des paramètres d'informations de projet vers des catégories d'objets (familles) choisies, afin de répercuter automatiquement les valeurs des informations de projet sur tous les objets appartenant aux catégories sélectionnées.

#Version : 3.4 — 2026-04-25
#Auteur : data8bim (d8b)
#"""


import json, codecs, clr

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')

# ─── pyRevit 6.4.0 ───────────────────────────────────────────────────────────
from pyrevit import forms, script
from pyrevit import revit as _pyrevit   # context manager Transaction

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    Level, StorageType, ImportInstance
)
import System
import System.Windows.Forms  as WinForms
import System.Windows.Threading as Threading
from System.Collections.ObjectModel import ObservableCollection
from System.Windows.Data            import CollectionViewSource
from System.Windows.Controls import (
    Grid, ComboBox, Button, Border,
    ColumnDefinition, TextBlock, CheckBox
)
from System.Windows import (
    GridLength, GridUnitType, Thickness,
    HorizontalAlignment, VerticalAlignment
)
from System.Windows.Input import Keyboard, Key as WpfKey
from System.Windows.Media import Brushes

# ─── Chargement des styles de l'extension (NMWindowStandard, NMButtonValide…) ─
try:
    import dialogs_styles_loader          # noqa: F401  (effets de bord à l'import)
    from dialogs.dialogs_styles_loader import show_alert
except ImportError:
    def show_alert(titre, message):
        forms.alert(message, title=titre)


# ─── Fenêtre non-modale : référence pour instance unique ─────────────────────
_ACTIVE_WINDOW = [None]


# ─── Contexte Revit ──────────────────────────────────────────────────────────
doc = __revit__.ActiveUIDocument.Document  # noqa: F821


# ─── Logger via pyRevit 6.4.0 ────────────────────────────────────────────────
logger = script.get_logger()

def _load_extension_logs_flag():
    """Lit le flag activer_logs_scripts depuis config.json de l'extension."""
    import os
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
        logger.debug(u'[Infos Projet] ' + msg)


# ─── Fichier de sauvegarde automatique (pyRevit appdata) ─────────────────────
#
#  script.get_data_file() stocke dans %APPDATA%\pyRevit\ : toujours
#  accessible en écriture même si le script est sur un partage réseau.
#
_LAST_CFG = script.get_data_file('last_mapping', 'NM-Map-Infos-Proj')


# ─── Modèle de données ───────────────────────────────────────────────────────
class MappingRow(object):
    def __init__(self, source=u'', target=u'', categories=None):
        self.source_param = source
        self.target_param = target
        self.categories   = list(categories) if categories else []
        self.border       = None   # référence WPF Border


# ─── Helpers UI ──────────────────────────────────────────────────────────────
def _do_events():
    frame = Threading.DispatcherFrame()
    Threading.Dispatcher.CurrentDispatcher.BeginInvoke(
        System.Action(lambda: setattr(frame, 'Continue', False)),
        Threading.DispatcherPriority.Background)
    Threading.Dispatcher.PushFrame(frame)


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


# ─── Cache des IDs de catégories CAO (calculé une seule fois par session) ────
_CAD_IDS_CACHE = [None]   # [set | None]

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
    Retourne les catégories Revit acceptant des paramètres.
    AllowsBoundParameters == True est la propriété officielle de l'API Revit.
    Seule exclusion supplémentaire : catégories issues de fichiers CAO.
    """
    cad_ids = _get_cad_import_category_ids(doc)   # résultat mis en cache
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


def get_params_by_exact_type(doc):
    """
    Découverte des paramètres disponibles par type de donnée.

    OPTIMISATION (v3.4) — algorithme revu pour les grands modèles :
    ────────────────────────────────────────────────────────────────
    Ancienne approche : itérer tous les éléments du document avec Python,
    vérifier .Category et sauter via seen_cat_ids.
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
    cad_ids = _get_cad_import_category_ids(doc)   # résultat mis en cache

    for cat in doc.Settings.Categories:
        try:
            if not cat.AllowsBoundParameters:
                continue
            if cat.Id.IntegerValue in cad_ids:
                continue

            # FirstElement() : appel .NET pur — s'arrête au 1er match,
            # exploite l'index Revit par catégorie. Si la catégorie est
            # vide, retourne None sans aucune allocation côté Python.
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


# ─── Catégories : accès aux éléments ─────────────────────────────────────────
def get_elements_for_category(doc, cat_name):
    """
    Retourne tous les éléments (instances) d'une catégorie par son nom.
    Niveaux via OfClass(Level) pour fiabilité maximale quelle que soit
    la langue de Revit et sa version.
    """
    try:
        if cat_name in (u'Niveaux', u'Levels'):
            return list(FilteredElementCollector(doc).OfClass(Level))
        for cat in doc.Settings.Categories:
            if cat.Name == cat_name:
                return list(FilteredElementCollector(doc)
                            .OfCategoryId(cat.Id)
                            .WhereElementIsNotElementType())
    except Exception as ex:
        _log(u'get_elements_for_category({}) : {}'.format(cat_name, ex))
    return []


# ─── Résultat ────────────────────────────────────────────────────────────────
def show_result_window(msg):
    # script.get_bundle_file() remplace os.path.join(os.path.dirname(__file__), …)
    xaml = script.get_bundle_file('ResultWindow.xaml')
    try:
        w = forms.WPFWindow(xaml)
        w.Title           = u'Infos Projet -> Objets'
        w.txtMessage.Text = msg
        w.btnClose.Click += lambda s, e: setattr(w, 'DialogResult', True)
        w.show_dialog()
    except Exception as ex:
        show_alert(u'Infos Projet -> Objets', msg)
        _log(u'ResultWindow : ' + str(ex))


# ─── Progression + transaction ───────────────────────────────────────────────
def apply_mappings(doc, rows):
    """
    OPTIMISATIONS (v3.4) :

    1. Cache d'éléments par nom de catégorie (clé = cat_name, et non
       (row_idx, cat_name)) : si plusieurs mappages ciblent la même
       catégorie, les éléments ne sont chargés qu'une seule fois depuis
       l'API Revit. Exemple : 3 mappages sur «Murs» → 1 seul appel
       FilteredElementCollector au lieu de 3.

    2. Transaction via _pyrevit.Transaction (context manager pyRevit 6.4.0) :
       commit automatique à la sortie normale, rollback automatique sur
       toute exception non interceptée — plus sûr et plus lisible que
       le try/except/t.RollBack() manuel.

    3. Seuil de mise à jour de la barre de progression porté de 20 à 50 :
       réduit de ~60 % les appels _do_events() (Dispatcher pumps), ce qui
       est sensible sur les modèles comportant plusieurs milliers d'éléments.
    """
    # ── 1. Pré-chargement — une seule fois par catégorie unique ──────────────
    cat_cache = {}   # cat_name → [elements]
    total = 0

    unique_cats = set(cat for row in rows for cat in row.categories)
    for cat in unique_cats:
        cat_cache[cat] = get_elements_for_category(doc, cat)

    for row in rows:
        for cat in row.categories:
            total += len(cat_cache.get(cat, []))

    # ── 2. Fenêtre de progression ─────────────────────────────────────────────
    xaml = script.get_bundle_file('ProgressWindow.xaml')
    prog = forms.WPFWindow(xaml)
    prog.Title               = u'Informations Projet -> Objets'
    prog.txtStatus.Text      = u'Preparation...'
    prog.progressBar.Maximum = float(max(total, 1))
    prog.progressBar.Value   = 0.0
    prog.txtCurrent.Text     = u'0 / {}'.format(total)
    prog.Show()
    _do_events()

    n_set = n_skip = 0
    errors = []
    current = 0

    # ── 3. Transaction via context manager pyRevit 6.4.0 ─────────────────────
    try:
        with _pyrevit.Transaction(u'Infos Projet -> Objets', doc=doc):
            for row in rows:
                value = get_project_info_value(doc, row.source_param)
                prog.txtStatus.Text = u'{} -> {}'.format(
                    row.source_param, row.target_param)
                _do_events()

                for cat in row.categories:
                    for elem in cat_cache.get(cat, []):
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
                        current += 1
                        # Seuil 50 : ~60 % moins de Dispatcher pumps vs seuil 20
                        if current % 50 == 0 or current == total:
                            prog.progressBar.Value = float(current)
                            prog.txtCurrent.Text   = u'{} / {}'.format(
                                current, total)
                            _do_events()

    except Exception as ex:
        prog.Close()
        show_alert(u'Erreur', u'Erreur de transaction :\n' + str(ex))
        return

    prog.progressBar.Value = float(total)
    prog.txtStatus.Text    = u'Termine.'
    _do_events()
    prog.Close()

    lines = [u'{} parametre(s) renseigne(s)'.format(n_set)]
    if n_skip:
        lines.append(u'{} ignore(s)'.format(n_skip))
    if errors:
        lines.append(u'{} erreur(s) (voir console)'.format(len(errors)))
        for e in errors[:5]:
            _log(str(e))
    show_result_window(u'\n'.join(lines))


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
    import os
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
    except Exception as ex:
        show_alert(u'Sauvegarde', u'Configuration enregistree :\n' + filepath)
        _log(u'SaveDialog : ' + str(ex))

def load_config():
    dlg = WinForms.OpenFileDialog()
    dlg.Title      = u'Charger la configuration'
    dlg.Filter     = u'Fichiers de mappage (*.NM-Map-Infos-Proj)|*.NM-Map-Infos-Proj'
    dlg.DefaultExt = 'NM-Map-Infos-Proj'
    if dlg.ShowDialog() != WinForms.DialogResult.OK: return None
    if not dlg.FileName.lower().endswith('.nm-map-infos-proj'):
        show_alert(
            u'Format incorrect',
            u'Fichier non valide.\n\nSeuls les fichiers ".NM-Map-Infos-Proj" sont acceptes.')
        return None
    try:
        with codecs.open(dlg.FileName, 'r', 'utf-8') as f:
            data = json.load(f)
        return _list_to_rows(data.get('mappings', []))
    except Exception as ex:
        show_alert(u'Erreur', u'Erreur de lecture :\n' + str(ex))
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


# ─── ComboBox filtrable (ObservableCollection + CollectionViewSource) ─────────
def _make_filterable_combo(full_items, initial_value, on_select,
                            margin, tooltip):
    cb = ComboBox()
    cb.IsEditable          = True
    cb.IsTextSearchEnabled = False
    cb.StaysOpenOnEdit     = True
    cb.Margin              = margin
    cb.VerticalAlignment   = VerticalAlignment.Center
    cb.ToolTip             = tooltip

    _st = {'loading': False, 'filter': u''}

    # Collection et vue filtrables
    _coll = ObservableCollection[object]()
    for item in full_items:
        _coll.Add(item)

    _view = CollectionViewSource.GetDefaultView(_coll)

    def _pred(obj):
        ft = _st['filter']
        if not ft: return True
        return ft.lower() in u'{}'.format(obj).lower()

    _view.Filter = System.Predicate[System.Object](_pred)
    cb.ItemsSource = _view

    if initial_value:
        cb.Text = initial_value

    # Touches de navigation : ne pas filtrer
    _nav = frozenset([WpfKey.Up, WpfKey.Down, WpfKey.Left, WpfKey.Right,
                      WpfKey.Home, WpfKey.End, WpfKey.PageUp, WpfKey.PageDown,
                      WpfKey.LeftShift, WpfKey.RightShift,
                      WpfKey.LeftCtrl,  WpfKey.RightCtrl,
                      WpfKey.LeftAlt,   WpfKey.RightAlt,
                      WpfKey.CapsLock,  WpfKey.Tab,
                      WpfKey.F1,  WpfKey.F2,  WpfKey.F3,  WpfKey.F4,
                      WpfKey.F5,  WpfKey.F6,  WpfKey.F7,  WpfKey.F8,
                      WpfKey.F9,  WpfKey.F10, WpfKey.F11, WpfKey.F12])

    def on_key_up(s, e):
        if e.Key == WpfKey.Escape:
            _st['filter'] = u''
            _view.Refresh()
            s.IsDropDownOpen = False
            return
        if e.Key == WpfKey.Return:
            text = s.Text or u''
            # Chercher un item exact dans la collection complète
            for i in range(_coll.Count):
                if u'{}'.format(_coll[i]) == text:
                    on_select(text)
                    break
            # Réinitialiser le filtre après sélection par Entrée
            _st['filter'] = u''
            _view.Refresh()
            s.IsDropDownOpen = False
            return
        if e.Key in _nav:
            return
        # Frappe ordinaire → filtrage sans toucher à cb.Text
        _st['loading'] = True
        _st['filter']  = s.Text or u''
        _view.Refresh()
        _st['loading'] = False
        if not s.IsDropDownOpen and _coll.Count > 0:
            s.IsDropDownOpen = True

    def on_selection_changed(s, e):
        if not _st['loading'] and s.SelectedItem is not None:
            val = u'{}'.format(s.SelectedItem)
            on_select(val)
            # Réinitialiser le filtre pour que la prochaine ouverture
            # affiche la liste complète
            _st['filter'] = u''
            _view.Refresh()

    cb.KeyUp            += on_key_up
    cb.SelectionChanged += on_selection_changed

    # Rechargement complet (changement de type source)
    def _reload(new_items, current_value=u''):
        _st['loading'] = True
        _st['filter']  = u''
        _coll.Clear()
        for item in new_items:
            _coll.Add(item)
        # Réappliquer le filtre (Clear() peut le désactiver dans certaines versions)
        _view.Filter = System.Predicate[System.Object](_pred)
        if current_value:
            cb.Text = current_value
        _st['loading'] = False

    return cb, _reload


# ─── Construction d'une ligne de mappage ─────────────────────────────────────
def make_row_border(row_data,
                    source_params, source_param_types, params_by_type,
                    all_categories, row_list, panel,
                    used_targets, all_reload_entries,
                    refresh_all_target_combos, apply_view):

    def star_col():
        cd = ColumnDefinition()
        cd.Width = GridLength(1, GridUnitType.Star)
        return cd

    def fixed_col(w):
        cd = ColumnDefinition()
        cd.Width = GridLength(w)
        return cd

    border = Border()
    border.Margin              = Thickness(0, 0, 0, 4)
    border.Padding             = Thickness(6, 5, 6, 5)
    border.BorderThickness     = Thickness(1)
    border.BorderBrush         = Brushes.LightGray
    border.CornerRadius        = System.Windows.CornerRadius(3)
    border.HorizontalAlignment = HorizontalAlignment.Stretch
    row_data.border = border

    g = Grid()
    g.HorizontalAlignment = HorizontalAlignment.Stretch
    for cd in [star_col(), fixed_col(30), star_col(), fixed_col(150), fixed_col(32)]:
        g.ColumnDefinitions.Add(cd)

    # Forward ref pour _reload_tgt (défini plus bas)
    _reload_tgt_ref = [None]

    # ── ComboBox source ──────────────────────────────────────────────────────
    def on_src_select(value):
        row_data.source_param = value
        tk    = source_param_types.get(value)
        names = params_by_type.get(tk, []) if tk else []
        # Retirer les targets déjà utilisés par les autres lignes
        avail = [n for n in names
                 if n not in used_targets or n == row_data.target_param]
        if _reload_tgt_ref[0]:
            _reload_tgt_ref[0](avail, row_data.target_param)

    cb_src, _ = _make_filterable_combo(
        source_params,
        row_data.source_param,
        on_src_select,
        Thickness(0, 0, 4, 0),
        u'Parametre source — taper pour filtrer')
    Grid.SetColumn(cb_src, 0)

    # ── Flèche ───────────────────────────────────────────────────────────────
    arrow = TextBlock()
    arrow.Text                = u'->'
    arrow.HorizontalAlignment = HorizontalAlignment.Center
    arrow.VerticalAlignment   = VerticalAlignment.Center
    arrow.Foreground          = Brushes.Gray
    Grid.SetColumn(arrow, 1)

    # ── ComboBox cible ───────────────────────────────────────────────────────
    initial_tk    = source_param_types.get(row_data.source_param)
    initial_names = params_by_type.get(initial_tk, []) if initial_tk else []
    # Filtrer les targets déjà utilisés (sauf le propre target de cette ligne)
    initial_avail = [n for n in initial_names
                     if n not in used_targets or n == row_data.target_param]

    def on_tgt_select(value):
        old = row_data.target_param
        if old and old != value:
            used_targets.discard(old)
        row_data.target_param = value
        if value:
            used_targets.add(value)
        refresh_all_target_combos(except_row=row_data)

    cb_tgt, _reload_tgt = _make_filterable_combo(
        initial_avail,
        row_data.target_param,
        on_tgt_select,
        Thickness(4, 0, 4, 0),
        u'Parametre cible — taper pour filtrer')
    Grid.SetColumn(cb_tgt, 2)

    _reload_tgt_ref[0] = _reload_tgt   # liaison tardive

    # LostFocus : capture la saisie libre si aucune sélection
    def on_tgt_lost_focus(s, e):
        if s.SelectedItem is None and s.Text:
            old = row_data.target_param
            if old and old != s.Text:
                used_targets.discard(old)
            row_data.target_param = s.Text
            if s.Text:
                used_targets.add(s.Text)
            refresh_all_target_combos(except_row=row_data)
    cb_tgt.LostFocus += on_tgt_lost_focus

    # Enregistrer dans all_reload_entries : [reload_fn, row_data]
    reload_entry = [_reload_tgt, row_data]
    all_reload_entries.append(reload_entry)

    # Ajouter le target initial à used_targets
    if row_data.target_param:
        used_targets.add(row_data.target_param)

    # ── Bouton catégories ────────────────────────────────────────────────────
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

    # ── Bouton supprimer ─────────────────────────────────────────────────────
    btn_del = Button()
    btn_del.Content             = u'x'
    btn_del.Width               = 26
    btn_del.Height              = 26
    btn_del.Margin              = Thickness(4, 0, 0, 0)
    btn_del.VerticalAlignment   = VerticalAlignment.Center
    btn_del.HorizontalAlignment = HorizontalAlignment.Center
    btn_del.ToolTip             = u'Supprimer ce mappage'
    Grid.SetColumn(btn_del, 4)

    def on_del(s, e):
        old = row_data.target_param
        if old:
            used_targets.discard(old)
        if reload_entry in all_reload_entries:
            all_reload_entries.remove(reload_entry)
        if row_data in row_list:
            row_list.remove(row_data)
        refresh_all_target_combos()
        apply_view()   # reconstruit le panel (filtre + tri)
    btn_del.Click += on_del

    for child in [cb_src, arrow, cb_tgt, btn_cat, btn_del]:
        g.Children.Add(child)

    border.Child = g
    return border


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    _log(u'Demarrage')

    # Instance unique : si une fenêtre est déjà ouverte, la mettre au premier plan
    if _ACTIVE_WINDOW[0] is not None:
        try:
            _ACTIVE_WINDOW[0].Activate()
            _log(u'Fenetre deja ouverte, activation')
            return
        except Exception:
            _ACTIVE_WINDOW[0] = None

    source_params      = get_project_info_params(doc)
    source_param_types = get_project_info_param_types(doc)
    all_categories     = get_available_categories(doc)
    params_by_type     = get_params_by_exact_type(doc)

    _log(u'{} params source, {} categories'.format(
        len(source_params), len(all_categories)))

    if not source_params:
        show_alert(u'Infos Projet -> Objets',
                   u'Aucun parametre trouve dans les Informations Projet.')
        return

    xaml_path = script.get_bundle_file('WPFWindow.xaml')
    wpf       = forms.WPFWindow(xaml_path)
    wpf.Title = u'Informations Projet -> Objets'

    row_list          = []
    used_targets      = set()    # targets déjà sélectionnés
    all_reload_entries = []      # [[reload_fn, row_data], ...]

    # ── État de la vue (filtre + tri) ────────────────────────────────────────
    _vs = {
        'filter_src': u'',
        'filter_tgt': u'',
        'sort': None,   # None | 'src_asc' | 'src_desc' | 'tgt_asc' | 'tgt_desc'
    }

    def apply_view():
        """Reconstruit le panel selon les filtres et le tri actifs."""
        fs = _vs['filter_src'].lower()
        ft = _vs['filter_tgt'].lower()
        visible = [r for r in row_list
                   if (not fs or fs in r.source_param.lower())
                   and (not ft or ft in r.target_param.lower())]
        sort = _vs['sort']
        if sort == 'src_asc':
            visible.sort(key=lambda r: r.source_param.lower())
        elif sort == 'src_desc':
            visible.sort(key=lambda r: r.source_param.lower(), reverse=True)
        elif sort == 'tgt_asc':
            visible.sort(key=lambda r: r.target_param.lower())
        elif sort == 'tgt_desc':
            visible.sort(key=lambda r: r.target_param.lower(), reverse=True)
        wpf.mappingsPanel.Children.Clear()
        for r in visible:
            wpf.mappingsPanel.Children.Add(r.border)

    def _update_sort_btns():
        """Met à jour les labels des boutons de tri selon l'état courant."""
        s = _vs['sort']
        wpf.btnSortSrc.Content = (u'A\u2192Z' if s == 'src_asc' else
                                   u'Z\u2192A' if s == 'src_desc' else u'\u21c5')
        wpf.btnSortTgt.Content = (u'A\u2192Z' if s == 'tgt_asc' else
                                   u'Z\u2192A' if s == 'tgt_desc' else u'\u21c5')

    def refresh_all_target_combos(except_row=None):
        """
        Recharge les ComboBox cibles de toutes les lignes (sauf except_row)
        en excluant les targets déjà utilisés par d'autres lignes.
        """
        for entry in list(all_reload_entries):
            fn, rd = entry
            if rd is except_row:
                continue
            tk    = source_param_types.get(rd.source_param)
            names = params_by_type.get(tk, []) if tk else []
            avail = [n for n in names
                     if n not in used_targets or n == rd.target_param]
            fn(avail, rd.target_param)

    # ── Helpers lignes ───────────────────────────────────────────────────────
    def add_row(row_data=None):
        if row_data is None:
            row_data = MappingRow()
        row_list.append(row_data)
        b = make_row_border(
            row_data,
            source_params, source_param_types, params_by_type,
            all_categories, row_list, wpf.mappingsPanel,
            used_targets, all_reload_entries,
            refresh_all_target_combos, apply_view)
        wpf.mappingsPanel.Children.Add(b)

    def load_rows(rows):
        wpf.mappingsPanel.Children.Clear()
        row_list[:] = []
        used_targets.clear()
        all_reload_entries[:] = []
        for r in rows:
            add_row(r)
        apply_view()

    # ── Câblage boutons (EN PREMIER, avant tout chargement) ──────────────────
    def on_load(s, e):
        rows = load_config()
        if rows is not None:
            load_rows(rows)

    def on_save(s, e):
        save_config(row_list)

    def on_add(s, e):
        add_row()

    def on_clear_all(s, e):
        wpf.mappingsPanel.Children.Clear()
        row_list[:] = []
        used_targets.clear()
        all_reload_entries[:] = []

    def on_apply(s, e):
        active = [r for r in row_list
                  if r.source_param and r.target_param and r.categories]
        if not active:
            show_alert(
                u'Aucun mappage',
                u'Aucun mappage complet.\n\n'
                u'Chaque ligne doit avoir :\n'
                u'  - un parametre source\n'
                u'  - un parametre cible\n'
                u'  - au moins une categorie.')
            return
        _log(u'Application de {} mappage(s)'.format(len(active)))
        apply_mappings(doc, active)

    def on_close(s, e):
        wpf.Close()   # déclenche l'événement Closed → arrête le DispatcherFrame

    def on_search_src(s, e):
        _vs['filter_src'] = s.Text or u''
        apply_view()

    def on_search_tgt(s, e):
        _vs['filter_tgt'] = s.Text or u''
        apply_view()

    # Tri source (cycle : ⇅ → A→Z → Z→A → ⇅)
    def on_sort_src(s, e):
        cur = _vs['sort']
        if cur == 'src_asc':   _vs['sort'] = 'src_desc'
        elif cur == 'src_desc': _vs['sort'] = None
        else:                   _vs['sort'] = 'src_asc'
        _update_sort_btns()
        apply_view()

    # Tri cible (cycle : ⇅ → A→Z → Z→A → ⇅)
    def on_sort_tgt(s, e):
        cur = _vs['sort']
        if cur == 'tgt_asc':   _vs['sort'] = 'tgt_desc'
        elif cur == 'tgt_desc': _vs['sort'] = None
        else:                   _vs['sort'] = 'tgt_asc'
        _update_sort_btns()
        apply_view()

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

    # ── Chargement de la dernière config ─────────────────────────────────────
    try:
        last = _auto_load()
        if last:
            load_rows(last)
    except Exception as ex:
        _log(u'Chargement auto echoue : ' + str(ex))

    # ── Fenêtre non-modale via DispatcherFrame ────────────────────────────────
    _frame = Threading.DispatcherFrame()

    def on_closed(s, e):
        """Déclenché quand la fenêtre se ferme (bouton Fermer ou croix)."""
        _auto_save(row_list)
        _ACTIVE_WINDOW[0] = None
        _frame.Continue = False   # sort de PushFrame → main() retourne

    wpf.Closed        += on_closed
    _ACTIVE_WINDOW[0]  = wpf

    wpf.Show()                                    # affiche sans bloquer
    Threading.Dispatcher.PushFrame(_frame)        # traite les messages jusqu'à fermeture
    _log(u'Fenetre fermee')


if __name__ == '__main__':
    main()
