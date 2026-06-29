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


#__title__ = 'Colorer ENTETES\npar copie'
#__doc__ = """Transfert couleurs d'entetes par parametre
#Description: Copie les couleurs d'entetes d'une nomenclature source vers d'autres
#en associant les couleurs aux parametres, pas aux positions

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""


import clr
clr.AddReference('WindowsBase')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('System.Xaml')

import os
import sys
import codecs
import System

from System.IO import File
from System.Windows.Markup import XamlReader

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB import TableCellStyleOverrideOptions
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

# ── Chemins ──────────────────────────────────────────────────────────────────
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir, os.pardir))
lib_dir    = os.path.join(ext_dir, 'lib')
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

try:
    from dialogs.dialogs_styles_loader import load as _load_styles, show_alert
    _load_styles(lib_dir=lib_dir)
except Exception:
    pass

try:
    from utils.config_loader import load_config as _load_config
    _cfg = _load_config() or {}
except Exception:
    _cfg = {}

doc    = revit.doc
output = script.get_output()


# ══════════════════════════════════════════════════════════════════════════════
#  RÉSULTAT (ResultWindow)
# ══════════════════════════════════════════════════════════════════════════════

def show_xaml_message(message, title='Information'):
    """Affiche ResultWindow.xaml avec un message."""
    try:
        xaml_path = os.path.join(script_dir, 'ResultWindow.xaml')
        with codecs.open(xaml_path, 'r', 'utf-8') as f:
            ui = XamlReader.Parse(f.read())
        ui.Title = title
        ui.FindName('txtMessage').Text = message
        ui.FindName('btnClose').Click += lambda s, e: ui.Close()
        ui.ShowDialog()
    except Exception:
        show_alert(title, message)


# ══════════════════════════════════════════════════════════════════════════════
#  SÉLECTION SOURCE  (SourceScheduleSelector.xaml — sélection simple)
# ══════════════════════════════════════════════════════════════════════════════

class SourceScheduleSelectorWindow(WPFWindow):
    """Sélection simple d'une nomenclature source (RadioButton).

    _on_search reconstruit la liste visible tout en conservant l'item
    sélectionné si celui-ci correspond encore au filtre.
    """

    def __init__(self, schedules_list):
        xaml_path = os.path.join(script_dir, 'SourceScheduleSelector.xaml')
        with codecs.open(xaml_path, 'r', 'utf-8') as f:
            self.UI = XamlReader.Parse(f.read())

        self.lst_schedules = self.UI.FindName('lstSchedules')
        self.txt_search    = self.UI.FindName('txtSearch')
        self.btn_ok        = self.UI.FindName('btnOk')

        self.all_schedules = schedules_list
        self.result        = None

        for item in schedules_list:
            self.lst_schedules.Items.Add(item)

        if self.txt_search:
            self.txt_search.TextChanged += self._on_search
        if self.btn_ok:
            self.btn_ok.Click += self._on_ok

    def _on_search(self, sender, args):
        """Filtrer en conservant l'item sélectionné si toujours visible."""
        text     = self.txt_search.Text.lower()
        selected = self.lst_schedules.SelectedItem   # string ou None

        self.lst_schedules.Items.Clear()
        for item in self.all_schedules:
            if not text or text in item.lower():
                self.lst_schedules.Items.Add(item)
                if item == selected:
                    self.lst_schedules.SelectedItem = item

    def _on_ok(self, sender, args):
        sel = self.lst_schedules.SelectedItem
        if sel is None:
            show_alert(u"Information", 'Sélectionnez une nomenclature source.')
            return
        self.result = sel
        self.UI.Close()

    def show(self):
        self.UI.ShowDialog()
        return self.result   # string (nom affiché) ou None


# ══════════════════════════════════════════════════════════════════════════════
#  SÉLECTION CIBLES  (ScheduleSelector.xaml — multi-sélection CheckBox)
# ══════════════════════════════════════════════════════════════════════════════

