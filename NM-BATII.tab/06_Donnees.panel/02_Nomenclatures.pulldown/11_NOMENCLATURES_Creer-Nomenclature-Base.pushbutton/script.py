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


#__title__ = "Créer\nNOMENCLATURES"
#__doc__ = """Créer et configurer des nomenclatures standards.
#Description : Créer et configurer des nomenclatures standards.
#Crée en masse des nomenclatures de base dans toutes les catégories sélectionnées, soit par recopie d’une nomenclature source existante, soit par création de nouvelles nomenclatures dans les catégories dépourvues de nomenclatures afin de servir de base.
#Les champs calculés et les champs combinés ne sont pas gérés et ne sont donc pas transférés de la nomenclature source vers les nomenclatures de destination.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""

import clr
clr.AddReference("WindowsBase")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("System.Xaml")

import System
from System.Windows.Markup import XamlReader
from System.Windows import Thickness
from System.Windows.Threading import DispatcherPriority
from System.IO import File

import os, sys, codecs, traceback, tempfile

from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

# -------------------------
# Chemins / loader standard
# -------------------------
script_dir = os.path.dirname(__file__)
ext_dir = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir, os.pardir))
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# loader styles
try:
    from dialogs.dialogs_styles_loader import load as load_dialog_styles, show_alert
    load_dialog_styles(lib_dir=lib_dir)
except Exception:
    load_dialog_styles = None
    def show_alert(titre, message):
        forms.alert(message, title=titre)

# loader config
try:
    from utils.config_loader import load_config
except Exception:
    def load_config():
        return {}

# Nommage des vues (helper partage avec 03_Vues/01_Vues_+, 04_Lier_importer/
# 01_Lier_CAO et 05_Pieces/Pieces-3D) + table des types de nomenclatures.
#
# Les nomenclatures ne passent PAS par types_vues_personnalises : leur axe de
# declinaison est (categorie x phase x type de nomenclature), pas
# (niveau x type de vue personnalise). Le type de vue Revit a appliquer est
# porte par la table "Types de nomenclatures" de 01_Parametres.
#
# Import defensif : en cas d'echec le script retombe sur l'ancien nommage code
# en dur (voir _NOMMAGE_DISPONIBLE plus bas).
try:
    from utils.vues_creation import resolve_view_name, verifier_template
    _NOMMAGE_DISPONIBLE = True
except Exception:
    _NOMMAGE_DISPONIBLE = False

try:
    from utils.nomenclatures_types import (
        get_types_nomenclatures, get_or_create_schedule_vft, appliquer_type_vue,
    )
    _TYPES_NOM_DISPONIBLE = True
except Exception:
    _TYPES_NOM_DISPONIBLE = False

# -------------------------
# Revit / logs safe
# -------------------------
doc = revit.doc

_cfg = load_config() or {}

# Identifiant de la ligne "Nomenclature" dans conventions_nommage.nommage_vues
VUE_ID_NOMENCLATURE = u'vue-nomenclature'
# 1re entree du combo "Nomenclature modele". Le prefixe "--" sert de marqueur
# a _on_ok() pour distinguer l'absence de source d'un nom de nomenclature.
SOURCE_AUCUNE = u"-- Aucune (créer sans configuration) --"
# Template applique tant que la ligne n'a pas ete enregistree depuis
# 01_Parametres (doit rester identique au defaut de _defaut_nommage_vues).
# {CATEGORIE} : la valeur est fournie brute par Revit (ex. "Portes"), c'est la
# casse ecrite du jeton qui la met en MAJUSCULES.
# Les autres jetons portent ':val' pour rester tels quels ("Existant",
# "2a - Saisie...") — un jeton tout en minuscules forcerait les minuscules.
TEMPLATE_NOMENCLATURE_DEFAUT = (
    u'{CATEGORIE} - {phase:val} - {type-nomenclature:val}')


def _assurer_template_nomenclature(cfg):
    """
    Garantit la presence de l'entree 'vue-nomenclature' dans
    cfg['conventions_nommage']['nommage_vues'] (en memoire uniquement,
    config.json n'est pas modifie).

    Sans cette entree, resolve_view_name() retombe sur son repli generique
    prevu pour les vues ({vue-pers-titre} - {niveau}) : comme {niveau}
    n'existe pas pour une nomenclature, toutes les nomenclatures seraient
    nommees avec le seul titre du type personnalise ("FM", "FM (1)", ...).
    """
    if not isinstance(cfg, dict):
        return
    _cnv = cfg.setdefault(u'conventions_nommage', {})
    if not isinstance(_cnv, dict):
        return
    _rows = _cnv.setdefault(u'nommage_vues', [])
    if not isinstance(_rows, list):
        return
    for _r in _rows:
        if isinstance(_r, dict) and _r.get(u'id') == VUE_ID_NOMENCLATURE:
            # Entree presente mais template vide : meme probleme de repli.
            if not (_r.get(u'template') or u'').strip():
                _r[u'template'] = TEMPLATE_NOMENCLATURE_DEFAUT
            return
    _rows.append({
        u'label':       u'Nomenclature',
        u'id':          VUE_ID_NOMENCLATURE,
        u'template':    TEMPLATE_NOMENCLATURE_DEFAUT,
        u'vues_et_dwg': False,
        u'vues_plus':   False,
        u'pieces_3d':   False,
    })


_assurer_template_nomenclature(_cfg)


def _parse_bool_like(v):
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true","1","yes","y","on"): return True
        if s in ("false","0","no","n","off"): return False
    return None

ACTIVER_LOGS = True
try:
    parsed = _parse_bool_like(_cfg.get("activer_logs_scripts", True))
    if parsed is not None:
        ACTIVER_LOGS = parsed
except:
    ACTIVER_LOGS = True

_output = None
if ACTIVER_LOGS:
    try:
        _output = script.get_output()
    except:
        _output = None

def log(msg):
    if not ACTIVER_LOGS:
        return
    try:
        if _output:
            _output.print_md(msg)
        else:
            print(msg)
    except:
        try:
            print(msg)
        except:
            pass

def save_traceback(tb_text):
    try:
        path = os.path.join(script_dir, "error_traceback.txt")
        with codecs.open(path, "w", "utf-8") as f:
            f.write(tb_text)
        return path
    except:
        try:
            fd, tmp = tempfile.mkstemp(prefix="pyrevit_trace_", suffix=".txt")
            os.close(fd)
            with codecs.open(tmp, "w", "utf-8") as f:
                f.write(tb_text)
            return tmp
        except:
            return None

# -------------------------
# Fonction show_xaml_message
# -------------------------
def show_xaml_message(message, title="Message"):
    xaml_path = os.path.join(script_dir, "ResultWindow.xaml")
    if not os.path.exists(xaml_path):
        show_alert(title, message)
        return

    try:
        xaml_content = File.ReadAllText(xaml_path)
        window = XamlReader.Parse(xaml_content)
        window.Title = title
        txt_msg = window.FindName("txtMessage")
        btn = window.FindName("btnClose")
        if txt_msg is None or btn is None:
            show_alert(title, message)
            return
        txt_msg.Text = message
        btn.Click += lambda s, e: window.Close()
        window.ShowDialog()
    except Exception:
        show_alert(title, message)


