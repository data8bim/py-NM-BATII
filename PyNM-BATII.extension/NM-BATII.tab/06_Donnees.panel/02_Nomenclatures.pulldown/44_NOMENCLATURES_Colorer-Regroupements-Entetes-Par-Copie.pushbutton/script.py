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


#__title__ = "Colorer REGROUPEMENTS ENTETES\npar copie"
#__doc__ = """Copier couleurs des regroupements d'entetes
#Description : Copie les couleurs appliquees aux regroupements d’une nomenclature source vers les nomenclatures de destinations sélectionnées.

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
from System.Windows.Threading import Dispatcher, DispatcherPriority

import os, sys, codecs, traceback

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB import TableCellStyle, TableCellStyleOverrideOptions
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

try:
    from dialogs.dialogs_styles_loader import load as load_dialog_styles
    load_dialog_styles(lib_dir=lib_dir)
except:
    pass

# Loader config
try:
    from utils.config_loader import load_config
except Exception:
    def load_config():
        return {}

doc = revit.doc

# Gestion des logs selon préférences utilisateur
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
    pass

_output = None
if ACTIVER_LOGS:
    try:
        _output = script.get_output()
    except:
        pass

def log(msg):
    """Affiche les logs uniquement si activé dans le JSON."""
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
        return None

# -------------------------
# Fonctions utilitaires (copiées de copier_couleurs.py)
# -------------------------
def get_all_schedules():
    return [s for s in FilteredElementCollector(doc).OfClass(ViewSchedule) if not s.IsTemplate]

