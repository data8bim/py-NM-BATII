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


#__title__ = 'Sélectionner\n/ Épingler'
#__author__ = 'data8bim (d8b)'

import os
import json
import codecs
from collections import OrderedDict
import System
from pyrevit import revit, DB, forms, script, HOST_APP
from Autodesk.Revit.DB import Element
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from System.Collections.Generic import List
from System.Windows import (
    Thickness, GridLength, GridUnitType, FontWeights, TextWrapping,
    TextAlignment, HorizontalAlignment, VerticalAlignment, DataTemplate,
    FrameworkElementFactory, LogicalTreeHelper, UIElement, Visibility
)
from System.Windows.Controls import (
    CheckBox, Grid, RowDefinition, TextBlock, Button, StackPanel, Orientation,
    DataGridRow, DataGridTextColumn, DataGridTemplateColumn, DataGridLength
)
from System.Windows.Data import Binding, BindingMode
from System.Windows.Input import Keyboard, Key as WpfKey, Mouse, Cursors
from System.Windows.Media import Brushes, Visual, VisualTreeHelper
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Collections.ObjectModel import ObservableCollection

from dialogs.dialogs_styles_loader import load as _load_styles, show_alert, show_confirm
_load_styles()

from utils.config_loader import load_config

doc   = revit.doc
uidoc = revit.uidoc

TITRE      = u"Sélectionner / Épingler les éléments"
CONFIG_KEY = 'selection_epinglage_elements'

# Au-delà de ce nombre d'éléments, la construction du tableau devient longue :
# on demande confirmation avant de la lancer.
_SEUIL_AVERTISSEMENT = 15000

_LARGEUR_DEFAUT = 160


# ─── Logs (convention NM-BATII : conditionnés par activer_logs_scripts) ────────
output = script.get_output()
try:
    _LOG_ACTIF = bool(load_config().get('activer_logs_scripts', False))
except Exception:
    _LOG_ACTIF = False
if not _LOG_ACTIF:
    try:
        output.close()
    except Exception:
        pass


def _log(msg):
    if _LOG_ACTIF:
        try:
            output.print_md(msg)
        except Exception:
            pass


# ─── Réglages persistants (config.json) ───────────────────────────────────────
def _config_path():
    cur = os.path.dirname(os.path.abspath(__file__))
    while not cur.lower().endswith('.extension'):
        parent = os.path.dirname(cur)
        if parent == cur:
            raise IOError("Dossier .extension introuvable depuis : " + cur)
        cur = parent
    return os.path.join(cur, 'config.json')


def _load_settings():
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    reglages = cfg.get(CONFIG_KEY, {})
    return reglages if isinstance(reglages, dict) else {}


