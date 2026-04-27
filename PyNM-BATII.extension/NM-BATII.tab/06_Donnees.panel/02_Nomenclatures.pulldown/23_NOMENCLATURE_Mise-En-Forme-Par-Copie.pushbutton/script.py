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


#__title__ = 'MISE EN FORME\npar copie'
#__doc__ = """Copier mise en forme des champs d'une nomenclature.
#Description: Copie les mises en forme des champs d'une nomenclature source vers les nomenclatures de destinations sélectionnées.
#ATTENTION : Ne copie pas les largeurs de colonnes, ni les paramètres calculés, ni paramètres combinés.

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
from System.IO import File
from System.Collections.Generic import List

import os
import sys
import codecs

from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

# -------------------------
# Chemins et loader
# -------------------------
script_dir = os.path.dirname(__file__)
ext_dir = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir, os.pardir))
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# Loader styles
try:
    from dialogs.dialogs_styles_loader import load as load_dialog_styles
    load_dialog_styles(lib_dir=lib_dir)
except Exception:
    pass

# Loader config
try:
    from utils.config_loader import load_config
except Exception:
    def load_config():
        return {}

# -------------------------
# Revit / logs
# -------------------------
doc = revit.doc

_cfg = load_config() or {}
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
        pass

# -------------------------
# Fonction show_xaml_message
# -------------------------
def show_xaml_message(message, title="Message"):
    xaml_path = os.path.join(script_dir, "ResultWindow.xaml")
    if not os.path.exists(xaml_path):
        forms.alert(message, title=title)
        return
    
    try:
        xaml_content = File.ReadAllText(xaml_path)
        window = XamlReader.Parse(xaml_content)
        window.Title = title
        txt_msg = window.FindName("txtMessage")
        btn = window.FindName("btnClose")
        if txt_msg is None or btn is None:
            forms.alert(message, title=title)
            return
        txt_msg.Text = message
        btn.Click += lambda s, e: window.Close()
        window.ShowDialog()
    except Exception:
        forms.alert(message, title=title)

# -------------------------
# Utilitaires
# -------------------------
def get_all_schedules():
    """Recuperer toutes les nomenclatures (pas les gabarits)."""
    collector = FilteredElementCollector(doc)
    schedules = collector.OfClass(ViewSchedule).ToElements()
    
    result = []
    for s in schedules:
        if s.IsTemplate:
            continue
        result.append(s)
    
    return sorted(result, key=lambda x: x.Name)

def get_schedule_display_name(schedule):
    """Obtenir le nom d'affichage avec la categorie."""
    try:
        cat_id = schedule.Definition.CategoryId
        if cat_id == ElementId.InvalidElementId or cat_id.IntegerValue == -1:
            cat_name = 'Autre'
        else:
            cat_elem = doc.GetElement(cat_id)
            cat_name = cat_elem.Name if cat_elem else 'Autre'
        return '{} ({})'.format(schedule.Name, cat_name)
    except:
        return '{} (Autre)'.format(schedule.Name)

