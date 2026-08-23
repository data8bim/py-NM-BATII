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


#__title__ = 'TRI/REGROUPEMENTS\npar copie'
#__doc__ = """Transfert les regroupements d'une nomenclature
#Description: Copie les tris/regroupements d'une nomenclature source vers les nomenclatures de destinations sélectionnées.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""

__author__ = 'Votre Nom'

import clr
import os
import sys
import codecs

clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

import System
from System.Windows.Markup import XamlReader
from System.Windows import Window

from Autodesk.Revit.DB import *
from pyrevit import revit, script

# -------------------------
# Configuration
# -------------------------
doc = revit.doc
script_dir = os.path.dirname(__file__)

# 🔥 Ajouter lib/ au sys.path
ext_dir = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# Import après ajout au sys.path
from utils.config_loader import load_config

# 🔥 Charger les styles personnalisés WPF
from dialogs.dialogs_styles_loader import load, show_alert
load(lib_dir=lib_dir)

# Gestion conditionnelle des logs
try:
    _config_global = load_config() or {}
    ACTIVER_LOGS = bool(_config_global.get("activer_logs_scripts", True))
except:
    ACTIVER_LOGS = True

if ACTIVER_LOGS:
    _output = script.get_output()

def log(msg):
    """Afficher un message dans les logs (si activé)"""
    if not ACTIVER_LOGS:
        return
    try:
        _output.print_md(msg)
    except:
        print(msg)

# -------------------------
# Classe WPFWindow
# -------------------------
class WPFWindow(Window):
    def __init__(self, xaml_file_name):
        pass

# -------------------------
# Fonctions utilitaires
# -------------------------
def get_all_schedules():
    """Recuperer toutes les nomenclatures (hors gabarits)"""
    collector = FilteredElementCollector(doc)
    schedules = collector.OfClass(ViewSchedule).ToElements()
    
    result = []
    for s in schedules:
        if s.IsTemplate:
            continue
        result.append(s)
    
    return sorted(result, key=lambda x: x.Name)

def get_schedule_display_name(schedule):
    """Obtenir le nom d'affichage d'une nomenclature"""
    try:
        cat_id = schedule.Definition.CategoryId
        if cat_id == ElementId.InvalidElementId or cat_id.IntegerValue == -1:
            cat_name = 'Autre'
        else:
            cat_elem = doc.GetElement(cat_id)
            cat_name = cat_elem.Name if cat_elem else 'Autre'
        
        # Ne pas afficher "(Autre)" - juste le nom
        if cat_name != 'Autre':
            return '{} ({})'.format(schedule.Name, cat_name)
        else:
            return schedule.Name
    except:
        return schedule.Name

def show_xaml_message(message, title='Information'):
    """Afficher un message avec ResultWindow"""
    try:
        result_window = ResultWindow(message)
        result_window.show()
    except:
        # Fallback : message simple
        show_alert(title, message)

