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


#__title__ = 'Colorer TITRES'
#__doc__ = """Colorer TITRE des nomenclatures
#Description: Coloriser les titres des nomenclatures en suivant les standards Nantes Metropole.

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
from Autodesk.Revit.DB import TableCellStyleOverrideOptions
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
output = script.get_output()

# ============================================================
#  GESTION DES LOGS PYREVIT (activation/désactivation)
# ============================================================

try:
    _config_global = load_config() or {}
    ACTIVER_LOGS = bool(_config_global.get("activer_logs_scripts", True))
except:
    ACTIVER_LOGS = True

def log(msg):
    """Log conditionnel : n'écrit dans le panneau pyRevit que si ACTIVER_LOGS = True"""
    if ACTIVER_LOGS:
        output.print_md(msg)


# ============================================================
#  FONCTION SHOW_XAML_MESSAGE (ResultWindow)
# ============================================================

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


# ============================================================
#  FENÊTRE DE SÉLECTION DE COULEUR
# ============================================================

class ColorPickerWindow(WPFWindow):
    def __init__(self):
        # Charger config.json
        try:
            self.config = load_config() or {}
        except Exception as e:
            log("ERREUR config.json : {}".format(e))
            self.config = {}

        # Charger XAML
        xaml_path = os.path.join(os.path.dirname(__file__), 'ColorPicker.xaml')
        with codecs.open(xaml_path, 'r', 'utf-8') as f:
            xaml = f.read()

        self.UI = XamlReader.Parse(xaml)
        self.selected_color = None
        self.selected_color_temp = None

        # Récupération des contrôles
        self.colors_panel = self.UI.FindName('colors_panel')
        self.standards_panel = self.UI.FindName('standards_panel')
        self.red_slider = self.UI.FindName('red_slider')
        self.green_slider = self.UI.FindName('green_slider')
        self.blue_slider = self.UI.FindName('blue_slider')
        self.red_text = self.UI.FindName('red_text')
        self.green_text = self.UI.FindName('green_text')
        self.blue_text = self.UI.FindName('blue_text')
        self.custom_preview = self.UI.FindName('custom_preview')
        self.ok_button = self.UI.FindName('ok_button')
        self.cancel_button = self.UI.FindName('cancel_button')

        # Presets existants
        self.preset_colors = [
            ('Bleu clair', 200, 220, 255),
            ('Bleu pastel', 173, 216, 230),
            ('Vert menthe', 200, 240, 220),
            ('Vert clair', 220, 255, 220),
            ('Rose pale', 255, 220, 230),
            ('Peche', 255, 230, 200),
            ('Jaune pale', 255, 255, 200),
            ('Lavande', 230, 230, 250),
            ('Gris clair', 220, 220, 220),
            ('Beige', 245, 245, 220),
            ('Corail', 255, 200, 180),
            ('Turquoise clair', 175, 238, 238),
        ]

        # ============================================================
        #  COULEURS NANTES 100% PILOTÉES PAR config.json
        # ============================================================

        n_cfg = self.config.get("nomenclatures_titres_couleurs")
        if not isinstance(n_cfg, dict):
            raise Exception(
                u'La section "nomenclatures_titres_couleurs" est absente ou invalide dans config.json'
            )

        def _rgb_required(key):
            val = n_cfg.get(key)
            if val is None:
                raise Exception(u'Clé "{}" manquante dans nomenclatures_titres_couleurs'.format(key))

            if isinstance(val, list) and len(val) >= 3:
                return [int(val[0]), int(val[1]), int(val[2])]

            if isinstance(val, dict):
                return [int(val["r"]), int(val["g"]), int(val["b"])]

            raise Exception(
                u'Format invalide pour "{}" dans config.json (liste [r,g,b] ou dict {{r,g,b}} attendu)'.format(key)
            )

        t = _rgb_required("tables_de_styles")
        st = _rgb_required("saisies_types")
        so = _rgb_required("saisies_occurrences")
        npres = _rgb_required("nomenclatures_presentations")

        self.standard_colors = [
            ("Tables de styles", t[0], t[1], t[2]),
            ("Saisies des informations des types", st[0], st[1], st[2]),
            ("Saisies des informations d'occurences", so[0], so[1], so[2]),
            ("Nomenclatures de présentations", npres[0], npres[1], npres[2]),
        ]

        self._setup_ui()
        self._setup_events()
        
        # Flag pour detecter l'annulation (par defaut = annule)
        self.cancelled = True

    def _setup_ui(self):
        # Boutons standards (Nantes)
        if self.standards_panel is not None:
            for name, r, g, b in self.standard_colors:
                btn = Button()
                btn.Height = 40
                btn.Margin = Thickness(0, 0, 0, 8)
                btn.HorizontalContentAlignment = HorizontalAlignment.Stretch
                btn.BorderThickness = Thickness(1)
                btn.BorderBrush = SolidColorBrush(WPFColor.FromRgb(136, 136, 136))
                btn.Tag = (r, g, b)
                btn.Click += self._on_standard_click

                grid = self._create_color_button_content(name, r, g, b)
                btn.Content = grid

                self.standards_panel.Children.Add(btn)

        # Presets existants
        if self.colors_panel is not None:
            for name, r, g, b in self.preset_colors:
                btn = Button()
                btn.Height = 40
                btn.Margin = Thickness(0, 0, 0, 8)
                btn.HorizontalContentAlignment = HorizontalAlignment.Stretch
                btn.BorderThickness = Thickness(1)
                btn.BorderBrush = SolidColorBrush(WPFColor.FromRgb(136, 136, 136))
                btn.Tag = (r, g, b)
                btn.Click += self._on_preset_click

                grid = self._create_color_button_content(name, r, g, b)
                btn.Content = grid

                self.colors_panel.Children.Add(btn)

    def _create_color_button_content(self, name, r, g, b):
        grid = Grid()
        col1 = ColumnDefinition()
        col1.Width = GridLength(60, GridUnitType.Pixel)
        col2 = ColumnDefinition()
        col2.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(col1)
        grid.ColumnDefinitions.Add(col2)

        preview = Border()
        preview.Width = 50
        preview.Height = 30
        preview.Background = SolidColorBrush(WPFColor.FromRgb(r, g, b))
        preview.BorderBrush = SolidColorBrush(WPFColor.FromRgb(136, 136, 136))
        preview.BorderThickness = Thickness(1)
        preview.CornerRadius = CornerRadius(3)
        Grid.SetColumn(preview, 0)

        text = TextBlock()
        text.Text = name
        text.VerticalAlignment = VerticalAlignment.Center
        text.Margin = Thickness(10, 0, 0, 0)
        Grid.SetColumn(text, 1)

        grid.Children.Add(preview)
        grid.Children.Add(text)
        return grid

    def _setup_events(self):
        if self.red_slider: self.red_slider.ValueChanged += self._on_slider_changed
        if self.green_slider: self.green_slider.ValueChanged += self._on_slider_changed
        if self.blue_slider: self.blue_slider.ValueChanged += self._on_slider_changed

        if self.red_text: self.red_text.TextChanged += self._on_text_changed
        if self.green_text: self.green_text.TextChanged += self._on_text_changed
        if self.blue_text: self.blue_text.TextChanged += self._on_text_changed

        if self.ok_button: self.ok_button.Click += self._on_ok
        if self.cancel_button: self.cancel_button.Click += self._on_cancel

        self._update_preview()

    def _on_standard_click(self, sender, args):
        r, g, b = sender.Tag
        self.red_slider.Value = r
        self.green_slider.Value = g
        self.blue_slider.Value = b
        self.red_text.Text = str(r)
        self.green_text.Text = str(g)
        self.blue_text.Text = str(b)
        self.selected_color_temp = Color(r, g, b)

    def _on_preset_click(self, sender, args):
        r, g, b = sender.Tag
        self.red_slider.Value = r
        self.green_slider.Value = g
        self.blue_slider.Value = b
        self.red_text.Text = str(r)
        self.green_text.Text = str(g)
        self.blue_text.Text = str(b)
        self.selected_color_temp = Color(r, g, b)

    def _on_slider_changed(self, sender, args):
        self.red_text.Text = str(int(self.red_slider.Value))
        self.green_text.Text = str(int(self.green_slider.Value))
        self.blue_text.Text = str(int(self.blue_slider.Value))
        self._update_preview()
        self.selected_color_temp = Color(
            int(self.red_slider.Value),
            int(self.green_slider.Value),
            int(self.blue_slider.Value)
        )

    def _on_text_changed(self, sender, args):
        try:
            self.red_slider.Value = int(self.red_text.Text)
            self.green_slider.Value = int(self.green_text.Text)
            self.blue_slider.Value = int(self.blue_text.Text)
        except:
            pass

    def _update_preview(self):
        try:
            r = int(self.red_slider.Value)
            g = int(self.green_slider.Value)
            b = int(self.blue_slider.Value)
            self.custom_preview.Background = SolidColorBrush(WPFColor.FromRgb(r, g, b))
        except:
            pass

    def _on_ok(self, sender, args):
        if self.selected_color_temp:
            self.selected_color = self.selected_color_temp
        else:
            self.selected_color = Color(
                int(self.red_slider.Value),
                int(self.green_slider.Value),
                int(self.blue_slider.Value)
            )
        self.cancelled = False  # Seul OK valide
        self.UI.Close()

    def _on_cancel(self, sender, args):
        self.selected_color = None
        self.cancelled = True  # Reste annule
        self.UI.Close()

    def show(self):
        self.UI.ShowDialog()
        # Si annule (X, Annuler, Echap), retourner None
        if self.cancelled:
            return None
        return self.selected_color