# -------------------------
# Analyse et copie
# -------------------------
def analyze_field_formatting(schedule, doc):
    """Analyser tous les parametres de mise en forme des champs.

    CLE DE MATCHING : tuple (param_id_int, field_type_int)
    --------------------------------------------------------
    Dans Revit, le meme ParameterId peut apparaitre PLUSIEURS FOIS dans
    une nomenclature avec des FieldType differents. Exemples :
      - "LOC - BATIMENT - Code SEI"  (FieldType=Instance)
      - "LOC - BATIMENT - Code SEI"  (FieldType=RoomAssociation  ou Room)
    Ces deux champs ont le meme ParameterId.IntegerValue mais des
    FieldType differents. Le discriminant OBLIGATOIRE est donc le tuple
    (param_id_int, field_type_int).

    En IronPython, les objets ElementId ne sont PAS fiables comme cles
    de dict (hash base sur la reference objet, pas la valeur). On utilise
    donc les int natifs Python :
      - param_id_int  = field.ParameterId.IntegerValue
      - field_type_int = int(field.FieldType)

    Si ce tuple reste en doublon (tres rare), on conserve une file (liste)
    et on consomme dans l'ordre lors de l'application.
    """
    log('## Analyse de: {}'.format(schedule.Name))

    result = {}   # (param_id_int, field_type_int) -> [field_format, ...]
    defn   = schedule.Definition

    log('  {} champ(s)'.format(defn.GetFieldCount()))

    for i in range(defn.GetFieldCount()):
        field        = defn.GetField(i)
        param_id     = field.ParameterId
        param_id_int = param_id.IntegerValue
        field_type_int = int(field.FieldType)
        compound_key   = (param_id_int, field_type_int)

        field_format = {
            'compound_key':        compound_key,
            'index':               i,
            'column_heading':      field.ColumnHeading,
            'heading_orientation': field.HeadingOrientation,
            'horizontal_alignment':field.HorizontalAlignment,
            'is_hidden':           field.IsHidden,
            'field_type':          field.FieldType,
            'display_type':        field.DisplayType,
        }

        # Valeurs multiples
        try:
            field_format['can_allow_overrides'] = (
                field.CanAllowOverrides() if hasattr(field, 'CanAllowOverrides') else None)
        except:
            field_format['can_allow_overrides'] = None

        try:
            field_format['multiple_values_behavior'] = (
                field.GetMultipleValuesBehavior() if hasattr(field, 'GetMultipleValuesBehavior') else None)
        except:
            field_format['multiple_values_behavior'] = None

        try:
            field_format['multiple_values_text'] = (
                field.GetMultipleValuesText() if hasattr(field, 'GetMultipleValuesText') else None)
        except:
            field_format['multiple_values_text'] = None

        # FormatOptions
        try:
            fmt_opts = field.GetFormatOptions()
            if fmt_opts:
                fo = {
                    'use_default':             fmt_opts.UseDefault,
                    'accuracy':                fmt_opts.Accuracy,
                    'rounding_method':         fmt_opts.RoundingMethod,
                    'suppress_leading_zeros':  fmt_opts.SuppressLeadingZeros,
                    'suppress_trailing_zeros': fmt_opts.SuppressTrailingZeros,
                    'suppress_spaces':         fmt_opts.SuppressSpaces,
                    'use_digit_grouping':      fmt_opts.UseDigitGrouping,
                    'use_plus_prefix':         fmt_opts.UsePlusPrefix,
                    'rounding_increment':      None,
                    'unit_type_id':            None,
                    'symbol_type_id':          None,
                }
                try:
                    if hasattr(fmt_opts, 'RoundingIncrement'):
                        fo['rounding_increment'] = fmt_opts.RoundingIncrement
                except: pass
                try:
                    fo['unit_type_id'] = fmt_opts.GetUnitTypeId()
                except: pass
                try:
                    fo['symbol_type_id'] = fmt_opts.GetSymbolTypeId()
                except: pass
                field_format['format_options'] = fo
            else:
                field_format['format_options'] = None
        except:
            field_format['format_options'] = None

        # Nom lisible pour les logs
        try:
            if param_id_int < 0:
                bip = BuiltInParameter(param_id_int)
                param_name = LabelUtils.GetLabelFor(bip)
            else:
                param_elem = doc.GetElement(param_id)
                param_name = param_elem.Name if param_elem else 'Param_{}'.format(param_id_int)
        except:
            param_name = 'Unknown'

        field_format['param_name'] = param_name

        # Stockage : liste par cle composee pour gerer les rares doublons
        if compound_key not in result:
            result[compound_key] = []
        result[compound_key].append(field_format)

        log('    [{}] key={} | {} | En-tete="{}" | Align={} | Cache={}'.format(
            i, compound_key, param_name,
            field.ColumnHeading, field.HorizontalAlignment, field.IsHidden
        ))

    return result