# -------------------------
# Fonction show_warning — avertissement en début de script
# -------------------------
def show_warning():
    """
    Affiche la fenêtre d'avertissement listant ce que le script copie
    et ne copie pas. Retourne True si l'utilisateur clique sur Continuer,
    False s'il annule.
    """
    xaml_path = os.path.join(script_dir, "WarningWindow.xaml")
    if not os.path.exists(xaml_path):
        # Fallback : message simple si le XAML est absent
        return forms.alert(
            u"AVERTISSEMENT\n\n"
            u"Ce script ne copie PAS :\n"
            u"  • Les paramètres calculés\n"
            u"  • Les paramètres combinés\n\n"
            u"Ces paramètres devront être recréés manuellement.\n\n"
            u"Continuer ?",
            title=u"Avertissement", yes=True, no=True
        )
    try:
        xaml_content = File.ReadAllText(xaml_path)
        window = XamlReader.Parse(xaml_content)
        confirmed = [False]

        btn_continuer = window.FindName("btnContinuer")
        btn_annuler   = window.FindName("btnAnnuler")

        def on_continuer(s, e):
            confirmed[0] = True
            window.Close()

        def on_annuler(s, e):
            window.Close()

        if btn_continuer: btn_continuer.Click += on_continuer
        if btn_annuler:   btn_annuler.Click   += on_annuler

        window.ShowDialog()
        return confirmed[0]

    except Exception:
        tb = traceback.format_exc()
        log(u"Erreur show_warning : {}".format(tb))
        return True   # En cas d'erreur sur le XAML, on continue quand même

# -------------------------
# Types de nomenclatures
# -------------------------
# Alimente la liste a cocher, depuis la table "Types de nomenclatures" de
# 01_Parametres > onglet "Nomenclatures". Chaque entree est un dict :
#   {'label': ..., 'type_vue': ...}
# 'label' sert de libelle de case a cocher ET de valeur a la variable
# {type-nomenclature} du template de nommage (valeur verbatim).
# 'type_vue' est le nom du ViewFamilyType Revit a appliquer (cree si absent).
# Repli code en dur si le module partage est indisponible.
_STANDARD_TYPES_REPLI = [
    {u'label': u"2a - Saisie des caractéristiques du TYPE",
     u'type_vue': u''},
    {u'label': u"2b - Saisie des caractéristiques d'OCCURRENCES",
     u'type_vue': u''},
    {u'label': u"3a - Présentation des caractéristiques du TYPE",
     u'type_vue': u''},
    {u'label': u"3b - Présentation des caractéristiques d'OCCURRENCES",
     u'type_vue': u''},
    {u'label': u"3c - Présentation des caractéristiques AUTRES",
     u'type_vue': u''},
]


def get_types_a_creer():
    """Liste des types de nomenclatures configures, ou le repli code en dur."""
    if not _TYPES_NOM_DISPONIBLE:
        return [dict(t) for t in _STANDARD_TYPES_REPLI]
    try:
        return get_types_nomenclatures(_cfg)
    except Exception:
        return [dict(t) for t in _STANDARD_TYPES_REPLI]

# -------------------------
# Utilitaires Revit - CREATION
# -------------------------
def get_schedulable_categories():
    cats = doc.Settings.Categories
    result = []
    for c in cats:
        try:
            if c.AllowsBoundParameters and c.CategoryType == CategoryType.Model:
                result.append(c)
        except:
            pass
    result.sort(key=lambda x: x.Name)
    return result

def get_project_phases():
    """
    Retourne les phases du projet dans l'ordre affiche par la boite de
    dialogue Revit "Phase de construction" (Gerer > Phases).

    doc.Phases (Document.Phases) reflete cet ordre y compris apres
    reorganisation manuelle (Inserer avant/apres), contrairement a
    FilteredElementCollector(doc).OfClass(Phase) qui renvoie les phases dans
    leur ordre de creation et dont le tri par SequenceNumber peut ne pas
    correspondre a l'ordre reellement affiche.
    """
    try:
        return list(doc.Phases)
    except Exception:
        phases = list(FilteredElementCollector(doc).OfClass(Phase))
        try:
            phases.sort(key=lambda p: p.SequenceNumber)
        except:
            pass
        return phases

def get_existing_schedules():
    """Retourne toutes les nomenclatures (pas les gabarits)."""
    return [s for s in FilteredElementCollector(doc).OfClass(ViewSchedule) if not s.IsTemplate]

def get_existing_schedule_names():
    return set(vs.Name for vs in get_existing_schedules())

def make_unique_name(base_name, existing_names):
    if base_name not in existing_names:
        existing_names.add(base_name)
        return base_name
    idx = 1
    while True:
        candidate = u"{} ({})".format(base_name, idx)
        if candidate not in existing_names:
            existing_names.add(candidate)
            return candidate
        idx += 1

def _build_schedule_name_legacy(category, phase, std_label):
    """Nommage code en dur, utilise si les helpers partages sont indisponibles."""
    cat_upper = category.Name.upper()
    phase_name = phase.Name if phase is not None else "Phase inconnue"
    return u"{} - {} - {}".format(cat_upper, phase_name, std_label)


def build_schedule_base_name(category, phase, std_label):
    """
    Construit le nom de la nomenclature depuis le template 'vue-nomenclature'
    de conventions_nommage.nommage_vues.

    Variables disponibles :
        {categorie}          nom de la categorie Revit, valeur brute
        {phase}              nom de la phase de projet
        {type-nomenclature}  colonne "Label" de la table "Types de
                             nomenclatures", reprise verbatim

    La casse ecrite du jeton pilote la casse produite : {CATEGORIE} en
    MAJUSCULES, {Categorie} avec la 1re lettre en majuscule, {categorie} brut.
    """
    if not _NOMMAGE_DISPONIBLE:
        return _build_schedule_name_legacy(category, phase, std_label)

    # Valeurs brutes : c'est le template qui decide de la casse.
    _vars = {
        u'categorie':         category.Name,
        u'phase':             phase.Name if phase is not None else u"Phase inconnue",
        u'type-nomenclature': std_label,
    }

    try:
        _nom = resolve_view_name(None, _vars, _cfg,
                                 vue_id=VUE_ID_NOMENCLATURE).strip()
    except Exception:
        _nom = u''
    # Template introuvable : resolve_view_name() retombe sur son repli
    # generique ({vue-pers-titre} - {niveau}), tous deux absents ici, et
    # renvoie donc une chaine vide.
    if not _nom:
        return _build_schedule_name_legacy(category, phase, std_label)
    return _nom


def create_schedule_for(category, phase, std_label, existing_names,
                         vft_id=None):
    base_name = build_schedule_base_name(category, phase, std_label)
    unique_name = make_unique_name(base_name, existing_names)
    try:
        sched = ViewSchedule.CreateSchedule(doc, category.Id, phase.Id)
    except:
        sched = ViewSchedule.CreateSchedule(doc, category.Id)
    try:
        sched.Name = unique_name
    except:
        pass
    try:
        p = sched.get_Parameter(BuiltInParameter.VIEW_PHASE)
        if p and not p.IsReadOnly:
            p.Set(phase.Id)
    except:
        pass
    try:
        defn = sched.Definition
        defn.AddField(ScheduleFieldType.Instance, ElementId(BuiltInParameter.SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM))
    except:
        pass
    # Type de vue Revit issu de la colonne "Type de nomenclature".
    # ViewSchedule.CreateSchedule() n'accepte pas de ViewFamilyType : il ne
    # peut etre pose qu'apres coup, et en dernier — changer le type peut
    # reinitialiser certains parametres de la nomenclature.
    if vft_id is not None and _TYPES_NOM_DISPONIBLE:
        appliquer_type_vue(doc, sched, vft_id)
    return sched

# -------------------------
# Utilitaires TRANSFERT
# -------------------------