def _save_settings(reglages):
    """Relit config.json puis n'y remplace que la section de ce script : les
    réglages des autres boutons ne sont jamais écrasés.

    object_pairs_hook=OrderedDict : sans lui, json.load rend un dict non
    ordonné et la réécriture ressort TOUTES les clés du fichier dans un ordre
    différent — config.json étant versionné, chaque fermeture de la palette
    produirait un diff de plusieurs centaines de lignes pour une seule valeur
    modifiée. Réaffecter une clé existante conserve en outre sa position."""
    try:
        path = _config_path()
        with codecs.open(path, 'r', 'utf-8') as f:
            cfg = json.load(f, object_pairs_hook=OrderedDict)
        cfg[CONFIG_KEY] = reglages
        with codecs.open(path, 'w', 'utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ─── Utilitaires ──────────────────────────────────────────────────────────────
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


def _entier_ou_zero(s):
    try:
        return int(s)
    except Exception:
        return 0


def _escape_access_text(s):
    """Échappe les "_" d'une chaîne affichée en Content d'un CheckBox/Button :
    WPF (AccessText) interprète un "_" simple comme marqueur de touche d'accès
    (le caractère suivant est souligné et le "_" disparaît). Doubler le "_"
    restitue un underscore littéral."""
    return (s or u'').replace(u'_', u'__')


def _eid_value(eid):
    """Valeur entière d'un ElementId, quelle que soit la version de l'API :
    ElementId.Value (Revit 2024+, 64 bits) sinon IntegerValue (historique)."""
    if eid is None:
        return 0
    try:
        return eid.Value
    except Exception:
        try:
            return eid.IntegerValue
        except Exception:
            return 0


def _element_name(elem):
    """Contournement IronPython : Element.Name est implémenté en interface
    explicite sur certains types (FamilySymbol, ElementType...), ce qui fait
    échouer l'accès direct `elem.Name` (AttributeError: Name)."""
    try:
        return Element.Name.__get__(elem) or u''
    except Exception:
        return u''


def _param_to_str(p):
    """Valeur affichable d'un paramètre, tous types de stockage confondus."""
    if p is None:
        return u''
    try:
        st = p.StorageType
    except Exception:
        return u''
    try:
        if st == DB.StorageType.String:
            return p.AsString() or u''
        if st == DB.StorageType.Integer:
            # AsValueString rend "Oui"/"Non" pour les paramètres booléens et le
            # libellé des énumérations : à privilégier sur l'entier brut.
            return p.AsValueString() or unicode(p.AsInteger())
        if st == DB.StorageType.Double:
            return p.AsValueString() or unicode(p.AsDouble())
        if st == DB.StorageType.ElementId:
            val = p.AsValueString()
            if val:
                return val
            eid = p.AsElementId()
            if eid is None or eid == DB.ElementId.InvalidElementId:
                return u''
            cible = doc.GetElement(eid)
            if cible is None:
                return unicode(_eid_value(eid))
            return _element_name(cible)
        return p.AsValueString() or u''
    except Exception:
        return u''


# ─── Caches de lecture du modèle ──────────────────────────────────────────────
# Un modèle contient couramment des dizaines de milliers d'éléments pour
# quelques centaines de types : tout ce qui se lit sur le type est mis en cache.
_cache_types  = {}   # valeur d'ElementId de type -> (famille, type, ElementType)
_cache_niveau = {}   # valeur d'ElementId de niveau -> nom
_cache_workset = {}  # entier de WorksetId -> nom
_cache_param_type = {}  # (valeur d'ElementId de type, nom de paramètre) -> valeur


def _type_info(elem):
    """(famille, type, ElementType) de l'élément, mis en cache par type."""
    try:
        tid = elem.GetTypeId()
    except Exception:
        tid = None
    cle = _eid_value(tid)
    if cle in _cache_types:
        return _cache_types[cle]
    famille, nom_type, etype = u'', u'', None
    if tid is not None and tid != DB.ElementId.InvalidElementId:
        try:
            etype = doc.GetElement(tid)
        except Exception:
            etype = None
    if etype is not None:
        try:
            famille = etype.FamilyName or u''
        except Exception:
            famille = u''
        nom_type = _element_name(etype)
    _cache_types[cle] = (famille, nom_type, etype)
    return _cache_types[cle]


def _safe_bip(nom):
    return getattr(DB.BuiltInParameter, nom, None)


# Paramètres porteurs du niveau, du plus courant au plus spécifique : le niveau
# n'est pas exposé de la même façon selon la catégorie d'élément.
_BIPS_NIVEAU = [bip for bip in (
    _safe_bip('LEVEL_PARAM'),
    _safe_bip('FAMILY_LEVEL_PARAM'),
    _safe_bip('SCHEDULE_LEVEL_PARAM'),
    _safe_bip('INSTANCE_REFERENCE_LEVEL_PARAM'),
    _safe_bip('FAMILY_BASE_LEVEL_PARAM'),
    _safe_bip('RBS_START_LEVEL_PARAM'),
    _safe_bip('ROOM_LEVEL_ID'),
    _safe_bip('WALL_BASE_CONSTRAINT'),
) if bip is not None]


def _nom_niveau(elem):
    lid = None
    try:
        lid = elem.LevelId
    except Exception:
        lid = None
    if lid is None or lid == DB.ElementId.InvalidElementId:
        for bip in _BIPS_NIVEAU:
            try:
                p = elem.get_Parameter(bip)
            except Exception:
                p = None
            if p is None:
                continue
            try:
                if p.StorageType != DB.StorageType.ElementId:
                    continue
                candidat = p.AsElementId()
            except Exception:
                continue
            if candidat is not None and candidat != DB.ElementId.InvalidElementId:
                lid = candidat
                break
    if lid is None or lid == DB.ElementId.InvalidElementId:
        return u''
    cle = _eid_value(lid)
    if cle not in _cache_niveau:
        try:
            niveau = doc.GetElement(lid)
        except Exception:
            niveau = None
        _cache_niveau[cle] = _element_name(niveau) if niveau is not None else u''
    return _cache_niveau[cle]


def _nom_workset(elem):
    if not doc.IsWorkshared:
        return u''
    try:
        wid = elem.WorksetId
        cle = wid.IntegerValue
    except Exception:
        return u''
    if cle not in _cache_workset:
        nom = u''
        try:
            ws = doc.GetWorksetTable().GetWorkset(wid)
            if ws is not None:
                nom = ws.Name or u''
        except Exception:
            nom = u''
        _cache_workset[cle] = nom
    return _cache_workset[cle]


def _vider_caches():
    _cache_types.clear()
    _cache_niveau.clear()
    _cache_workset.clear()
    _cache_param_type.clear()


# ─── Collecte des éléments ────────────────────────────────────────────────────
# Repères et objets de référence : catégories d'annotation que l'on liste
# toujours, parce qu'elles font partie des éléments que l'on épingle le plus.
_CATEGORIES_REPERES = ('OST_Grids', 'OST_Levels', 'OST_CLines', 'OST_VolumeOfInterest')


def _ids_categories_reperes():
    ids = set()
    for nom in _CATEGORIES_REPERES:
        bic = getattr(DB.BuiltInCategory, nom, None)
        if bic is None:
            continue
        try:
            cat = DB.Category.GetCategory(doc, bic)
        except Exception:
            cat = None
        if cat is not None:
            ids.add(_eid_value(cat.Id))
    return ids


def collect_elements(portee, inclure_annotations):
    """Éléments proposés dans le tableau selon la portée retenue.

    portee : 'projet' | 'vue' | 'selection'
    """
    if portee == 'selection':
        try:
            ids = uidoc.Selection.GetElementIds()
        except Exception:
            ids = []
        bruts = [doc.GetElement(i) for i in ids]
    elif portee == 'vue':
        try:
            vue = doc.ActiveView
            bruts = list(DB.FilteredElementCollector(doc, vue.Id)
                         .WhereElementIsNotElementType().ToElements())
        except Exception:
            bruts = []
    else:
        bruts = list(DB.FilteredElementCollector(doc)
                     .WhereElementIsNotElementType().ToElements())

    ids_reperes = _ids_categories_reperes()
    retenus = []
    for e in bruts:
        if e is None:
            continue
        try:
            cat = e.Category
        except Exception:
            continue
        if cat is None:
            continue
        try:
            type_cat = cat.CategoryType
        except Exception:
            continue
        if type_cat == DB.CategoryType.Model:
            retenus.append(e)
        elif _eid_value(cat.Id) in ids_reperes:
            retenus.append(e)
        elif inclure_annotations and type_cat == DB.CategoryType.Annotation:
            retenus.append(e)
    return retenus


# ─── Ligne du tableau ─────────────────────────────────────────────────────────
class _ElementRow(object, INotifyPropertyChanged):
    """Ligne du tableau. 'Selected' et 'PinnedLabel' notifient leurs changements
    (INotifyPropertyChanged) pour que la case à cocher et la colonne « Épinglé »
    restent synchrones avec le modèle lors des traitements en masse."""

    def __init__(self, elem):
        self.element    = elem
        self.element_id = elem.Id
        self._selected  = False
        self._PropertyChanged = None
        # Types .NET capturés sur l'instance : add_PropertyChanged et
        # remove_PropertyChanged sont appelées PAR WPF, pas par un callback à
        # nous — le moteur de liaison accroche puis retire PropertyChanged sur
        # la source à chaque réalisation puis recyclage d'une ligne
        # virtualisée, donc à chaque défilement. Elles s'exécutent sans que
        # _restaurer() soit passé, sur des globals de module que pyRevit a
        # vidés à la fin de la commande : un nom global y lèverait NameError,
        # que WPF avale, et la ligne cesse d'être rendue — le tableau se vide
        # au défilement. __init__, lui, ne tourne que depuis reload_rows(),
        # toujours atteint après restauration des globals.
        self._Delegate  = System.Delegate
        self._EventArgs = PropertyChangedEventArgs

        try:
            self.CategoryName = elem.Category.Name or u''
        except Exception:
            self.CategoryName = u''
        famille, nom_type, _etype = _type_info(elem)
        self.FamilyName  = famille
        self.TypeName    = nom_type
        self.ElementName = _element_name(elem)
        self.LevelName   = _nom_niveau(elem)
        self.WorksetName = _nom_workset(elem)
        self.IdText      = unicode(_eid_value(elem.Id))
        try:
            self._pinned = bool(elem.Pinned)
        except Exception:
            self._pinned = False

    def add_PropertyChanged(self, value):
        self._PropertyChanged = self._Delegate.Combine(self._PropertyChanged, value)

    def remove_PropertyChanged(self, value):
        self._PropertyChanged = self._Delegate.Remove(self._PropertyChanged, value)

    def _notifier(self, nom):
        if self._PropertyChanged is not None:
            self._PropertyChanged(self, self._EventArgs(nom))

    def _get_Selected(self):
        return self._selected

    def _set_Selected(self, value):
        if self._selected != value:
            self._selected = value
            self._notifier(u'Selected')
            self._notifier(u'SelectedLabel')

    Selected = property(_get_Selected, _set_Selected)

    def _get_SelectedLabel(self):
        return u'Coché' if self._selected else u'Non coché'

    SelectedLabel = property(_get_SelectedLabel)

    def _get_Pinned(self):
        return self._pinned

    def _set_Pinned(self, value):
        if self._pinned != value:
            self._pinned = value
            self._notifier(u'PinnedLabel')

    Pinned = property(_get_Pinned, _set_Pinned)

    def _get_PinnedLabel(self):
        return u'Oui' if self._pinned else u'Non'

    PinnedLabel = property(_get_PinnedLabel)


# ─── Découverte des paramètres disponibles ────────────────────────────────────
def discover_parameters(elements):
    """(paramètres d'occurrence, paramètres de type) proposés en colonnes.

    Les paramètres sont attachés par catégorie et par famille : les lire sur un
    représentant de chaque couple (catégorie, type) donne la même liste qu'un
    balayage exhaustif, pour une fraction du temps de calcul."""
    occurrences, types = set(), set()
    vus = set()
    for e in elements:
        try:
            cle_cat = _eid_value(e.Category.Id)
        except Exception:
            cle_cat = 0
        try:
            cle_type = _eid_value(e.GetTypeId())
        except Exception:
            cle_type = 0
        cle = (cle_cat, cle_type)
        if cle in vus:
            continue
        vus.add(cle)
        try:
            for p in e.Parameters:
                try:
                    nom = p.Definition.Name
                    if nom:
                        occurrences.add(nom)
                except Exception:
                    pass
        except Exception:
            pass
        etype = _type_info(e)[2]
        if etype is not None:
            try:
                for p in etype.Parameters:
                    try:
                        nom = p.Definition.Name
                        if nom:
                            types.add(nom)
                    except Exception:
                        pass
            except Exception:
                pass
    return (sorted(occurrences, key=_normalize), sorted(types, key=_normalize))


def _valeur_param_occurrence(elem, nom):
    try:
        return _param_to_str(elem.LookupParameter(nom))
    except Exception:
        return u''


def _valeur_param_type(elem, nom):
    try:
        cle_type = _eid_value(elem.GetTypeId())
    except Exception:
        return u''
    cle = (cle_type, nom)
    if cle not in _cache_param_type:
        etype = _type_info(elem)[2]
        valeur = u''
        if etype is not None:
            try:
                valeur = _param_to_str(etype.LookupParameter(nom))
            except Exception:
                valeur = u''
        _cache_param_type[cle] = valeur
    return _cache_param_type[cle]


# ─── Colonnes : identité persistante et clé de liaison WPF ────────────────────
# ident  : identité stable enregistrée dans config.json ('fixe:LevelName',
#          'inst:Commentaires', 'type:Description'). Insensible à l'ordre des
#          colonnes et au contenu du modèle.
# key    : nom d'attribut porté par la ligne et cible du Binding WPF. Doit être
#          un identifiant simple : les noms de paramètres (espaces, accents,
#          ponctuation) ne peuvent pas servir de chemin de liaison.
_cles_par_ident = {}
_compteur_cles  = [0]


def _cle_param(ident):
    if ident not in _cles_par_ident:
        _cles_par_ident[ident] = u'P{}'.format(_compteur_cles[0])
        _compteur_cles[0] += 1
    return _cles_par_ident[ident]


class _Colonne(object):
    def __init__(self, ident, key, label, genre, nom_param=None):
        self.ident     = ident      # identité persistante
        self.key       = key        # chemin de liaison WPF / attribut de ligne
        self.label     = label      # en-tête affiché
        self.genre     = genre      # 'check' | 'fixe' | 'inst' | 'type'
        self.nom_param = nom_param
        self.col       = None       # DataGridColumn associée
        self.largeur   = _LARGEUR_DEFAUT


def _colonnes_fixes():
    cols = [
        _Colonne(u'fixe:Selected',     u'SelectedLabel', u'Sélection', 'check'),
        _Colonne(u'fixe:CategoryName', u'CategoryName',  u'Catégorie', 'fixe'),
        _Colonne(u'fixe:FamilyName',   u'FamilyName',    u'Famille',   'fixe'),
        _Colonne(u'fixe:TypeName',     u'TypeName',      u'Type',      'fixe'),
        _Colonne(u'fixe:ElementName',  u'ElementName',   u'Nom',       'fixe'),
        _Colonne(u'fixe:LevelName',    u'LevelName',     u'Niveau',    'fixe'),
        _Colonne(u'fixe:PinnedLabel',  u'PinnedLabel',   u'Épinglé',   'fixe'),
        _Colonne(u'fixe:IdText',       u'IdText',        u'Id',        'fixe'),
    ]
    if doc.IsWorkshared:
        cols.append(_Colonne(u'fixe:WorksetName', u'WorksetName',
                             u'Espace de travail', 'fixe'))
    largeurs = {
        u'fixe:Selected': 90, u'fixe:PinnedLabel': 80, u'fixe:IdText': 100,
    }
    for c in cols:
        c.largeur = largeurs.get(c.ident, _LARGEUR_DEFAUT)
    return cols


def _colonne_param(ident, avail_inst, avail_type):
    """Colonne de paramètre à partir de son identité persistante, ou None si le
    paramètre n'existe plus parmi les éléments chargés."""
    if ident.startswith(u'inst:'):
        nom = ident[5:]
        if nom not in avail_inst:
            return None
        return _Colonne(ident, _cle_param(ident), nom, 'inst', nom)
    if ident.startswith(u'type:'):
        nom = ident[5:]
        if nom not in avail_type:
            return None
        return _Colonne(ident, _cle_param(ident), u'{} (type)'.format(nom), 'type', nom)
    return None


# ─── Dialogue générique de liste à cocher ─────────────────────────────────────
def _show_checklist(xaml_name, titre, sections, valeurs_cochees, owner=None):
    """Liste à cocher avec recherche et sélection multiple (Maj+Clic pour une
    plage), utilisée pour les filtres de colonne comme pour le choix des
    colonnes de paramètres.

    sections : liste de couples (titre de section ou None, [(valeur, libellé)]).
    Retourne l'ensemble des valeurs cochées, ou None si l'utilisateur annule."""
    xaml_path = os.path.join(os.path.dirname(__file__), xaml_name)
    # set_owner=False : forms.WPFWindow fixe par défaut l'owner Win32 natif
    # directement sur la fenêtre de Revit (WindowInteropHelper), ce qui
    # court-circuite l'owner WPF passé ici. Résultat : Windows ne redemande
    # jamais le repaint de la fenêtre masquée sous ce dialogue à sa fermeture,
    # seulement celui de Revit — d'où un affichage décalé d'une action.
    dlg = forms.WPFWindow(xaml_path, set_owner=False)
    dlg.Title = titre
    if owner is not None:
        dlg.Owner = owner

    coches      = set(valeurs_cochees)
    checks      = []   # [(CheckBox, valeur)]
    entetes     = []   # [(TextBlock, index de début, index de fin exclus)]
    dernier_idx = [-1]

    for titre_section, items in sections:
        if not items:
            continue
        if titre_section:
            tb = TextBlock()
            tb.Text = titre_section
            tb.FontWeight = FontWeights.Bold
            tb.Margin = Thickness(2, 8, 2, 2)
            dlg.valuesPanel.Children.Add(tb)
            entetes.append([tb, len(checks), 0])
        for valeur, libelle in items:
            cb = CheckBox()
            cb.Content = _escape_access_text(libelle) if libelle else u'(vide)'
            cb.IsChecked = valeur in coches
            cb.Margin = Thickness(2, 2, 2, 2)

            def _mk(idx, val, checkbox):
                def on_click(s, e):
                    etat = bool(checkbox.IsChecked)
                    maj = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                           Keyboard.IsKeyDown(WpfKey.RightShift))
                    if maj and dernier_idx[0] >= 0:
                        lo, hi = min(dernier_idx[0], idx), max(dernier_idx[0], idx)
                        for j in range(lo, hi + 1):
                            cb_j, val_j = checks[j]
                            cb_j.IsChecked = etat
                            if etat:
                                coches.add(val_j)
                            else:
                                coches.discard(val_j)
                    else:
                        if etat:
                            coches.add(val)
                        else:
                            coches.discard(val)
                    dernier_idx[0] = idx
                return on_click

            cb.Click += _mk(len(checks), valeur, cb)
            dlg.valuesPanel.Children.Add(cb)
            checks.append((cb, valeur))
        if entetes and titre_section:
            entetes[-1][2] = len(checks)

    def _visible(cb):
        return cb.Visibility == Visibility.Visible

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
            etat = not bool(cb.IsChecked)
            cb.IsChecked = etat
            if etat:
                coches.add(val)
            else:
                coches.discard(val)

    def on_search_changed(s, e):
        contient = _normalize(dlg.txtSearch.Text)
        exclut   = _normalize(dlg.txtSearchExclude.Text)
        for cb, val in checks:
            texte = _normalize(cb.Content)
            montrer = ((not contient or contient in texte) and
                       (not exclut or exclut not in texte))
            cb.Visibility = Visibility.Visible if montrer else Visibility.Collapsed
        # Un titre de section dont plus aucun élément n'est visible disparaît.
        for tb, debut, fin in entetes:
            reste = any(_visible(checks[j][0]) for j in range(debut, min(fin, len(checks))))
            tb.Visibility = Visibility.Visible if reste else Visibility.Collapsed

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