def apply_field_formatting(schedule, source_formatting, doc):
    """Appliquer la mise en forme aux champs d'une nomenclature cible.

    source_formatting : dict  (param_id_int, field_type_int) -> [field_format, ...]
    Matching par cle composee (param_id_int, field_type_int) pour distinguer
    correctement les champs Instance des champs RoomAssociation qui partagent
    le meme ParameterId.
    """
    log('## Application sur: {}'.format(schedule.Name))

    # Copie locale des files pour ne pas alterer la source entre plusieurs cibles
    queues = {}
    for key, lst in source_formatting.items():
        queues[key] = list(lst)

    defn            = schedule.Definition
    fields_updated  = 0
    headings_copied = 0
    fields_skipped  = 0

    for i in range(defn.GetFieldCount()):
        field          = defn.GetField(i)
        param_id_int   = field.ParameterId.IntegerValue
        field_type_int = int(field.FieldType)
        compound_key   = (param_id_int, field_type_int)

        if compound_key in queues and queues[compound_key]:
            source_format = queues[compound_key].pop(0)
            param_name    = source_format.get('param_name', 'Unknown')

            log('  [{}] {} | key={}'.format(i, param_name, compound_key))

            # ── En-tete : bloc ISOLE pour garantir la copie quoi qu'il arrive ──
            try:
                src_heading = source_format.get('column_heading', '')
                # Conversion explicite en str Python au cas ou c'est un System.String
                src_heading_str = str(src_heading) if src_heading is not None else ''
                field.ColumnHeading = src_heading_str
                headings_copied += 1
                log('    + En-tete : "{}" -> "{}"'.format(
                    src_heading_str, field.ColumnHeading))
            except Exception as e:
                log('    ! Erreur En-tete : {}'.format(str(e)))

            # ── Autres proprietes de mise en forme ──
            try:
                field.HeadingOrientation  = source_format['heading_orientation']
                field.HorizontalAlignment = source_format['horizontal_alignment']
                field.IsHidden            = source_format['is_hidden']

                try:
                    field.DisplayType = source_format['display_type']
                except Exception as e:
                    log('    ! DisplayType : {}'.format(str(e)))

                try:
                    if source_format.get('can_allow_overrides') is not None:
                        if hasattr(field, 'SetCanAllowOverrides'):
                            field.SetCanAllowOverrides(source_format['can_allow_overrides'])
                except: pass

                try:
                    if source_format.get('multiple_values_behavior') is not None:
                        if hasattr(field, 'SetMultipleValuesBehavior'):
                            field.SetMultipleValuesBehavior(source_format['multiple_values_behavior'])
                except: pass

                try:
                    if source_format.get('multiple_values_text') is not None:
                        if hasattr(field, 'SetMultipleValuesText'):
                            field.SetMultipleValuesText(source_format['multiple_values_text'])
                            log('    + MultipleValuesText: "{}"'.format(source_format['multiple_values_text']))
                except: pass

                # FormatOptions
                if source_format.get('format_options'):
                    try:
                        cur_fmt    = field.GetFormatOptions()
                        source_fmt = source_format['format_options']

                        cur_fmt.UseDefault = source_fmt['use_default']

                        if not source_fmt['use_default']:
                            cur_fmt.Accuracy       = source_fmt['accuracy']
                            cur_fmt.RoundingMethod = source_fmt['rounding_method']

                            if source_fmt.get('rounding_increment') is not None:
                                try:
                                    if hasattr(cur_fmt, 'RoundingIncrement'):
                                        cur_fmt.RoundingIncrement = source_fmt['rounding_increment']
                                except: pass

                            cur_fmt.SuppressLeadingZeros  = source_fmt['suppress_leading_zeros']
                            cur_fmt.SuppressTrailingZeros = source_fmt['suppress_trailing_zeros']
                            cur_fmt.SuppressSpaces        = source_fmt['suppress_spaces']
                            cur_fmt.UseDigitGrouping      = source_fmt['use_digit_grouping']
                            cur_fmt.UsePlusPrefix         = source_fmt['use_plus_prefix']

                            if source_fmt.get('unit_type_id'):
                                try: cur_fmt.SetUnitTypeId(source_fmt['unit_type_id'])
                                except: pass
                            if source_fmt.get('symbol_type_id'):
                                try: cur_fmt.SetSymbolTypeId(source_fmt['symbol_type_id'])
                                except: pass

                        field.SetFormatOptions(cur_fmt)
                        log('    + FormatOptions appliquees')
                    except Exception as e:
                        log('    ! Erreur FormatOptions : {}'.format(str(e)))

                fields_updated += 1

            except Exception as e:
                log('    ! ERREUR champ [{}] : {}'.format(i, str(e)))
                fields_skipped += 1

        else:
            log('  [{}] key={} absent dans la source - ignore'.format(i, compound_key))
            fields_skipped += 1

    log('  ---')
    log('  {} champs mis a jour | {} en-tetes copies | {} ignores'.format(
        fields_updated, headings_copied, fields_skipped))
    return fields_updated, headings_copied

