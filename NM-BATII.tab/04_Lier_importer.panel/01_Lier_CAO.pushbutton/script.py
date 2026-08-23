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


#__title__ = 'Lier CAO \u2192 Vues'
#__author__ = 'data8bim (d8b)'

import sys
import os
import re
import fnmatch as _fnmatch
import traceback
import clr
import System
import System.Reflection
clr.AddReference("PresentationFramework")
from Microsoft.Win32 import OpenFileDialog as _OpenFileDialog


def _pick_cao_folder():
    """Ouvre un dialog fichier avec filtre multi-extensions CAO, retourne le dossier."""
    dlg = _OpenFileDialog()
    dlg.Title  = u"Choisissez un fichier CAO"
    dlg.Filter = (u"Fichiers CAO (*.dwg;*.dxf;*.axm;*.sat;*.dgn;*.obj;*.3dm;*.skp;*.stl;*.step;*.stp;*.stpz)"
                  u"|*.dwg;*.dxf;*.axm;*.sat;*.dgn;*.obj;*.3dm;*.skp;*.stl;*.step;*.stp;*.stpz")
    if dlg.ShowDialog() == True:
        return os.path.dirname(dlg.FileName)
    return None

from Autodesk.Revit.DB import (
    Element,
    ViewPlan,
    ViewDrafting,
    ViewFamily,
    ViewFamilyType,
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    Transaction,
    DWGImportOptions,
    View,
    ImportPlacement,
    ImportInstance,
    ElementId,
)
from pyrevit import forms, revit, script as pyscript


# ---------- Chemin lib/ ----------
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

from utils.config_loader import load_config
from utils.selection_fichier import pick_file_info
import utils.types_vues_personnalises as _tvp_mod
reload(_tvp_mod)
from utils.types_vues_personnalises import (get_types_vues, get_row_by_label,
                                            get_template_vars,
                                            filtrer_labels_pour_famille,
                                            filtrer_labels_pour_disciplines,
                                            get_disciplines_utilisees,
                                            cle_ordre as _cle_ordre)
import utils.disciplines as _disc_mod
reload(_disc_mod)
import dialogs.combo_recherche as _combo_mod
reload(_combo_mod)
from dialogs.combo_recherche import ComboCherchable
import utils.vues_creation as _vues_creation_mod
reload(_vues_creation_mod)
from utils.vues_creation import (
    create_views_from_candidates,
    resolve_view_name,
    prepare_view_creation,
    create_view_element,
    verifier_template,
)
import utils.extrac_nom_fichier_convention as _extrac_conv_mod
reload(_extrac_conv_mod)
from utils.extrac_nom_fichier_convention import (
    extract_file_name_info,
    delimiter_from_template,
    resolve_template,
    get_convention_template,
    build_regex,
    diagnostiquer_nom_fichier,
)
from dialogs.dialogs_styles_loader import load as load_styles, show_alert
import dialogs.selection_liste as _selection_liste_mod
reload(_selection_liste_mod)
from dialogs.selection_liste import choisir_dans_liste
load_styles(lib_dir=lib_dir)


# ---------- Logs ----------
_cfg_log = load_config() or {}

def _parse_bool_like(v):
    if isinstance(v, bool):   return v
    if isinstance(v, (int, float)): return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true",  "1", "yes", "y", "on"):  return True
        if s in ("false", "0", "no",  "n", "off"): return False
    return None

ACTIVER_LOGS = True
try:
    _parsed = _parse_bool_like(_cfg_log.get("activer_logs_scripts", True))
    if _parsed is not None:
        ACTIVER_LOGS = _parsed
except Exception:
    ACTIVER_LOGS = True

_output = None
if ACTIVER_LOGS:
    try:
        _output = pyscript.get_output()
    except Exception:
        _output = None

def log(msg):
    if not ACTIVER_LOGS:
        return
    try:
        if _output:
            _output.print_md(msg)
        else:
            print(msg)
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


# ---------- Utilitaires vues ----------
def get_building_code(level_name, delim="_"):
    return level_name.split(delim)[0] if delim in level_name else level_name


def _phase_name(phase):
    """
    Retourne le nom d'une phase de projet (DB.Phase).
    Contournement IronPython : Element.Name est implemente en interface
    explicite sur certains types, ce qui fait echouer l'acces direct phase.Name.
    """
    return Element.Name.__get__(phase)


# Marqueur affiche DANS une liste deroulante que la cascade a videe. Un menu
# vide et grise ne dit pas s'il n'y a rien ou si le remplissage a echoue ; ce
# faux item le dit, sans allonger les libelles.
# Il n'est jamais une valeur : ComboCherchable.valeur() rend None dessus.
_AUCUNE_VALEUR = u"< Aucune valeur disponible >"


# ---------- Utilitaires DWG ----------
# Charge l'enum ImportLayerMode par reflection (n'est pas toujours expose directement)
asm = System.Reflection.Assembly.GetAssembly(clr.GetClrType(DWGImportOptions))
layer_mode_type = None
for _t in asm.GetTypes():
    if _t.IsEnum and _t.Name == "ImportLayerMode":
        layer_mode_type = _t
        break

try:
    from Autodesk.Revit.DB import ImportColorMode
except ImportError:
    ImportColorMode = None

try:
    from Autodesk.Revit.DB import ImportUnit
except ImportError:
    ImportUnit = None


def get_enum_name(enum_type, predicate):
    for name in System.Enum.GetNames(enum_type):
        if predicate(name.lower()):
            return name
    return None

def get_existing_dwg_link_info(doc):
    """
    Retourne {filename.lower(): 'global' | 'view_only'} pour tous les liens CAO.
    - 'global'    : instance visible dans toutes les vues (ViewSpecific=False)
    - 'view_only' : instance visible uniquement dans sa vue (ViewSpecific=True)
    Si un fichier a des instances globales ET view_only, 'global' prend la precedence.
    """
    _cao_exts = (u".dwg", u".dxf", u".axm", u".sat", u".dgn", u".obj", u".3dm",
                 u".skp", u".stl", u".step", u".stp", u".stpz")
    info = {}
    for inst in FilteredElementCollector(doc).OfClass(ImportInstance):
        sym = doc.GetElement(inst.GetTypeId())
        if not sym:
            continue
        _p = sym.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if not _p:
            _p = sym.LookupParameter(u"Type Name")
        val = _p.AsString() if _p else None
        if not val or not any(val.lower().endswith(e) for e in _cao_exts):
            continue
        key = val.lower()
        _is_global = not inst.ViewSpecific
        if _is_global or info.get(key) == u'global':
            info[key] = u'global'
        elif key not in info:
            info[key] = u'view_only'
    return info


# ---------- Fenetre de progression liaison ----------
from System.Windows.Threading import DispatcherPriority as _DP
from System import Action as _Action
from System.Windows.Controls import CheckBox as _WPFCheckBox
from System.Windows.Controls import ListBoxItem as _ListBoxItem
from System.Windows.Media import VisualTreeHelper as _VisualTreeHelper
from System.Windows.Input import Keyboard as _Keyboard
from System.Windows.Input import ModifierKeys as _ModifierKeys
from System.Windows import Thickness as _Thickness
from System.Windows import VerticalAlignment as _VerticalAlignment

def open_link_dialog(total):
    """Cree la fenetre de progression UNE SEULE FOIS avant la boucle."""
    xaml = os.path.join(script_dir, "LinkDialog.xaml")
    win = forms.WPFWindow(xaml)
    win.Title = u"Liaison en cours"
    win.lblCounter.Text    = u"Liaison (0/{}) :".format(total)
    win.lblMessage.Text    = u""
    win.progressBar.Minimum = 0
    win.progressBar.Maximum = total
    win.progressBar.Value   = 0
    win._cancelled = False

    def on_cancel(s, e):
        win._cancelled = True
        win.Close()

    win.btnCancel.Click += on_cancel
    win.Show()
    return win

def update_link_dialog(win, fname, idx, total):
    """Met a jour le contenu sans recrer la fenetre, puis force le rendu WPF."""
    win.lblCounter.Text   = u"Liaison ({}/{}) :".format(idx, total)
    win.lblMessage.Text   = fname
    win.progressBar.Value = idx - 1
    try:
        win.Dispatcher.Invoke(_DP.Background, _Action(lambda: None))
    except Exception:
        pass