def show_column_filter_dialog(label, valeurs, autorisees, owner=None):
    """Valeurs uniques (triées) d'une colonne, à cocher, pour filtrer le
    tableau."""
    items = [(v, v if v else u'(vide)') for v in valeurs]
    return _show_checklist('ColumnFilterDialog.xaml',
                           u"Filtrer — {}".format(label),
                           [(None, items)], autorisees, owner=owner)


def show_columns_picker_dialog(avail_inst, avail_type, idents_coches, owner=None):
    """Choix des paramètres affichés en colonnes. Retourne la liste ordonnée des
    identités retenues (occurrence puis type, ordre alphabétique), ou None."""
    items_inst = [(u'inst:{}'.format(n), n) for n in avail_inst]
    items_type = [(u'type:{}'.format(n), n) for n in avail_type]
    sections = [
        (u"Paramètres d'occurrence", items_inst),
        (u"Paramètres de type", items_type),
    ]
    resultat = _show_checklist('ColumnsPickerDialog.xaml',
                               u"Colonnes à afficher", sections,
                               idents_coches, owner=owner)
    if resultat is None:
        return None
    ordonnes = []
    for _titre, items in sections:
        for ident, _libelle in items:
            if ident in resultat:
                ordonnes.append(ident)
    return ordonnes