# -------------------------
# Interface SourceScheduleSelector
# -------------------------
class SourceScheduleSelectorWindow(WPFWindow):
    def __init__(self, schedules_list):
        xaml_path = os.path.join(script_dir, 'SourceScheduleSelector.xaml')
        
        if not os.path.exists(xaml_path):
            raise Exception("SourceScheduleSelector.xaml introuvable dans {}".format(script_dir))
        
        try:
            with codecs.open(xaml_path, 'r', 'utf-8') as f:
                xaml = f.read()
            self.UI = XamlReader.Parse(xaml)
        except Exception as e:
            raise Exception("Erreur parsing XAML: {}".format(str(e)))
        
        # FindName avec verification
        self.lst_schedules = self.UI.FindName('lstSchedules')
        self.txt_search = self.UI.FindName('txtSearch')
        self.btn_ok = self.UI.FindName('btnOk')
        
        if not self.lst_schedules:
            raise Exception("lstSchedules introuvable dans le XAML")
        if not self.btn_ok:
            raise Exception("btnOk introuvable dans le XAML")
        
        self.all_schedules = schedules_list
        self.filtered_schedules = list(schedules_list)
        self.selected_item = None
        
        for item in schedules_list:
            self.lst_schedules.Items.Add(item)
        
        if self.txt_search:
            self.txt_search.TextChanged += self._on_search
        
        self.btn_ok.Click += self._on_ok
    
    def _on_search(self, sender, args):
        try:
            search_text = self.txt_search.Text.lower()
            selected = self.lst_schedules.SelectedItem
            
            self.lst_schedules.Items.Clear()
            self.filtered_schedules = []
            
            for item in self.all_schedules:
                if search_text == "" or search_text in item.lower():
                    self.lst_schedules.Items.Add(item)
                    self.filtered_schedules.append(item)
                    if item == selected:
                        self.lst_schedules.SelectedItem = item
        except:
            pass
    
    def _on_ok(self, sender, args):
        self.selected_item = self.lst_schedules.SelectedItem
        self.UI.Close()
    
    def show(self):
        self.UI.ShowDialog()
        return self.selected_item

