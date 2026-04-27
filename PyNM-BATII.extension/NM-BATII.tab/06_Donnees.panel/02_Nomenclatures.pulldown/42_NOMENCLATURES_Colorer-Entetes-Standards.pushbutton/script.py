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


#__title__ = 'Colorer ENTETES'
#__doc__ = """Colorer entetes de COLONNES
#Description: Coloriser les entetes des nomenclatures en suivant les standards Nantes Metropole.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""


import clr

# Charger les assemblies WPF
clr.AddReference("WindowsBase")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("System.Xaml")

import os
import sys
import codecs

# Imports pour ResultWindow
from System.IO import File
from System.Windows.Markup import XamlReader

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Architecture import Room
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

# 1) 🔥 Ajouter lib/ au sys.path
script_dir = os.path.dirname(__file__)
ext_dir = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# Import après ajout au sys.path
from utils.config_loader import load_config

# 🔥 Charger les styles personnalisés WPF
from dialogs.dialogs_styles_loader import load
load(lib_dir=lib_dir)

from System.Windows.Media import SolidColorBrush
from System.Windows.Media import Color as WPFColor
from System.Windows.Controls import Button, Grid, Border, TextBlock, ColumnDefinition
from System.Windows import Thickness, GridLength, GridUnitType, HorizontalAlignment, VerticalAlignment, CornerRadius

doc = revit.doc

# Variables globales pour les logs
output = None
LOGS_ENABLED = False

# -------------------------------------------------------------------
def show_xaml_message(message, title="Message"):
    """
    Charge ResultWindow.xaml, assigne Title et txtMessage.Text, puis ShowDialog().
    Utilise FindName() pour retrouver txtMessage et btnClose.
    """
    script_dir = os.path.dirname(__file__)
    xaml_path = os.path.join(script_dir, "ResultWindow.xaml")
    xaml_content = File.ReadAllText(xaml_path)
    window = XamlReader.Parse(xaml_content)

    # Titre
    window.Title = title

    # Récupération des contrôles nommés
    txt_msg = window.FindName("txtMessage")
    btn = window.FindName("btnClose")

    if txt_msg is None or btn is None:
        raise Exception("Impossible de trouver txtMessage ou btnClose dans le XAML")

    # Injection du texte
    txt_msg.Text = message

    # Fermer au clic
    btn.Click += lambda s, e: window.Close()

    # Affichage modal
    window.ShowDialog()
# -------------------------------------------------------------------

def log(msg):
    """Log avec gestion activer_logs_scripts."""
    global output
    if not LOGS_ENABLED or output is None:
        return
    try:
        output.print_md(msg)
    except:
        print(msg)

def log_exc():
    """Log exception courante."""
    global output
    if not LOGS_ENABLED or output is None:
        return
    import traceback
    log("```python")
    log(traceback.format_exc())
    log("```")