def is_parameter_applicable_to_category(param_id, target_category_id, field_name):
    if param_id.IntegerValue < 0:
        return True
    
    if param_id == ElementId.InvalidElementId:
        return False
    
    try:
        bm = doc.ParameterBindings
        it = bm.ForwardIterator()
        it.Reset()
        
        param_found = False
        
        while it.MoveNext():
            defn = it.Key
            binding = it.Current
            
            is_match = False
            
            if defn.Id == param_id:
                is_match = True
            elif hasattr(defn, 'Name') and defn.Name == field_name:
                is_match = True
            
            if is_match:
                param_found = True
                
                if hasattr(binding, 'Categories') and binding.Categories is not None:
                    categories = binding.Categories
                    
                    project_info_id = ElementId(BuiltInCategory.OST_ProjectInformation)
                    
                    for cat in categories:
                        try:
                            if cat.Id == project_info_id:
                                return True
                            if cat.Id == target_category_id:
                                return True
                        except:
                            pass
                    
                    return False
                else:
                    return False
        
        if not param_found:
            try:
                param_elem = doc.GetElement(param_id)
                if param_elem is not None:
                    if isinstance(param_elem, SharedParameterElement):
                        return False
                    return True
            except:
                pass
            
            return False
        
        return False
        
    except Exception as e:
        log("  ⚠️ Erreur verification binding : {}".format(str(e)))
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Utilitaires internes – champs spéciaux (calculés / combinés)
# ═══════════════════════════════════════════════════════════════════════════

def _has_valid_param_id(field):
    """True si le champ a un ParameterId non invalide (champ régulier)."""
    try:
        return field.ParameterId != ElementId.InvalidElementId
    except:
        return False


def _is_combined_field(field):
    """True si le champ est un paramètre combiné.
    Détection sans dépendre de ScheduleFieldType.CombinedParameter."""
    try:
        cp = field.GetCombinedParameters()
        return cp is not None and cp.Count > 0
    except:
        pass
    try:
        ct = getattr(ScheduleFieldType, 'CombinedParameter', None)
        if ct is not None and field.FieldType == ct:
            return True
    except:
        pass
    return False


def _find_methods(obj, *keywords):
    """Liste des méthodes de obj dont le nom contient l'un des mots-clés."""
    try:
        return [m for m in dir(obj)
                if not m.startswith('_')
                and any(k.lower() in m.lower() for k in keywords)]
    except:
        return []


# ── Champs calculés ─────────────────────────────────────────────────────────

def _get_calculated_field_formula(src_field):
    """Extraire la formule d'un champ calculé.
    Essaie tous les attributs/méthodes possibles selon la version Revit."""
    for attr in ['GetScheduleFormula', 'Formula', 'GetFormula',
                 'Expression', 'GetExpression', 'CalculatedFormula']:
        try:
            val = getattr(src_field, attr, None)
            if val is None:
                continue
            s = str(val() if callable(val) else val).strip()
            if s:
                return s
        except:
            pass
    return ""


def _get_field_spec_type(src_field):
    """ForgeTypeId (unités/spec) d'un champ calculé."""
    try:
        sid = src_field.GetSpecTypeId()
        if sid is not None:
            return sid
    except:
        pass
    return None


def _add_calculated_field(tgt_def, name, formula, spec_type_id, available_methods):
    """Tenter d'ajouter un champ calculé.
    - Add*    : signature (name, spec, formula)
    - Insert* : signature (index, name, spec, formula)
    """
    field_count = tgt_def.GetFieldCount()

    exact_calls = []

    # ── Variantes Add* ───────────────────────────────────────────────────
    if spec_type_id is not None:
        exact_calls.append(('AddCalculatedValueField',   (name, spec_type_id, formula)))
    try:
        from Autodesk.Revit.DB import SpecTypeId as _ST
        exact_calls.append(('AddCalculatedValueField',   (name, _ST.Number, formula)))
    except: pass
    try:
        from Autodesk.Revit.DB import UnitType as _UT
        exact_calls.append(('AddCalculatedValueField',   (name, formula, _UT.UT_Undefined)))
    except: pass
    exact_calls.append(('AddCalculatedValueField',       (name, formula)))
    exact_calls.append(('AddCalculatedValueField',       (name,)))

    # ── Variantes Insert* (avec index en premier) ────────────────────────
    if spec_type_id is not None:
        exact_calls.append(('InsertCalculatedValueField', (field_count, name, spec_type_id, formula)))
    try:
        from Autodesk.Revit.DB import SpecTypeId as _ST
        exact_calls.append(('InsertCalculatedValueField', (field_count, name, _ST.Number, formula)))
    except: pass
    try:
        from Autodesk.Revit.DB import UnitType as _UT
        exact_calls.append(('InsertCalculatedValueField', (field_count, name, formula, _UT.UT_Undefined)))
    except: pass
    exact_calls.append(('InsertCalculatedValueField',    (field_count, name, formula)))
    exact_calls.append(('InsertCalculatedValueField',    (field_count, name)))

    for mname, args in exact_calls:
        m = getattr(tgt_def, mname, None)
        if m is None:
            continue
        try:
            m(*args)
            return True, "{}({})".format(mname, len(args))
        except Exception as e:
            log("    ⚠️  {}({}) : {}".format(mname, args, str(e)[:120]))

    # ── Méthodes alternatives par introspection ──────────────────────────
    alt_names = [
        'AddCalculatedField',    'InsertCalculatedField',
        'AddFormulaField',       'InsertFormulaField',
        'AddScheduleCalculatedValueField',
    ]
    for mname in alt_names + available_methods:
        m = getattr(tgt_def, mname, None)
        if m is None:
            continue
        is_insert = mname.startswith('Insert')
        variants = [(field_count, name, formula), (name, formula)] if is_insert \
                   else [(name, formula), (name,)]
        for args in variants:
            try:
                m(*args)
                return True, "{}({})".format(mname, len(args))
            except: pass

    # Diagnostic
    all_calc_methods = [m for m in dir(tgt_def)
                        if not m.startswith('_') and
                        any(k in m.lower() for k in ('calc', 'formula', 'insert', 'value'))]
    log("    [diag] méthodes calc/formula/insert disponibles : {}".format(all_calc_methods))
    return False, "aucune méthode pour champ calculé dans cette version Revit"


# ── Champs combinés ─────────────────────────────────────────────────────────

def _build_target_field_map(tgt_def):
    """Dict param_id_int → [ScheduleFieldId, …] pour tous les champs de la cible.
    Inclut les BuiltIn parameters (valeurs négatives) — nécessaire pour les
    champs combinés qui peuvent référencer des BuiltIn (ex: Famille, Type…).
    """
    mapping = {}
    try:
        for fid in tgt_def.GetFieldOrder():
            try:
                f = tgt_def.GetField(fid)
                pid_int = f.ParameterId.IntegerValue
                # On exclut seulement InvalidElementId (-1) et 0
                if pid_int in (-1, 0):
                    continue
                mapping.setdefault(pid_int, []).append(fid)
            except:
                pass
    except:
        # Fallback si GetFieldOrder échoue
        for i in range(tgt_def.GetFieldCount()):
            try:
                f = tgt_def.GetField(i)
                pid_int = f.ParameterId.IntegerValue
                if pid_int in (-1, 0):
                    continue
                mapping.setdefault(pid_int, []).append(f.FieldId)
            except:
                pass
    return mapping