# ============================================================
#  INTERFACE DE SÉLECTION DES NOMENCLATURES (ScheduleSelector)
# ============================================================

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
        # SelectionChanged retire les items de-sélectionnés de selected_names

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
        xaml_path = os.path.join(script_dir, 'ProgressWindow.xaml')

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

def color_schedule_headers(schedule, color):
    table_data = schedule.GetTableData()
    header_section = table_data.GetSectionData(SectionType.Header)

    num_cols = header_section.NumberOfColumns
    num_rows = header_section.NumberOfRows

    log('  Lignes header: {} | Colonnes: {}'.format(num_rows, num_cols))

    cells_colored = 0
    cells_skipped = 0

    for row in range(num_rows):
        for col in range(num_cols):
            if header_section.AllowOverrideCellStyle(row, col):
                cell_style = TableCellStyle()
                options = TableCellStyleOverrideOptions()
                options.BackgroundColor = True
                cell_style.SetCellStyleOverrideOptions(options)
                cell_style.BackgroundColor = color
                header_section.SetCellStyle(row, col, cell_style)
                cells_colored += 1
            else:
                cells_skipped += 1

    log('  {} cellules titre colorees, {} ignorees'.format(cells_colored, cells_skipped))
    return cells_colored


def get_all_schedules():
    collector = FilteredElementCollector(doc)
    schedules = collector.OfClass(ViewSchedule).ToElements()
    return sorted([s for s in schedules if not s.IsTemplate], key=lambda x: x.Name)