# Interface graphique (identique a v6.1)
class ColorPickerWindow(WPFWindow):
    def __init__(self):
        # Charger config.json
        try:
            self.config = load_config() or {}
        except Exception as e:
            print("ERREUR config.json : {}".format(e))
            self.config = {}

        # Charger XAML externe (IronPython compatible)
        xaml_path = os.path.join(os.path.dirname(__file__), 'ColorPicker.xaml')
        with codecs.open(xaml_path, 'r', 'utf-8') as f:
            xaml = f.read()

        self.UI = XamlReader.Parse(xaml)

        # Recuperation des controles
        self.standards_panel = self.UI.FindName('standards_panel')
        self.ok_button = self.UI.FindName('ok_button')
        self.cancel_button = self.UI.FindName('cancel_button')

        # Couleurs standards pilotees par config.json
        defaults = {
            'colonnes_readonly': [192, 192, 192],
            'colonnes_types': [232, 113, 134],
            'colonnes_occurrences': [255, 255, 151],
        }

        cfg_section = self.config.get('nomenclatures_colonnes_couleurs') or {}

        def _rgb_from_cfg(key):
            v = cfg_section.get(key)
            if isinstance(v, list) and len(v) >= 3:
                return [int(v[0]), int(v[1]), int(v[2])]
            if isinstance(v, dict):
                return [int(v.get('r', defaults[key][0])),
                        int(v.get('g', defaults[key][1])),
                        int(v.get('b', defaults[key][2]))]
            return defaults[key]

        self.color_readonly = _rgb_from_cfg('colonnes_readonly')
        self.color_types = _rgb_from_cfg('colonnes_types')
        self.color_occ = _rgb_from_cfg('colonnes_occurrences')

        self.standard_colors = [
            ('Colonnes Lecture seule', self.color_readonly),
            ('Colonnes de types', self.color_types),
            ("Colonnes d'occurences", self.color_occ),
        ]

        self._setup_ui()
        self._setup_events()
        
        # Flag pour detecter l'annulation (par defaut = annule)
        self.cancelled = True

    def _setup_ui(self):
        # Boutons standards desactives (juste un apercu)
        for name, rgb in self.standard_colors:
            r, g, b = rgb
            btn = Button()
            btn.Height = 40
            btn.Margin = Thickness(0, 0, 0, 8)
            btn.HorizontalContentAlignment = HorizontalAlignment.Stretch
            btn.BorderThickness = Thickness(1)
            btn.BorderBrush = SolidColorBrush(WPFColor.FromRgb(136, 136, 136))
            btn.IsEnabled = False  # Desactive (juste un apercu)
            
            # Creer le contenu du bouton (preview + texte)
            grid = self._create_color_button_content(name, r, g, b)
            btn.Content = grid
            
            self.standards_panel.Children.Add(btn)
    
    def _create_color_button_content(self, name, r, g, b):
        """Cree le contenu d'un bouton de couleur (identique au script Colorer TITRE)"""
        grid = Grid()
        col1 = ColumnDefinition()
        col1.Width = GridLength(60, GridUnitType.Pixel)
        col2 = ColumnDefinition()
        col2.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(col1)
        grid.ColumnDefinitions.Add(col2)
        
        # Preview de couleur (rectangle arrondi)
        preview = Border()
        preview.Width = 50
        preview.Height = 30
        preview.Background = SolidColorBrush(WPFColor.FromRgb(r, g, b))
        preview.BorderBrush = SolidColorBrush(WPFColor.FromRgb(136, 136, 136))
        preview.BorderThickness = Thickness(1)
        preview.CornerRadius = CornerRadius(3)
        Grid.SetColumn(preview, 0)
        
        # Texte
        text = TextBlock()
        text.Text = name
        text.VerticalAlignment = VerticalAlignment.Center
        text.Margin = Thickness(10, 0, 0, 0)
        Grid.SetColumn(text, 1)
        
        grid.Children.Add(preview)
        grid.Children.Add(text)
        return grid

    def _setup_events(self):
        self.ok_button.Click += self._on_ok
        self.cancel_button.Click += self._on_cancel

    def _on_ok(self, sender, args):
        self.cancelled = False
        self.UI.Close()

    def _on_cancel(self, sender, args):
        self.cancelled = True
        self.UI.Close()

    def show(self):
        self.UI.ShowDialog()
        # Si annule, retourner None
        if self.cancelled:
            return None
        # Sinon retourner les couleurs du config.json
        return {
            'readonly': self.color_readonly,
            'types': self.color_types,
            'occurrences': self.color_occ
        }


