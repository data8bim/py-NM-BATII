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


#__title__ = "Pièces → Objets par pièce"
#__doc__ = """Transfert des valeurs de paramètres de pièces vers les objets référencés à cette pièce.
#Description : Transfert des valeurs de paramètres des pièces (ex: Nom, Numéro) vers les objets (mobilier, agencement, appareils...) référencés à chaque pièce via leur propriété Room, associés à chaque pièce.
#Permet de mapper des paramètres de pièces vers des catégories d'objets choisies, afin de répercuter automatiquement les valeurs de chaque pièce sur les objets qu'elle contient.

#Version : 1.0 — 2026-07-07
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
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    StorageType, ImportInstance, SpatialElement
)
from Autodesk.Revit.DB.Architecture import Room as _RoomClass
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
        # Dernier recours : boîte de dialogue Windows native (pas pyRevit).
        WinForms.MessageBox.Show(message, titre)


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
        logger.debug(u'[Pieces -> Objets] ' + msg)


# ─── Fichier de sauvegarde automatique (pyRevit appdata) ─────────────────────
#
#  script.get_data_file() stocke dans %APPDATA%\pyRevit\ : toujours
#  accessible en écriture même si le script est sur un partage réseau.
#
_LAST_CFG = script.get_data_file('last_mapping', 'NM-Map-Pieces')


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


# ─── Lecture Revit : pièces et leurs paramètres ──────────────────────────────
def _exact_type_key(param):
    try:
        return param.Definition.GetDataType().TypeId
    except Exception:
        return str(param.StorageType)


def _get_room_name(room):
    """Room.Name n'est pas exposé directement en IronPython : passer par le paramètre."""
    try:
        p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
        if p is not None:
            return p.AsString() or u''
    except Exception:
        pass
    return u''


def get_rooms(doc):
    rooms = list(FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Rooms)
                 .WhereElementIsNotElementType())
    return sorted(rooms, key=lambda r: (r.Number or u'', _get_room_name(r)))


# ─── Portes/fenêtres : "De la pièce" / "A la pièce" ──────────────────────────
#
#  Les portes et fenêtres ne sont pas "contenues" dans une pièce (elles sont
#  hébergées par un mur) : Revit leur associe DEUX pièces, une de chaque côté
#  ("De la pièce" / "A la pièce" dans les nomenclatures, FromRoom/ToRoom dans
#  l'API). Chaque paramètre source est donc proposé deux fois :
#    "Pièce : X"      -> Room (ou self-référence) avec repli sur FromRoom
#    "A la pièce : X" -> ToRoom uniquement
#
_PREFIX_PIECE       = u'Pièce : '
_PREFIX_A_LA_PIECE  = u'A la pièce : '


def _split_source_param(source_param):
    """Retourne (mode, nom_reel) où mode vaut 'piece' ou 'a_la_piece'."""
    if source_param.startswith(_PREFIX_A_LA_PIECE):
        return 'a_la_piece', source_param[len(_PREFIX_A_LA_PIECE):]
    if source_param.startswith(_PREFIX_PIECE):
        return 'piece', source_param[len(_PREFIX_PIECE):]
    return 'piece', source_param   # compatibilité anciennes configs


def get_room_params(doc):
    """
    Union des noms de paramètres présents sur les pièces du projet,
    proposés sous deux formes (voir section "Portes/fenêtres" ci-dessus).
    """
    names = set()
    for room in get_rooms(doc):
        for p in room.Parameters:
            if p.Definition and p.Definition.Name:
                names.add(p.Definition.Name)
    names = sorted(names)
    return ([_PREFIX_PIECE + n for n in names] +
            [_PREFIX_A_LA_PIECE + n for n in names])


def get_room_param_types(doc):
    types = {}
    for room in get_rooms(doc):
        for p in room.Parameters:
            name = p.Definition.Name if p.Definition else None
            if name and (_PREFIX_PIECE + name) not in types:
                key = _exact_type_key(p)
                types[_PREFIX_PIECE + name]      = key
                types[_PREFIX_A_LA_PIECE + name] = key
    return types