def _resolve_combined_items(src_sub_items, src_def, tgt_field_map):
    """Convertir la liste de TableCellCombinedParameterData source
    en liste de ScheduleFieldId cible.

    L'attribut est ParamId (pas ParameterId) dans cette version Revit.
    On tente plusieurs stratégies pour résoudre chaque sous-champ.
    """
    from System.Collections.Generic import List as _List
    tgt_ids = _List[ScheduleFieldId]()
    n_total = 0
    n_ok    = 0

    diag_done = [False]

    for item in src_sub_items:
        n_total += 1
        pid_int = None

        if not diag_done[0]:
            try:
                attrs = [a for a in dir(item) if not a.startswith('_')]
                log("  [diag TableCellCombinedParameterData] attrs={}".format(attrs))
                diag_done[0] = True
            except:
                pass

        # ── Tentative 1 : ParamId (nom correct dans cette version Revit) ──
        try:
            pid_int = item.ParamId.IntegerValue
        except:
            pass

        # ── Tentative 2 : ParameterId (anciennes versions) ────────────────
        if pid_int is None:
            try:
                pid_int = item.ParameterId.IntegerValue
            except:
                pass

        # ── Tentative 3 : via FieldId → source field → ParameterId ────────
        if pid_int is None:
            try:
                src_fld = src_def.GetField(item.FieldId)
                pid_int = src_fld.ParameterId.IntegerValue
            except:
                pass

        # ── Tentative 4 : scan de tous les attributs ElementId ────────────
        if pid_int is None:
            for attr in dir(item):
                if attr.startswith('_'):
                    continue
                try:
                    val = getattr(item, attr)
                    if hasattr(val, 'IntegerValue'):
                        candidate = val.IntegerValue
                        # Ignorer les valeurs nulles ou InvalidElementId
                        if candidate not in (0, -1):
                            pid_int = candidate
                            log("  [fallback attr={}] pid_int={}".format(attr, pid_int))
                            break
                except:
                    pass

        if pid_int is None:
            log("  [{}] ❌ ParamId introuvable".format(n_total))
            continue

        log("  [{}] ParamId.IntegerValue={}".format(n_total, pid_int))

        # ── Recherche dans les champs de la cible ─────────────────────────
        fids = tgt_field_map.get(pid_int)
        if fids:
            tgt_ids.Add(fids[0])
            n_ok += 1
            log("  [{}] ✅ pid_int={} → ScheduleFieldId={}".format(n_total, pid_int, fids[0]))
        else:
            # Le param_id peut être un BuiltIn (valeur négative) :
            # chercher par correspondance dans tous les champs de la cible
            log("  [{}] ⚠ pid_int={} absent du field_map — tentative recherche directe".format(
                n_total, pid_int))
            found = False
            try:
                tgt_def_ref = None
                # On reconstruit la liste des champs cible pour rechercher par ElementId
                for fid_key, fid_list in tgt_field_map.items():
                    if fid_key == pid_int:
                        tgt_ids.Add(fid_list[0])
                        n_ok += 1
                        found = True
                        break
            except:
                pass
            if not found:
                log("  [{}] ❌ pid_int={} non résolu".format(n_total, pid_int))

    log("  Résolu : {}/{} sous-champs".format(n_ok, n_total))
    return tgt_ids, n_ok, n_total


def _add_combined_field(tgt_def, tgt_ids, available_methods):
    """Tenter d'ajouter un champ combiné.
    - Add*    : signature (ids)         → ajoute en fin
    - Insert* : signature (index, ids)  → insère à la position index
    """
    field_count = tgt_def.GetFieldCount()   # position = fin de liste

    name_candidates = [
        'AddCombinedParameterField',
        'InsertCombinedParameterField',
    ] + [m for m in available_methods
         if m not in ('AddCombinedParameterField', 'InsertCombinedParameterField')]

    for mname in name_candidates:
        m = getattr(tgt_def, mname, None)
        if m is None:
            continue

        # Variantes de signature selon que la méthode est Add* ou Insert*
        is_insert = mname.startswith('Insert')
        if is_insert:
            arg_variants = [
                (field_count, tgt_ids),
                (field_count, tgt_ids, ""),
                (0, tgt_ids),               # fallback position 0
            ]
        else:
            arg_variants = [
                (tgt_ids,),
                (tgt_ids, ""),
            ]

        for args in arg_variants:
            try:
                m(*args)
                return True, "{}({} args)".format(mname, len(args))
            except Exception as e:
                log("    ⚠️  {}({}) : {}".format(mname, args, str(e)[:120]))

    # Diagnostic
    all_comb_methods = [m for m in dir(tgt_def)
                        if not m.startswith('_') and
                        any(k in m.lower() for k in ('combined', 'combine', 'insert'))]
    log("    [diag] méthodes combined/insert disponibles : {}".format(all_comb_methods))
    return False, "aucune méthode pour champ combiné dans cette version Revit"


# ── Champs réguliers (logique originale) ────────────────────────────────────

def _add_regular_field(tgt_def, src_field, field_name):
    """Retourne (ok, méthode)."""
    field_type = src_field.FieldType
    param_id   = src_field.ParameterId
    try:
        tgt_def.AddField(field_type, param_id)
        return True, "direct"
    except:
        pass
    try:
        param_elem = doc.GetElement(param_id)
        if param_elem is not None:
            bm = doc.ParameterBindings
            it = bm.ForwardIterator(); it.Reset()
            found_def = None
            while it.MoveNext():
                d = it.Key
                if d.Name == field_name:
                    found_def = d; break
            if found_def is not None:
                binding = bm.get_Item(found_def)
                ft = (ScheduleFieldType.Instance
                      if isinstance(binding, InstanceBinding)
                      else ScheduleFieldType.ElementType)
                tgt_def.AddField(ft, found_def.Id)
                return True, "via bindings"
    except:
        pass
    _builtin = {
        "Type":               BuiltInParameter.ELEM_TYPE_PARAM,
        "Famille":            BuiltInParameter.ELEM_FAMILY_PARAM,
        "Famille et type":    BuiltInParameter.ELEM_FAMILY_AND_TYPE_PARAM,
        "Commentaires":       BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
        "Marque":             BuiltInParameter.ALL_MODEL_MARK,
        "Description":        BuiltInParameter.ALL_MODEL_DESCRIPTION,
        "Fabricant":          BuiltInParameter.ALL_MODEL_MANUFACTURER,
        "Code type":          BuiltInParameter.ALL_MODEL_TYPE_MARK,
        "Modèle":             BuiltInParameter.ALL_MODEL_MODEL,
        "URL":                BuiltInParameter.ALL_MODEL_URL,
        "Coût":               BuiltInParameter.ALL_MODEL_COST,
    }
    if field_name in _builtin:
        try:
            tgt_def.AddField(field_type, ElementId(_builtin[field_name]))
            return True, "BuiltInParameter"
        except:
            pass
    return False, "toutes tentatives échouées"


# ═══════════════════════════════════════════════════════════════════════════
# Transfert principal — 3 passes
# ═══════════════════════════════════════════════════════════════════════════