# Interface de selection des nomenclatures (identique a pyRevit mais en francais)
class ScheduleSelectorWindow(WPFWindow):
    """Fenêtre de sélection des nomenclatures.

    SOURCE DE VÉRITÉ : self.selected_names (set Python)
    ────────────────────────────────────────────────────
    Le ListBox utilise la sélection WPF (SelectedItems).
    Quand _on_search vide puis re-remplit le ListBox, WPF efface
    SelectedItems → SelectionChanged se déclenche et supprimerait
    toutes les sélections si on les y stockait.

    Solution :
    • self.selected_names  = set de strings → source de vérité permanente
    • self._syncing        = flag qui bloque _on_selection_changed pendant
                             le filtrage (Items.Clear / SelectedItems.Add)
    • SelectionChanged     → _on_selection_changed → met selected_names à jour
    • _on_search           → restaure SelectedItems depuis selected_names
    """

    def __init__(self, schedules_list):
        xaml_path = os.path.join(os.path.dirname(__file__), 'ScheduleSelector.xaml')
        with codecs.open(xaml_path, 'r', 'utf-8') as f:
            xaml = f.read()

        self.UI = XamlReader.Parse(xaml)

        self.lst_schedules   = self.UI.FindName('lstSchedules')
        self.txt_search      = self.UI.FindName('txtSearch')
        self.btn_check_all   = self.UI.FindName('btnCheckAll')
        self.btn_uncheck_all = self.UI.FindName('btnUncheckAll')
        self.btn_toggle_all  = self.UI.FindName('btnToggleAll')
        self.btn_ok          = self.UI.FindName('btnOk')

        self.all_schedules      = schedules_list
        self.filtered_schedules = list(schedules_list)
        self.selected_items     = None
        self.last_selected_index = -1

        # ── Source de vérité Python ──────────────────────────────────────
        self.selected_names = set()   # strings correspondant aux items affichés
        self._syncing       = False   # True pendant Items.Clear / re-add

        # ── Peupler la liste ─────────────────────────────────────────────
        for item in schedules_list:
            self.lst_schedules.Items.Add(item)

        # ── Événements ───────────────────────────────────────────────────
        # SelectionChanged maintient selected_names à jour en temps réel.
        self.lst_schedules.SelectionChanged += self._on_selection_changed

        self.txt_search.TextChanged      += self._on_search
        self.btn_check_all.Click         += self._on_check_all
        self.btn_uncheck_all.Click       += self._on_uncheck_all
        self.btn_toggle_all.Click        += self._on_toggle_all
        self.btn_ok.Click                += self._on_ok
        self.lst_schedules.PreviewMouseLeftButtonDown += self._on_mouse_down

    # ── Synchronisation automatique ─────────────────────────────────────

    def _on_selection_changed(self, sender, args):
        """Maintenir selected_names en sync avec la sélection WPF.

        Ignoré pendant _on_search (flag _syncing) pour éviter que
        Items.Clear() ou SelectedItems.Add() ne perturbent le set.
        """
        if self._syncing:
            return
        try:
            for item in args.AddedItems:
                self.selected_names.add(str(item))
            for item in args.RemovedItems:
                self.selected_names.discard(str(item))
        except:
            pass

    # ── Filtrage ─────────────────────────────────────────────────────────

    def _on_search(self, sender, args):
        """Filtrer la liste en conservant TOUTES les sélections.

        Le flag _syncing empêche _on_selection_changed de vider
        selected_names quand Items.Clear() déclenche SelectionChanged.
        On restaure ensuite SelectedItems depuis selected_names.
        """
        search_text = self.txt_search.Text.lower()

        self._syncing = True
        try:
            self.lst_schedules.Items.Clear()
            self.filtered_schedules = []
            self.last_selected_index = -1

            for item in self.all_schedules:
                if search_text == "" or search_text in item.lower():
                    self.lst_schedules.Items.Add(item)
                    self.filtered_schedules.append(item)
                    # Restaurer depuis la source de vérité Python
                    if item in self.selected_names:
                        self.lst_schedules.SelectedItems.Add(item)
        finally:
            self._syncing = False

    # ── Sélection en masse ───────────────────────────────────────────────

    def _on_check_all(self, sender, args):
        """Tout sélectionner (items visibles)."""
        self.lst_schedules.SelectAll()
        # SelectionChanged → selected_names mis à jour automatiquement
        self.last_selected_index = (self.lst_schedules.Items.Count - 1
                                    if self.lst_schedules.Items.Count > 0 else -1)

    def _on_uncheck_all(self, sender, args):
        """Tout désélectionner — vide aussi les items masqués par le filtre."""
        self._syncing = True
        try:
            self.lst_schedules.UnselectAll()
            self.selected_names.clear()   # Items cachés par filtre inclus
        finally:
            self._syncing = False
        self.last_selected_index = -1

    def _on_toggle_all(self, sender, args):
        """Inverser la sélection des items visibles."""
        currently_selected = set()
        for item in self.lst_schedules.SelectedItems:
            currently_selected.add(str(item))

        self.lst_schedules.UnselectAll()
        # SelectionChanged retire les items dé-sélectionnés de selected_names

        for item in self.lst_schedules.Items:
            if str(item) not in currently_selected:
                self.lst_schedules.SelectedItems.Add(item)
        # SelectionChanged ajoute les nouveaux items à selected_names

        if self.lst_schedules.SelectedItems.Count > 0:
            last_item = self.lst_schedules.SelectedItems[
                self.lst_schedules.SelectedItems.Count - 1]
            self.last_selected_index = self.lst_schedules.Items.IndexOf(last_item)
        else:
            self.last_selected_index = -1

    # ── Clic souris (CTRL / MAJ) ─────────────────────────────────────────

    def _on_mouse_down(self, sender, args):
        """Clic simple = toggle, MAJ+clic = plage, CTRL+clic = toggle."""
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper

        shift_pressed = (Keyboard.IsKeyDown(Key.LeftShift) or
                         Keyboard.IsKeyDown(Key.RightShift))
        ctrl_pressed  = (Keyboard.IsKeyDown(Key.LeftCtrl) or
                         Keyboard.IsKeyDown(Key.RightCtrl))

        current = args.OriginalSource
        clicked_index       = -1
        clicked_listboxitem = None

        while current is not None:
            if (hasattr(current, '__class__') and
                    current.__class__.__name__ == 'ListBoxItem'):
                clicked_listboxitem = current
                clicked_index = (self.lst_schedules.ItemContainerGenerator
                                 .IndexFromContainer(current))
                break
            try:
                current = VisualTreeHelper.GetParent(current)
            except:
                break

        if clicked_index < 0 or clicked_listboxitem is None:
            return

        # MAJ+clic : sélection par plage
        if shift_pressed and not ctrl_pressed:
            if self.last_selected_index < 0:
                if self.lst_schedules.SelectedItems.Count > 0:
                    first = self.lst_schedules.SelectedItems[0]
                    self.last_selected_index = self.lst_schedules.Items.IndexOf(first)
                else:
                    self.last_selected_index = clicked_index

            start = min(self.last_selected_index, clicked_index)
            end   = max(self.last_selected_index, clicked_index)

            for i in range(start, end + 1):
                if i < self.lst_schedules.Items.Count:
                    item = self.lst_schedules.Items[i]
                    if item not in self.lst_schedules.SelectedItems:
                        self.lst_schedules.SelectedItems.Add(item)
                        # SelectionChanged met selected_names à jour

            self.last_selected_index = clicked_index
            args.Handled = True

        # CTRL+clic : toggle sans dé-sélectionner les autres
        elif ctrl_pressed:
            self.last_selected_index = clicked_index
            # Laisser WPF gérer (SelectionChanged mettra selected_names à jour)

        # Clic simple : toggle sans dé-sélectionner les autres
        else:
            item = self.lst_schedules.Items[clicked_index]
            if item in self.lst_schedules.SelectedItems:
                self.lst_schedules.SelectedItems.Remove(item)
            else:
                self.lst_schedules.SelectedItems.Add(item)
            # SelectionChanged met selected_names à jour

            self.last_selected_index = clicked_index
            args.Handled = True

    # ── Validation ───────────────────────────────────────────────────────

    def _on_ok(self, sender, args):
        """Retourner TOUS les items sélectionnés, y compris les items
        masqués par un filtre actif."""
        self.selected_items = list(self.selected_names)
        self.UI.Close()

    def show(self):
        self.UI.ShowDialog()
        return self.selected_items