def show_xaml_message(message, title="Information"):
    try:
        xaml_path = os.path.join(script_dir, "ResultWindow.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            ui = XamlReader.Parse(f.read())
        ui.Title = title
        ui.FindName("txtMessage").Text = message
        ui.FindName("btnClose").Click += lambda s, e: ui.Close()
        ui.ShowDialog()
    except:
        forms.alert(message, title=title)

def get_cell_color(body_section, row, col):
    """Récupère la couleur d'une cellule."""
    try:
        cell_style = body_section.GetTableCellStyle(row, col)
        if cell_style:
            options = cell_style.GetCellStyleOverrideOptions()
            if options.BackgroundColor:
                return cell_style.BackgroundColor
    except:
        pass
    return None

def analyze_source_schedule(schedule):
    """
    Analyser la nomenclature source et extraire les couleurs de regroupements.
    COPIE EXACTE de la logique de copier_couleurs.py
    """
    log("## Analyse de la source : {}".format(schedule.Name))
    
    result = {
        'header_text_colors': {},
        'num_header_rows': 0
    }
    
    try:
        table_data = schedule.GetTableData()
        body_section = table_data.GetSectionData(SectionType.Body)
        
        num_cols = body_section.NumberOfColumns
        first_row = body_section.FirstRowNumber
        
        # Détecter les lignes d'en-têtes
        max_rows_to_check = min(10, body_section.NumberOfRows)
        header_rows = []
        
        for row in range(first_row, first_row + max_rows_to_check):
            cell_type = body_section.GetCellType(row, 0)
            if cell_type == CellType.ParameterText:
                break
            header_rows.append(row)
        
        result['num_header_rows'] = len(header_rows)
        log("  {} ligne(s) d'en-têtes détectées".format(len(header_rows)))
        
        if len(header_rows) == 0:
            log("  ATTENTION: Aucune ligne d'en-tête trouvée !")
            return result
        
        # Récupérer les couleurs des regroupements (lignes précédentes)
        # LOGIQUE EXACTE de copier_couleurs.py
        if len(header_rows) > 1:
            log("  Analyse des regroupements :")
            
            for row in header_rows[:-1]:  # Toutes sauf la dernière
                for col in range(num_cols):
                    try:
                        text = body_section.GetCellText(row, col)
                        if text and text.strip():
                            color = get_cell_color(body_section, row, col)
                            if color:
                                result['header_text_colors'][text.strip()] = color
                                log('    "{}" - R:{} G:{} B:{}'.format(
                                    text.strip(), color.Red, color.Green, color.Blue
                                ))
                    except:
                        pass
        
        log("  **Total : {} couleurs de regroupements**".format(
            len(result['header_text_colors'])
        ))
    
    except Exception as e:
        log("  ERREUR analyse : {}".format(str(e)))
    
    return result

def apply_colors_to_schedule(schedule, source_colors):
    """
    Appliquer les couleurs de regroupements à une nomenclature cible.
    COPIE EXACTE de la logique de copier_couleurs.py
    """
    log("## Application sur : {}".format(schedule.Name))
    
    try:
        table_data = schedule.GetTableData()
        body_section = table_data.GetSectionData(SectionType.Body)
        
        num_cols = body_section.NumberOfColumns
        first_row = body_section.FirstRowNumber
        
        # Détecter lignes d'en-têtes
        max_rows_to_check = min(10, body_section.NumberOfRows)
        header_rows = []
        
        for row in range(first_row, first_row + max_rows_to_check):
            cell_type = body_section.GetCellType(row, 0)
            if cell_type == CellType.ParameterText:
                break
            header_rows.append(row)
        
        if len(header_rows) == 0:
            log("  ATTENTION: Aucune ligne d'en-tête trouvée")
            return 0
        
        log("  {} ligne(s) d'en-têtes détectées".format(len(header_rows)))
        
        cells_colored = 0
        
        # Appliquer couleurs des regroupements (lignes précédentes)
        # LOGIQUE EXACTE de copier_couleurs.py
        if len(header_rows) > 1 and source_colors['header_text_colors']:
            log("  Application regroupements :")
            
            for row in header_rows[:-1]:
                for col in range(num_cols):
                    try:
                        text = body_section.GetCellText(row, col)
                        if text and text.strip() in source_colors['header_text_colors']:
                            color = source_colors['header_text_colors'][text.strip()]
                            
                            if body_section.AllowOverrideCellStyle(row, col):
                                cell_style = TableCellStyle()
                                options = TableCellStyleOverrideOptions()
                                options.BackgroundColor = True
                                cell_style.SetCellStyleOverrideOptions(options)
                                cell_style.BackgroundColor = color
                                
                                body_section.SetCellStyle(row, col, cell_style)
                                cells_colored += 1
                                
                                log('    "{}" - Coloré'.format(text.strip()))
                    except:
                        pass
        
        log("  **Total : {} cellules colorées**".format(cells_colored))
        return cells_colored
    
    except Exception as e:
        log("  ERREUR : {}".format(str(e)))
        return 0

# -------------------------
# Interface : Sélection SOURCE
# -------------------------
class SourceScheduleWindow(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(script_dir, "SourceScheduleSelector.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())
        
        self.lstSchedules = self.UI.FindName("lstSchedules")
        self.txtSearch = self.UI.FindName("txtSearch")
        self.btnOk = self.UI.FindName("btnOk")
        
        self.all_schedules = []
        self.result = None
        
        schedules = get_all_schedules()
        schedules.sort(key=lambda s: s.Name)
        self.all_schedules = schedules
        
        for sched in schedules:
            self.lstSchedules.Items.Add(sched.Name)
        
        self.btnOk.Click += self._on_ok
        
        if self.txtSearch:
            self.txtSearch.TextChanged += self._on_search
    
    def _on_search(self, sender, args):
        text = self.txtSearch.Text.lower()
        selected_index = self.lstSchedules.SelectedIndex
        selected_name = None
        if selected_index >= 0 and selected_index < len(self.all_schedules):
            selected_name = self.all_schedules[selected_index].Name
        
        self.lstSchedules.Items.Clear()
        new_index = -1
        for idx, sched in enumerate(self.all_schedules):
            if not text or text in sched.Name.lower():
                self.lstSchedules.Items.Add(sched.Name)
                if selected_name and sched.Name == selected_name:
                    new_index = self.lstSchedules.Items.Count - 1
        
        if new_index >= 0:
            self.lstSchedules.SelectedIndex = new_index
    
    def _on_ok(self, sender, args):
        if self.lstSchedules.SelectedIndex < 0:
            forms.alert("Sélectionnez une nomenclature source")
            return
        
        selected_name = self.lstSchedules.SelectedItem
        for sched in self.all_schedules:
            if sched.Name == selected_name:
                self.result = sched
                break
        
        self.UI.Close()
    
    def show_dialog(self):
        self.UI.ShowDialog()
        return self.result

# -------------------------
# Interface : Sélection DESTINATIONS
# -------------------------
class DestinationSchedulesWindow(WPFWindow):
    def __init__(self, source):
        self.source = source
        xaml_path = os.path.join(script_dir, "DestinationScheduleSelector.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())
        
        self.lstSchedules = self.UI.FindName("lstSchedules")
        self.txtSearch = self.UI.FindName("txtSearch")
        self.btnCheckAll = self.UI.FindName("btnCheckAll")
        self.btnUncheckAll = self.UI.FindName("btnUncheckAll")
        self.btnToggleAll = self.UI.FindName("btnToggleAll")
        self.btnOk = self.UI.FindName("btnOk")
        
        # Liste de tuples (CheckBox, schedule) — pattern du script "Grouper En-têtes"
        self.sched_checkboxes = []
        self.all_schedules = []
        self.last_selected_idx = -1
        self.result = None
        
        schedules = get_all_schedules()
        schedules.sort(key=lambda s: s.Name)
        
        for sched in schedules:
            if sched.Id == source.Id:
                continue
            self.all_schedules.append(sched)
            
            # Créer une CheckBox pour cette nomenclature
            cb = System.Windows.Controls.CheckBox()
            cb.Content = sched.Name
            cb.Margin = System.Windows.Thickness(0, 2, 0, 2)
            cb.IsChecked = False
            
            self.sched_checkboxes.append((cb, sched))
            self.lstSchedules.Items.Add(cb)
        
        # Boutons
        if self.btnCheckAll:
            self.btnCheckAll.Click += lambda s, e: self._select_all(True)
        if self.btnUncheckAll:
            self.btnUncheckAll.Click += lambda s, e: self._select_all(False)
        if self.btnToggleAll:
            self.btnToggleAll.Click += lambda s, e: self._toggle_all()
        if self.btnOk:
            self.btnOk.Click += self._on_ok
        
        # Recherche
        if self.txtSearch:
            self.txtSearch.TextChanged += self._on_search
        
        # CTRL+clic et MAJ+clic — pattern du script "Grouper En-têtes"
        self.lstSchedules.PreviewMouseLeftButtonDown += self._on_mouse_down
    
    def _select_all(self, value):
        """Cocher/décocher toutes les checkboxes VISIBLES."""
        for i in range(self.lstSchedules.Items.Count):
            cb = self.lstSchedules.Items[i]
            try:
                cb.IsChecked = value
            except:
                pass
    
    def _toggle_all(self):
        """Inverser toutes les checkboxes VISIBLES."""
        for i in range(self.lstSchedules.Items.Count):
            cb = self.lstSchedules.Items[i]
            try:
                cb.IsChecked = not cb.IsChecked
            except:
                pass
    
    def _on_search(self, sender, args):
        """Filtrer la liste selon le texte, en conservant les sélections."""
        text = self.txtSearch.Text.lower()
        
        # Sauvegarder les noms cochés
        checked_names = set()
        for cb, sched in self.sched_checkboxes:
            if cb.IsChecked:
                checked_names.add(sched.Name)
        
        self.lstSchedules.Items.Clear()
        for cb, sched in self.sched_checkboxes:
            if not text or text in sched.Name.lower():
                # Restaurer l'état coché
                cb.IsChecked = sched.Name in checked_names
                self.lstSchedules.Items.Add(cb)
    
    def _on_mouse_down(self, sender, args):
        """Gérer CTRL+clic et MAJ+clic — identique au script 'Grouper En-têtes'."""
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper
        
        try:
            clicked_item = args.OriginalSource
            current = clicked_item
            clicked_index = -1
            
            while current is not None:
                if hasattr(current, "__class__") and current.__class__.__name__ == "ListBoxItem":
                    clicked_index = self.lstSchedules.ItemContainerGenerator.IndexFromContainer(current)
                    break
                try:
                    current = VisualTreeHelper.GetParent(current)
                except:
                    break
            
            if clicked_index < 0 or clicked_index >= self.lstSchedules.Items.Count:
                return
            
            clicked_cb = self.lstSchedules.Items[clicked_index]
            
        except:
            return
        
        # CTRL+clic : toggle uniquement la checkbox cliquée
        if Keyboard.IsKeyDown(Key.LeftCtrl) or Keyboard.IsKeyDown(Key.RightCtrl):
            try:
                clicked_cb.IsChecked = not clicked_cb.IsChecked
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
                target_state = not clicked_cb.IsChecked
                for i in range(start, end + 1):
                    if i < self.lstSchedules.Items.Count:
                        self.lstSchedules.Items[i].IsChecked = target_state
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
        checked_names = set()
        for cb, sched in self.sched_checkboxes:
            if cb.IsChecked:
                checked_names.add(sched.Name)
        
        if not checked_names:
            forms.alert("Sélectionnez au moins une nomenclature cible.")
            return
        
        self.result = []
        for cb, sched in self.sched_checkboxes:
            if sched.Name in checked_names:
                self.result.append(sched)
        self.UI.Close()
    
    def show_dialog(self):
        self.UI.ShowDialog()
        return self.result

# -------------------------
# Barre de progression
# -------------------------
class ProgressWindow(WPFWindow):
    def __init__(self, total):
        xaml_path = os.path.join(script_dir, "ProgressWindow.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())
        
        self.progressBar = self.UI.FindName("progressBar")
        self.txtStatus = self.UI.FindName("txtStatus")
        self.txtCurrent = self.UI.FindName("txtCurrent")
        
        self.total = total
        if self.progressBar:
            self.progressBar.Maximum = total
            self.progressBar.Value = 0
        if self.txtCurrent:
            self.txtCurrent.Text = "0 / {}".format(total)
    
    def update(self, current, name):
        if self.progressBar:
            self.progressBar.Value = current
        if self.txtStatus:
            self.txtStatus.Text = name
        if self.txtCurrent:
            self.txtCurrent.Text = "{} / {}".format(current, self.total)
        Dispatcher.CurrentDispatcher.Invoke(DispatcherPriority.Background, System.Action(lambda: None))

# -------------------------
# Main
# -------------------------
def main():
    try:
        log("# Copie des couleurs de regroupements")
        log("---")
        
        # Étape 1 : Sélection SOURCE
        win_src = SourceScheduleWindow()
        source = win_src.show_dialog()
        if not source:
            log("Annulé par l'utilisateur (étape 1).")
            return
        
        log("## Source : **{}**".format(source.Name))
        log("")
        
        # Analyser la source
        source_colors = analyze_source_schedule(source)
        
        if len(source_colors['header_text_colors']) == 0:
            log("**Aucune couleur de regroupement trouvée dans la source !**")
            forms.alert("Aucune couleur de regroupement trouvée dans la nomenclature source.", title="Aucune couleur")
            return
        
        log("---")
        log("")
        
        # Étape 2 : Sélection DESTINATIONS
        win_dest = DestinationSchedulesWindow(source)
        dests = win_dest.show_dialog()
        if not dests:
            log("Annulé par l'utilisateur (étape 2).")
            return
        
        log("## Destinations : **{}**".format(len(dests)))
        for d in dests:
            log("- {}".format(d.Name))
        log("---")
        log("")
        
        # Barre de progression
        progress = ProgressWindow(len(dests))
        progress.UI.Show()
        
        # Transaction
        t = Transaction(doc, "Copier couleurs regroupements")
        t.Start()
        
        total_colored = 0
        success_count = 0
        
        for idx, target in enumerate(dests, 1):
            progress.update(idx, target.Name)
            
            log("**[{}/{}]** {}".format(idx, len(dests), target.Name))
            
            try:
                cells_colored = apply_colors_to_schedule(target, source_colors)
                total_colored += cells_colored
                success_count += 1
                
            except Exception:
                tb = traceback.format_exc()
                path = save_traceback(tb)
                log("❌ Erreur : {}".format(path or "n/a"))
        
        t.Commit()
        
        progress.UI.Close()
        
        log("---")
        log("## ✔ Terminé")
        log("**Nomenclatures traitées : {}**".format(success_count))
        log("**Total cellules colorées : {}**".format(total_colored))
        
        message = u"{} nomenclatures traitées".format(success_count)
        show_xaml_message(message, title="Terminé")
        
    except Exception:
        tb = traceback.format_exc()
        path = save_traceback(tb)
        log("Erreur critique : {}".format(path or "n/a"))
        log("```python\n{}\n```".format(tb))
        forms.alert("Une erreur est survenue. Voir error_traceback.txt.", title="Erreur critique")

if __name__ == "__main__":
    main()