def get_room_value(room, param_name):
    p = room.LookupParameter(param_name)
    if p is None:
        return u''
    st = p.StorageType
    if   st == StorageType.String:  return p.AsString() or u''
    elif st == StorageType.Integer: return str(p.AsInteger())
    elif st == StorageType.Double:  return p.AsValueString() or str(p.AsDouble())
    else:                           return p.AsValueString() or u''


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


_EXCLUDED_CATEGORIES = frozenset([u'Informations sur le projet', u'Niveaux'])


def get_available_categories(doc):
    """
    Retourne les catégories Revit acceptant des paramètres.
    AllowsBoundParameters == True est la propriété officielle de l'API Revit.
    Exclusions supplémentaires : catégories issues de fichiers CAO, ainsi que
    "Informations sur le projet" et "Niveaux" (aucun paramètre de pièce ne
    peut leur être mappé).
    """
    cad_ids = _get_cad_import_category_ids(doc)   # résultat mis en cache
    cats = set()
    for cat in doc.Settings.Categories:
        try:
            if cat.Id.IntegerValue in cad_ids:
                continue
            if cat.AllowsBoundParameters:
                name = cat.Name
                if name and name not in _EXCLUDED_CATEGORIES:
                    cats.add(name)
        except Exception:
            pass
    return sorted(cats)


def get_params_by_exact_type(doc):
    """
    Découverte des paramètres cibles disponibles par type de donnée.
    Un seul élément par catégorie est inspecté (FirstElement()) — appel
    .NET pur qui exploite l'index interne de Revit par catégorie et
    s'arrête immédiatement après le premier résultat.
    """
    by_type = {}
    cad_ids = _get_cad_import_category_ids(doc)   # résultat mis en cache

    for cat in doc.Settings.Categories:
        try:
            if not cat.AllowsBoundParameters:
                continue
            if cat.Id.IntegerValue in cad_ids:
                continue

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
    """Retourne tous les éléments (instances) d'une catégorie par son nom."""
    try:
        for cat in doc.Settings.Categories:
            if cat.Name == cat_name:
                return list(FilteredElementCollector(doc)
                            .OfCategoryId(cat.Id)
                            .WhereElementIsNotElementType())
    except Exception as ex:
        _log(u'get_elements_for_category({}) : {}'.format(cat_name, ex))
    return []


def _get_last_phase(doc):
    """Dernière phase du projet (utilisée par FamilyInstance.get_Room)."""
    try:
        phases = doc.Phases
        if phases.Size == 0:
            return None
        return phases[phases.Size - 1]
    except Exception:
        return None


_DOOR_WINDOW_CAT_IDS = frozenset([
    int(BuiltInCategory.OST_Doors),
    int(BuiltInCategory.OST_Windows),
])


def _is_door_or_window(elem):
    """
    Portes/fenêtres : hébergées entre deux pièces via un mur. Pour ces
    catégories, la propriété générique "Room" (sans repère De/A) est
    AMBIGUË — Revit peut lui faire retourner indifféremment la pièce "De"
    ou la pièce "A" selon l'orientation du mur hôte (retour observé :
    valeur de ToRoom au lieu de FromRoom). Il ne faut donc jamais
    l'utiliser pour ces catégories, uniquement FromRoom/ToRoom.
    """
    try:
        cat = elem.Category
        return cat is not None and cat.Id.IntegerValue in _DOOR_WINDOW_CAT_IDS
    except Exception:
        return False


def _get_element_piece_id(elem, phase):
    """
    Association "Pièce :" — retourne l'IntegerValue de la pièce, ou None.
      - Si l'élément EST une pièce, il se référence lui-même (permet de
        mapper un paramètre de pièce vers un autre paramètre de la même
        pièce quand la catégorie « Pièces » est choisie comme cible).
      - Si l'élément est une porte/fenêtre : uniquement
        FamilyInstance.get_FromRoom(phase)/.FromRoom (« De la pièce » dans
        les nomenclatures). Voir _is_door_or_window.
      - Sinon, FamilyInstance.get_Room(phase)/.Room : mobilier, agencement,
        appareils sanitaires, etc.
    NB : les propriétés "Room"/"FromRoom" sans argument ne se lient pas de
    façon fiable en IronPython (même piège que Room.Name) ; on utilise donc
    en priorité les méthodes get_Room(phase)/get_FromRoom(phase) avec la
    dernière phase du projet.
    """
    try:
        if isinstance(elem, _RoomClass):
            return elem.Id.IntegerValue
    except Exception:
        pass

    room = None
    if _is_door_or_window(elem):
        if phase is not None:
            try:
                room = elem.get_FromRoom(phase)
            except Exception:
                room = None
        if room is None:
            try:
                room = elem.FromRoom
            except Exception:
                room = None
    else:
        if phase is not None:
            try:
                room = elem.get_Room(phase)
            except Exception:
                room = None
        if room is None:
            try:
                room = elem.Room
            except Exception:
                room = None
        if room is None and phase is not None:
            try:
                room = elem.get_FromRoom(phase)
            except Exception:
                room = None
        if room is None:
            try:
                room = elem.FromRoom
            except Exception:
                room = None

    if room is None:
        return None
    try:
        return room.Id.IntegerValue
    except Exception:
        return None