# ============================================================
#  BARRE DE PROGRESSION
# ============================================================

class ProgressWindow(WPFWindow):
    def __init__(self, total):
        xaml_path = os.path.join(os.path.dirname(__file__), 'ProgressWindow.xaml')

        if not os.path.exists(xaml_path):
            self.UI = None
            return

        try:
            xaml_content = File.ReadAllText(xaml_path)
            self.UI = XamlReader.Parse(xaml_content)
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


def build_bindings_cache():
    """Cache des bindings pour classification rapide."""
    cache = {}
    try:
        bm = doc.ParameterBindings
        it = bm.ForwardIterator()
        it.Reset()
        while it.MoveNext():
            defn = it.Key
            binding = it.Current
            cache[defn.Name] = {
                'definition': defn,
                'binding': binding,
                'is_instance': isinstance(binding, InstanceBinding)
            }
    except:
        pass
    return cache


def classify_field(field, bindings_cache):
    """Classifier un field : readonly, type, ou occurrence."""
    field_type = field.FieldType
    
    # Readonly
    if field_type in [ScheduleFieldType.ProjectInfo, 
                      ScheduleFieldType.Room, 
                      ScheduleFieldType.Space,
                      ScheduleFieldType.Count,
                      ScheduleFieldType.Formula]:
        return 'readonly'
    
    # ElementType readonly
    if field_type == ScheduleFieldType.ElementType:
        param_id = field.ParameterId
        try:
            param_def = doc.GetElement(param_id)
            if param_def and not param_def.IsUserModifiable:
                return 'readonly'
        except:
            pass
    
    # Verifier dans cache bindings
    param_name = field.GetName()
    if param_name in bindings_cache:
        if bindings_cache[param_name]['is_instance']:
            return 'occurrence'
        else:
            return 'type'
    
    # Par defaut selon FieldType
    if field_type == ScheduleFieldType.Instance:
        return 'occurrence'
    else:
        return 'type'