def transfer_schedule_configuration(source_sched, target_sched):
    """Passe 1 : champs réguliers   (ParameterId valide  → AddField)
       Passe 2 : champs calculés    (ParameterId invalide, pas combiné)
       Passe 3 : champs combinés    (GetCombinedParameters non vide)

    Compatibilité : aucune référence à ScheduleFieldType.CalculatedValue
    ni .CombinedParameter (absent dans certaines versions de Revit).
    Les méthodes AddCalculatedValueField / AddCombinedParameterField sont
    découvertes à l'exécution via dir().
    """
    src_def       = source_sched.Definition
    tgt_def       = target_sched.Definition
    target_cat_id = tgt_def.CategoryId

    added   = 0
    skipped = 0

    log("#### Traitement de : **{}**".format(target_sched.Name))
    log("- Catégorie cible : **{}**".format(target_cat_id))
    log("")

    # Découverte des méthodes disponibles sur ScheduleDefinition (une fois)
    avail_calc = _find_methods(tgt_def, 'calc', 'formula', 'expression')
    avail_comb = _find_methods(tgt_def, 'combined', 'combine')
    log("**[diag]** méthodes calc/formula : `{}`".format(avail_calc))
    log("**[diag]** méthodes combined     : `{}`".format(avail_comb))
    log("")

    # ══ PASSE 1 : champs réguliers ════════════════════════════════════════
    log("**Passe 1 – champs réguliers**")
    for i in range(src_def.GetFieldCount()):
        src_field  = src_def.GetField(i)
        field_name = src_field.GetName()
        param_id   = src_field.ParameterId

        if not _has_valid_param_id(src_field):
            tag = "combiné" if _is_combined_field(src_field) else "calculé/autre"
            log("- [{}] `{}` | FieldType={} → passe {} ({})".format(
                i + 1, field_name, int(src_field.FieldType),
                "3" if tag == "combiné" else "2", tag))
            continue

        log("- Champ [{}] : `{}`".format(i + 1, field_name))

        if not is_parameter_applicable_to_category(param_id, target_cat_id, field_name):
            log("  ↳ ❌ Non lié à la catégorie cible")
            skipped += 1
            continue

        ok, method = _add_regular_field(tgt_def, src_field, field_name)
        if ok:
            log("  ↳ ✅ Ajouté ({})".format(method))
            added += 1
        else:
            log("  ↳ ❌ Erreur lors de l'ajout")
            skipped += 1

    # ══ PASSE 2 : champs calculés ════════════════════════════════════════
    log("")
    log("**Passe 2 – champs calculés**")
    n_calc = 0
    for i in range(src_def.GetFieldCount()):
        src_field = src_def.GetField(i)
        if _has_valid_param_id(src_field) or _is_combined_field(src_field):
            continue
        n_calc += 1
        field_name   = src_field.GetName()
        formula      = _get_calculated_field_formula(src_field)
        spec_type_id = _get_field_spec_type(src_field)

        # Diagnostic champ calculé
        calc_attrs = _find_methods(src_field, 'formula', 'calc', 'expression', 'spec')
        log("- Champ calculé [{}] : `{}` | FieldType={}".format(
            i + 1, field_name, int(src_field.FieldType)))
        log("  attrs utiles : `{}`".format(calc_attrs))
        log("  Formule=`{}` | SpecType=`{}`".format(formula, spec_type_id))

        ok, method = _add_calculated_field(
            tgt_def, field_name, formula, spec_type_id, avail_calc)
        if ok:
            log("  ↳ ✅ Ajouté ({})".format(method))
            added += 1
        else:
            log("  ↳ ❌ {} — champ calculé non copié".format(method))
            skipped += 1

    if n_calc == 0:
        log("  (aucun champ calculé dans la source)")

    # ══ PASSE 3 : champs combinés ════════════════════════════════════════
    log("")
    log("**Passe 3 – champs combinés**")

    # Index des champs réguliers déjà ajoutés dans la cible
    tgt_field_map = _build_target_field_map(tgt_def)

    n_comb = 0
    for i in range(src_def.GetFieldCount()):
        src_field = src_def.GetField(i)
        if not _is_combined_field(src_field):
            continue
        n_comb += 1
        field_name = src_field.GetName()
        log("- Champ combiné [{}] : `{}` | FieldType={}".format(
            i + 1, field_name, int(src_field.FieldType)))

        src_sub_items = None
        try:
            src_sub_items = src_field.GetCombinedParameters()
        except Exception as e:
            log("  ↳ ❌ GetCombinedParameters() : {}".format(str(e)))
            skipped += 1
            continue

        if src_sub_items is None or src_sub_items.Count == 0:
            log("  ↳ ❌ Liste vide")
            skipped += 1
            continue

        tgt_ids, n_ok, n_total = _resolve_combined_items(
            src_sub_items, src_def, tgt_field_map)

        if tgt_ids.Count == 0:
            log("  ↳ ❌ Aucun sous-champ résolu → combiné ignoré")
            skipped += 1
            continue

        ok, method = _add_combined_field(tgt_def, tgt_ids, avail_comb)
        if ok:
            log("  ↳ ✅ Champ combiné ajouté ({})".format(method))
            added += 1
        else:
            log("  ↳ ❌ {} — champ combiné non copié".format(method))
            skipped += 1

    if n_comb == 0:
        log("  (aucun champ combiné dans la source)")

    log("")
    return added, skipped

# -------------------------
# Interface ProgressWindow
# -------------------------
class ProgressWindow(WPFWindow):
    def __init__(self, total_count):
        xaml_path = os.path.join(script_dir, 'ProgressWindow.xaml')
        
        if not os.path.exists(xaml_path):
            self.UI = None
            return
        
        try:
            with codecs.open(xaml_path, 'r', 'utf-8') as f:
                xaml = f.read()
            
            self.UI = XamlReader.Parse(xaml)
            
            self.progress_bar = self.UI.FindName('progressBar')
            self.txt_status = self.UI.FindName('txtStatus')
            self.txt_current = self.UI.FindName('txtCurrent')
            
            self.total_count = total_count
            
            if self.progress_bar:
                self.progress_bar.Maximum = total_count
                self.progress_bar.Value = 0
            
            if self.txt_status:
                self.txt_status.Text = "Préparation..."
            
            if self.txt_current:
                self.txt_current.Text = "0 / {}".format(total_count)
        except:
            self.UI = None
    
    def show_progress(self):
        if self.UI:
            try:
                self.UI.Show()
            except:
                pass
    
    def update_progress(self, current, schedule_name):
        if self.UI:
            try:
                if self.progress_bar:
                    self.progress_bar.Value = current

                if self.txt_status:
                    self.txt_status.Text = u"Traitement : {}".format(schedule_name)

                if self.txt_current:
                    self.txt_current.Text = "{} / {}".format(current, self.total_count)

                # Forcer le rafraichissement WPF independamment des logs
                from System.Windows.Threading import Dispatcher, DispatcherPriority
                Dispatcher.CurrentDispatcher.Invoke(
                    DispatcherPriority.Background,
                    System.Action(lambda: None)
                )
            except:
                pass
    
    def close_progress(self):
        if self.UI:
            try:
                self.UI.Close()
            except:
                pass