# -------------------------
# Interface ScheduleSelector (cibles)
# -------------------------
# -------------------------
# Interface ScheduleSelector (cibles) - PATTERN CHECKBOX MANUEL
# -------------------------
class ScheduleSelectorWindow(WPFWindow):
    def __init__(self, schedules_list):
        xaml_path = os.path.join(script_dir, 'ScheduleSelector.xaml')
        
        if not os.path.exists(xaml_path):
            raise Exception("ScheduleSelector.xaml introuvable dans {}".format(script_dir))
        
        try:
            with codecs.open(xaml_path, 'r', 'utf-8') as f:
                xaml = f.read()
            self.UI = XamlReader.Parse(xaml)
        except Exception as e:
            raise Exception("Erreur parsing XAML: {}".format(str(e)))
        
        # FindName avec verification
        self.lst_schedules = self.UI.FindName('lstSchedules')
        self.txt_search = self.UI.FindName('txtSearch')
        self.btn_check_all = self.UI.FindName('btnCheckAll')
        self.btn_uncheck_all = self.UI.FindName('btnUncheckAll')
        self.btn_toggle_all = self.UI.FindName('btnToggleAll')
        self.btn_ok = self.UI.FindName('btnOk')
        
        if not self.lst_schedules:
            raise Exception("lstSchedules introuvable dans le XAML")
        if not self.btn_ok:
            raise Exception("btnOk introuvable dans le XAML")
        
        # Liste de tuples (CheckBox, nom) - PATTERN MANUEL
        self.sched_checkboxes = []
        self.schedule_names = schedules_list
        self.last_selected_idx = -1
        self.selected_items = []
        
        # Créer les CheckBox manuellement
        from System.Windows import Thickness
        
        for name in schedules_list:
            cb = System.Windows.Controls.CheckBox()
            cb.Content = name
            cb.Margin = Thickness(0, 2, 0, 2)
            cb.IsChecked = False
            
            self.sched_checkboxes.append((cb, name))
            self.lst_schedules.Items.Add(cb)
        
        # Events
        if self.txt_search:
            self.txt_search.TextChanged += self._on_search
        
        if self.btn_check_all:
            self.btn_check_all.Click += lambda s, e: self._select_all(True)
        if self.btn_uncheck_all:
            self.btn_uncheck_all.Click += lambda s, e: self._select_all(False)
        if self.btn_toggle_all:
            self.btn_toggle_all.Click += lambda s, e: self._toggle_all()
        
        self.btn_ok.Click += self._on_ok
        
        # CTRL+MAJ+clic
        self.lst_schedules.PreviewMouseLeftButtonDown += self._on_mouse_down
    
    def _select_all(self, value):
        """Cocher/décocher toutes les checkboxes VISIBLES."""
        for i in range(self.lst_schedules.Items.Count):
            cb = self.lst_schedules.Items[i]
            try:
                cb.IsChecked = value
            except:
                pass
    
    def _toggle_all(self):
        """Inverser toutes les checkboxes VISIBLES."""
        for i in range(self.lst_schedules.Items.Count):
            cb = self.lst_schedules.Items[i]
            try:
                cb.IsChecked = not (cb.IsChecked == True)
            except:
                pass
    
    def _on_search(self, sender, args):
        """Filtrer la liste, en conservant les sélections."""
        try:
            search_text = self.txt_search.Text.lower()
            
            # Sauvegarder les noms cochés
            checked_names = set()
            for cb, name in self.sched_checkboxes:
                if cb.IsChecked == True:
                    checked_names.add(name)
            
            # Filtrer
            self.lst_schedules.Items.Clear()
            for cb, name in self.sched_checkboxes:
                if search_text == "" or search_text in name.lower():
                    # Restaurer l'état coché
                    cb.IsChecked = name in checked_names
                    self.lst_schedules.Items.Add(cb)
        except:
            pass
    
    def _on_mouse_down(self, sender, args):
        """Gérer CTRL+clic et MAJ+clic."""
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper
        
        try:
            clicked_item = args.OriginalSource
            current = clicked_item
            clicked_index = -1
            
            while current is not None:
                if hasattr(current, "__class__") and current.__class__.__name__ == "ListBoxItem":
                    clicked_index = self.lst_schedules.ItemContainerGenerator.IndexFromContainer(current)
                    break
                try:
                    current = VisualTreeHelper.GetParent(current)
                except:
                    break
            
            if clicked_index < 0 or clicked_index >= self.lst_schedules.Items.Count:
                return
            
            clicked_cb = self.lst_schedules.Items[clicked_index]
            
        except:
            return
        
        # CTRL+clic : toggle uniquement la checkbox cliquée
        if Keyboard.IsKeyDown(Key.LeftCtrl) or Keyboard.IsKeyDown(Key.RightCtrl):
            try:
                clicked_cb.IsChecked = not (clicked_cb.IsChecked == True)
                self.last_selected_idx = clicked_index
                args.Handled = True
            except:
                pass
            return
        
        # MAJ+clic : cocher/décocher une plage
        if Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift):
            try:
                last = self.last_selected_idx if self.last_selected_idx >= 0 else 0
                start = min(last, clicked_index)
                end = max(last, clicked_index)
                target_state = not (clicked_cb.IsChecked == True)
                for i in range(start, end + 1):
                    if i < self.lst_schedules.Items.Count:
                        self.lst_schedules.Items[i].IsChecked = target_state
                self.last_selected_idx = clicked_index
                args.Handled = True
            except:
                pass
            return
        
        # Clic normal : mettre à jour le dernier index
        try:
            self.last_selected_idx = clicked_index
        except:
            pass
    
    def _on_ok(self, sender, args):
        # Récupérer les noms cochés
        checked_names = []
        for cb, name in self.sched_checkboxes:
            if cb.IsChecked == True:
                checked_names.append(name)
        
        if not checked_names:
            from pyrevit import forms
            forms.alert("Sélectionnez au moins une nomenclature cible")
            return
        
        self.selected_items = checked_names
        self.UI.Close()
    
    def show(self):
        self.UI.ShowDialog()
        return self.selected_items

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
            except:
                pass
    
    def close_progress(self):
        if self.UI:
            try:
                self.UI.Close()
            except:
                pass