def color_schedule_columns(schedule, colors, bindings_cache):
    """Coloriser les entetes d'une nomenclature."""
    
    table_data = schedule.GetTableData()
    body_section = table_data.GetSectionData(SectionType.Body)
    
    num_cols = body_section.NumberOfColumns
    first_row = body_section.FirstRowNumber
    last_row = body_section.LastRowNumber
    
    defn = schedule.Definition
    field_count = defn.GetFieldCount()
    
    # ETAPE 1 : DETECTER LA VRAIE LIGNE D'ENTETES
    log("  --- DETECTION VRAIE LIGNE ENTETES ---")
    log("  Recherche de la ligne avec le meilleur pourcentage...")
    log("")
    
    max_rows_to_check = min(20, last_row - first_row + 1)
    best_match_row = first_row
    best_match_percent = 0.0
    best_match_count = 0
    
    for row in range(first_row, first_row + max_rows_to_check):
        match_count = 0
        total_checked = 0
        
        for col in range(num_cols):
            try:
                cell_text = body_section.GetCellText(row, col)
                if not cell_text or cell_text.strip() == "":
                    continue
                
                total_checked += 1
                
                for field_idx in range(field_count):
                    try:
                        field = defn.GetField(field_idx)
                        if field is None:
                            continue
                        
                        field_name = field.GetName()
                        column_heading = field.ColumnHeading
                        
                        if cell_text == field_name or cell_text == column_heading:
                            match_count += 1
                            break
                    except:
                        pass
            except:
                pass
        
        if total_checked > 0:
            match_percent = (match_count * 100.0) / total_checked
        else:
            match_percent = 0.0
        
        log("  Ligne {}: {} correspondances / {} cellules = {:.1f}%".format(
            row, match_count, total_checked, match_percent
        ))
        
        if match_percent > best_match_percent or (match_percent == best_match_percent and match_count >= best_match_count):
            best_match_percent = match_percent
            best_match_count = match_count
            best_match_row = row
    
    header_row = best_match_row
    
    log("")
    log("  ✅ VRAIE LIGNE DETECTEE : Ligne {} ({} correspondances = {:.1f}%)".format(
        header_row, best_match_count, best_match_percent
    ))
    log("  ---")
    log("")
    
    # ETAPE 2 : COLORISER TOUTE LA ZONE D'ENTETES
    log("  --- COLORATION ZONE ENTETES ---")
    log("  Coloration de toutes les lignes {} a {} (zone d'entetes)".format(first_row, header_row))
    log("")
    
    total_cells_colored = 0
    
    for row in range(first_row, header_row + 1):
        cells_colored_this_row = 0
        
        for col in range(num_cols):
            try:
                cell_text = body_section.GetCellText(row, col)
                
                # Chercher quel field correspond
                found_field = None
                if cell_text and cell_text.strip() != "":
                    for field_idx in range(field_count):
                        try:
                            field = defn.GetField(field_idx)
                            if field is None:
                                continue
                            
                            field_name = field.GetName()
                            column_heading = field.ColumnHeading
                            
                            if cell_text == field_name or cell_text == column_heading:
                                found_field = field
                                break
                        except:
                            pass
                
                # NE coloriser QUE si field trouve
                if found_field is None:
                    continue
                
                classification = classify_field(found_field, bindings_cache)
                
                if classification == 'readonly':
                    rgb = colors['readonly']
                elif classification == 'occurrence':
                    rgb = colors['occurrences']
                else:
                    rgb = colors['types']
                
                r, g, b = rgb
                
                if body_section.AllowOverrideCellStyle(row, col):
                    cell_style = TableCellStyle()
                    options = TableCellStyleOverrideOptions()
                    options.BackgroundColor = True
                    cell_style.SetCellStyleOverrideOptions(options)
                    cell_style.BackgroundColor = Color(r, g, b)
                    body_section.SetCellStyle(row, col, cell_style)
                    cells_colored_this_row += 1
                    total_cells_colored += 1
            
            except:
                pass
        
        log("  Ligne {}: {} cellules colorisees".format(row, cells_colored_this_row))
    
    log("")
    log("  📊 RESULTAT : {} cellules colorisees au total".format(total_cells_colored))