class ScheduleSelectorWindow(WPFWindow):
    """Sélection multiple des nomenclatures cibles via CheckBox.

    SOURCE DE VÉRITÉ : self.checked_names (set Python)
    ────────────────────────────────────────────────────
    CheckBox.IsChecked retourne System.Nullable<bool> en IronPython.
    Tester `if cb.IsChecked:` est dangereux (Nullable<bool>(False) est
    un objet non-None → toujours truthy en Python).

    Solution :
    • checked_names   = set Python mis à jour par cb.Checked / cb.Unchecked
    • _on_search      = reconstruit la liste sans toucher IsChecked (sauf
                        pour la restauration visuelle depuis checked_names)
    • _uncheck_all    = vide aussi les items masqués par le filtre
    • _on_ok          = retourne list(checked_names)
    """

    def __init__(self, schedules_list):
        xaml_path = os.path.join(script_dir, 'ScheduleSelector.xaml')
        with codecs.open(xaml_path, 'r', 'utf-8') as f:
            self.UI = XamlReader.Parse(f.read())

        self.lst_schedules   = self.UI.FindName('lstSchedules')
        self.txt_search      = self.UI.FindName('txtSearch')
        self.btn_check_all   = self.UI.FindName('btnCheckAll')
        self.btn_uncheck_all = self.UI.FindName('btnUncheckAll')
        self.btn_toggle_all  = self.UI.FindName('btnToggleAll')
        self.btn_ok          = self.UI.FindName('btnOk')

        self.all_schedules     = schedules_list   # liste de strings (noms affichés)
        self.sched_checkboxes  = []               # [(CheckBox, name), …]
        self.last_selected_idx = -1
        self.result            = None

        # ── Source de vérité ────────────────────────────────────────────
        self.checked_names = set()

        # ── Peupler la liste ────────────────────────────────────────────
        for name in schedules_list:
            cb = System.Windows.Controls.CheckBox()
            cb.Content   = name
            cb.Margin    = System.Windows.Thickness(0, 2, 0, 2)
            cb.IsChecked = False

            # Capture explicite du nom (évite le piège de la variable de boucle)
            cb.Checked   += lambda s, e, n=name: self.checked_names.add(n)
            cb.Unchecked += lambda s, e, n=name: self.checked_names.discard(n)

            self.sched_checkboxes.append((cb, name))
            self.lst_schedules.Items.Add(cb)

        # ── Événements boutons ───────────────────────────────────────────
        if self.btn_check_all:
            self.btn_check_all.Click   += lambda s, e: self._select_all(True)
        if self.btn_uncheck_all:
            self.btn_uncheck_all.Click += lambda s, e: self._select_all(False)
        if self.btn_toggle_all:
            self.btn_toggle_all.Click  += lambda s, e: self._toggle_all()
        if self.btn_ok:
            self.btn_ok.Click += self._on_ok
        if self.txt_search:
            self.txt_search.TextChanged += self._on_search

        self.lst_schedules.PreviewMouseLeftButtonDown += self._on_mouse_down

    # ── Sélection en masse (items visibles uniquement) ───────────────────

    def _select_all(self, value):
        """Cocher / décocher tous les items visibles.
        Le bouton 'Tout désélectionner' vide aussi checked_names entièrement
        (y compris les items masqués par un filtre actif).
        """
        if not value:
            # Désélectionner TOUT — y compris les items cachés par filtre
            for cb, _ in self.sched_checkboxes:
                cb.IsChecked = False
            self.checked_names.clear()
        else:
            # Sélectionner les items visibles
            for i in range(self.lst_schedules.Items.Count):
                try:
                    self.lst_schedules.Items[i].IsChecked = True
                    # cb.Checked event met checked_names à jour
                except:
                    pass

    def _toggle_all(self):
        """Inverser la sélection des items visibles."""
        for i in range(self.lst_schedules.Items.Count):
            try:
                cb   = self.lst_schedules.Items[i]
                name = str(cb.Content)
                cb.IsChecked = name not in self.checked_names
                # cb.Checked / cb.Unchecked met checked_names à jour
            except:
                pass

    # ── Filtrage ─────────────────────────────────────────────────────────

    def _on_search(self, sender, args):
        """Filtrer en conservant TOUTES les sélections.

        On ne touche PAS à cb.IsChecked des items cachés.
        On restaure uniquement l'état visuel des items re-affichés
        depuis la source de vérité Python (checked_names).
        """
        text = self.txt_search.Text.lower()
        self.lst_schedules.Items.Clear()
        for cb, name in self.sched_checkboxes:
            if not text or text in name.lower():
                # Restaurer l'état visuel depuis checked_names (fiable)
                cb.IsChecked = (name in self.checked_names)
                self.lst_schedules.Items.Add(cb)

    # ── Clic souris (CTRL / MAJ) ─────────────────────────────────────────

    def _on_mouse_down(self, sender, args):
        """Clic simple = toggle, CTRL+clic = toggle, MAJ+clic = plage."""
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper

        try:
            current = args.OriginalSource
            clicked_index = -1
            while current is not None:
                if (hasattr(current, '__class__') and
                        current.__class__.__name__ == 'ListBoxItem'):
                    clicked_index = (self.lst_schedules.ItemContainerGenerator
                                     .IndexFromContainer(current))
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

        # CTRL+clic : toggle la case cliquée
        if Keyboard.IsKeyDown(Key.LeftCtrl) or Keyboard.IsKeyDown(Key.RightCtrl):
            try:
                name = str(clicked_cb.Content)
                clicked_cb.IsChecked = name not in self.checked_names
                self.last_selected_idx = clicked_index
                args.Handled = True
            except:
                pass
            return

        # MAJ+clic : sélection par plage
        if Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift):
            try:
                name         = str(clicked_cb.Content)
                target_state = name not in self.checked_names
                last         = self.last_selected_idx if self.last_selected_idx >= 0 else 0
                start        = min(last, clicked_index)
                end          = max(last, clicked_index)
                for i in range(start, end + 1):
                    if i < self.lst_schedules.Items.Count:
                        self.lst_schedules.Items[i].IsChecked = target_state
                self.last_selected_idx = clicked_index
                args.Handled = True
            except:
                pass
            return

        # Clic normal : mémoriser l'index pour MAJ+clic ultérieur
        try:
            self.last_selected_idx = clicked_index
        except:
            pass

    # ── Validation ───────────────────────────────────────────────────────

    def _on_ok(self, sender, args):
        if not self.checked_names:
            show_alert(u"Information", 'Sélectionnez au moins une nomenclature cible.')
            return
        self.result = list(self.checked_names)
        self.UI.Close()

    def show(self):
        self.UI.ShowDialog()
        return self.result   # list de strings ou None