# ─── Contexte d'exécution d'une fenêtre non modale ────────────────────────────
#
# La fenêtre reste ouverte après la fin de la commande pyRevit. Deux
# conséquences, toutes deux traitées par cette classe :
#
# 1. pyRevit vide les globals du module dès que la commande rend la main : tout
#    callback (clic, filtre, fermeture) qui référence un nom du fichier lèverait
#    NameError — que WPF avale en silence. On garde une COPIE des globals au
#    démarrage et on la réinjecte en tête de chaque callback.
# 2. Revit interdit de modifier le document depuis une fenêtre non modale. Les
#    actions qui écrivent (épinglage) ou qui pilotent l'UI (sélection) sont donc
#    planifiées et exécutées dans Execute(), seul contexte API valide.
class _ActionHandler(IExternalEventHandler):

    def __init__(self):
        self._fn      = [None]           # mutable — pas de nonlocal en IPy 2.7
        self._globals = dict(globals())  # snapshot ICI : globals encore vivants

    def restaurer_globals(self):
        globals().update(self._globals)

    def planifier(self, fn):
        self._fn[0] = fn

    def Execute(self, uiapp):
        try:
            self.restaurer_globals()
        except Exception:
            pass
        fn = self._fn[0]
        self._fn[0] = None
        if fn is None:
            return
        try:
            fn(uiapp)
        except Exception:
            # Ne jamais avaler en silence : sans cette remontée, une action
            # planifiée qui échoue se traduit par un bouton qui « ne fait rien ».
            import traceback
            try:
                import System.Windows as _SW
                _SW.MessageBox.Show(traceback.format_exc(), u'NM-BATII — Erreur')
            except Exception:
                pass

    def GetName(self):
        return u"NM-BATII — Selection et epinglage des elements"


def _doc_actif():
    try:
        return HOST_APP.doc
    except Exception:
        return None


# ─── Fenêtre principale ───────────────────────────────────────────────────────
_PORTEES = ('projet', 'vue', 'selection')