# -------------------------
# Interface CreateSchedules (CODE ORIGINAL QUI FONCTIONNE)
# -------------------------
class CreateSchedulesWindow(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(script_dir, "CreateSchedules.xaml")
        if not os.path.exists(xaml_path):
            raise Exception("CreateSchedules.xaml introuvable")

        try:
            with codecs.open(xaml_path, "r", "utf-8") as f:
                xaml = f.read()
            self.UI = XamlReader.Parse(xaml)
        except Exception:
            tb = traceback.format_exc()
            path = save_traceback(tb)
            if ACTIVER_LOGS:
                log("Erreur parsing XAML: {}".format(path or "n/a"))
            show_alert("Erreur XAML", "Erreur chargement interface.")
            raise

        # FindName
        try:
            self.categories_panel = self.UI.FindName("categories_panel")
            self.types_panel = self.UI.FindName("types_panel")
            self.phases_panel = self.UI.FindName("phases_panel")
            self.btn_source = self.UI.FindName("btn_source")
            self.popup_source = self.UI.FindName("popup_source")
            self.txt_source_value = self.UI.FindName("txt_source_value")
            self.list_source = self.UI.FindName("list_source")
            self.txtSearchSource = self.UI.FindName("txtSearchSource")
            self.txtSourceCount = self.UI.FindName("txtSourceCount")
            self.txtSearchCategories = self.UI.FindName("txtSearchCategories")

            self.btn_check_cat = self.UI.FindName("btn_check_cat")
            self.btn_uncheck_cat = self.UI.FindName("btn_uncheck_cat")
            self.btn_toggle_cat = self.UI.FindName("btn_toggle_cat")

            self.btn_check_types = self.UI.FindName("btn_check_types")
            self.btn_uncheck_types = self.UI.FindName("btn_uncheck_types")
            self.btn_toggle_types = self.UI.FindName("btn_toggle_types")

            self.btn_check_phases = self.UI.FindName("btn_check_phases")
            self.btn_uncheck_phases = self.UI.FindName("btn_uncheck_phases")
            self.btn_toggle_phases = self.UI.FindName("btn_toggle_phases")

            self.btn_ok = self.UI.FindName("btn_ok")
            self.btn_cancel = self.UI.FindName("btn_cancel")
        except Exception:
            tb = traceback.format_exc()
            path = save_traceback(tb)
            if ACTIVER_LOGS:
                log("Erreur FindName: {}".format(path or "n/a"))
            show_alert("Erreur FindName", "Erreur initialisation interface.")
            raise

        if self.categories_panel is None or self.types_panel is None or self.phases_panel is None:
            raise Exception("Panels manquants dans le XAML.")

        # Variables pour MAJ+clic sur chaque ListBox
        self.last_selected_index_cat = -1
        self.last_selected_index_types = -1
        self.last_selected_index_phases = -1

        # Collections
        self.cat_checkboxes = []
        self.type_checkboxes = []
        self.phase_checkboxes = []
        self.all_categories = []
        # Noms des nomenclatures existantes, source du filtre de recherche.
        self.all_source_names = []
        # Valeur retenue dans le champ "Nomenclature modele".
        self.source_selected = SOURCE_AUCUNE
        # Vrai pendant une selection programmee de la liste : empeche
        # _on_source_item_click de refermer le Popup a l'ouverture.
        self._source_syncing = False

        self.result = None

        # Populate
        self._populate_categories()
        self._populate_types()
        self._populate_phases()
        self._populate_source_combo()

        # Connect handlers
        try:
            if self.btn_check_cat: self.btn_check_cat.Click += lambda s,e: self._select_all_list(self.categories_panel, self.cat_checkboxes, True)
            if self.btn_uncheck_cat: self.btn_uncheck_cat.Click += lambda s,e: self._select_all_list(self.categories_panel, self.cat_checkboxes, False)
            if self.btn_toggle_cat: self.btn_toggle_cat.Click += lambda s,e: self._toggle_list(self.categories_panel, self.cat_checkboxes)

            if self.btn_check_types: self.btn_check_types.Click += lambda s,e: self._select_all_list(self.types_panel, self.type_checkboxes, True)
            if self.btn_uncheck_types: self.btn_uncheck_types.Click += lambda s,e: self._select_all_list(self.types_panel, self.type_checkboxes, False)
            if self.btn_toggle_types: self.btn_toggle_types.Click += lambda s,e: self._toggle_list(self.types_panel, self.type_checkboxes)

            if self.btn_check_phases: self.btn_check_phases.Click += lambda s,e: self._select_all_list(self.phases_panel, self.phase_checkboxes, True)
            if self.btn_uncheck_phases: self.btn_uncheck_phases.Click += lambda s,e: self._select_all_list(self.phases_panel, self.phase_checkboxes, False)
            if self.btn_toggle_phases: self.btn_toggle_phases.Click += lambda s,e: self._toggle_list(self.phases_panel, self.phase_checkboxes)

            if self.btn_ok: self.btn_ok.Click += self._on_ok
            if self.btn_cancel: self.btn_cancel.Click += self._on_cancel
        except Exception:
            pass

        # Gestion MAJ+clic pour les 3 ListBox
        try:
            self.categories_panel.PreviewMouseLeftButtonDown += lambda s,e: self._on_mouse_down(s, e, self.categories_panel, 'cat')
            self.types_panel.PreviewMouseLeftButtonDown += lambda s,e: self._on_mouse_down(s, e, self.types_panel, 'types')
            self.phases_panel.PreviewMouseLeftButtonDown += lambda s,e: self._on_mouse_down(s, e, self.phases_panel, 'phases')
        except Exception:
            pass

        # Synchronisation visuelle : SelectionChanged -> met à jour les CheckBox
        try:
            if hasattr(self.categories_panel, "SelectionChanged"):
                self.categories_panel.SelectionChanged += (lambda lb, coll: (lambda s,e: self._sync_selection_to_checkboxes(lb, coll)))(self.categories_panel, self.cat_checkboxes)
            if hasattr(self.types_panel, "SelectionChanged"):
                self.types_panel.SelectionChanged += (lambda lb, coll: (lambda s,e: self._sync_selection_to_checkboxes(lb, coll)))(self.types_panel, self.type_checkboxes)
            if hasattr(self.phases_panel, "SelectionChanged"):
                self.phases_panel.SelectionChanged += (lambda lb, coll: (lambda s,e: self._sync_selection_to_checkboxes(lb, coll)))(self.phases_panel, self.phase_checkboxes)
        except Exception:
            pass

        # Recherche categories
        if self.txtSearchCategories:
            self.txtSearchCategories.TextChanged += self._on_search_categories

        # Champ deroulant "Nomenclature modele" avec recherche integree
        if self.txtSearchSource:
            self.txtSearchSource.TextChanged += self._on_search_source
            self.txtSearchSource.PreviewKeyDown += self._on_search_source_keydown
        if self.popup_source:
            self.popup_source.Opened += self._on_source_popup_opened
        if self.list_source:
            # SelectionChanged plutot que MouseUp : couvre aussi la navigation
            # au clavier depuis la liste.
            self.list_source.SelectionChanged += self._on_source_item_click

    def _on_mouse_down(self, sender, args, listbox, panel_type):
        """Gérer CTRL+clic et MAJ+clic pour sélection multiple des checkboxes."""
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper
        
        # Déterminer quelle collection utiliser
        if panel_type == 'cat':
            collection = self.cat_checkboxes
            last_idx_attr = 'last_selected_index_cat'
        elif panel_type == 'types':
            collection = self.type_checkboxes
            last_idx_attr = 'last_selected_index_types'
        else:
            collection = self.phase_checkboxes
            last_idx_attr = 'last_selected_index_phases'
        
        # Trouver l'item cliqué
        try:
            clicked_item = args.OriginalSource
            current = clicked_item
            clicked_index = -1
            
            while current is not None:
                if hasattr(current, '__class__') and current.__class__.__name__ == 'ListBoxItem':
                    clicked_index = listbox.ItemContainerGenerator.IndexFromContainer(current)
                    break
                try:
                    current = VisualTreeHelper.GetParent(current)
                except:
                    break
            
            if clicked_index < 0 or clicked_index >= listbox.Items.Count:
                return
            
            # Récupérer la checkbox cliquée
            clicked_checkbox = listbox.Items[clicked_index]
            
        except:
            return
        
        # CTRL+clic : Toggle uniquement la checkbox cliquée
        if Keyboard.IsKeyDown(Key.LeftCtrl) or Keyboard.IsKeyDown(Key.RightCtrl):
            try:
                clicked_checkbox.IsChecked = not clicked_checkbox.IsChecked
                setattr(self, last_idx_attr, clicked_index)
                args.Handled = True
            except:
                pass
            return
        
        # MAJ+clic : Sélectionner/désélectionner une plage
        if Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift):
            try:
                last_selected_index = getattr(self, last_idx_attr, -1)
                
                # Si pas de dernier index, partir du début
                if last_selected_index < 0:
                    last_selected_index = 0
                
                # Calculer la plage
                start = min(last_selected_index, clicked_index)
                end = max(last_selected_index, clicked_index)
                
                # Déterminer l'état cible : si la checkbox cliquée est cochée, on décoche la plage, sinon on coche
                target_state = not clicked_checkbox.IsChecked
                
                # Appliquer à toute la plage
                for i in range(start, end + 1):
                    if i < listbox.Items.Count:
                        checkbox = listbox.Items[i]
                        checkbox.IsChecked = target_state
                
                # Mettre à jour le dernier index
                setattr(self, last_idx_attr, clicked_index)
                
                # Empêcher le comportement par défaut
                args.Handled = True
                
            except:
                pass
            return
        
        # Clic normal : mettre à jour le dernier index et laisser le comportement normal
        try:
            setattr(self, last_idx_attr, clicked_index)
        except:
            pass

    def _populate_categories(self):
        cats = get_schedulable_categories()
        self.all_categories = cats
        
        for cat in cats:
            cb = System.Windows.Controls.CheckBox()
            cb.Content = cat.Name
            cb.Margin = Thickness(0,2,0,2)
            cb.IsChecked = False
            cb.Checked += (lambda chk, lb: (lambda s,e: self._on_checkbox_checked(chk, lb, True)))(cb, self.categories_panel)
            cb.Unchecked += (lambda chk, lb: (lambda s,e: self._on_checkbox_checked(chk, lb, False)))(cb, self.categories_panel)
            self.cat_checkboxes.append((cb, cat))
            try:
                self.categories_panel.Items.Add(cb)
            except Exception:
                try:
                    self.categories_panel.Children.Add(cb)
                except:
                    pass

    def _populate_types(self):
        """
        Une case a cocher par ligne de la table "Types de nomenclatures"
        (01_Parametres > onglet Nomenclatures). La ligne complete est
        conservee : le label alimente {type-nomenclature}, le type_vue sera
        resolu en ViewFamilyType au moment de la creation.
        """
        for row in get_types_a_creer():
            lbl = row.get(u'label', u'')
            if not lbl:
                continue
            cb = System.Windows.Controls.CheckBox()
            cb.Content = lbl
            cb.Margin = Thickness(0,2,0,2)
            cb.IsChecked = False
            cb.Checked += (lambda chk, lb: (lambda s,e: self._on_checkbox_checked(chk, lb, True)))(cb, self.types_panel)
            cb.Unchecked += (lambda chk, lb: (lambda s,e: self._on_checkbox_checked(chk, lb, False)))(cb, self.types_panel)
            self.type_checkboxes.append((cb, row))
            try:
                self.types_panel.Items.Add(cb)
            except Exception:
                try:
                    self.types_panel.Children.Add(cb)
                except:
                    pass

    def _populate_phases(self):
        phases = get_project_phases()
        for p in phases:
            cb = System.Windows.Controls.CheckBox()
            cb.Content = p.Name
            cb.Margin = Thickness(0,2,0,2)
            cb.IsChecked = False
            cb.Checked += (lambda chk, lb: (lambda s,e: self._on_checkbox_checked(chk, lb, True)))(cb, self.phases_panel)
            cb.Unchecked += (lambda chk, lb: (lambda s,e: self._on_checkbox_checked(chk, lb, False)))(cb, self.phases_panel)
            self.phase_checkboxes.append((cb, p))
            try:
                self.phases_panel.Items.Add(cb)
            except Exception:
                try:
                    self.phases_panel.Children.Add(cb)
                except:
                    pass
    
    def _populate_source_combo(self):
        """
        Prepare le champ deroulant "Nomenclature modele".

        La valeur retenue vit dans self.source_selected (et non dans un
        SelectedItem) : la ListBox du Popup est reconstruite a chaque frappe,
        sa selection ne survit donc pas au filtrage.
        """
        if not self.list_source:
            return
        # Noms memorises une fois : le filtrage ne reinterroge pas le document.
        self.all_source_names = sorted(
            (s.Name for s in get_existing_schedules()),
            key=lambda n: n.lower())
        self.source_selected = SOURCE_AUCUNE
        self._refresh_source_list(u'')

    def _refresh_source_list(self, filtre):
        """
        Reconstruit la liste du Popup en ne gardant que les nomenclatures dont
        le nom contient 'filtre' (insensible a la casse).

        "Aucune" reste toujours en tete, quel que soit le filtre : c'est le
        seul moyen de revenir a "pas de source" sans vider la recherche.
        """
        _f = (filtre or u'').strip().lower()
        self.list_source.Items.Clear()
        self.list_source.Items.Add(SOURCE_AUCUNE)
        _n_vis = 0
        for _nom in self.all_source_names:
            if not _f or _f in _nom.lower():
                self.list_source.Items.Add(_nom)
                _n_vis += 1

        if self.txtSourceCount is not None:
            _total = len(self.all_source_names)
            if _f:
                self.txtSourceCount.Text = u"{} nomenclature(s) sur {}".format(
                    _n_vis, _total)
            else:
                self.txtSourceCount.Text = u"{} nomenclature(s)".format(_total)

        # Mettre en evidence la valeur courante si elle survit au filtre.
        # Le drapeau evite que le SelectionChanged declenche par cette
        # affectation ne soit pris pour un clic utilisateur — sans lui, le
        # Popup se refermerait aussitot apres s'etre ouvert.
        self._source_syncing = True
        try:
            if self.list_source.Items.Contains(self.source_selected):
                self.list_source.SelectedItem = self.source_selected
        finally:
            self._source_syncing = False

    def _set_source_selected(self, valeur):
        """Ecrit la valeur dans le champ ferme et referme le Popup."""
        self.source_selected = valeur or SOURCE_AUCUNE
        if self.txt_source_value is not None:
            self.txt_source_value.Text = self.source_selected
        # Decocher le ToggleButton referme le Popup (binding TwoWay sur IsOpen).
        if self.btn_source is not None:
            self.btn_source.IsChecked = False

    def _on_source_popup_opened(self, sender, args):
        """
        Vide la recherche et donne le focus a la zone de saisie a l'ouverture.

        Le focus est repousse via le Dispatcher : appele directement dans
        Opened, le Popup n'est pas encore rendu et Focus() reste sans effet.
        """
        try:
            self.txtSearchSource.Text = u''
            self._refresh_source_list(u'')
            self.UI.Dispatcher.BeginInvoke(
                DispatcherPriority.Input,
                System.Action(lambda: self.txtSearchSource.Focus()))
        except Exception:
            pass

    def _on_search_source(self, sender, args):
        """Filtrer la liste selon le texte de recherche."""
        try:
            self._refresh_source_list(self.txtSearchSource.Text)
        except Exception:
            pass

    def _on_source_item_click(self, sender, args):
        """Selection utilisateur dans la liste (souris ou clavier)."""
        if self._source_syncing:
            return
        try:
            _item = self.list_source.SelectedItem
            if _item is not None:
                self._set_source_selected(str(_item))
        except Exception:
            pass

    def _on_search_source_keydown(self, sender, args):
        """Entree = 1er resultat, Echap = fermer sans changer la selection."""
        from System.Windows.Input import Key
        try:
            if args.Key == Key.Escape:
                if self.btn_source is not None:
                    self.btn_source.IsChecked = False
                args.Handled = True
            elif args.Key == Key.Enter:
                # Item[0] est toujours "Aucune" : on vise le 1er resultat reel
                # s'il existe, sinon on retombe sur "Aucune".
                _idx = 1 if self.list_source.Items.Count > 1 else 0
                self._set_source_selected(str(self.list_source.Items[_idx]))
                args.Handled = True
        except Exception:
            pass


    def _on_search_categories(self, sender, args):
        """Filtrer les categories selon le texte de recherche."""
        try:
            search_text = self.txtSearchCategories.Text.lower()
            
            # Sauvegarder les selections actuelles
            selected_cats = set()
            for cb, cat in self.cat_checkboxes:
                if cb.IsChecked:
                    selected_cats.add(cat.Name)
            
            # Vider la liste
            self.categories_panel.Items.Clear()
            
            # Re-ajouter les categories filtrees
            for cb, cat in self.cat_checkboxes:
                if search_text == "" or search_text in cat.Name.lower():
                    try:
                        self.categories_panel.Items.Add(cb)
                        # Restaurer la selection
                        if cat.Name in selected_cats:
                            cb.IsChecked = True
                    except:
                        pass
        except:
            pass

    def _select_all_list(self, listbox, collection, value):
        """Sélectionner/désélectionner seulement les checkboxes VISIBLES dans la listbox."""
        try:
            for cb, _ in collection:
                # Ne modifier que les checkboxes visibles (filtrées)
                if cb in listbox.Items:
                    cb.IsChecked = value
        except:
            pass

    def _toggle_list(self, listbox, collection):
        """Inverser la selection des checkboxes VISIBLES dans la listbox."""
        try:
            # Inverser seulement les checkboxes qui sont dans listbox.Items
            for cb, _ in collection:
                if cb in listbox.Items:
                    cb.IsChecked = not cb.IsChecked
        except:
            pass

    def _sync_selection_to_checkboxes(self, listbox, collection):
        """Ne rien faire - la synchronisation n'est pas nécessaire."""
        pass

    def _on_checkbox_checked(self, checkbox, listbox, checked):
        """Ne rien faire - la synchronisation avec ListBox.SelectedItems n'est pas nécessaire.
        
        Les sélections sont récupérées directement depuis cb.IsChecked dans _on_ok().
        """
        pass

    def _on_ok(self, sender, args):
        selected_cats = [c for cb, c in self.cat_checkboxes if bool(cb.IsChecked)]
        selected_types = [t for cb, t in self.type_checkboxes if bool(cb.IsChecked)]
        selected_phases = [p for cb, p in self.phase_checkboxes if bool(cb.IsChecked)]
        
        if not selected_cats:
            show_xaml_message("Veuillez sélectionner au moins une catégorie.", title="Erreur")
            return
        if not selected_types:
            show_xaml_message("Veuillez sélectionner au moins un type de nomenclature.", title="Erreur")
            return
        if not selected_phases:
            show_xaml_message("Veuillez sélectionner au moins une phase.", title="Erreur")
            return
        
        # Source selectionnee (si any)
        source_name = None
        source_text = getattr(self, 'source_selected', SOURCE_AUCUNE)
        if source_text and source_text != SOURCE_AUCUNE:
            source_name = source_text
        
        self.result = {
            "categories": selected_cats,
            "types": selected_types,
            "phases": selected_phases,
            "source_name": source_name,
        }
        
        try:
            self.UI.Close()
        except:
            pass

    def _on_cancel(self, sender, args):
        self.result = None
        try:
            self.UI.Close()
        except:
            pass

    def show_dialog(self):
        try:
            self.UI.ShowDialog()
        except Exception as e:
            tb = traceback.format_exc()
            path = save_traceback(tb)
            if ACTIVER_LOGS:
                log("Erreur ShowDialog: {}".format(path or "n/a"))
            show_alert("Erreur ShowDialog", "Erreur affichage interface: {}".format(str(e)))
            raise
        return self.result