def _get_element_a_la_piece_id(elem, phase):
    """
    Association "A la pièce :" — uniquement FamilyInstance.get_ToRoom(phase)
    /.ToRoom (portes et fenêtres, côté "arrivée" dans les nomenclatures).
    """
    room = None
    if phase is not None:
        try:
            room = elem.get_ToRoom(phase)
        except Exception:
            room = None
    if room is None:
        try:
            room = elem.ToRoom
        except Exception:
            room = None
    if room is None:
        return None
    try:
        return room.Id.IntegerValue
    except Exception:
        return None


def _is_unplaced_spatial_element(elem):
    """
    Detecte les Pieces / Espaces / Surfaces "Non placee(s)".
    Ces elements conservent des parametres valides mais n'ont aucune
    geometrie : Location est None. Ils doivent etre exclus du traitement
    (aussi bien comme cible que comme source auto-referencee).
    """
    try:
        if isinstance(elem, SpatialElement):
            return elem.Location is None
    except Exception:
        pass
    return False


def build_elements_by_room(doc, cat_names):
    """
    Pré-charge les éléments des catégories sélectionnées, regroupés par
    pièce (IntegerValue de l'Id de la pièce), selon les DEUX associations
    possibles ("Pièce :" et "A la pièce :" — voir _get_element_piece_id /
    _get_element_a_la_piece_id). Un seul passage par catégorie, quel que
    soit le nombre de mappages qui la référencent.
    Exclut les Pièces/Espaces/Surfaces "Non placée(s)" (voir
    _is_unplaced_spatial_element) ainsi que tout élément sans pièce
    associée valide pour l'association concernée.
    Retourne : {cat_name: {'piece': {room_id_int: [elements]},
                            'a_la_piece': {room_id_int: [elements]}}}
    """
    phase = _get_last_phase(doc)
    result = {}
    for cat in cat_names:
        by_piece      = {}
        by_a_la_piece = {}
        for elem in get_elements_for_category(doc, cat):
            if _is_unplaced_spatial_element(elem):
                continue
            rid = _get_element_piece_id(elem, phase)
            if rid is not None:
                by_piece.setdefault(rid, []).append(elem)
            rid2 = _get_element_a_la_piece_id(elem, phase)
            if rid2 is not None:
                by_a_la_piece.setdefault(rid2, []).append(elem)
        result[cat] = {'piece': by_piece, 'a_la_piece': by_a_la_piece}
    return result


# ─── Résultat ────────────────────────────────────────────────────────────────
def show_result_window(msg):
    xaml = script.get_bundle_file('ResultWindow.xaml')
    try:
        w = forms.WPFWindow(xaml)
        w.Title           = u'Pieces -> Objets'
        w.txtMessage.Text = msg
        w.btnClose.Click += lambda s, e: setattr(w, 'DialogResult', True)
        w.show_dialog()
    except Exception as ex:
        show_alert(u'Pieces -> Objets', msg)
        _log(u'ResultWindow : ' + str(ex))