def main(action_handler, ext_event):
    reglages = _load_settings()

    xaml_path = os.path.join(os.path.dirname(__file__), 'MainWindow.xaml')
    # handle_esc=False : sur une palette non modale, Échap appartient au flux de
    # travail Revit (sortir d'un outil, vider la sélection) et ne doit pas
    # fermer la fenêtre.
    wpf = forms.WPFWindow(xaml_path, handle_esc=False)

    # Remet le module dans son état de départ : à appeler en TÊTE de tout
    # callback WPF, avant de référencer quoi que ce soit du fichier.
    _restaurer = action_handler.restaurer_globals

    fenetre = reglages.get('fenetre', {})
    try:
        if fenetre.get('largeur'):
            wpf.Width = max(780.0, float(fenetre['largeur']))
        if fenetre.get('hauteur'):
            wpf.Height = max(440.0, float(fenetre['hauteur']))
    except Exception:
        pass

    portee_init = reglages.get('portee', 'projet')
    if portee_init not in _PORTEES:
        portee_init = 'projet'
    wpf.cboScope.SelectedIndex = _PORTEES.index(portee_init)
    wpf.chkAnnotations.IsChecked = bool(reglages.get('inclure_annotations', False))

    etat = {
        'all_rows':        [],
        'visible_rows':    [],
        'colonnes':        [],    # [_Colonne] dans l'ordre d'affichage courant
        'filtres':         {},    # clé de colonne -> set(valeurs autorisées)|None
        'tri':             None,  # (clé de colonne, 'asc'|'desc')
        'entetes':         {},    # clé de colonne -> boutons de l'en-tête
        'params_choisis':  [i for i in reglages.get('colonnes_parametres', [])
                            if isinstance(i, basestring)],
        'ordre':           [i for i in reglages.get('ordre_colonnes', [])
                            if isinstance(i, basestring)],
        'largeurs':        dict(reglages.get('largeurs_colonnes', {})),
        'avail_inst':      [],
        'avail_type':      [],
        'idents_calcules': set(),  # colonnes de paramètres déjà valorisées
        'chargement':      False,
        # Index dans 'visible_rows' de la dernière ligne cliquée sans MAJ : c'est
        # l'ancre des plages MAJ+clic. -1 = pas d'ancre.
        'ancre':           -1,
    }

    tri_enregistre = reglages.get('tri')

    # ── Compteur et filtrage ─────────────────────────────────────────────────
    def _maj_compteur():
        n = sum(1 for r in etat['all_rows'] if r.Selected)
        wpf.txtCount.Text = u"({} élément(s) coché(s) sur {} affiché(s))".format(
            n, len(etat['visible_rows']))

    def _ligne_visible(row):
        for cle, autorisees in etat['filtres'].items():
            if autorisees is not None and getattr(row, cle, u'') not in autorisees:
                return False
        return True

    def apply_filter():
        # Le filtre et le tri sont recalculés côté Python puis appliqués en
        # réaffectant ItemsSource à une collection neuve : plus robuste que
        # ICollectionView (Filter + Refresh()), dont le rendu s'est révélé
        # décalé d'une action dans cet hôte WPF.
        lignes = [r for r in etat['all_rows'] if _ligne_visible(r)]
        if etat['tri']:
            cle, sens = etat['tri']
            if cle == u'IdText':
                # Les Id se comparent en nombres : en texte, "1000" passerait
                # avant "999".
                cle_tri = lambda r: _entier_ou_zero(getattr(r, cle, u''))
            else:
                cle_tri = lambda r: _normalize(getattr(r, cle, u''))
            lignes.sort(key=cle_tri, reverse=(sens == 'desc'))
        etat['visible_rows'] = lignes
        # L'ancre est un index dans 'visible_rows' : elle ne veut plus rien dire
        # dès que la liste change de contenu ou d'ordre.
        etat['ancre'] = -1
        collection = ObservableCollection[object]()
        for r in lignes:
            collection.Add(r)
        wpf.dataGrid.ItemsSource = collection
        _maj_compteur()

    # ── En-têtes de colonne (tri, filtre, réinitialisation) ──────────────────
    def _maj_boutons_tri():
        courant = etat['tri']
        for cle, widgets in etat['entetes'].items():
            if courant and courant[0] == cle:
                widgets['tri'].Content = u'A→Z' if courant[1] == 'asc' else u'Z→A'
            else:
                widgets['tri'].Content = u'A-Z ↕'

    def _maj_bouton_filtre(cle):
        widgets = etat['entetes'].get(cle)
        if not widgets:
            return
        actif = etat['filtres'].get(cle) is not None
        widgets['filtre'].Foreground = Brushes.OrangeRed if actif else Brushes.Black

    def _mk_handler_tri(cle):
        def handler(s, e):
            _restaurer()
            courant = etat['tri']
            if courant == (cle, 'asc'):
                etat['tri'] = (cle, 'desc')
            elif courant == (cle, 'desc'):
                etat['tri'] = None
            else:
                etat['tri'] = (cle, 'asc')
            _maj_boutons_tri()
            apply_filter()
        return handler

    def _mk_handler_filtre(cle, label):
        def handler(s, e):
            _restaurer()
            valeurs = sorted(set(getattr(r, cle, u'') for r in etat['all_rows']),
                             key=_normalize)
            autorisees = etat['filtres'].get(cle)
            if autorisees is None:
                # Aucun filtre encore posé : on ouvre la liste tout décoché,
                # l'utilisateur coche les seules valeurs qu'il veut garder.
                # Un filtre déjà actif, lui, se rouvre sur les valeurs gardées.
                autorisees = set()
            resultat = show_column_filter_dialog(label, valeurs, autorisees, owner=wpf)
            wpf.Activate()
            if resultat is not None:
                tout = (resultat == set(valeurs))
                etat['filtres'][cle] = None if tout else resultat
                _maj_bouton_filtre(cle)
                apply_filter()
        return handler

    def _mk_handler_reset_colonne(cle):
        def handler(s, e):
            _restaurer()
            if etat['filtres'].get(cle) is not None:
                etat['filtres'][cle] = None
                _maj_bouton_filtre(cle)
                apply_filter()
        return handler

    def _on_reset_all_filters(s, e):
        _restaurer()
        change = False
        for cle in etat['filtres'].keys():
            if etat['filtres'][cle] is not None:
                etat['filtres'][cle] = None
                _maj_bouton_filtre(cle)
                change = True
        if change:
            apply_filter()

    def _make_header(label, cle):
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
        tb.ToolTip = u"{}\n(glisser l'en-tête pour déplacer la colonne)".format(label)
        Grid.SetRow(tb, 0)

        panneau = Grid()
        panneau.HorizontalAlignment = HorizontalAlignment.Center
        Grid.SetRow(panneau, 1)

        def _mk_bouton(contenu, infobulle, largeur=22, taille=10):
            b = Button()
            b.Content = contenu
            b.Width = largeur; b.Height = 20
            b.Margin = Thickness(2, 0, 2, 0)
            b.Padding = Thickness(0)
            b.FontSize = taille
            b.HorizontalContentAlignment = HorizontalAlignment.Center
            b.VerticalContentAlignment = VerticalAlignment.Center
            b.ToolTip = infobulle
            return b

        btn_tri    = _mk_bouton(u'A-Z ↕', u'Trier', largeur=34, taille=9)
        btn_filtre = _mk_bouton(u'▼', u'Filtrer')
        btn_reset  = _mk_bouton(u'X', u'Réinitialiser le filtre de cette colonne')

        ligne = StackPanel()
        ligne.Orientation = Orientation.Horizontal
        ligne.HorizontalAlignment = HorizontalAlignment.Center
        ligne.Children.Add(btn_tri)
        ligne.Children.Add(btn_filtre)
        ligne.Children.Add(btn_reset)
        panneau.Children.Add(ligne)

        g.Children.Add(tb)
        g.Children.Add(panneau)

        btn_tri.Click    += _mk_handler_tri(cle)
        btn_filtre.Click += _mk_handler_filtre(cle, label)
        btn_reset.Click  += _mk_handler_reset_colonne(cle)

        etat['entetes'][cle] = {'tri': btn_tri, 'filtre': btn_filtre, 'reset': btn_reset}
        return g

    # ── Cocher / décocher : clic sur la ligne, avec CTRL et MAJ ──────────────
    #
    # Le clic est traité au niveau du tableau et non sur la case à cocher : il
    # doit agir depuis n'importe quelle colonne de la ligne. La case n'est donc
    # plus qu'un indicateur (voir _make_checkbox_column).
    #
    #   clic            bascule la ligne, pose l'ancre
    #   CTRL + clic     idem — bascule isolée, le reste du tableau intact
    #   MAJ + clic      la plage ancre→ligne prend l'état de la ligne cliquée
    #                   une fois basculée (coche OU décoche toute la plage)
    #   CTRL+MAJ+clic   coche la plage ancre→ligne, sans jamais rien décocher
    #
    # MAJ ne déplace pas l'ancre : des MAJ+clics successifs réajustent la même
    # plage, comme dans l'explorateur Windows.
    def _ligne_depuis_clic(origine):
        """Ligne du tableau sous le point cliqué, ou None (en-tête, barre de
        défilement, zone vide sous la dernière ligne)."""
        obj = origine
        while obj is not None:
            if isinstance(obj, DataGridRow):
                return obj.Item
            if isinstance(obj, Visual):
                obj = VisualTreeHelper.GetParent(obj)
            else:
                # Run, FlowDocument... : hors arbre visuel, remonter en logique.
                obj = LogicalTreeHelper.GetParent(obj)
        return None

    def _on_grid_click(sender, e):
        _restaurer()
        try:
            ligne = _ligne_depuis_clic(e.OriginalSource)
        except Exception:
            ligne = None
        if ligne is None:
            return
        visibles = etat['visible_rows']
        try:
            idx = visibles.index(ligne)
        except ValueError:
            return

        ctrl = (Keyboard.IsKeyDown(WpfKey.LeftCtrl) or
                Keyboard.IsKeyDown(WpfKey.RightCtrl))
        maj  = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                Keyboard.IsKeyDown(WpfKey.RightShift))
        ancre = etat['ancre']

        if maj and 0 <= ancre < len(visibles):
            lo, hi = min(ancre, idx), max(ancre, idx)
            cible = True if ctrl else (not visibles[idx].Selected)
            for j in range(lo, hi + 1):
                visibles[j].Selected = cible
        else:
            visibles[idx].Selected = not visibles[idx].Selected
            etat['ancre'] = idx
        _maj_compteur()

    def _make_checkbox_column(colonne):
        col = DataGridTemplateColumn()
        col.Header = _make_header(colonne.label, colonne.key)
        col.Width = DataGridLength(colonne.largeur)
        col.CanUserReorder = False
        # Sans ça, un double-clic bascule la cellule en édition : faute de
        # CellEditingTemplate, le DataGrid réutilise le CellTemplate et la case
        # réapparaît, cette fois cliquable — donc désynchronisée du modèle.
        col.IsReadOnly = True
        fabrique = FrameworkElementFactory(CheckBox)
        fabrique.SetValue(CheckBox.HorizontalAlignmentProperty, HorizontalAlignment.Center)
        # Indicateur passif : sans IsHitTestVisible=False, un clic sur la case
        # la basculerait elle-même EN PLUS de la bascule faite par
        # _on_grid_click, et les deux s'annuleraient.
        fabrique.SetValue(UIElement.IsHitTestVisibleProperty, False)
        fabrique.SetValue(UIElement.FocusableProperty, False)
        liaison = Binding('Selected')
        liaison.Mode = BindingMode.OneWay
        fabrique.SetBinding(CheckBox.IsCheckedProperty, liaison)
        modele = DataTemplate()
        modele.VisualTree = fabrique
        col.CellTemplate = modele
        return col

    def _make_text_column(colonne):
        col = DataGridTextColumn()
        col.Header = _make_header(colonne.label, colonne.key)
        col.Binding = Binding(colonne.key)
        col.IsReadOnly = True
        col.Width = DataGridLength(colonne.largeur)
        return col

    # ── Construction / reconstruction des colonnes ───────────────────────────
    def _valoriser_colonne(colonne):
        """Calcule la valeur de la colonne de paramètre sur toutes les lignes.
        N'est fait qu'une fois par paramètre : réafficher une colonne déjà
        connue est instantané."""
        if colonne.genre not in ('inst', 'type'):
            return
        if colonne.ident in etat['idents_calcules']:
            return
        lecteur = (_valeur_param_occurrence if colonne.genre == 'inst'
                   else _valeur_param_type)
        for r in etat['all_rows']:
            setattr(r, colonne.key, lecteur(r.element, colonne.nom_param))
        etat['idents_calcules'].add(colonne.ident)

    def _capturer_ordre_et_largeurs():
        """Relit l'ordre (modifié par glissé des en-têtes) et les largeurs
        réellement affichées, pour les réappliquer ou les enregistrer."""
        for c in etat['colonnes']:
            if c.col is None:
                continue
            try:
                if c.col.ActualWidth > 0:
                    c.largeur = int(round(c.col.ActualWidth))
                    etat['largeurs'][c.ident] = c.largeur
            except Exception:
                pass
        try:
            visibles = sorted([c for c in etat['colonnes'] if c.col is not None],
                              key=lambda c: c.col.DisplayIndex)
            # Tableau pas encore construit : l'ordre enregistré dans config.json
            # doit survivre à cet appel, sans quoi il serait écrasé par une
            # liste vide au premier chargement.
            if visibles:
                etat['ordre'] = [c.ident for c in visibles]
        except Exception:
            pass

    def rebuild_columns():
        _capturer_ordre_et_largeurs()

        fixes = _colonnes_fixes()
        params = []
        for ident in etat['params_choisis']:
            colonne = _colonne_param(ident, etat['avail_inst'], etat['avail_type'])
            if colonne is not None:
                params.append(colonne)

        par_ident = {}
        for c in fixes + params:
            c.largeur = etat['largeurs'].get(c.ident, c.largeur)
            par_ident[c.ident] = c

        # Ordre : les colonnes déjà placées gardent leur position, les
        # nouvelles sont ajoutées à la suite. La case à cocher reste en tête.
        ordonnees = []
        for ident in etat['ordre']:
            if ident in par_ident and par_ident[ident] not in ordonnees:
                ordonnees.append(par_ident[ident])
        for c in fixes + params:
            if c not in ordonnees:
                ordonnees.append(c)
        colonne_check = par_ident[u'fixe:Selected']
        ordonnees.remove(colonne_check)
        ordonnees.insert(0, colonne_check)

        for c in params:
            _valoriser_colonne(c)

        # Les filtres portant sur une colonne retirée sont abandonnés.
        cles_valides = set(c.key for c in ordonnees)
        for cle in list(etat['filtres'].keys()):
            if cle not in cles_valides:
                del etat['filtres'][cle]
        if etat['tri'] and etat['tri'][0] not in cles_valides:
            etat['tri'] = None

        etat['entetes'] = {}
        grille = wpf.dataGrid
        grille.FrozenColumnCount = 0
        grille.Columns.Clear()
        for c in ordonnees:
            c.col = (_make_checkbox_column(c) if c.genre == 'check'
                     else _make_text_column(c))
            grille.Columns.Add(c.col)
            etat['filtres'].setdefault(c.key, None)
            _maj_bouton_filtre(c.key)
        grille.FrozenColumnCount = 1

        etat['colonnes'] = ordonnees
        etat['ordre'] = [c.ident for c in ordonnees]
        _maj_boutons_tri()

    # ── Chargement des éléments ──────────────────────────────────────────────
    def _portee_courante():
        idx = wpf.cboScope.SelectedIndex
        if idx < 0 or idx >= len(_PORTEES):
            return 'projet'
        return _PORTEES[idx]

    def reload_rows():
        """Recharge la liste des éléments depuis le modèle. Retourne False si
        l'utilisateur renonce devant le volume à traiter, ou si le document
        d'origine n'est plus le document actif."""
        actif = _doc_actif()
        if actif is not None:
            try:
                conforme = actif.Equals(doc)
            except Exception:
                conforme = True
            if not conforme:
                show_alert(TITRE,
                           u"Le document actif n'est plus celui à partir duquel "
                           u"cet outil a été lancé.\n\nRéactivez ce document, ou "
                           u"relancez l'outil depuis le document voulu.",
                           close_label=u'Retour')
                return False
        portee = _portee_courante()
        inclure = bool(wpf.chkAnnotations.IsChecked)
        elements = collect_elements(portee, inclure)

        if len(elements) > _SEUIL_AVERTISSEMENT:
            if not show_confirm(
                    TITRE,
                    u"La portée retenue comporte **{} éléments**.\n\n"
                    u"La construction du tableau peut demander plusieurs "
                    u"dizaines de secondes.\n\nContinuer ?".format(len(elements)),
                    yes_label=u'Continuer', no_label=u'Annuler'):
                return False

        Mouse.OverrideCursor = Cursors.Wait
        try:
            _vider_caches()
            etat['all_rows'] = [_ElementRow(e) for e in elements]
            etat['avail_inst'], etat['avail_type'] = discover_parameters(elements)
            etat['idents_calcules'] = set()
            # Les valeurs disponibles ont changé : les filtres de valeurs
            # deviendraient arbitraires, on repart d'un tableau non filtré.
            etat['filtres'] = {}
            rebuild_columns()
            apply_filter()
        finally:
            Mouse.OverrideCursor = None
        _log(u"### {}\n\n- Portée : {}\n- Éléments chargés : {}\n"
             u"- Paramètres d'occurrence : {}\n- Paramètres de type : {}".format(
                 TITRE, portee, len(etat['all_rows']),
                 len(etat['avail_inst']), len(etat['avail_type'])))
        return True

    # ── Actions sur les éléments cochés ──────────────────────────────────────
    #
    # Épinglage et sélection écrivent dans le document ou pilotent l'UI de
    # Revit : depuis une fenêtre non modale c'est refusé hors contexte API. Le
    # clic se contente donc de planifier l'action, que l'ExternalEvent exécute
    # dès que Revit est disponible.
    def _lignes_cochees():
        return [r for r in etat['all_rows'] if r.Selected]

    def _planifier(fn):
        action_handler.planifier(fn)
        ext_event.Raise()

    def _uidoc_conforme(uiapp):
        """UIDocument actif, à condition qu'il s'agisse toujours du document à
        partir duquel le tableau a été construit — sinon None, avec message.
        La palette restant ouverte, l'utilisateur peut avoir changé de projet
        entre-temps : les Id du tableau ne voudraient plus rien dire."""
        try:
            uidoc_actif = uiapp.ActiveUIDocument
        except Exception:
            uidoc_actif = None
        if uidoc_actif is not None:
            try:
                if uidoc_actif.Document.Equals(doc):
                    return uidoc_actif
            except Exception:
                pass
        show_alert(TITRE,
                   u"Le document actif n'est plus celui à partir duquel la "
                   u"liste a été construite.\n\nRéactivez ce document, ou "
                   u"relancez l'outil depuis le document voulu.",
                   close_label=u'Retour')
        return None

    def _executer_epinglage(uiapp, valeur):
        if _uidoc_conforme(uiapp) is None:
            return
        lignes = _lignes_cochees()
        if not lignes:
            return
        libelle = u"Épingler" if valeur else u"Désépingler"
        n_modifies = n_inchanges = n_echecs = 0
        Mouse.OverrideCursor = Cursors.Wait
        try:
            with revit.Transaction(u"NM-BATII : {} les éléments".format(libelle.lower())):
                for r in lignes:
                    try:
                        elem = doc.GetElement(r.element_id)
                        if elem is None:
                            n_echecs += 1
                            continue
                        if bool(elem.Pinned) == valeur:
                            n_inchanges += 1
                            r.Pinned = valeur
                            continue
                        elem.Pinned = valeur
                        r.Pinned = bool(elem.Pinned)
                        if r.Pinned == valeur:
                            n_modifies += 1
                        else:
                            n_echecs += 1
                    except Exception:
                        n_echecs += 1
        finally:
            Mouse.OverrideCursor = None

        apply_filter()
        message = u"**{} élément(s)** {}.".format(
            n_modifies, u"épinglé(s)" if valeur else u"désépinglé(s)")
        if n_inchanges:
            message += u"\n{} élément(s) déjà dans cet état.".format(n_inchanges)
        if n_echecs:
            message += (u"\n{} élément(s) non traité(s) : épinglage refusé par "
                        u"Revit (élément de groupe, de lien ou supprimé).".format(n_echecs))
        show_alert(TITRE, message, close_label=u'Retour')

    def _executer_selection(uiapp):
        uidoc_actif = _uidoc_conforme(uiapp)
        if uidoc_actif is None:
            return
        ids = List[DB.ElementId]()
        for r in _lignes_cochees():
            if doc.GetElement(r.element_id) is not None:
                ids.Add(r.element_id)
        if ids.Count == 0:
            return
        try:
            uidoc_actif.Selection.SetElementIds(ids)
        except Exception:
            show_alert(TITRE, u"Revit a refusé la sélection de ces éléments.",
                       close_label=u'Retour')

    def _demander(action):
        """Contrôle commun aux trois boutons d'action puis planification."""
        if not _lignes_cochees():
            show_alert(TITRE, u"Aucun élément coché dans le tableau.",
                       close_label=u'Retour')
            return
        _planifier(action)

    def _on_pin(s, e):
        _restaurer()
        _demander(lambda uiapp: _executer_epinglage(uiapp, True))

    def _on_unpin(s, e):
        _restaurer()
        _demander(lambda uiapp: _executer_epinglage(uiapp, False))

    def _on_select_in_revit(s, e):
        _restaurer()
        _demander(_executer_selection)

    # ── Barre du haut ────────────────────────────────────────────────────────
    def _on_reload(s, e):
        _restaurer()
        if etat['chargement']:
            return
        etat['chargement'] = True
        try:
            if reload_rows():
                etat['portee_ok'] = _portee_courante()
                etat['annotations_ok'] = bool(wpf.chkAnnotations.IsChecked)
            else:
                # Chargement refusé : on rétablit les critères précédents sans
                # relancer de chargement (drapeau 'chargement' encore posé).
                wpf.cboScope.SelectedIndex = _PORTEES.index(etat['portee_ok'])
                wpf.chkAnnotations.IsChecked = etat['annotations_ok']
        finally:
            etat['chargement'] = False

    def _on_columns(s, e):
        _restaurer()
        if not etat['all_rows']:
            show_alert(TITRE, u"Chargez d'abord des éléments dans le tableau.",
                       close_label=u'Retour')
            return
        resultat = show_columns_picker_dialog(etat['avail_inst'], etat['avail_type'],
                                              etat['params_choisis'], owner=wpf)
        wpf.Activate()
        if resultat is None:
            return
        etat['params_choisis'] = resultat
        Mouse.OverrideCursor = Cursors.Wait
        try:
            rebuild_columns()
            apply_filter()
        finally:
            Mouse.OverrideCursor = None

    def _on_reset_columns(s, e):
        _restaurer()
        etat['ordre'] = []
        etat['largeurs'] = {}
        for c in etat['colonnes']:
            c.col = None
        rebuild_columns()
        apply_filter()

    def _on_select_all(s, e):
        _restaurer()
        for r in etat['visible_rows']:
            r.Selected = True
        _maj_compteur()

    def _on_deselect_all(s, e):
        _restaurer()
        for r in etat['visible_rows']:
            r.Selected = False
        _maj_compteur()

    def _on_invert(s, e):
        _restaurer()
        for r in etat['visible_rows']:
            r.Selected = not r.Selected
        _maj_compteur()

    # ── Fermeture : enregistrement des réglages ──────────────────────────────
    def _enregistrer_reglages():
        _capturer_ordre_et_largeurs()
        largeur = hauteur = None
        try:
            if wpf.Width > 0:
                largeur = int(round(wpf.Width))
            if wpf.Height > 0:
                hauteur = int(round(wpf.Height))
        except Exception:
            pass
        tri = None
        if etat['tri']:
            for c in etat['colonnes']:
                if c.key == etat['tri'][0]:
                    tri = [c.ident, etat['tri'][1]]
                    break
        # OrderedDict et largeurs triées par identité : la section réécrite est
        # identique d'une session à l'autre tant que les réglages ne changent
        # pas, donc pas de diff parasite dans config.json (fichier versionné).
        _save_settings(OrderedDict([
            ('portee',              _portee_courante()),
            ('inclure_annotations', bool(wpf.chkAnnotations.IsChecked)),
            ('colonnes_parametres', list(etat['params_choisis'])),
            ('ordre_colonnes',      list(etat['ordre'])),
            ('largeurs_colonnes',   OrderedDict(sorted(etat['largeurs'].items()))),
            ('tri',                 tri),
            ('fenetre',             OrderedDict([('largeur', largeur),
                                                 ('hauteur', hauteur)])),
        ]))

    # Tunneling : le handler passe AVANT que DataGridRow ne traite le clic pour
    # son propre surlignage, et reçoit donc l'événement quelle que soit la
    # colonne touchée. On ne marque pas e.Handled : le surlignage natif des
    # lignes reste actif et donne un retour visuel sur la plage MAJ+clic.
    wpf.dataGrid.PreviewMouseLeftButtonDown += _on_grid_click

    wpf.cboScope.SelectionChanged += _on_reload
    wpf.chkAnnotations.Click      += _on_reload
    wpf.btnReload.Click           += _on_reload
    wpf.btnColumns.Click          += _on_columns
    wpf.btnResetColumns.Click     += _on_reset_columns
    wpf.btnSelectAll.Click        += _on_select_all
    wpf.btnDeselectAll.Click      += _on_deselect_all
    wpf.btnInvert.Click           += _on_invert
    wpf.btnResetAllFilters.Click  += _on_reset_all_filters
    wpf.btnPin.Click              += _on_pin
    wpf.btnUnpin.Click            += _on_unpin
    wpf.btnSelectInRevit.Click    += _on_select_in_revit
    # Pas d'IsCancel sur ce bouton : la fenêtre est ouverte par Show(), WPF
    # lèverait une exception en tentant d'y poser DialogResult.
    wpf.btnClose.Click            += lambda s, e: wpf.Close()

    # Chargement initial.
    etat['chargement'] = True
    try:
        etat['portee_ok'] = portee_init
        etat['annotations_ok'] = bool(wpf.chkAnnotations.IsChecked)
        if not reload_rows():
            etat['all_rows'] = []
            etat['avail_inst'], etat['avail_type'] = [], []
            rebuild_columns()
            apply_filter()
    finally:
        etat['chargement'] = False

    # Tri enregistré : rétabli une fois les colonnes construites.
    if isinstance(tri_enregistre, (list, tuple)) and len(tri_enregistre) == 2:
        for c in etat['colonnes']:
            if c.ident == tri_enregistre[0] and tri_enregistre[1] in ('asc', 'desc'):
                etat['tri'] = (c.key, tri_enregistre[1])
                _maj_boutons_tri()
                apply_filter()
                break

    def _on_closed(s, e):
        _restaurer()
        _enregistrer_reglages()

    wpf.Closed += _on_closed

    # Palette non modale : Show() rend la main immédiatement, la commande
    # pyRevit se termine et Revit reste entièrement utilisable pendant que le
    # tableau reste affiché.
    wpf.Show()


if __name__ == '__main__':
    # Le handler est instancié APRÈS toutes les définitions du fichier : c'est
    # à cet instant qu'est pris le snapshot des globals que restaureront les
    # callbacks de la palette.
    _action_handler = _ActionHandler()
    _ext_event      = ExternalEvent.Create(_action_handler)
    main(_action_handler, _ext_event)