# ---------- Programme principal ----------
def main():
    try:
        doc = revit.doc

        # 1. Charger la config
        cfg = load_config() or {}
        cfg_dwg = cfg.get("fichiers_lies_dwg", {})

        # --- Filtres types de niveaux (meme logique que 01_Vues_en_masse) ---
        _prefixes_config = cfg.get(u"creer_niveaux", {}).get(u"prefixes", [])
        _vm_defaults     = cfg.get(u"vues_en_masse", {}).get(u"filtres_types_niveaux_defaut", {})
        _sign_pos = cfg.get(u"creer_niveaux", {}).get(u"signe_positif", u"+")
        _sign_neg = cfg.get(u"creer_niveaux", {}).get(u"signe_negatif", u"-")

        _pfx_patterns = []
        for _p in _prefixes_config:
            _pfx  = _p.get(u"prefixe",    u"")
            _defn = _p.get(u"definition", u"")
            if _pfx:
                _pat = re.compile(
                    u"_" + re.escape(_pfx)
                    + u"[" + re.escape(_sign_pos) + re.escape(_sign_neg) + u"]"
                )
                _pfx_patterns.append((_pat, _defn.lower()))

        def _def_key_for_lvl(lvl_name):
            for _pat, _defn_key in _pfx_patterns:
                if _pat.search(lvl_name):
                    return _defn_key
            return None

        def _construire_filtres_fichiers():
            def_to_pfxs = {}
            for _p in _prefixes_config:
                _defn = _p.get(u"definition", u"")
                _pfx  = _p.get(u"prefixe",    u"")
                if _defn:
                    if _defn not in def_to_pfxs:
                        def_to_pfxs[_defn] = []
                    def_to_pfxs[_defn].append(_pfx)
            items = []
            for _defn in sorted(def_to_pfxs.keys()):
                _pfxs  = def_to_pfxs[_defn]
                _label = u"{} - {}".format(_defn, u", ".join(_pfxs))
                _key   = _defn.lower()
                _default = _vm_defaults.get(_key, _key == u"batiment")
                items.append((_key, _label, _default))
            _autres_default = _vm_defaults.get(u"autres", False)
            items.append((None, u"Autres", _autres_default))
            return items

        _filtre_items = _construire_filtres_fichiers()
        # --------------------------------------------------------------------

        delim            = delimiter_from_template(cfg)
        _tvp_list        = get_types_vues(cfg)

        log(u"## Lier CAO \u2192 Vues")
        log(u"Delimiteur detecte : `{}`".format(delim))
        log(u"[DEBUG] Regex fichiers : `{}`".format(build_regex(cfg)))

        _tpl_nom_niveau = get_convention_template(
            cfg, 'niveau-revit', '{construction}_{niveau-code}_{demi-niv}')
        log(u"Template nommage niveaux : `{}`".format(_tpl_nom_niveau))

        # 2. Collecter les niveaux du projet
        # Controle fait AVANT de demander le dossier : sans niveau, aucune vue
        # ne peut etre creee ni aucun DWG rattache. Inutile de faire choisir un
        # dossier pour ne rien pouvoir en faire.
        levels = {
            lvl.Name: lvl
            for lvl in FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Levels)
                .WhereElementIsNotElementType()
        }
        log(u"Niveaux Revit ({}) : {}".format(
            len(levels),
            u", ".join(u"`{}`".format(n) for n in sorted(levels)[:10]) or u"(aucun)"
        ))
        if not levels:
            show_alert(u"Aucun niveau",
                       u"Le projet Revit ne contient aucun niveau.",
                       centrer=True)
            return

        buildings = {
            get_building_code(name, delim)
            for name in levels if delim in name
        }

        # 3. Choix du dossier
        folder = _pick_cao_folder()
        if not folder:
            return

        # 3bis. Collecter les phases du projet
        phases_projet = list(doc.Phases)
        if not phases_projet:
            show_alert(u"Aucune phase", u"Aucune phase trouv\u00e9e dans le projet.")
            return

        # 4. Fonction de scan (appelable depuis la fenetre via refresh)
        def scan_candidates(fld, include_sub):
            _exts = (".dwg", ".dxf", ".axm", ".sat", ".dgn", ".obj", ".3dm",
                     ".skp", ".stl", ".step", ".stp", ".stpz")
            result             = []
            nb_dwg_pdf_        = 0
            nb_convention_     = 0
            nb_batiment_absent_= 0
            nb_niveau_absent_  = 0
            bat_codes_         = set()

            walk_iter = os.walk(fld) if include_sub else [(fld, [], os.listdir(fld))]
            for root, _, files in walk_iter:
                for fn in files:
                    low = fn.lower()
                    if not any(low.endswith(e) for e in _exts):
                        continue
                    nb_dwg_pdf_ += 1
                    info = extract_file_name_info(fn, cfg)
                    if not info:
                        continue
                    nb_convention_ += 1
                    bat_codes_.add(info.get("building", ""))
                    if info.get("building") not in buildings:
                        nb_batiment_absent_ += 1
                        continue
                    bat       = info.get("building")
                    _level    = info.get("level", "")
                    _demi_str = info.get("half", "")
                    _sous_tpl = {"niveau-code": _level}
                    _vals     = {"construction": bat, "demi-niv": _demi_str}
                    lvl_name  = resolve_template(_tpl_nom_niveau, _vals, _sous_tpl)
                    if lvl_name not in levels:
                        nb_niveau_absent_ += 1
                        continue
                    full_path = os.path.join(root, fn)
                    result.append((fn, lvl_name, full_path, info.get("site", "")))
            return result, nb_dwg_pdf_, nb_convention_, nb_batiment_absent_, nb_niveau_absent_, bat_codes_

        # Extraire le code site du fichier Revit ouvert.
        # Tentative 1 : convention de nommage complete.
        # Tentative 2 : si echec (ex: niveau "XXXX" non conforme), valider le
        #   premier segment du nom contre la regex du groupe "site" uniquement.
        _rvt_path     = doc.PathName or ""
        _rvt_filename = os.path.basename(_rvt_path) if _rvt_path else (doc.Title or "")
        _rvt_info     = extract_file_name_info(_rvt_filename, cfg)
        rvt_site      = _rvt_info.get("site", "").lower() if _rvt_info else ""
        if not rvt_site:
            _nm          = cfg.get("nm_convention_noms_fichiers", {})
            _site_regex  = next(
                (g.get("regex", "") for g in _nm.get("groupes", []) if g.get("id") == "site"),
                ""
            )
            _rvt_bare    = os.path.splitext(_rvt_filename)[0]
            _first_seg   = _rvt_bare.split(delim)[0] if delim and delim in _rvt_bare else _rvt_bare
            if _site_regex and re.match(u"^(?:{})$".format(_site_regex), _first_seg, re.IGNORECASE):
                rvt_site = _first_seg.lower()
        log(u"Fichier Revit : `{}`".format(_rvt_filename))
        log(u"Code site Revit detecte : `{}`".format(rvt_site or u"(non reconnu dans le nom du fichier Revit)"))

        # Scan initial
        candidates, nb_dwg_pdf, nb_convention, nb_batiment_absent, nb_niveau_absent, bat_codes_fichiers = \
            scan_candidates(folder, False)
        log(u"Scan : {} fichier(s) CAO trouves, {} conformes a la convention, "
            u"{} batiment(s) absent(s), {} niveau(x) absent(s)".format(
                nb_dwg_pdf, nb_convention, nb_batiment_absent, nb_niveau_absent))

        # Aucun fichier conforme alors que le dossier en contient : sans
        # explication, l'utilisateur ne peut pas savoir quoi corriger. On
        # diagnostique le premier fichier rencontre a titre d'exemple.
        if nb_dwg_pdf > 0 and nb_convention == 0:
            _exemple = u""
            try:
                for _f in sorted(os.listdir(folder)):
                    if any(_f.lower().endswith(_e) for _e in ('.dwg', '.pdf')):
                        _exemple = _f
                        break
            except Exception:
                _exemple = u""
            _detail = u""
            if _exemple:
                try:
                    _ok_diag, _lignes = diagnostiquer_nom_fichier(_exemple, cfg)
                    _detail = u"\n".join(_lignes)
                except Exception:
                    _detail = u""
            _msg = (u"Aucun des {} fichier(s) CAO du dossier ne respecte la "
                    u"convention de nommage.\n\n".format(nb_dwg_pdf))
            if _exemple:
                _msg += u"Exemple analysé :\n\n    {}\n\n".format(_exemple)
            if _detail:
                _msg += _detail + u"\n\n"
            _msg += u"Convention attendue :\n    {}".format(
                get_convention_template(cfg, "fichiers", u"(non configurée)"))
            show_alert(u"Aucun fichier conforme à la convention", _msg)

        # 5. Ouvrir la fenetre combinee
        xaml = os.path.join(script_dir, "MainWindow.xaml")
        win  = forms.WPFWindow(xaml)

        # -- Section Dossier --
        win.txtFolder.Text          = folder
        win.chkIncludeSub.IsChecked = False
        win._candidates = candidates  # liste de tuples (fn, lvl_name, full_path, site_code)
        win._rvt_site   = rvt_site    # code site du fichier Revit (pour le filtre)

        def refresh_candidates(sender=None, args=None):
            fld = win.txtFolder.Text
            if not os.path.isdir(fld):
                win._candidates = []
                win.lstViews.ItemsSource = []
                return
            inc_sub = bool(win.chkIncludeSub.IsChecked)
            new_cands, _, _, _, _, _ = scan_candidates(fld, inc_sub)
            win._candidates = new_cands
            _refresh_list()

        _filter_checkboxes = []  # (key_or_None, checkbox_ctrl) — rempli apres creation WPF

        def _refresh_list(sender=None, args=None):
            cands = win._candidates
            if bool(win.chkSiteOnly.IsChecked):
                cands = [c for c in cands if c[3].lower() == win._rvt_site]
            # Filtre types de niveaux
            if _filter_checkboxes:
                _enabled_keys  = set()
                _enable_autres = False
                for _fk, _fcb in _filter_checkboxes:
                    if _fcb.IsChecked:
                        if _fk is None:
                            _enable_autres = True
                        else:
                            _enabled_keys.add(_fk)
                cands = [
                    c for c in cands
                    if (_def_key_for_lvl(c[1]) in _enabled_keys)
                    or (_def_key_for_lvl(c[1]) is None and _enable_autres)
                ]
            names = [c[0] for c in cands]
            ext = win.cmbFileFilter.SelectedItem
            if ext and ext != "Tout":
                if ext == "step":
                    names = [fn for fn in names
                             if any(fn.lower().endswith(e) for e in (".step", ".stp", ".stpz"))]
                else:
                    names = [fn for fn in names if fn.lower().endswith("." + ext.lower())]
            _flt = win.txtListFilter.Text.strip().lower()
            if _flt:
                if u'*' in _flt:
                    names = [fn for fn in names if _fnmatch.fnmatch(fn.lower(), _flt)]
                else:
                    names = [fn for fn in names if _flt in fn.lower()]
            win.lstViews.ItemsSource = names

        def on_browse(sender, args):
            fld = _pick_cao_folder()
            if not fld:
                return
            win.txtFolder.Text = fld
            refresh_candidates()

        win.btnBrowse.Click         += on_browse
        win.txtFolder.TextChanged   += refresh_candidates
        win.chkIncludeSub.Checked   += refresh_candidates
        win.chkIncludeSub.Unchecked += refresh_candidates

        # -- Section Vues : remplissage des combos --
        # Mapping id nommage_vues → ViewFamily Revit.
        # Seules ces familles sont prises en charge par Lier CAO : ce sont
        # celles que create_view_element() sait produire a partir d'un niveau
        # (ViewPlan / ViewDrafting / Legend). Coupe, Elevation et Vue 3D en
        # sont volontairement exclues — leur case "Lier CAO → Vues" est grisee
        # dans 01_Parametres > Disponibilites familles de vues.
        # Certains membres de ViewFamily peuvent etre absents selon la version de Revit
        # → getattr(..., None) pour eviter AttributeError
        _VUE_ID_TO_FAMILY = {
            u'vue-plan':      ViewFamily.FloorPlan,
            u'vue-plaf':      ViewFamily.CeilingPlan,
            u'vue-structure': ViewFamily.StructuralPlan,
            u'vue-dessin':    ViewFamily.Drafting,
            # Plan de surface = AreaPlan, PAS FloorPlan : mappe sur FloorPlan,
            # ViewPlan.Create() produisait des plans d'etage.
            u'vue-surface':   ViewFamily.AreaPlan,
        }
        _vf_legend = getattr(ViewFamily, 'Legend', None)
        if _vf_legend is not None:
            _VUE_ID_TO_FAMILY[u'vue-legende'] = _vf_legend
        # Construire view_options dynamiquement depuis config.json (nommage_vues avec vues_et_dwg=true)
        _nommage_vues_cfg = cfg.get(u'conventions_nommage', {}).get(u'nommage_vues', [])
        view_options = []
        _fams_non_gerees = []
        for _nv in _nommage_vues_cfg:
            if _nv.get(u'vues_et_dwg', False):
                _fam = _VUE_ID_TO_FAMILY.get(_nv.get(u'id', u''))
                if _fam is not None:
                    view_options.append((_nv.get(u'label', u''), _fam,
                                         _nv.get(u'id', u'')))
                else:
                    # Famille cochee dans les parametres mais non prise en charge
                    # ici : on le signale au lieu de l'ignorer silencieusement.
                    _fams_non_gerees.append(_nv.get(u'label', _nv.get(u'id', u'?')))
        if _fams_non_gerees:
            show_alert(
                u"Familles de vues non prises en charge",
                u"Les familles suivantes sont cochées dans la colonne "
                u"« Lier CAO → Vues » des paramètres mais ne sont pas gérées "
                u"par cet outil, elles n'apparaîtront pas dans la liste :\n\n"
                u"  • {}".format(u"\n  • ".join(_fams_non_gerees)))
        # Fallback si aucune entree configuree
        if not view_options:
            view_options = [
                (u"Plan d'etage",           ViewFamily.FloorPlan,      u'vue-plan'),
                (u"Plans de faux-plafonds", ViewFamily.CeilingPlan,    u'vue-plaf'),
                (u"Plan de structure",      ViewFamily.StructuralPlan, u'vue-structure'),
                (u"Vue de dessin",          ViewFamily.Drafting,       u'vue-dessin'),
            ]
        view_labels   = [lbl for lbl, _, __ in view_options]
        view_families = {lbl: enum for lbl, enum, _ in view_options}
        view_vue_ids  = {lbl: vid for lbl, _, vid in view_options}

        # Les menus sont remplis par la cascade, plus bas. Seule la liste brute
        # des phases est preparee ici.
        _phase_labels = [_phase_name(ph) for ph in phases_projet]

        # Type de vue personnalisé : trié par 'ordre'.
        # Lignes systeme toujours en tete : PIECES 3D=0, TEMPORAIRE=1, FM=2
        # (meme ordre que 01_Parametres), puis tri par 'ordre' de la config.
        # « Ord. » est du TEXTE libre depuis qu'il accepte « A1 » ou « 10bis » :
        # le tri passe par la clé naturelle partagée, sinon « 10 » se rangerait
        # avant « 2 ». Les lignes système restent en tête (préfixe 0).
        # Comparaison en MAJUSCULES : les labels le sont depuis que la fenetre
        # des parametres les normalise, mais une config pas encore
        # re-enregistree porte encore « Temporaire ». Sans cela cette ligne
        # perdrait sa place en tete de liste.
        _TVP_LOCKED_ORD_DWG = {u'PIECES 3D': 0, u'TEMPORAIRE': 1, u'FM': 2}
        def _tvp_ord_key(t):
            _lbl = (t.get(u'label', u'') or u'').upper()
            if _lbl in _TVP_LOCKED_ORD_DWG:
                return (0, _cle_ordre(_TVP_LOCKED_ORD_DWG[_lbl]))
            return (1, _cle_ordre(t.get(u'ordre', u'')))
        _tvp_list_sorted = sorted(_tvp_list, key=_tvp_ord_key)
        # Filtrer selon la disponibilite configuree dans Parametres → Vues
        _dispo_tpd = {d.get(u'label', u''): d.get(u'lier_cao', True)
                      for d in cfg.get(u'dispo_types_pers_lier_cao', [])}
        # Disponibilite par SCRIPT (colonne "Lier CAO → Vues"). La
        # disponibilite par FAMILLE de vue est appliquee ensuite, a chaque
        # changement du menu "Famille de vue" (voir _maj_types_pers).
        _tvp_labels = [t.get(u'label', u'') for t in _tvp_list_sorted
                       if _dispo_tpd.get(t.get(u'label', u''), True)]
        _tvp_list = _tvp_list_sorted  # garder la référence triée pour _selected_tvp

        # -- Cascade Discipline -> Sous-discipline -> Famille -> Type -> Phase -
        # Les cinq menus forment une cascade : chacun ne propose que des
        # valeurs qui laissent au moins un choix au suivant. Une famille dont
        # plus aucun type personnalise ne releve pour la discipline courante
        # n'est donc pas affichee, au lieu de mener a un « Type personnalise »
        # vide.
        #
        # Deux tables portent ces disponibilites, cumulatives :
        # cfg['dispo_types_pers_familles'] (colonne "Familles de vues" de
        # 01_Parametres > Vues > Vues personnalisees) et
        # cfg['dispo_types_pers_disciplines'] (colonne "Discipline").
        #
        # Les disciplines proposees sont celles REELLEMENT employees par les
        # vues personnalisees disponibles ici, et NON les ~100 lignes du
        # referentiel de l'onglet « Disciplines » : la quasi-totalite n'y
        # menerait a aucun type, ce qui rendait le menu inutilisable.
        #
        # La PHASE n'a pas de table de disponibilite : rien ne restreint la
        # liste des phases du projet. Elle ferme la cascade — active seulement
        # une fois les menus au-dessus pourvus (voir _maj_phases).
        #
        # Indexe sur les listes de couples, pas sur le libelle affiche : deux
        # branches distinctes du referentiel peuvent partager un libelle.
        _TOUTES_DISC = u"Toutes les disciplines"
        _TOUTES_SOUS = u"Toutes les sous-disciplines"

        _fmt_disc   = _disc_mod.get_format(cfg)
        _codes_util = get_disciplines_utilisees(cfg, _tvp_labels)

        # Une sous-discipline employee implique sa discipline de tete : sans
        # cela « ARCHITECTURE » manquerait alors que « SPACE PLANNING » en
        # releve.
        _par_code = {}
        for _e_d in _disc_mod.get_table(cfg):
            _par_code[_disc_mod.code_ouvrage(_e_d, fmt=_fmt_disc)] = _e_d

        def _racine(code):
            """Code de la ligne de niveau 1 dont releve `code`."""
            _anc = _disc_mod.get_ancetres(code, cfg)
            return (_disc_mod.code_ouvrage(_anc[0], fmt=_fmt_disc)
                    if _anc else code)

        _disc_racines = []
        _vus_rac = set()
        for _c in sorted(_codes_util):
            if _c not in _par_code:
                continue          # code obsolete : referentiel modifie depuis
            _r = _racine(_c)
            if _r in _vus_rac or _r not in _par_code:
                continue
            _vus_rac.add(_r)
            _disc_racines.append(
                (_r, (_par_code[_r].get(u'discipline') or u'').strip() or _r))

        _sous_par_racine = {}
        for _c in sorted(_codes_util):
            _e = _par_code.get(_c)
            if _e is None or _disc_mod.get_niveau(_e, fmt=_fmt_disc) <= 1:
                continue
            _sous_par_racine.setdefault(_racine(_c), []).append(
                (_c, (_e.get(u'sous_discipline') or u'').strip() or _c))

        _disc_options = []      # [(code, libelle)] du menu Discipline
        _sous_options = []      # [(code, libelle)] du menu Sous-discipline

        # Remplir un ItemsSource declenche SelectionChanged : sans ce drapeau,
        # une mise a jour relancerait la cascade depuis son propre milieu, sur
        # des listes d'options a demi remplacees.
        _cascade_en_cours = {u'v': False}

        # L'indisponibilite s'affiche DANS le menu (_AUCUNE_VALEUR), pas dans
        # le libelle : la colonne des labels est en largeur Auto, une phrase y
        # decalerait tous les menus. Le detail passe en infobulle — d'ou le
        # ToolTipService.ShowOnDisabled du XAML, sans quoi elle resterait
        # invisible sur un menu grise.
        _AIDE_INDISPO = (
            u"Aucun type personnalis\xe9 ne correspond \xe0 cette combinaison.\n"
            u"R\xe9glez les colonnes « Familles de vues », « Discipline » et "
            u"« Lier CAO → Vues » (colonne « Disponibilit\xe9 ») dans\n"
            u"01_Param\xe8tres > Vues > Vues personnalis\xe9es.")

        def _code_selectionne(combo_cherchable, options, marqueur):
            """Code associe au libelle retenu dans un menu, ou '' si neutre."""
            _v = combo_cherchable.valeur()
            if _v is None or _v == marqueur:
                return u''
            for _code, _lbl in options:
                if _lbl == _v:
                    return _code
            return u''

        def _codes_actifs():
            """
            Codes de discipline a tester pour le filtrage des types.

            Sous-discipline choisie -> ce seul code. Discipline seule -> la
            tete ET toutes ses sous-disciplines employees : choisir une
            discipline sans preciser doit rendre les types de TOUTE la branche.
            Rien de choisi -> aucun filtre.
            """
            _sc = _code_selectionne(_cmb_sous, _sous_options, _TOUTES_SOUS)
            if _sc:
                return [_sc]
            _dc = _code_selectionne(_cmb_disc, _disc_options, _TOUTES_DISC)
            if not _dc:
                return []
            return [_dc] + [_c for _c, _l in _sous_par_racine.get(_dc, [])]

        def _labels_disponibles():
            """Types personnalises passant les filtres Discipline + Sous."""
            return filtrer_labels_pour_disciplines(
                cfg, _tvp_labels, _codes_actifs())

        def _maj_sous_disciplines():
            _dc = _code_selectionne(_cmb_disc, _disc_options, _TOUTES_DISC)
            _opts = [(u'', _TOUTES_SOUS)]
            if _dc:
                _opts.extend(_sous_par_racine.get(_dc, []))
            else:
                for _r, _lbl_r in _disc_racines:
                    for _c, _lbl_s in _sous_par_racine.get(_r, []):
                        _opts.append((_c, u"{} — {}".format(_lbl_r, _lbl_s)))
            _prec = _code_selectionne(_cmb_sous, _sous_options, _TOUTES_SOUS)
            _sous_options[:] = _opts
            _codes = [_c for _c, _l in _opts]
            _cmb_sous.definir(
                [_l for _c, _l in _opts],
                selection=(_opts[_codes.index(_prec)][1]
                           if _prec in _codes else None))
            _cmb_sous.combo.IsEnabled = len(_opts) > 1
            _cmb_sous.combo.ToolTip = (
                None if len(_opts) > 1 else
                u"Aucune sous-discipline n'est renseign\xe9e pour cette "
                u"discipline dans les vues personnalis\xe9es.")

        def _maj_familles():
            _labels = _labels_disponibles()
            _opts = [_lbl for _lbl in view_labels
                     if filtrer_labels_pour_famille(
                         cfg, _labels, view_vue_ids.get(_lbl, u''))]
            _prec = _cmb_fam.valeur()
            _cmb_fam.definir(_opts if _opts else [],
                             selection=(_prec if _prec in _opts else None))
            _cmb_fam.combo.IsEnabled = bool(_opts)
            _cmb_fam.combo.ToolTip   = None if _opts else _AIDE_INDISPO

        def _maj_types_pers():
            _fam_lbl = _cmb_fam.valeur() or u''
            _dispo = filtrer_labels_pour_famille(
                cfg, _labels_disponibles(), view_vue_ids.get(_fam_lbl, u''))
            _prec = _cmb_type.valeur()
            _cmb_type.definir(_dispo if _dispo else [],
                              selection=(_prec if _prec in _dispo else None))
            _cmb_type.combo.IsEnabled = bool(_dispo)
            _cmb_type.combo.ToolTip   = None if _dispo else _AIDE_INDISPO
            _maj_phases()

        def _maj_phases():
            """
            Dernier maillon : la phase n'est proposee que si les menus
            au-dessus portent chacun une valeur reelle.

            Rien ne restreint la liste des phases elle-meme — c'est celle du
            projet. Ce qui se decide ici, c'est de ne pas faire choisir une
            phase pour une combinaison qui ne creera aucune vue.
            """
            _amont_ok = (_cmb_fam.valeur() is not None
                         and _cmb_type.valeur() is not None)
            _prec = _cmb_phase.valeur()
            if _amont_ok and _phase_labels:
                # Repli sur la derniere phase, comportement par defaut de Revit
                # a la creation d'une vue.
                _cmb_phase.definir(
                    _phase_labels,
                    selection=(_prec if _prec in _phase_labels
                               else _phase_labels[-1]))
                _cmb_phase.combo.IsEnabled = True
                _cmb_phase.combo.ToolTip   = None
            else:
                _cmb_phase.definir([])
                _cmb_phase.combo.IsEnabled = False
                _cmb_phase.combo.ToolTip = (
                    u"Aucune phase dans ce projet." if not _phase_labels else
                    u"Renseignez d'abord la discipline, la famille de vue et "
                    u"le type personnalis\xe9.")

        def _depuis(etage):
            """Rejoue la cascade a partir de l'etage donne."""
            if _cascade_en_cours[u'v']:
                return
            _cascade_en_cours[u'v'] = True
            try:
                if etage <= 2:
                    _maj_sous_disciplines()
                if etage <= 3:
                    _maj_familles()
                if etage <= 4:
                    _maj_types_pers()
                else:
                    _maj_phases()
            finally:
                _cascade_en_cours[u'v'] = False

        _cmb_disc  = ComboCherchable(win.cmbDiscipline,
                                     on_change=lambda: _depuis(2),
                                     marqueur_vide=_AUCUNE_VALEUR)
        _cmb_sous  = ComboCherchable(win.cmbSousDiscipline,
                                     on_change=lambda: _depuis(3),
                                     marqueur_vide=_AUCUNE_VALEUR)
        _cmb_fam   = ComboCherchable(win.cmbViewFamily,
                                     on_change=lambda: _depuis(4),
                                     marqueur_vide=_AUCUNE_VALEUR)
        _cmb_type  = ComboCherchable(win.cmbVueTypePers,
                                     on_change=lambda: _depuis(5),
                                     marqueur_vide=_AUCUNE_VALEUR)
        _cmb_phase = ComboCherchable(win.cmbPhase,
                                     marqueur_vide=_AUCUNE_VALEUR)

        _disc_options[:] = [(u'', _TOUTES_DISC)] + _disc_racines
        _cmb_disc.definir([_l for _c, _l in _disc_options])
        _cascade_en_cours[u'v'] = True
        try:
            _maj_sous_disciplines()
            _maj_familles()
            _maj_types_pers()
        finally:
            _cascade_en_cours[u'v'] = False

        win.cmbFileFilter.ItemsSource   = ["dwg", "dxf", "axm", "sat", "dgn",
                                           "obj", "3dm", "skp", "stl", "step", "Tout"]
        win.cmbFileFilter.SelectedIndex = 0
        win.cmbFileFilter.SelectionChanged  += _refresh_list
        win.txtListFilter.TextChanged        += _refresh_list

        # Checkbox filtre site
        win.chkSiteOnly.IsChecked = bool(rvt_site)  # coche par defaut si site detecte
        win.chkSiteOnly.Checked   += _refresh_list
        win.chkSiteOnly.Unchecked += _refresh_list

        # Creer les checkboxes de filtre type de niveaux dynamiquement
        for _fkey, _flabel, _fdefault in _filtre_items:
            _fcb = _WPFCheckBox()
            _fcb.Content   = _flabel
            _fcb.IsChecked = _fdefault
            _fcb.Margin    = _Thickness(0, 0, 12, 2)
            _fcb.VerticalContentAlignment = _VerticalAlignment.Center
            win.pnlFiltresTypes.Children.Add(_fcb)
            _filter_checkboxes.append((_fkey, _fcb))
            _fcb.Checked   += _refresh_list
            _fcb.Unchecked += _refresh_list

        # Types de niveaux par defaut, propres au type personnalise : le
        # reglage n'est plus global, chaque vue personnalisee porte les siens
        # (01_Parametres > Vues > Vues personnalisees, colonne "Types de
        # niveaux par défaut"). On reapplique les cases a chaque changement de
        # type — etat initial, l'utilisateur reste libre de les modifier.
        _niv_defaut_pers = {}
        for _nd in cfg.get(u'niveaux_defaut_types_pers', []) or []:
            _lbl_nd = _nd.get(u'label', u'')
            if _lbl_nd:
                _niv_defaut_pers[_lbl_nd] = _nd.get(u'niveaux', {}) or {}

        def _maj_filtres_niveaux(sender=None, args=None):
            # Les menus etant editables, la valeur se lit sur l'enveloppe
            # et non sur SelectedItem : ce dernier suit la liste filtree
            # par la frappe, pas la valeur reellement retenue.
            _lbl_tvp = _cmb_type.valeur()
            if _lbl_tvp is None:
                return
            # Repli sur l'ancien reglage global tant que ce type n'a pas ete
            # configure : comportement identique a celui d'avant.
            _defauts = _niv_defaut_pers.get(_lbl_tvp)
            if _defauts is None:
                _defauts = _vm_defaults
            for _key_f, _cb_f in _filter_checkboxes:
                _cle_f = _key_f if _key_f is not None else u'autres'
                _cb_f.IsChecked = bool(
                    _defauts.get(_cle_f, _cle_f == u'batiment'))

        win.cmbVueTypePers.SelectionChanged += _maj_filtres_niveaux
        _maj_filtres_niveaux()

        _refresh_list()

        win.btnSelectAll.Click += lambda s, e: [
            win.lstViews.SelectedItems.Add(item)
            for item in win.lstViews.Items
            if not win.lstViews.SelectedItems.Contains(item)
        ]
        win.btnDeselectAll.Click += lambda s, e: win.lstViews.SelectedItems.Clear()

        def invert_selection():
            new_sel = [
                item for item in win.lstViews.Items
                if not win.lstViews.SelectedItems.Contains(item)
            ]
            win.lstViews.SelectedItems.Clear()
            for item in new_sel:
                win.lstViews.SelectedItems.Add(item)

        win.btnInvert.Click += lambda s, e: invert_selection()

        def _lst_views_preview_click(sender, e):
            # Clic sur la case a cocher elle-meme : comportement standard inchange.
            d = e.OriginalSource
            while d is not None and not isinstance(d, _ListBoxItem):
                if isinstance(d, _WPFCheckBox):
                    return
                d = _VisualTreeHelper.GetParent(d)
            if d is None:
                return
            # Maj+clic (plage) et Ctrl+clic (ajout/retrait) : comportement standard
            # du ListBox inchange.
            mods = _Keyboard.Modifiers
            if (mods & _ModifierKeys.Shift) == _ModifierKeys.Shift or \
               (mods & _ModifierKeys.Control) == _ModifierKeys.Control:
                return
            # Clic simple ailleurs sur la ligne (nom du fichier, etc.) : basculer
            # la selection de cette seule ligne, sans deselectionner les autres
            # (meme comportement que la case a cocher).
            d.IsSelected = not d.IsSelected
            e.Handled = True

        win.lstViews.PreviewMouseLeftButtonDown += _lst_views_preview_click

        # -- Section DWG : defaults depuis config --
        default_color = cfg_dwg.get("color_mode_default", "")
        for i in range(win.cmbColorMode.Items.Count):
            txt = getattr(win.cmbColorMode.Items[i], "Content",
                          win.cmbColorMode.Items[i]).ToString().lower()
            if default_color.lower() in txt:
                win.cmbColorMode.SelectedIndex = i
                break
        else:
            win.cmbColorMode.SelectedIndex = 0

        default_layer = cfg_dwg.get("layers_default", "")
        for i in range(win.cmbLayers.Items.Count):
            txt = getattr(win.cmbLayers.Items[i], "Content",
                          win.cmbLayers.Items[i]).ToString()
            if txt == default_layer:
                win.cmbLayers.SelectedIndex = i
                break
        else:
            win.cmbLayers.SelectedIndex = 0

        # Unites : gestion via ImportUnit si disponible
        unit_labels = [u"Metres", u"Centimetres", u"Millimetres", u"Automatique"]
        unit_enums  = None
        if ImportUnit:
            unit_enums = [
                ImportUnit.Meter,
                ImportUnit.Centimeter,
                ImportUnit.Millimeter,
                ImportUnit.Default,
            ]
        default_unit = cfg_dwg.get("unit_default", "")
        sel_unit = 0
        for i, lbl in enumerate(unit_labels):
            if lbl == default_unit:
                sel_unit = i
                break
        win.cmbUnits.SelectedIndex = sel_unit

        default_place = cfg_dwg.get("placement_default", "")
        place_items   = [
            u"Automatique - Emplacement partage",
            u"Automatique - Centre a centre",
            u"Automatique - Origine vers origine interne",
        ]
        sel_place = 0
        for i, lbl in enumerate(place_items):
            if default_place.lower() in lbl.lower():
                sel_place = i
                break
        win.cmbPlacement.SelectedIndex = sel_place

        win.chkCorrectLines.IsChecked = bool(cfg_dwg.get("correct_lines", True))
        win.chkViewOnly.IsChecked     = bool(cfg_dwg.get("view_only", True))

        # -- Profils --
        _profils_cfg = cfg.get(u'profils_liaison_cao', [])
        _LOCKED_PROFIL = u'< Par d\xe9faut >'
        # Trier par 'ordre' : < Par défaut > toujours en tête (fallback ordre=1)
        def _profil_ord_key(p):
            if p.get(u'label') == _LOCKED_PROFIL:
                return 1
            return p.get(u'ordre', 999)
        _profils_cfg_sorted = sorted(_profils_cfg, key=_profil_ord_key)
        _profils_by_label = {}
        for _p in _profils_cfg_sorted:
            _profils_by_label[_p.get(u'label', u'')] = _p
        _profil_labels = [_LOCKED_PROFIL] if _LOCKED_PROFIL in _profils_by_label else []
        _profil_labels += [_p.get(u'label', u'') for _p in _profils_cfg_sorted
                           if _p.get(u'label', u'') != _LOCKED_PROFIL]
        win.cmbProfil.ItemsSource   = _profil_labels
        win.cmbProfil.SelectedIndex = 0

        _color_map   = {u'Conserver': 0, u'Inverser': 1, u'Noir et blanc': 2}
        _layer_map   = {u'Tous': 0, u'Visibles': 1}
        _unit_map    = {u'Metres': 0, u'Centimetres': 1, u'Millimetres': 2, u'Automatique': 3}
        _place_items = [
            u'Automatique - Emplacement partage',
            u'Automatique - Centre a centre',
            u'Automatique - Origine vers origine interne',
        ]
        _fam_map = {lbl: i for i, (lbl, _, __) in enumerate(view_options)}

        # Normalisation sans accents pour le lookup des familles de vues
        # Le suffixe entre parentheses (ex: "(Structure)") est ignore pour la retrocompat
        import unicodedata as _ud
        def _norm_fam(s):
            _s = re.sub(u'\\s*\\([^)]*\\)', u'', s)
            return u''.join(
                c for c in _ud.normalize(u'NFD', _s.lower())
                if _ud.category(c) != u'Mn'
            )
        _fam_map_norm = {_norm_fam(lbl): i for lbl, i in _fam_map.items()}

        def _apply_profil(lbl):
            _p = _profils_by_label.get(lbl, {})
            _opts = _p.get(u'options_liaisons', {})
            _vues = _p.get(u'vues', {})
            _ci = _color_map.get(_opts.get(u'color_mode', u''), -1)
            if _ci >= 0: win.cmbColorMode.SelectedIndex = _ci
            _li = _layer_map.get(_opts.get(u'layers', u''), -1)
            if _li >= 0: win.cmbLayers.SelectedIndex = _li
            _ui = _unit_map.get(_opts.get(u'units', u''), -1)
            if _ui >= 0: win.cmbUnits.SelectedIndex = _ui
            _place = _opts.get(u'placement', u'')
            for _pi, _pv in enumerate(_place_items):
                if _place.lower() in _pv.lower():
                    win.cmbPlacement.SelectedIndex = _pi
                    break
            if u'correct_lines' in _opts:
                win.chkCorrectLines.IsChecked = bool(_opts[u'correct_lines'])
            if u'view_only' in _opts:
                win.chkViewOnly.IsChecked = bool(_opts[u'view_only'])
            # Le rappel suit l'ORDRE DE LA CASCADE — discipline, puis famille,
            # puis type, puis phase. Chaque affectation reconstruit les menus
            # suivants : dans le desordre, on ecrirait dans des listes que
            # l'etape d'apres remplacerait aussitot.
            #
            # La sous-discipline n'est pas enregistree dans les profils : elle
            # reste sur « Toutes les sous-disciplines », ce qui laisse la
            # branche entiere disponible et n'exclut aucun type du profil.

            # Discipline : la cle stockee est le CODE OUVRAGE, pas le libelle,
            # qui peut etre renomme dans le referentiel sans casser les profils.
            # Un profil enregistre avant l'ajout de ce reglage n'en a pas : le
            # menu garde alors « Toutes les disciplines ».
            _dc = _vues.get(u'discipline', u'')
            if _dc:
                for _c_o, _l_o in _disc_options:
                    if _c_o == _dc:
                        _cmb_disc.selectionner(_l_o)
                        break

            # Familles REELLEMENT proposees apres filtrage par la discipline :
            # se fier a la liste complete donnerait une valeur absente du menu.
            _fam = _vues.get(u'famille', u'')
            for _lbl_o in (_cmb_fam.items() or []):
                if _lbl_o == _fam or _norm_fam(_lbl_o) == _norm_fam(_fam):
                    _cmb_fam.selectionner(_lbl_o)
                    break

            _tp = _vues.get(u'type_personnalise', u'')
            _cmb_type.selectionner(_tp)

            # Phase : stockee par NOM. Un projet qui ne connait pas ce nom
            # garde le repli de _maj_phases (derniere phase du projet).
            _cmb_phase.selectionner(_vues.get(u'phase', u''))

            if u'vue_par_niveau' in _vues:
                win.chkVueNiveau.IsChecked = bool(_vues[u'vue_par_niveau'])

        # Appliquer le profil par défaut à l'ouverture
        _apply_profil(_LOCKED_PROFIL)

        def _on_profil_changed(sender, e):
            try:
                if e.AddedItems is not None and e.AddedItems.Count > 0:
                    _apply_profil(str(e.AddedItems[0]))
            except Exception:
                _lbl = win.cmbProfil.SelectedItem
                if _lbl is not None:
                    _apply_profil(str(_lbl))

        win.cmbProfil.SelectionChanged += _on_profil_changed

        def _on_lier_cao_click(s, e):
            # Validation AVANT fermeture : ne pas affecter DialogResult laisse
            # le dialogue ouvert, donc tous les reglages deja saisis intacts.
            # (WPF interdit de rappeler ShowDialog() sur une fenetre fermee,
            # il n'est donc pas possible de "revenir" apres coup.)
            if win.lstViews.SelectedItems.Count == 0:
                show_alert(
                    u"Aucune selection",
                    u"Aucun fichier CAO n'est coché.\n\n"
                    u"Sélectionnez au moins un fichier à lier, puis relancez "
                    u"« Lier CAO ».",
                    close_label=u"Retour")
                return
            # Sans type personnalisé disponible pour la famille choisie, le
            # nommage des vues créées serait incomplet : on bloque ici plutôt
            # que de produire des vues mal nommées.
            if _cmb_type.valeur() is None:
                show_alert(
                    u"Aucun type personnalisé",
                    u"Aucun type personnalisé n'est disponible pour la famille "
                    u"de vue « {} ».\n\n"
                    u"Cochez cette famille dans 01_Paramètres > Vues > Vues "
                    u"personnalisées, colonne « Familles de vues » (et "
                    u"« Lier CAO → Vues » dans la colonne « Disponibilité »), "
                    u"ou choisissez une autre famille de "
                    u"vue.".format(_cmb_fam.valeur() or u''),
                    close_label=u"Retour")
                return
            win.DialogResult = True

        win.btnOk.Click     += _on_lier_cao_click
        win.btnCancel.Click += lambda s, e: setattr(win, "DialogResult", False)

        if not win.ShowDialog():
            return

        # 6. Lecture des choix
        selected_files = [item for item in win.lstViews.SelectedItems]
        chosen_lbl     = _cmb_fam.valeur()
        fam_enum       = view_families[chosen_lbl]
        # Phase de projet choisie pour les vues creees. None quand le menu est
        # grise (voir _maj_phases) : _apply_view_phase(None) ne fait rien et le
        # template resout un segment vide.
        _phase_map        = {_phase_name(ph): ph for ph in phases_projet}
        _chosen_phase_lbl = _cmb_phase.valeur()
        _selected_phase   = _phase_map.get(_chosen_phase_lbl)
        # Retrouver le vue_id de l'entree nommage_vues selectionnee (ex. 'vue-surface')
        _chosen_vue_id = None
        for _nv in _nommage_vues_cfg:
            if _nv.get(u'label', u'') == chosen_lbl:
                _chosen_vue_id = _nv.get(u'id')
                break
        # Garde-fou : un jeton inconnu dans le template de nommage serait
        # recopie tel quel dans le nom des vues creees.
        _tpl_ok, _tpl_msg = verifier_template(cfg, _chosen_vue_id)
        if not _tpl_ok:
            show_alert(u"Convention de nommage invalide", _tpl_msg)
            return

        # -- Positionnement incompatible avec la famille de vue --------------
        # Une vue de dessin ou une legende n'a pas de systeme de coordonnees
        # partage : "Automatique - Emplacement partage" n'y est pas applicable.
        # On avertit ici (au clic sur "Lier CAO") sans avoir contraint le
        # dialogue principal, et on laisse choisir le positionnement de
        # remplacement.
        _VUE_IDS_SANS_PARTAGE = (u'vue-dessin', u'vue-legende')
        _PLACE_IDX_PARTAGE = 0   # index dans _place_items / cmbPlacement
        _PLACE_IDX_CENTRE  = 1
        _PLACE_IDX_ORIGINE = 2
        if (_chosen_vue_id in _VUE_IDS_SANS_PARTAGE
                and win.cmbPlacement.SelectedIndex == _PLACE_IDX_PARTAGE):
            # Choix proposes, dans l'ordre : l'origine interne est la valeur
            # par defaut (premier element, presélectionné).
            _choix_idx = [_PLACE_IDX_ORIGINE, _PLACE_IDX_CENTRE]
            _warn_xaml = os.path.join(os.path.dirname(__file__),
                                      'PlacementWarningDialog.xaml')
            _warn = forms.WPFWindow(_warn_xaml)
            _warn.Title = u"Positionnement incompatible"
            _warn.txtMessage.Text = (
                u"La famille de vue « {} » ne prend pas en charge le "
                u"positionnement « {} » : une vue de dessin ou une légende "
                u"n'a pas de système de coordonnées partagé.\n\n"
                u"Choisissez le positionnement à appliquer à la place, puis "
                u"cliquez sur « Appliquer » pour lancer la liaison CAO.".format(
                    chosen_lbl, _place_items[_PLACE_IDX_PARTAGE]))
            _warn.cmbNouveauPlacement.ItemsSource   = [_place_items[_i]
                                                       for _i in _choix_idx]
            _warn.cmbNouveauPlacement.SelectedIndex = 0
            _warn.btnAppliquer.Click += (
                lambda s, e: setattr(_warn, 'DialogResult', True))
            _warn.btnAnnuler.Click += (
                lambda s, e: setattr(_warn, 'DialogResult', False))

            if not _warn.ShowDialog():
                # "Annuler" : sortie du script, aucune liaison effectuee.
                log(u"Operation annulee : positionnement « {} » incompatible "
                    u"avec la famille « {} ».".format(
                        _place_items[_PLACE_IDX_PARTAGE], chosen_lbl))
                return

            _sel = _warn.cmbNouveauPlacement.SelectedIndex
            _nouveau_idx = _choix_idx[_sel if _sel >= 0 else 0]
            win.cmbPlacement.SelectedIndex = _nouveau_idx
            log(u"Positionnement « {} » incompatible avec la famille « {} » : "
                u"« {} » applique a la place.".format(
                    _place_items[_PLACE_IDX_PARTAGE], chosen_lbl,
                    _place_items[_nouveau_idx]))

        do_link_dwg    = True
        do_vue_niveau  = bool(win.chkVueNiveau.IsChecked)
        # Type de vue personnalisé sélectionné
        _tvp_label_sel  = _cmb_type.valeur() or u''
        _selected_tvp   = get_row_by_label(cfg, _tvp_label_sel) or (_tvp_list[0] if _tvp_list else {})
        _vue_suffix = _selected_tvp.get(u'titre', _selected_tvp.get(u'nom', u'FM'))
        # Reconstruire candidates depuis win._candidates (dossier/sous-dossiers eventuels)
        candidates     = win._candidates  # [(fn, lvl_name, full_path, site_code)]

        # Filet de securite : le cas est normalement intercepte dans
        # _on_lier_cao_click, qui laisse le dialogue ouvert. Ici le dialogue est
        # deja ferme, on ne peut que sortir.
        if not selected_files:
            show_alert(u"Aucune selection", u"Aucun fichier selectionne. Operation annulee.")
            return

        # Gabarit configure mais absent du projet : proposer une substitution.
        # Fait AVANT toute Transaction / TransactionGroup — une fenetre modale
        # ouverte pendant une transaction Revit laisserait le modele verrouille
        # tout le temps de la reflexion de l'utilisateur.
        # Un nom de gabarit errone est sinon sans effet visible : les vues se
        # creent, sans gabarit, et rien ne le signale.
        _gabarit_configure = _vues_creation_mod.get_gabarit_name(
            cfg, _selected_tvp, fam_enum, vue_id=_chosen_vue_id)
        _gabarit_final     = _gabarit_configure
        _gabarit_substitue = False
        if _gabarit_configure:
            _tpls_projet = _vues_creation_mod.get_view_templates(doc)
            _noms_tpl = [_vues_creation_mod.element_name(_t) for _t in _tpls_projet]
            if _gabarit_configure not in _noms_tpl:
                if not _tpls_projet:
                    show_alert(
                        u"Gabarit de vue introuvable",
                        u"Le gabarit « {} » configuré pour « {} » n'existe pas "
                        u"dans ce projet, qui ne contient d'ailleurs aucun "
                        u"gabarit de vue.\n\n"
                        u"Les vues seront créées sans gabarit.".format(
                            _gabarit_configure, _tvp_label_sel))
                    _gabarit_final = u''
                else:
                    # Filtre de compatibilite sur le NOM D'ENUMERATION ; la
                    # traduction francaise n'intervient qu'a l'affichage.
                    _vt_attendu = _vues_creation_mod.VUE_ID_TO_VIEWTYPE.get(
                        _chosen_vue_id)
                    _fr = lambda _lst: [
                        (_vues_creation_mod.element_name(_t),
                         _vues_creation_mod.libelle_view_type(
                             cfg, _t.ViewType.ToString()))
                        for _t in _lst]
                    _compat = ([_t for _t in _tpls_projet
                                if _t.ViewType.ToString() == _vt_attendu]
                               if _vt_attendu else None)
                    _choix_tpl = choisir_dans_liste(
                        titre=u"Gabarit de vue introuvable — Lier CAO",
                        description=(
                            u"Sélectionnez le gabarit à appliquer aux vues "
                            u"« {} » créées, ou annulez pour les créer sans "
                            u"gabarit.".format(chosen_lbl)),
                        note=(u"Le gabarit « {} » configuré dans 01_Paramètres "
                              u"> Vues > Vues personnalisées > Gabarits de "
                              u"vues (ligne « {} », type « {} ») n'existe pas "
                              u"dans ce projet.".format(
                                  _gabarit_configure, chosen_lbl,
                                  _tvp_label_sel)),
                        entete_nom=u"Gabarit de vue",
                        entete_info=u"Type de vue",
                        items_tous=_fr(_tpls_projet),
                        items_compat=(_fr(_compat) if _compat is not None
                                      else None),
                        libelle_compat=(
                            u"Uniquement les gabarits compatibles avec "
                            u"« {} »".format(chosen_lbl)),
                        valeur_courante=u'')
                    # Substitution valable pour CETTE execution seulement : la
                    # configuration n'est pas reecrite ici (seul 01_Parametres
                    # ecrit config.json).
                    _gabarit_final     = _choix_tpl or u''
                    _gabarit_substitue = bool(_choix_tpl)

        log(u"---")
        log(u"Fichiers selectionnes : {}".format(len(selected_files)))
        log(u"Famille de vue : `{}`".format(chosen_lbl))
        log(u"Phase : `{}`".format(_chosen_phase_lbl or u"aucune"))
        log(u"Type personnalise : `{}`  (label `{}`)".format(
            _vue_suffix, _tvp_label_sel))
        log(u"Mode : {}".format(
            u"une vue par niveau" if do_vue_niveau else u"une vue par fichier lie"))
        _profil_choisi = win.cmbProfil.SelectedItem
        if _profil_choisi:
            log(u"Profil : `{}`".format(_profil_choisi))

        # 7. Creer les vues manquantes (uniquement si liaison DWG non demandee).
        # Quand do_link_dwg=True, la creation de vue est faite par fichier de facon
        # atomique avec la liaison (TransactionGroup) dans le bloc 9 ci-dessous.
        created_views = []
        # Drapeau remonte depuis la fenetre de progression (bloc 9) : permet a
        # la fenetre de resultat (bloc 10) de distinguer une operation terminee
        # d'une operation interrompue par l'utilisateur.
        _was_cancelled = False
        if not do_link_dwg:
            # Cas Legende : l'API Revit ne permet pas de creer une legende depuis zero.
            if _vf_legend is not None and fam_enum == _vf_legend:
                _has_legend = any(
                    True for _v in FilteredElementCollector(doc).OfClass(View)
                    if not _v.IsTemplate and _v.ViewType.ToString() == u'Legend'
                )
                if not _has_legend:
                    show_alert(
                        u"Vue Legende impossible",
                        u"L'API Revit ne permet pas de creer une vue Legende depuis zero.\n\n"
                        u"Creez manuellement au moins une vue Legende dans le projet "
                        u"(onglet Vue > Creer > Legende), puis relancez l'operation."
                    )
                    return
            _vue_warnings = []
            created_views = create_views_from_candidates(
                doc, candidates, selected_files, levels,
                fam_enum, _selected_tvp, cfg,
                do_vue_niveau=do_vue_niveau,
                vue_id=_chosen_vue_id,
                warnings=_vue_warnings,
                # Gabarit deja resolu plus haut, substitution comprise : sans
                # cela la resolution interne reimposerait le nom erroné.
                gabarit_name=_gabarit_final,
            )
            log(u"Vues creees : {}".format(len(created_views)))
            for _w in _vue_warnings:
                log(_w)

        # Mode "une vue par fichier" : renommer les vues créées avec le préfixe {vue-pers-titre}
        # (uniquement quand la creation se fait sans liaison DWG)
        if not do_link_dwg and not do_vue_niveau and _vue_suffix and created_views:
            _created_set = set(created_views)
            _rename_map = {}  # ancien nom → nouveau nom
            t_rename = Transaction(doc, u"Renommer vues (prefixe vue perso)")
            t_rename.Start()
            for _v in FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType():
                if not _v.IsTemplate and _v.Name in _created_set:
                    _new_name = u'{} - {}'.format(_vue_suffix, _v.Name)
                    try:
                        _v.Name = _new_name
                        _rename_map[_v.Name] = _v.Name  # juste pour log
                    except Exception:
                        pass
            t_rename.Commit()
            log(u"Vues renommees avec prefixe '{}' : {}".format(_vue_suffix, len(_rename_map)))

        # 9. Lier les DWG si demande
        linked_dwgs        = []
        failed_create_link = []
        _view_files_order  = []
        _view_files_map    = {}

        def _log_view_file(view_name, fname):
            if view_name not in _view_files_map:
                _view_files_map[view_name] = []
                _view_files_order.append(view_name)
            _view_files_map[view_name].append(fname)
        if do_link_dwg:
            # Construire les options DWG
            opts = DWGImportOptions()

            layer_idx = win.cmbLayers.SelectedIndex
            opts.VisibleLayersOnly = (layer_idx != 0)

            if ImportColorMode:
                sel_text = win.cmbColorMode.SelectedItem.Content.lower()
                if u"conserver" in sel_text:
                    opts.ColorMode = ImportColorMode.Preserved
                elif u"inverser" in sel_text:
                    opts.ColorMode = ImportColorMode.Inverted
                elif u"noir" in sel_text:
                    opts.ColorMode = ImportColorMode.BlackAndWhite
                else:
                    opts.ColorMode = ImportColorMode.Preserved

            if ImportUnit and unit_enums:
                idx_u = win.cmbUnits.SelectedIndex
                if 0 <= idx_u < len(unit_enums):
                    opts.Unit = unit_enums[idx_u]

            shared_name = get_enum_name(ImportPlacement, lambda x: "shared" in x)
            center_name = get_enum_name(ImportPlacement, lambda x: "center" in x)
            origin_name = get_enum_name(ImportPlacement, lambda x: "origin" in x)
            place_idx = win.cmbPlacement.SelectedIndex
            choice = (
                shared_name if place_idx == 0
                else center_name if place_idx == 1
                else origin_name
            )
            opts.Placement = getattr(ImportPlacement, choice)

            if hasattr(opts, "CorrectLines"):
                opts.CorrectLines = bool(win.chkCorrectLines.IsChecked)
            opts.ThisViewOnly = bool(win.chkViewOnly.IsChecked)

            # Collecter les vues cibles (nom de fichier → vue)
            # Construire la liste des ViewType attendus depuis view_options actives
            _active_vt = set()
            _VF_TO_VT = {
                ViewFamily.FloorPlan:      u"FloorPlan",
                ViewFamily.AreaPlan:       u"AreaPlan",
                ViewFamily.CeilingPlan:    u"CeilingPlan",
                ViewFamily.StructuralPlan: u"StructuralPlan",
                ViewFamily.Drafting:       u"DraftingView",
                ViewFamily.Section:        u"Section",
                ViewFamily.Elevation:      u"Elevation",
            }
            if _vf_legend is not None:
                _VF_TO_VT[_vf_legend] = u"Legend"
            # Section / Elevation restent listees ci-dessus par securite, mais
            # view_options ne peut plus les contenir (voir _VUE_ID_TO_FAMILY).
            for _, _vf, __ in view_options:
                _vt = _VF_TO_VT.get(_vf)
                if _vt:
                    _active_vt.add(_vt)
            if not _active_vt:
                _active_vt = {u"FloorPlan", u"CeilingPlan", u"StructuralPlan", u"DraftingView"}
            # views_map : uniquement les vues de la famille selectionnee,
            # pour eviter de confondre une vue "Plan d'etage" et une vue
            # "Plan de faux plafond" ayant le meme nom.
            _selected_vt = _VF_TO_VT.get(fam_enum)
            views_map = {}
            for v in FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType():
                if not v.IsTemplate and _selected_vt and v.ViewType.ToString() == _selected_vt:
                    views_map[v.Name.strip().lower()] = v

            existing_dwg_info = get_existing_dwg_link_info(doc)

            # Filtrer les fichiers CAO selectionnes et determiner leur statut de liaison
            _cao_exts = (u".dwg", u".dxf", u".axm", u".sat", u".dgn", u".obj", u".3dm",
                         u".skp", u".stl", u".step", u".stp", u".stpz")
            dwg_paths = []
            for name, _key, full_path, _site in candidates:
                if name not in selected_files:
                    continue
                if not any(name.lower().endswith(e) for e in _cao_exts):
                    continue
                _link_status = existing_dwg_info.get(name.lower(), u'new')
                dwg_paths.append((_link_status, full_path, _key))

            if dwg_paths:
                import shutil as _shutil

                old_ids = {
                    inst.Id.IntegerValue
                    for inst in FilteredElementCollector(doc).OfClass(ImportInstance)
                }

                shared_val = getattr(ImportPlacement, shared_name)
                center_val = getattr(ImportPlacement, center_name)

                # Pre-calcul VFT pour la creation eventuelle de vues. Le gabarit
                # retourne ici est ignore : _gabarit_final a deja ete resolu
                # plus haut, substitution comprise.
                _vft_for_creation    = None
                _gabarit_for_creation = _gabarit_final
                try:
                    _vft_for_creation, _ = prepare_view_creation(
                        doc, fam_enum, _selected_tvp, cfg, vue_id=_chosen_vue_id)
                except RuntimeError as _e_vft:
                    log(u"Preparation creation vues impossible : {}".format(_e_vft))

                total  = len(dwg_paths)
                dialog = open_link_dialog(total)

                for idx, (_link_status, p, _lvl_name) in enumerate(dwg_paths, start=1):
                    fname = os.path.basename(p)

                    if getattr(dialog, "_cancelled", False):
                        break

                    # Resoudre le nom de vue et la cle de lookup
                    _lookup_vars = get_template_vars(_selected_tvp)
                    _lookup_vars[u'phase'] = _chosen_phase_lbl or u''
                    if do_vue_niveau:
                        _lookup_vars[u'niveau'] = _lvl_name
                        _vue_name_new = resolve_view_name(
                            fam_enum, _lookup_vars, cfg, vue_id=_chosen_vue_id).strip()
                        _vue_key = _vue_name_new.lower()
                    else:
                        _vue_name_new = fname
                        _vue_key = (u'{} - {}'.format(_vue_suffix, fname).lower()
                                    if _vue_suffix else fname.lower())

                    view = views_map.get(_vue_key)
                    _view_is_new = (view is None)

                    if _view_is_new and _vft_for_creation is None:
                        log(u"Vue introuvable et creation impossible pour `{}`, DWG non lie.".format(fname))
                        failed_create_link.append(fname)
                        continue

                    update_link_dialog(dialog, fname, idx, total)
                    if getattr(dialog, "_cancelled", False):
                        break

                    # --- Creer la vue si elle n'existe pas encore ---
                    _view_id_created = None
                    if _view_is_new:
                        _t_view = Transaction(doc, u"Creer vue")
                        _t_view.Start()
                        view = create_view_element(
                            doc, _vue_name_new, _lvl_name, fam_enum,
                            _vft_for_creation, levels, _gabarit_for_creation,
                            phase=_selected_phase)
                        if view is None:
                            _t_view.Rollback()
                            log(u"Impossible de creer la vue pour `{}`, DWG non lie.".format(fname))
                            failed_create_link.append(fname)
                            continue
                        _view_id_created = view.Id
                        _t_view.Commit()
                        views_map[view.Name.strip().lower()] = view

                    # --- Lien global : vue creee/existante, pas de nouvelle instance ---
                    if _link_status == u'global':
                        if _view_id_created is not None:
                            created_views.append(view.Name)
                            if not do_vue_niveau and _vue_suffix:
                                _t_rn = Transaction(doc, u"Renommer vue")
                                _t_rn.Start()
                                try:
                                    view.Name = u'{} - {}'.format(_vue_suffix, fname)
                                except Exception:
                                    pass
                                _t_rn.Commit()
                                if created_views:
                                    created_views[-1] = view.Name
                                views_map[view.Name.strip().lower()] = view
                            log(u"Vue creee pour lien global : `{}` → vue `{}`".format(
                                fname, view.Name))
                        else:
                            log(u"Vue deja existante pour lien global : `{}`".format(fname))
                        _log_view_file(view.Name, fname)
                        dialog.progressBar.Value = idx
                        continue

                    # --- Lien 'new' ou 'view_only' : creer une nouvelle instance ---

                    # Snapshot des categories avant liaison
                    old_cat_names = set()
                    try:
                        for _c in doc.Settings.Categories:
                            old_cat_names.add(_c.Name)
                    except Exception:
                        pass

                    # Copie temporaire avec double extension (ex: .dwg.dwg, .dxf.dxf) :
                    # Revit derive le nom de categorie en strippant la derniere extension,
                    # ce qui donne "file.dwg" / "file.dxf" dans Categories importees (VG).
                    # La copie est supprimee apres liaison (Revit a deja charge le contenu).
                    _fext        = os.path.splitext(fname)[1]
                    fname_double = fname + _fext
                    p_double     = os.path.join(os.path.dirname(p), fname_double)
                    use_double   = False
                    try:
                        _shutil.copy2(p, p_double)
                        use_double = True
                    except Exception:
                        pass
                    p_link = p_double if use_double else p

                    def _cleanup_double():
                        if use_double:
                            try: os.remove(p_double)
                            except Exception: pass

                    # Pour un lien 'view_only' sur une vue existante : verifier les
                    # instances deja presentes dans la vue cible et agir selon le mode.
                    if _link_status == u'view_only' and not _view_is_new:
                        _fname_lower = fname.lower()
                        _instances_in_view = []
                        for _inst in FilteredElementCollector(doc).OfClass(ImportInstance):
                            if not _inst.ViewSpecific or _inst.OwnerViewId != view.Id:
                                continue
                            _sym = doc.GetElement(_inst.GetTypeId())
                            if not _sym:
                                continue
                            _sp = (_sym.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
                                   or _sym.LookupParameter(u"Type Name"))
                            if _sp and _sp.AsString().lower() == _fname_lower:
                                _instances_in_view.append(_inst.Id)
                        if _instances_in_view:
                            if not opts.ThisViewOnly:
                                # Remplacer les instances vue-only par un lien global :
                                # supprimer les anciennes, puis lier en mode global.
                                _t_del = Transaction(doc, u"Remplacer instances vue-only")
                                _t_del.Start()
                                for _iid in _instances_in_view:
                                    try:
                                        _inst_del = doc.GetElement(_iid)
                                        if _inst_del and _inst_del.Pinned:
                                            _inst_del.Pinned = False
                                        doc.Delete(_iid)
                                    except Exception:
                                        pass
                                _t_del.Commit()
                                log(u"Instances vue-only supprimees, remplacement global : `{}`".format(fname))
                                # La liaison globale est creee juste apres (fall-through)
                            else:
                                # Deja present en vue-only dans cette vue, rien a faire.
                                _cleanup_double()
                                log(u"Instance deja presente dans la vue, ignore : `{}`".format(fname))
                                _log_view_file(view.Name, fname)
                                continue

                    _t_cur = Transaction(doc, u"Lier DWG")
                    _t_cur.Start()

                    ok = doc.Link(p_link, opts, view)
                    if not ok and opts.Placement == shared_val:
                        opts.Placement = center_val
                        ok = doc.Link(p_link, opts, view)

                    if not ok:
                        _t_cur.Rollback()
                        if _view_id_created is not None:
                            # Supprimer la vue creee puisque la liaison a echoue
                            _t_del = Transaction(doc, u"Supprimer vue sans lien")
                            _t_del.Start()
                            try:
                                doc.Delete(_view_id_created)
                            except Exception:
                                pass
                            _t_del.Commit()
                            views_map.pop(view.Name.strip().lower(), None)
                            failed_create_link.append(fname)
                        _cleanup_double()
                        log(u"Echec de liaison : `{}`".format(fname))
                        continue

                    new_ids = {
                        inst.Id.IntegerValue
                        for inst in FilteredElementCollector(doc).OfClass(ImportInstance)
                    } - old_ids

                    for nid in new_ids:
                        inst_new = doc.GetElement(ElementId(nid))
                        inst_new.Pinned = True
                        sym = doc.GetElement(inst_new.GetTypeId())
                        if sym:
                            if use_double:
                                try:
                                    sym.LoadFrom(p)
                                except Exception as _ex:
                                    log(u"  Repoint chemin erreur : {}".format(_ex))
                            sym.Name = fname

                    _cleanup_double()
                    _t_cur.Commit()

                    if _view_id_created is not None:
                        created_views.append(view.Name)
                        # Renommage avec prefixe (mode "une vue par fichier")
                        if not do_vue_niveau and _vue_suffix:
                            _t_rn = Transaction(doc, u"Renommer vue")
                            _t_rn.Start()
                            try:
                                view.Name = u'{} - {}'.format(_vue_suffix, fname)
                            except Exception:
                                pass
                            _t_rn.Commit()
                            if created_views:
                                created_views[-1] = view.Name
                            views_map[view.Name.strip().lower()] = view

                    old_ids.update(new_ids)
                    linked_dwgs.append(fname)
                    _log_view_file(view.Name, fname)
                    log(u"Lie : `{}` → vue `{}`".format(fname, view.Name))
                    dialog.progressBar.Value = idx
                    try:
                        dialog.Dispatcher.Invoke(_DP.Background, _Action(lambda: None))
                    except Exception:
                        pass

                # Relever le drapeau AVANT Close() : la fenetre de resultat doit
                # annoncer une interruption et non une operation terminee.
                _was_cancelled = getattr(dialog, "_cancelled", False)
                dialog.Close()
                if _was_cancelled:
                    log(u"Operation interrompue par l'utilisateur.")
                log(u"DWG lies : {}".format(len(linked_dwgs)))
                if failed_create_link:
                    log(u"Non traites (vue non creee / DWG non lie) : {}".format(
                        u', '.join(u'`{}`'.format(f) for f in failed_create_link)))

                if _view_files_order:
                    log(u"### Vues \u2192 fichiers CAO lies")
                    for _vname in _view_files_order:
                        _files = _view_files_map[_vname]
                        log(u"{} : {}".format(
                            _vname, u', '.join(u'`{}`'.format(f) for f in _files)))

        # 10. Fenetre de resultat
        lines = []
        if _was_cancelled:
            lines.append(u"Opération interrompue par l'utilisateur.")
        _nb_v = len(created_views)
        _nb_f = len(linked_dwgs)
        lines.append(u"{} {} {}, {} {} {}.".format(
            _nb_v, u"vue" if _nb_v <= 1 else u"vues",
            u"cr\u00e9\u00e9e" if _nb_v <= 1 else u"cr\u00e9\u00e9es",
            _nb_f, u"fichier" if _nb_f <= 1 else u"fichiers",
            u"li\u00e9" if _nb_f <= 1 else u"li\u00e9s"))
        if failed_create_link:
            lines.append(u"{} fichier(s) non traite(s) : vue non creee, DWG non lie.".format(
                len(failed_create_link)))

        # Substitution de gabarit : sans ce rappel, rien ne distingue une
        # execution normale d'une execution ou le reglage etait erroné.
        if _gabarit_substitue:
            lines.append(
                u"Gabarit « {} » appliqué à la place de « {} », introuvable "
                u"dans ce projet. Remplacement valable pour cette exécution "
                u"seulement — corrigez-le dans 01_Paramètres > Vues > Vues "
                u"personnalisées > Gabarits de vues.".format(
                    _gabarit_final, _gabarit_configure))
        elif _gabarit_configure and not _gabarit_final:
            lines.append(
                u"Gabarit « {} » introuvable dans ce projet et aucun "
                u"remplacement choisi : vues créées sans gabarit.".format(
                    _gabarit_configure))

        # Tableau vues creees / fichiers CAO lies (DataTable -> DataGrid WPF)
        clr.AddReference("System.Data")
        clr.AddReference("PresentationCore")
        from System.Data import DataTable as SysDataTable
        from System.Windows import Clipboard

        dt = SysDataTable()
        dt.Columns.Add("Vue")
        dt.Columns.Add("Fichiers")
        for _vname in _view_files_order:
            r = dt.NewRow()
            r["Vue"]      = _vname
            r["Fichiers"] = u", ".join(_view_files_map[_vname])
            dt.Rows.Add(r)

        res_xaml = os.path.join(script_dir, "ResultWindow.xaml")
        res_win  = forms.WPFWindow(res_xaml)
        # Le XAML porte Title="Termine" : le corriger quand l'utilisateur a
        # interrompu, sinon la fenetre annonce une fin normale a tort.
        if _was_cancelled:
            res_win.Title = u"Interrompu"
        res_win.txtMessage.Text  = u"\n".join(lines)
        res_win.dataGrid.ItemsSource = dt.DefaultView

        def _copy_table(sender, args):
            _tsv = [u"Vue\tFichiers"]
            for _vname in _view_files_order:
                _tsv.append(u"{}\t{}".format(
                    _vname, u", ".join(_view_files_map[_vname])))
            Clipboard.SetText(u"\n".join(_tsv))

        res_win.btnCopy.Click += _copy_table
        res_win.btnClose.Click += lambda s, e: setattr(res_win, "DialogResult", True)
        res_win.ShowDialog()

    except Exception:
        show_alert(u"Erreur Lier CAO \u2192 Vues", traceback.format_exc())


if __name__ == "__main__":
    main()