# -------------------------
# Main flow
# -------------------------
def main():
    try:
        log("# Creation de nomenclatures")
        log("---")

        # ── Avertissement ────────────────────────────────────────────────────
        if not show_warning():
            log("Annulé par l'utilisateur (avertissement).")
            return

        categories = get_schedulable_categories()
        if not categories:
            show_xaml_message("Aucune catégorie disponible.", title="Erreur")
            return

        phases = get_project_phases()
        if not phases:
            show_xaml_message("Aucune phase trouvée.", title="Erreur")
            return

        win = CreateSchedulesWindow()
        res = win.show_dialog()
        if not res:
            log("Annulé par l'utilisateur.")
            return

        selected_cats = res["categories"]
        selected_types = res["types"]
        selected_phases = res["phases"]
        source_name = res.get("source_name")

        # Garde-fou : un jeton inconnu serait recopie tel quel dans le nom des
        # nomenclatures creees.
        if _NOMMAGE_DISPONIBLE:
            _tpl_ok, _tpl_msg = verifier_template(_cfg, VUE_ID_NOMENCLATURE)
            if not _tpl_ok:
                show_alert(u"Convention de nommage invalide", _tpl_msg)
                return

        existing_names = get_existing_schedule_names()

        # CREATION
        t = Transaction(doc, "Créer nomenclatures standard")
        t.Start()

        # Types de vue Revit resolus une seule fois pour toute la session : la
        # duplication d'un ViewFamilyType absent ne doit se produire qu'une
        # fois, pas a chaque combinaison categorie x phase.
        # Cle : nom du type -> ElementId (ou None si non resoluble).
        vft_par_type = {}
        for _row_t in selected_types:
            _nom_vft = (_row_t.get(u'type_vue') or u'').strip()
            if not _nom_vft or _nom_vft in vft_par_type:
                continue
            _vid = None
            if _TYPES_NOM_DISPONIBLE:
                try:
                    _vid = get_or_create_schedule_vft(doc, _nom_vft)
                except Exception:
                    _vid = None
            vft_par_type[_nom_vft] = _vid
            if _vid is None:
                log(u"⚠ Type de nomenclature `{}` introuvable et non créable "
                    u"— type par défaut conservé.".format(_nom_vft))
            else:
                log(u"Type de nomenclature : `{}`".format(_nom_vft))

        created_schedules = []
        created = 0
        errors = 0

        for cat in selected_cats:
            for ph in selected_phases:
                for row_t in selected_types:
                    lbl = row_t.get(u'label', u'')
                    try:
                        sched = create_schedule_for(
                            cat, ph, lbl, existing_names,
                            vft_id=vft_par_type.get(
                                (row_t.get(u'type_vue') or u'').strip()))
                        log(u"✔ Créé : **{}**".format(sched.Name))
                        created_schedules.append(sched)
                        created += 1
                    except Exception:
                        tb = traceback.format_exc()
                        path = save_traceback(tb)
                        if ACTIVER_LOGS:
                            log("Erreur création : {}".format(path or "n/a"))
                        errors += 1

        t.Commit()
        
        log("---")
        log("## Nomenclatures créées : **{}**".format(created))
        if errors > 0:
            log("## Erreurs : **{}**".format(errors))
        log("")
        
        if created == 0:
            show_xaml_message(u"Aucune nomenclature créée.", title="Terminé")
            return
        
        # TRANSFERT (si source selectionnee)
        if source_name:
            log("---")
            log("# Transfert de configuration")
            log("---")
            log("## Source : **{}**".format(source_name))
            
            # Trouver la source
            all_schedules = get_existing_schedules()
            source = None
            for s in all_schedules:
                if s.Name == source_name:
                    source = s
                    break
            
            if not source:
                show_xaml_message(u"{} nomenclatures créées.\n\nSource '{}' introuvable.".format(created, source_name), title="Terminé")
                return
            
            log("- Categorie : **{}**".format(source.Definition.CategoryId))
            log("- Nombre de champs : **{}**".format(source.Definition.GetFieldCount()))
            log("")
            
            # Barre de progression
            progress_window = ProgressWindow(len(created_schedules))
            progress_window.show_progress()
            
            t2 = Transaction(doc, "Transferer configuration")
            t2.Start()
            
            total_added = 0
            total_skipped = 0
            
            for idx, target_sched in enumerate(created_schedules):
                progress_window.update_progress(idx + 1, target_sched.Name)
                
                added, skipped = transfer_schedule_configuration(source, target_sched)
                total_added += added
                total_skipped += skipped
                
                log("### ➤ Résumé : **{}**".format(target_sched.Name))
                log("- Champs ajoutés : **{}**".format(added))
                log("")
            
            t2.Commit()
            
            progress_window.close_progress()
            
            log("---")
            log("## ✔ Terminé")
            log("**Nomenclatures créées : {}**".format(created))
            log("**Nomenclatures configurées : {}**".format(created))
            
            message = u"{} nomenclatures créées et configurées.".format(created)
            show_xaml_message(message, title="Terminé")
        else:
            # Pas de source
            message = u"{} nomenclatures créées.\n\nAucune configuration transférée.".format(created)
            show_xaml_message(message, title="Terminé")
        
    except Exception:
        tb = traceback.format_exc()
        path = save_traceback(tb)
        if ACTIVER_LOGS:
            log("Erreur critique : {}".format(path or "n/a"))
            log("```python\n{}\n```".format(tb))
        show_alert("Erreur critique", "Une erreur est survenue. Voir error_traceback.txt.")

if __name__ == "__main__":
    main()