# -------------------------
# Analyse et application des regroupements
# -------------------------
def analyze_sorts(schedule, doc):
    """Analyser tous les tris/regroupements d'une nomenclature"""
    log('## Analyse de: {}'.format(schedule.Name))
    
    result = {
        'sorts': [],
        'grand_total_settings': {}
    }
    
    defn = schedule.Definition
    
    # ANALYSER LES TRIS/REGROUPEMENTS
    sort_count = defn.GetSortGroupFieldCount()
    log('  {} tri(s)/regroupement(s)'.format(sort_count))
    
    for i in range(sort_count):
        sort_field = defn.GetSortGroupField(i)
        
        # Recuperer le champ associe
        field_id = sort_field.FieldId
        field = defn.GetField(field_id)
        param_id = field.ParameterId
        
        # Nom du parametre pour le log
        try:
            if param_id.IntegerValue < 0:
                bip = BuiltInParameter(param_id.IntegerValue)
                param_name = LabelUtils.GetLabelFor(bip)
            else:
                param_elem = doc.GetElement(param_id)
                param_name = param_elem.Name if param_elem else 'Param_{}'.format(param_id.IntegerValue)
        except:
            param_name = 'Unknown'
        
        sort_info = {
            'field_id': field_id,
            'param_id': param_id,
            'param_name': param_name,
            'sort_order': sort_field.SortOrder,
            'show_header': sort_field.ShowHeader,
            'show_footer': sort_field.ShowFooter,
            'show_blank_line': sort_field.ShowBlankLine
        }
        
        # Ajouter les propriétés du pied de page (ShowFooterTitle, ShowFooterCount)
        if hasattr(sort_field, 'ShowFooterTitle'):
            sort_info['show_footer_title'] = sort_field.ShowFooterTitle
        
        if hasattr(sort_field, 'ShowFooterCount'):
            sort_info['show_footer_count'] = sort_field.ShowFooterCount
        
        # Log avec toutes les propriétés
        log('    Tri {}: {} | Ordre={} | Header={} | Footer={} (Title={}, Count={}) | BlankLine={}'.format(
            i,
            param_name,
            'Croissant' if sort_field.SortOrder == ScheduleSortOrder.Ascending else 'Decroissant',
            sort_field.ShowHeader,
            sort_field.ShowFooter,
            sort_info.get('show_footer_title', 'N/A'),
            sort_info.get('show_footer_count', 'N/A'),
            sort_field.ShowBlankLine
        ))
        
        result['sorts'].append(sort_info)
    
    # ANALYSER LES PARAMETRES DE TOTAUX GENERAUX
    # Ces proprietes sont au niveau de ScheduleDefinition, pas au niveau du champ
    grand_total_settings = {}
    
    # ShowGrandTotal (afficher totaux generaux)
    if hasattr(defn, 'ShowGrandTotal'):
        grand_total_settings['show_grand_total'] = defn.ShowGrandTotal
        log('  Totaux generaux: {}'.format(defn.ShowGrandTotal))
    
    # ShowGrandTotalTitle (afficher titre des totaux)
    if hasattr(defn, 'ShowGrandTotalTitle'):
        grand_total_settings['show_grand_total_title'] = defn.ShowGrandTotalTitle
        log('  Afficher titre totaux: {}'.format(defn.ShowGrandTotalTitle))
    
    # ShowGrandTotalCount (afficher nombre dans totaux)
    if hasattr(defn, 'ShowGrandTotalCount'):
        grand_total_settings['show_grand_total_count'] = defn.ShowGrandTotalCount
        log('  Afficher nombre dans totaux: {}'.format(defn.ShowGrandTotalCount))
    
    # GrandTotalTitle (titre personnalise)
    if hasattr(defn, 'GrandTotalTitle'):
        grand_total_settings['grand_total_title'] = defn.GrandTotalTitle
        log('  Titre personnalise: "{}"'.format(defn.GrandTotalTitle))
    
    # IsItemized (detailler chaque occurrence)
    if hasattr(defn, 'IsItemized'):
        grand_total_settings['is_itemized'] = defn.IsItemized
        log('  Detailler chaque occurrence: {}'.format(defn.IsItemized))
    
    result['grand_total_settings'] = grand_total_settings
    
    return result