def get_all_schedules():
    """Recuperer toutes les nomenclatures."""
    result = []
    for s in FilteredElementCollector(doc).OfClass(ViewSchedule).ToElements():
        if not s.IsTemplate:
            result.append(s)
    return sorted(result, key=lambda x: x.Name)


def get_schedule_display_name(schedule):
    """Nom + categorie (sans '(Autre)' si categorie invalide)."""
    try:
        cat_id = schedule.Definition.CategoryId
        if cat_id == ElementId.InvalidElementId or cat_id.IntegerValue == -1:
            return schedule.Name  # Juste le nom, sans (Autre)
        cat_elem = doc.GetElement(cat_id)
        if cat_elem is None:
            return schedule.Name  # Juste le nom, sans (Autre)
        return u"{} ({})".format(schedule.Name, cat_elem.Name)
    except:
        return schedule.Name  # Juste le nom, sans (Autre)


def main():
    # Charger config et activer/desactiver les logs
    global LOGS_ENABLED, output
    config = load_config()
    LOGS_ENABLED = config.get('activer_logs_scripts', False)
    
    # Initialiser output SEULEMENT si logs actives
    if LOGS_ENABLED:
        output = script.get_output()
    
    log("# Coloration des entetes de colonnes - Version 11.6")
    log("---")

    log("Construction du cache des bindings...")
    bindings_cache = build_bindings_cache()
    log("Cache construit: {} parametres".format(len(bindings_cache)))
    log("---")

    schedules = get_all_schedules()
    if not schedules:
        show_xaml_message("Aucune nomenclature trouvée", title="Erreur")
        return

    display_list = [get_schedule_display_name(s) for s in schedules]

    # Interface personnalisee en francais
    selector = ScheduleSelectorWindow(display_list)
    selected = selector.show()

    if not selected:
        return

    schedules_to_color = [schedules[i] for i, name in enumerate(display_list) if name in selected]

    picker = ColorPickerWindow()
    colors = picker.show()

    # Si l'utilisateur a annule
    if not colors:
        show_xaml_message("Colorisation annulée", title="Annulé")
        return

    # Barre de progression
    progress = ProgressWindow(len(schedules_to_color))
    progress.show()

    t = Transaction(doc, "Colorer entetes de colonnes")
    t.Start()

    for idx, schedule in enumerate(schedules_to_color):
        progress.update(idx + 1, schedule.Name)
        log("📋 Traitement : {}".format(schedule.Name))
        log("")

        color_schedule_columns(schedule, colors, bindings_cache)
        log("---")
        log("")

    t.Commit()
    progress.close()

    show_xaml_message("Coloration terminée avec succès.", title="Terminé")


if __name__ == "__main__":
    main()