# ─── Progression + transaction ───────────────────────────────────────────────
def apply_mappings(doc, rows):
    """
    Pour chaque pièce du projet, lit la valeur du paramètre source SUR
    CETTE PIECE, puis l'écrit sur les éléments des catégories
    sélectionnées dont la propriété Room correspond à cette pièce.
    """
    rooms = get_rooms(doc)

    # ── 1. Pré-chargement des éléments par catégorie, groupés par pièce ──────
    unique_cats = set(cat for row in rows for cat in row.categories)
    elems_by_cat_room = build_elements_by_room(doc, unique_cats)

    total = 0
    for row in rows:
        mode, _raw = _split_source_param(row.source_param)
        for room in rooms:
            if _is_unplaced_spatial_element(room):
                continue
            rid = room.Id.IntegerValue
            for cat in row.categories:
                total += len(
                    elems_by_cat_room.get(cat, {}).get(mode, {}).get(rid, []))

    # ── 2. Fenêtre de progression ─────────────────────────────────────────────
    xaml = script.get_bundle_file('ProgressWindow.xaml')
    prog = forms.WPFWindow(xaml)
    prog.Title               = u'Pieces -> Objets'
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
        with _pyrevit.Transaction(u'Pieces -> Objets', doc=doc):
            for row in rows:
                mode, raw_name = _split_source_param(row.source_param)
                for room in rooms:
                    if _is_unplaced_spatial_element(room):
                        continue
                    rid   = room.Id.IntegerValue
                    value = get_room_value(room, raw_name)
                    prog.txtStatus.Text = u'{} : {} -> {}'.format(
                        _get_room_name(room), row.source_param, row.target_param)
                    _do_events()

                    for cat in row.categories:
                        for elem in (elems_by_cat_room.get(cat, {})
                                     .get(mode, {}).get(rid, [])):
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
    dlg.Filter     = u'Fichiers de mappage (*.NM-Map-Pieces)|*.NM-Map-Pieces'
    dlg.DefaultExt = 'NM-Map-Pieces'
    dlg.FileName   = 'pieces_mappages.NM-Map-Pieces'
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
    dlg.Filter     = u'Fichiers de mappage (*.NM-Map-Pieces)|*.NM-Map-Pieces'
    dlg.DefaultExt = 'NM-Map-Pieces'
    if dlg.ShowDialog() != WinForms.DialogResult.OK: return None
    if not dlg.FileName.lower().endswith('.nm-map-pieces'):
        show_alert(
            u'Format incorrect',
            u'Fichier non valide.\n\nSeuls les fichiers ".NM-Map-Pieces" sont acceptes.')
        return None
    try:
        with codecs.open(dlg.FileName, 'r', 'utf-8') as f:
            data = json.load(f)
        return _list_to_rows(data.get('mappings', []))
    except Exception as ex:
        show_alert(u'Erreur', u'Erreur de lecture :\n' + str(ex))
        return None


# ─── Dialogue catégories ─────────────────────────────────────────────────────
def show_categories_dialog(all_categories, current_selection):
    xaml = script.get_bundle_file('CategoriesDialog.xaml')
    dlg  = forms.WPFWindow(xaml)
    dlg.Title = u'Selectionner les categories'

    selected_set = set(current_selection)
    visible_cbs  = []
    last_idx     = [-1]

    def _sync():
        for cb, cat in visible_cbs:
            if bool(cb.IsChecked): selected_set.add(cat)
            else:                  selected_set.discard(cat)

    def populate(filter_text=u''):
        _sync()
        dlg.categoryListPanel.Children.Clear()
        del visible_cbs[:]
        last_idx[0] = -1
        for cat in all_categories:
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
        u'Parametre source (piece) — taper pour filtrer')
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
        u'Parametre cible (objets) — taper pour filtrer')
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
    btn_cat.ToolTip           = u'Selectionner les categories d\'objets cibles (references a la piece)'
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

    source_params      = get_room_params(doc)
    source_param_types = get_room_param_types(doc)
    all_categories     = get_available_categories(doc)
    params_by_type     = get_params_by_exact_type(doc)

    _log(u'{} params source (pieces), {} categories'.format(
        len(source_params), len(all_categories)))

    if not source_params:
        show_alert(u'Pieces -> Objets',
                   u'Aucun parametre trouve sur les pieces du projet.')
        return

    if not get_rooms(doc):
        show_alert(u'Pieces -> Objets',
                   u'Aucune piece trouvee dans le projet.')
        return

    xaml_path = script.get_bundle_file('WPFWindow.xaml')
    wpf       = forms.WPFWindow(xaml_path)
    wpf.Title = u'Pieces -> Objets'

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
                u'  - un parametre source (piece)\n'
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