def apply_sorts(schedule, source_data, doc):
    """Appliquer les tris/regroupements a une nomenclature cible"""
    log('## Application sur: {}'.format(schedule.Name))
    
    defn = schedule.Definition
    
    # Creer un mapping ParamId -> FieldId pour cette nomenclature
    param_to_field = {}
    for i in range(defn.GetFieldCount()):
        field = defn.GetField(i)
        param_to_field[field.ParameterId] = field.FieldId
    
    sorts_added = 0
    sorts_skipped = 0
    
    # SUPPRIMER LES TRIS EXISTANTS
    existing_sort_count = defn.GetSortGroupFieldCount()
    if existing_sort_count > 0:
        log('  Suppression de {} tri(s) existant(s)...'.format(existing_sort_count))
        defn.ClearSortGroupFields()
    
    # APPLIQUER LES TRIS/REGROUPEMENTS
    log('  Application des nouveaux tris:')
    for sort_info in source_data['sorts']:
        param_id = sort_info['param_id']
        param_name = sort_info.get('param_name', 'Unknown')
        
        if param_id in param_to_field:
            target_field_id = param_to_field[param_id]
            
            try:
                # Creer le tri
                new_sort = ScheduleSortGroupField(target_field_id)
                new_sort.SortOrder = sort_info['sort_order']
                new_sort.ShowHeader = sort_info['show_header']
                new_sort.ShowFooter = sort_info['show_footer']
                new_sort.ShowBlankLine = sort_info['show_blank_line']
                
                # Appliquer ShowFooterTitle
                if 'show_footer_title' in sort_info:
                    if hasattr(new_sort, 'ShowFooterTitle'):
                        try:
                            new_sort.ShowFooterTitle = sort_info['show_footer_title']
                        except Exception as e:
                            log('    ! Erreur ShowFooterTitle: {}'.format(str(e)))
                
                # Appliquer ShowFooterCount
                if 'show_footer_count' in sort_info:
                    if hasattr(new_sort, 'ShowFooterCount'):
                        try:
                            new_sort.ShowFooterCount = sort_info['show_footer_count']
                        except Exception as e:
                            log('    ! Erreur ShowFooterCount: {}'.format(str(e)))
                
                # Ajouter le tri au ScheduleDefinition
                defn.AddSortGroupField(new_sort)
                
                # Log avec détails du pied de page
                if 'show_footer_title' in sort_info or 'show_footer_count' in sort_info:
                    log('    + Tri ajoute: {} (FooterTitle={}, FooterCount={})'.format(
                        param_name,
                        sort_info.get('show_footer_title', 'N/A'),
                        sort_info.get('show_footer_count', 'N/A')
                    ))
                else:
                    log('    + Tri ajoute: {}'.format(param_name))
                
                sorts_added += 1
            
            except Exception as e:
                log('    ! Erreur ajout tri {}: {}'.format(param_name, str(e)))
                sorts_skipped += 1
        else:
            log('    - Champ non trouve dans cible: {}'.format(param_name))
            sorts_skipped += 1
    
    # APPLIQUER LES PARAMETRES DE TOTAUX GENERAUX
    grand_total_settings = source_data.get('grand_total_settings', {})
    
    if grand_total_settings:
        log('  Application des parametres de totaux generaux:')
        
        # ShowGrandTotal
        if 'show_grand_total' in grand_total_settings:
            if hasattr(defn, 'ShowGrandTotal'):
                try:
                    defn.ShowGrandTotal = grand_total_settings['show_grand_total']
                    log('    + Totaux generaux: {}'.format(grand_total_settings['show_grand_total']))
                except Exception as e:
                    log('    ! Erreur ShowGrandTotal: {}'.format(str(e)))
        
        # ShowGrandTotalTitle
        if 'show_grand_total_title' in grand_total_settings:
            if hasattr(defn, 'ShowGrandTotalTitle'):
                try:
                    defn.ShowGrandTotalTitle = grand_total_settings['show_grand_total_title']
                    log('    + Afficher titre totaux: {}'.format(grand_total_settings['show_grand_total_title']))
                except Exception as e:
                    log('    ! Erreur ShowGrandTotalTitle: {}'.format(str(e)))
        
        # ShowGrandTotalCount
        if 'show_grand_total_count' in grand_total_settings:
            if hasattr(defn, 'ShowGrandTotalCount'):
                try:
                    defn.ShowGrandTotalCount = grand_total_settings['show_grand_total_count']
                    log('    + Afficher nombre dans totaux: {}'.format(grand_total_settings['show_grand_total_count']))
                except Exception as e:
                    log('    ! Erreur ShowGrandTotalCount: {}'.format(str(e)))
        
        # GrandTotalTitle
        if 'grand_total_title' in grand_total_settings:
            if hasattr(defn, 'GrandTotalTitle'):
                try:
                    defn.GrandTotalTitle = grand_total_settings['grand_total_title']
                    log('    + Titre personnalise: "{}"'.format(grand_total_settings['grand_total_title']))
                except Exception as e:
                    log('    ! Erreur GrandTotalTitle: {}'.format(str(e)))
        
        # IsItemized
        if 'is_itemized' in grand_total_settings:
            if hasattr(defn, 'IsItemized'):
                try:
                    defn.IsItemized = grand_total_settings['is_itemized']
                    log('    + Detailler chaque occurrence: {}'.format(grand_total_settings['is_itemized']))
                except Exception as e:
                    log('    ! Erreur IsItemized: {}'.format(str(e)))
    
    log('  ---')
    log('  Resultat: {} tris ajoutes, {} ignores'.format(sorts_added, sorts_skipped))
    return sorts_added

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
        
        self.lst_schedules = self.UI.FindName('lstSchedules')
        self.txt_search = self.UI.FindName('txtSearch')
        self.btn_ok = self.UI.FindName('btnOk')
        
        if not self.lst_schedules:
            raise Exception("lstSchedules introuvable dans le XAML")
        if not self.btn_ok:
            raise Exception("btnOk introuvable dans le XAML")
        
        self.all_schedules = schedules_list
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
            
            for item in self.all_schedules:
                if search_text == "" or search_text in item.lower():
                    self.lst_schedules.Items.Add(item)
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
            show_alert(u"Information", "Sélectionnez au moins une nomenclature cible")
            return
        
        self.selected_items = checked_names
        self.UI.Close()
    
    def show(self):
        self.UI.ShowDialog()
        return self.selected_items