# ============================================================
#  BARRE DE PROGRESSION
# ============================================================

class ProgressWindow:
    def __init__(self, total):
        xaml_path = os.path.join(script_dir, 'ProgressWindow.xaml')

        if not os.path.exists(xaml_path):
            self.UI = None
            return

        try:
            with codecs.open(xaml_path, 'r', 'utf-8') as f:
                self.UI = XamlReader.Parse(f.read())
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
            import System as _Sys
            if self.progressBar: self.progressBar.Value = current
            if self.txtStatus:   self.txtStatus.Text    = name
            if self.txtCurrent:  self.txtCurrent.Text   = '{} / {}'.format(current, self.total)
            Dispatcher.CurrentDispatcher.Invoke(
                DispatcherPriority.Background,
                _Sys.Action(lambda: None)
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


def get_column_info(body_section, col_index, doc):
    """
    Recuperer les informations d'une colonne
    Retourne: {
        'param_id': ElementId,
        'category_id': ElementId,
        'param_name': str,
        'category_name': str
    }
    """
    info = {
        'param_id': None,
        'category_id': None,
        'param_name': '',
        'category_name': ''
    }
    
    try:
        # Recuperer le ParamId et CategoryId de la colonne
        param_id = body_section.GetCellParamId(col_index)
        category_id = body_section.GetCellCategoryId(col_index)
        
        info['param_id'] = param_id
        info['category_id'] = category_id
        
        # Recuperer le nom du parametre
        if param_id and param_id != ElementId.InvalidElementId:
            if param_id.IntegerValue < 0:
                # Parametre integre
                try:
                    bip = BuiltInParameter(param_id.IntegerValue)
                    info['param_name'] = LabelUtils.GetLabelFor(bip)
                except:
                    info['param_name'] = 'BIP_{}'.format(param_id.IntegerValue)
            else:
                # Parametre personnalise
                param_elem = doc.GetElement(param_id)
                if param_elem:
                    info['param_name'] = param_elem.Name
        
        # Recuperer le nom de la categorie
        if category_id and category_id != ElementId.InvalidElementId:
            cat_elem = doc.GetElement(category_id)
            if cat_elem:
                info['category_name'] = cat_elem.Name
            else:
                info['category_name'] = 'Cat_{}'.format(category_id.IntegerValue)
    
    except Exception as e:
        output.print_md('  Erreur info colonne {}: {}'.format(col_index, str(e)))
    
    return info

def get_cell_color(body_section, row, col):
    """
    Recuperer la couleur d'une cellule
    Retourne Color ou None
    """
    try:
        cell_style = body_section.GetTableCellStyle(row, col)
        if cell_style:
            # Verifier si la couleur est overridee
            options = cell_style.GetCellStyleOverrideOptions()
            if options.BackgroundColor:
                return cell_style.BackgroundColor
    except:
        pass
    
    return None

def analyze_source_schedule(schedule, doc):
    """
    Analyser la nomenclature source et extraire toutes les couleurs
    Retourne: {
        'column_colors': {(param_id, category_id): Color},
        'header_text_colors': {text: Color},  # Pour regroupements
        'num_header_rows': int
    }
    """
    output.print_md('## Analyse de la nomenclature source: {}'.format(schedule.Name))
    
    result = {
        'column_colors': {},
        'header_text_colors': {},
        'num_header_rows': 0
    }
    
    try:
        table_data = schedule.GetTableData()
        body_section = table_data.GetSectionData(SectionType.Body)
        
        num_cols = body_section.NumberOfColumns
        first_row = body_section.FirstRowNumber
        
        # Detecter le nombre de lignes d'entetes
        max_rows_to_check = min(10, body_section.NumberOfRows)
        header_rows = []
        
        for row in range(first_row, first_row + max_rows_to_check):
            cell_type = body_section.GetCellType(row, 0)
            # Les lignes de donnees ont le type ParameterText
            # Les lignes d'entetes ont le type Text
            if cell_type == CellType.ParameterText:
                break
            header_rows.append(row)
        
        result['num_header_rows'] = len(header_rows)
        output.print_md('  {} ligne(s) d\'entetes detectees'.format(len(header_rows)))
        
        if len(header_rows) == 0:
            output.print_md('  ATTENTION: Aucune ligne d\'entete trouvee !')
            return result
        
        # Derniere ligne d'entetes = noms des colonnes
        last_header_row = header_rows[-1]
        
        # Pour chaque colonne, recuperer param_id, category_id et couleur
        for col in range(num_cols):
            # Info de la colonne
            col_info = get_column_info(body_section, col, doc)
            
            # Couleur de la cellule
            color = get_cell_color(body_section, last_header_row, col)
            
            if color:
                key = (col_info['param_id'], col_info['category_id'])
                result['column_colors'][key] = color
                
                output.print_md('  Col {}: {} ({}) - R:{} G:{} B:{}'.format(
                    col,
                    col_info['param_name'],
                    col_info['category_name'] if col_info['category_name'] else 'Projet',
                    color.Red, color.Green, color.Blue
                ))
        
        # Recuperer les couleurs des regroupements (lignes precedentes)
        if len(header_rows) > 1:
            output.print_md('  Analyse des regroupements:')
            
            for row in header_rows[:-1]:  # Toutes sauf la derniere
                for col in range(num_cols):
                    # Texte de la cellule
                    try:
                        text = body_section.GetCellText(row, col)
                        if text and text.strip():
                            # Couleur
                            color = get_cell_color(body_section, row, col)
                            if color:
                                result['header_text_colors'][text.strip()] = color
                                output.print_md('    "{}" - R:{} G:{} B:{}'.format(
                                    text.strip(), color.Red, color.Green, color.Blue
                                ))
                    except:
                        pass
        
        output.print_md('  Total: {} couleurs par parametre, {} couleurs de regroupements'.format(
            len(result['column_colors']),
            len(result['header_text_colors'])
        ))
    
    except Exception as e:
        output.print_md('  ERREUR analyse: {}'.format(str(e)))
    
    return result

def apply_colors_to_schedule(schedule, source_colors, doc):
    """
    Appliquer les couleurs a une nomenclature cible
    """
    output.print_md('## Application sur: {}'.format(schedule.Name))
    
    try:
        table_data = schedule.GetTableData()
        body_section = table_data.GetSectionData(SectionType.Body)
        
        num_cols = body_section.NumberOfColumns
        first_row = body_section.FirstRowNumber
        
        # Detecter lignes d'entetes
        max_rows_to_check = min(10, body_section.NumberOfRows)
        header_rows = []
        
        for row in range(first_row, first_row + max_rows_to_check):
            cell_type = body_section.GetCellType(row, 0)
            if cell_type == CellType.ParameterText:
                break
            header_rows.append(row)
        
        if len(header_rows) == 0:
            output.print_md('  ATTENTION: Aucune ligne d\'entete trouvee')
            return 0
        
        output.print_md('  {} ligne(s) d\'entetes detectees'.format(len(header_rows)))
        
        last_header_row = header_rows[-1]
        cells_colored = 0
        
        # Appliquer couleurs par parametre (derniere ligne)
        for col in range(num_cols):
            col_info = get_column_info(body_section, col, doc)
            key = (col_info['param_id'], col_info['category_id'])
            
            if key in source_colors['column_colors']:
                color = source_colors['column_colors'][key]
                
                if body_section.AllowOverrideCellStyle(last_header_row, col):
                    cell_style = TableCellStyle()
                    options = TableCellStyleOverrideOptions()
                    options.BackgroundColor = True
                    cell_style.SetCellStyleOverrideOptions(options)
                    cell_style.BackgroundColor = color
                    
                    body_section.SetCellStyle(last_header_row, col, cell_style)
                    cells_colored += 1
                    
                    output.print_md('  Col {}: {} ({}) - Colore'.format(
                        col,
                        col_info['param_name'],
                        col_info['category_name'] if col_info['category_name'] else 'Projet'
                    ))
        
        # Appliquer couleurs des regroupements (lignes precedentes)
        if len(header_rows) > 1 and source_colors['header_text_colors']:
            output.print_md('  Application regroupements:')
            
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
                                
                                output.print_md('    "{}" - Colore'.format(text.strip()))
                    except:
                        pass
        
        output.print_md('  Total: {} cellules colorees'.format(cells_colored))
        return cells_colored
    
    except Exception as e:
        output.print_md('  ERREUR: {}'.format(str(e)))
        return 0

def get_all_schedules():
    collector = FilteredElementCollector(doc)
    schedules = collector.OfClass(ViewSchedule).ToElements()
    
    result = []
    for s in schedules:
        if s.IsTemplate:
            continue
        result.append(s)
    
    return sorted(result, key=lambda x: x.Name)

def main():
    output.print_md('# Copier couleurs d\'entetes par parametre')
    output.print_md('---')

    # ── 1. Toutes les nomenclatures ───────────────────────────────────────
    all_schedules = get_all_schedules()
    if not all_schedules:
        show_xaml_message('Aucune nomenclature trouvée', title='Erreur')
        return

    output.print_md('OK {} nomenclatures trouvees'.format(len(all_schedules)))
    output.print_md('---')

    # ── 2. Construire la liste d'affichage ────────────────────────────────
    display_list = []
    for s in all_schedules:
        try:
            cat_id = s.Definition.CategoryId
            if cat_id == ElementId.InvalidElementId or cat_id.IntegerValue == -1:
                cat_name = 'Autre'
            else:
                cat_elem = doc.GetElement(cat_id)
                cat_name = cat_elem.Name if cat_elem else 'Autre'
            display_list.append('{} ({})'.format(s.Name, cat_name))
        except:
            display_list.append('{} (Autre)'.format(s.Name))

    # ── 3. Sélection SOURCE ───────────────────────────────────────────────
    src_win          = SourceScheduleSelectorWindow(display_list)
    source_selection = src_win.show()

    if not source_selection:
        return

    source_schedule = all_schedules[display_list.index(source_selection)]
    output.print_md('SOURCE: {}'.format(source_schedule.Name))
    output.print_md('---')

    # ── 4. Analyser la source ─────────────────────────────────────────────
    source_colors = analyze_source_schedule(source_schedule, doc)

    if not source_colors['column_colors'] and not source_colors['header_text_colors']:
        show_xaml_message(
            'Aucune couleur trouvée dans la nomenclature source !',
            title='Erreur')
        return

    output.print_md('---')

    # ── 5. Sélection CIBLES ───────────────────────────────────────────────
    target_display_list  = []
    target_schedules_map = []

    for i, schedule in enumerate(all_schedules):
        if schedule.Id != source_schedule.Id:
            target_display_list.append(display_list[i])
            target_schedules_map.append(schedule)

    tgt_win          = ScheduleSelectorWindow(target_display_list)
    target_selection = tgt_win.show()

    if not target_selection:
        return

    target_schedules = [
        target_schedules_map[target_display_list.index(sel)]
        for sel in target_selection
        if sel in target_display_list
    ]

    if not target_schedules:
        show_xaml_message('Aucune nomenclature cible sélectionnée.', title='Erreur')
        return

    output.print_md('OK {} nomenclatures cibles'.format(len(target_schedules)))
    output.print_md('---')

    # ── 6. Appliquer les couleurs ─────────────────────────────────────────
    output.print_md('# Application des couleurs...')
    output.print_md('---')

    # Barre de progression
    progress = ProgressWindow(len(target_schedules))
    progress.show()

    t = Transaction(doc, 'Copier couleurs entetes')
    t.Start()

    success = 0
    errors  = 0

    for idx, target in enumerate(target_schedules):
        progress.update(idx + 1, target.Name)
        try:
            cells = apply_colors_to_schedule(target, source_colors, doc)
            if cells > 0:
                success += 1
            output.print_md('---')
        except Exception as e:
            output.print_md('ERREUR {}: {}'.format(target.Name, str(e)))
            output.print_md('---')
            errors += 1

    t.Commit()
    progress.close()

    # ── 7. Résumé ─────────────────────────────────────────────────────────
    output.print_md('# Resume')
    output.print_md('Succes: {}'.format(success))
    if errors > 0:
        output.print_md('Erreurs: {}'.format(errors))

    msg = '{} nomenclature(s) mise(s) a jour !'.format(success)
    if errors > 0:
        msg += '\n{} erreur(s).'.format(errors)
    show_xaml_message(msg, title='Terminé')


if __name__ == '__main__':
    main()