# -------------------------
# Interface WarningWindow
# -------------------------
class WarningWindow(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(script_dir, 'WarningWindow.xaml')
        
        if not os.path.exists(xaml_path):
            raise Exception("WarningWindow.xaml introuvable dans {}".format(script_dir))
        
        try:
            with codecs.open(xaml_path, 'r', 'utf-8') as f:
                xaml = f.read()
            self.UI = XamlReader.Parse(xaml)
        except Exception as e:
            raise Exception("Erreur parsing XAML: {}".format(str(e)))
        
        self.btn_continuer = self.UI.FindName('btnContinuer')
        self.btn_annuler = self.UI.FindName('btnAnnuler')
        
        self.user_continued = False
        
        if self.btn_continuer:
            self.btn_continuer.Click += self._on_continuer
        
        if self.btn_annuler:
            self.btn_annuler.Click += self._on_annuler
    
    def _on_continuer(self, sender, args):
        self.user_continued = True
        self.UI.Close()
    
    def _on_annuler(self, sender, args):
        self.user_continued = False
        self.UI.Close()
    
    def show(self):
        try:
            self.UI.ShowDialog()
            return self.user_continued
        except:
            return True  # En cas d'erreur, continuer quand meme

# -------------------------
# Main
# -------------------------
def main():
    log('# Copier mise en forme des champs')
    log('---')
    
    # 1. Recuperer nomenclatures
    all_schedules = get_all_schedules()
    
    if not all_schedules:
        show_xaml_message('Aucune nomenclature trouvée dans le projet.', title='Erreur')
        return
    
    log('OK {} nomenclatures trouvees'.format(len(all_schedules)))
    log('---')
    
    # AVERTISSEMENT - Parametres non copies
    try:
        warning_window = WarningWindow()
        user_continued = warning_window.show()
        
        if not user_continued:
            log('Script annule par l\'utilisateur')
            return
    except Exception as e:
        log('Erreur affichage avertissement: {}'.format(str(e)))
        # Si erreur, continuer quand meme
        pass
    
    log('---')
    
    # 2. Preparer affichage
    display_list = [get_schedule_display_name(s) for s in all_schedules]
    
    # 3. Selectionner SOURCE
    source_selector = SourceScheduleSelectorWindow(display_list)
    source_selection = source_selector.show()
    
    if not source_selection:
        return
    
    source_schedule = all_schedules[display_list.index(source_selection)]
    log('SOURCE: {}'.format(source_schedule.Name))
    log('---')
    
    # 4. Analyser source
    source_formatting = analyze_field_formatting(source_schedule, doc)
    
    if not source_formatting:
        show_xaml_message('Aucun champ trouvé dans la nomenclature source !', title='Erreur')
        return
    
    log('---')
    
    # 5. Selectionner CIBLES (sans la source)
    target_display_list = [d for i, d in enumerate(display_list) if all_schedules[i].Id != source_schedule.Id]
    target_schedules_map = [s for s in all_schedules if s.Id != source_schedule.Id]
    
    target_selector = ScheduleSelectorWindow(target_display_list)
    target_selection = target_selector.show()
    
    if not target_selection:
        return
    
    target_schedules = [target_schedules_map[target_display_list.index(sel)] for sel in target_selection]
    
    if not target_schedules:
        show_xaml_message('Aucune nomenclature cible sélectionnée.', title='Erreur')
        return
    
    log('OK {} nomenclatures cibles'.format(len(target_schedules)))
    log('---')
    
    # 6. Barre de progression
    progress_window = ProgressWindow(len(target_schedules))
    progress_window.show_progress()
    
    # 7. Appliquer
    log('# Application de la mise en forme...')
    log('---')
    
    t = Transaction(doc, 'Copier mise en forme champs')
    t.Start()
    
    success        = 0
    errors         = 0
    total_headings = 0

    for idx, target in enumerate(target_schedules):
        try:
            progress_window.update_progress(idx + 1, target.Name)

            updated, headings = apply_field_formatting(target, source_formatting, doc)
            if updated > 0:
                success += 1
            total_headings += headings
            log('---')
        except Exception as e:
            log('ERREUR {}: {}'.format(target.Name, str(e)))
            log('---')
            errors += 1
    
    t.Commit()
    progress_window.close_progress()
    
    # 8. Resume
    log('# Resume')
    log('Nomenclatures mises a jour : {}'.format(success))
    log('En-tetes copies au total   : {}'.format(total_headings))
    if errors > 0:
        log('Erreurs : {}'.format(errors))

    message = u'{} nomenclature(s) mise(s) à jour !\n{} en-tête(s) copié(s).'.format(
        success, total_headings)
    if errors > 0:
        message += u'\n{} erreur(s) — voir les logs pyRevit.'.format(errors)

    show_xaml_message(message, title='Terminé')

if __name__ == '__main__':
    main()