# ============================================================
#  MAIN
# ============================================================

def main():
    log('# Coloration du TITRE de nomenclature')
    log('---')

    all_schedules = get_all_schedules()
    if not all_schedules:
        show_xaml_message('Aucune nomenclature trouvée', title='Erreur')
        return

    log('OK {} nomenclatures trouvées'.format(len(all_schedules)))

    display_list = []
    for s in all_schedules:
        try:
            cat_id = s.Definition.CategoryId
            if cat_id == ElementId.InvalidElementId or cat_id.IntegerValue == -1:
                cat_name = 'Autre'
            else:
                cat_elem = doc.GetElement(cat_id)
                cat_name = cat_elem.Name if cat_elem else 'Autre'
            
            # Ne pas afficher "(Autre)" - juste le nom
            if cat_name != 'Autre':
                display_list.append('{} ({})'.format(s.Name, cat_name))
            else:
                display_list.append(s.Name)
        except:
            display_list.append(s.Name)

    # Interface personnalisee en francais
    selector = ScheduleSelectorWindow(display_list)
    selected = selector.show()

    if not selected:
        return

    schedules_to_color = [
        all_schedules[i]
        for i, name in enumerate(display_list)
        if name in selected
    ]

    log('OK {} nomenclatures sélectionnées'.format(len(schedules_to_color)))
    log('---')

    picker = ColorPickerWindow()
    color = picker.show()

    if not color:
        show_xaml_message('Colorisation annulée', title='Annulé')
        log('Annulé')
        return

    log('OK Couleur sélectionnée: R:{} G:{} B:{}'.format(color.Red, color.Green, color.Blue))
    log('---')

    log('# Application de la couleur...')

    # Barre de progression
    progress = ProgressWindow(len(schedules_to_color))
    progress.show()

    t = Transaction(doc, 'Colorer titre de nomenclatures')
    t.Start()

    success = 0
    errors  = 0

    for schedule in schedules_to_color:
        progress.update(schedules_to_color.index(schedule) + 1, schedule.Name)
        try:
            color_schedule_headers(schedule, color)
            log('OK {}'.format(schedule.Name))
            success += 1
        except Exception as e:
            log('ERREUR {}: {}'.format(schedule.Name, e))
            errors += 1

    t.Commit()
    progress.close()

    log('---')
    log('# Résumé')
    log('Succès: {}'.format(success))
    if errors > 0:
        log('Erreurs: {}'.format(errors))

    # Message de succes avec ResultWindow
    show_xaml_message(
        '{} nomenclature(s) colorée(s) avec succès !'.format(success),
        title='Terminé'
    )


if __name__ == '__main__':
    main()