# -------------------------
# Interface ResultWindow
# -------------------------
class ResultWindow(WPFWindow):
    def __init__(self, message):
        xaml_path = os.path.join(script_dir, 'ResultWindow.xaml')
        
        if not os.path.exists(xaml_path):
            raise Exception("ResultWindow.xaml introuvable dans {}".format(script_dir))
        
        try:
            with codecs.open(xaml_path, 'r', 'utf-8') as f:
                xaml = f.read()
            self.UI = XamlReader.Parse(xaml)
        except Exception as e:
            raise Exception("Erreur parsing XAML: {}".format(str(e)))
        
        self.txt_message = self.UI.FindName('txtMessage')
        self.btn_ok = self.UI.FindName('btnClose')  # Le bouton s'appelle btnClose dans le XAML
        
        if self.txt_message:
            self.txt_message.Text = message
        
        if self.btn_ok:
            self.btn_ok.Click += lambda s,e: self.UI.Close()
    
    def show(self):
        try:
            self.UI.ShowDialog()
        except:
            pass

# -------------------------
# Interface ProgressWindow
# -------------------------
class ProgressWindow(WPFWindow):
    def __init__(self, total):
        xaml_path = os.path.join(script_dir, 'ProgressWindow.xaml')

        if not os.path.exists(xaml_path):
            self.UI = None
            return

        try:
            with codecs.open(xaml_path, 'r', 'utf-8') as f:
                xaml = f.read()
            self.UI = XamlReader.Parse(xaml)
        except Exception:
            self.UI = None
            return

        self.progressBar = self.UI.FindName('progressBar')
        self.txtStatus   = self.UI.FindName('txtStatus')
        self.txtCurrent  = self.UI.FindName('txtCurrent')
        self.total = total

        if self.progressBar:
            self.progressBar.Maximum = total
            self.progressBar.Value   = 0
        if self.txtCurrent:
            self.txtCurrent.Text = '0 / {}'.format(total)

    def update(self, current, name):
        if self.UI is None:
            return
        try:
            from System.Windows.Threading import Dispatcher, DispatcherPriority
            if self.progressBar: self.progressBar.Value = current
            if self.txtStatus:   self.txtStatus.Text    = name
            if self.txtCurrent:  self.txtCurrent.Text   = '{} / {}'.format(current, self.total)
            Dispatcher.CurrentDispatcher.Invoke(
                DispatcherPriority.Background,
                System.Action(lambda: None)
            )
        except:
            pass

    def show(self):
        if self.UI is not None:
            self.UI.Show()

    def close(self):
        if self.UI is not None:
            try:
                self.UI.Close()
            except:
                pass
def main():
    log('# Copier regroupements de nomenclatures')
    log('---')
    
    # 1. Recuperer nomenclatures
    all_schedules = get_all_schedules()
    
    if not all_schedules:
        show_xaml_message('Aucune nomenclature trouvée dans le projet.', title='Erreur')
        return
    
    log('OK {} nomenclatures trouvees'.format(len(all_schedules)))
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
    source_data = analyze_sorts(source_schedule, doc)
    
    if not source_data['sorts']:
        show_xaml_message('Aucun tri/regroupement trouvé dans la nomenclature source !', title='Erreur')
        return
    
    log('---')
    
    # 5. Selectionner CIBLES (sans la source)
    target_display_list = []
    target_schedules_map = []
    
    for i, schedule in enumerate(all_schedules):
        if schedule.Id != source_schedule.Id:
            target_display_list.append(display_list[i])
            target_schedules_map.append(schedule)
    
    target_selector = ScheduleSelectorWindow(target_display_list)
    target_selection = target_selector.show()
    
    if not target_selection:
        return
    
    target_schedules = []
    for sel in target_selection:
        idx = target_display_list.index(sel)
        target_schedules.append(target_schedules_map[idx])
    
    if not target_schedules:
        show_xaml_message('Aucune nomenclature cible sélectionnée.', title='Erreur')
        return
    
    log('OK {} nomenclatures cibles'.format(len(target_schedules)))
    log('---')
    
    # 6. Appliquer les regroupements
    log('# Application des regroupements...')
    log('---')

    # Barre de progression
    progress = ProgressWindow(len(target_schedules))
    progress.show()

    t = Transaction(doc, 'Copier regroupements de nomenclatures')
    t.Start()

    success = 0
    errors  = 0

    for idx, target in enumerate(target_schedules):
        progress.update(idx + 1, target.Name)
        try:
            applied = apply_sorts(target, source_data, doc)
            if applied > 0:
                success += 1
            log('---')
        except Exception as e:
            log('ERREUR {}: {}'.format(target.Name, str(e)))
            log('---')
            errors += 1

    t.Commit()
    progress.close()
    
    # 7. Resume
    log('# Resume')
    log('Succes: {}'.format(success))
    if errors > 0:
        log('Erreurs: {}'.format(errors))
    
    # Message final simplifié
    message = '{} nomenclatures traitées'.format(success)
    show_xaml_message(message, title='Terminé')

if __name__ == '__main__':
    main()
