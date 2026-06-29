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


#__title__ = "LARGEURS COLONNES"
#__doc__ = """Configurer les largeurs de colonnes d'une nomenclature
#Description: Configurer en masse les largeurs de colonnes d'une nomenclature.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""

import clr
clr.AddReference("WindowsBase")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("System.Xaml")

import System
from System.Windows        import GridLength, GridUnitType, Thickness
from System.Windows.Markup import XamlReader

import os, sys, codecs, traceback

from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

# ─────────────────────────────────────────────────────────────────────────────
# Chemins / loader standard
# ─────────────────────────────────────────────────────────────────────────────
script_dir = os.path.dirname(__file__)
ext_dir = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

try:
    from dialogs.dialogs_styles_loader import load as load_dialog_styles, show_alert
    load_dialog_styles(lib_dir=lib_dir)
except Exception:
    pass

try:
    from utils.config_loader import load_config
except Exception:
    def load_config():
        return {}

# ─────────────────────────────────────────────────────────────────────────────
# Logs
# ─────────────────────────────────────────────────────────────────────────────
doc  = revit.doc
_cfg = load_config() or {}

def _parse_bool_like(v):
    if isinstance(v, bool):         return v
    if isinstance(v, (int, float)): return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true",  "1", "yes", "y", "on"):  return True
        if s in ("false", "0", "no",  "n", "off"): return False
    return None

ACTIVER_LOGS = True
try:
    parsed = _parse_bool_like(_cfg.get("activer_logs_scripts", True))
    if parsed is not None:
        ACTIVER_LOGS = parsed
except Exception:
    pass

_output = None
if ACTIVER_LOGS:
    try:
        _output = script.get_output()
    except Exception:
        pass

def log(msg):
    if not ACTIVER_LOGS:
        return
    try:
        if _output: _output.print_md(msg)
        else: print(msg)
    except Exception:
        try: print(msg)
        except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
# Conversions
# ─────────────────────────────────────────────────────────────────────────────
def mm_to_feet(mm):   return mm / 304.8
def feet_to_mm(feet): return feet * 304.8

# ─────────────────────────────────────────────────────────────────────────────
# Propriété largeur (découverte selon la version de Revit)
# ─────────────────────────────────────────────────────────────────────────────
_WIDTH_ATTR = None

def _find_width_attr(field):
    global _WIDTH_ATTR
    if _WIDTH_ATTR is not None:
        return _WIDTH_ATTR
    for candidate in ["ColumnWidth", "Width", "GridColumnWidth", "HeaderWidth"]:
        if hasattr(field, candidate):
            _WIDTH_ATTR = candidate
            return _WIDTH_ATTR
    return None

def get_field_width(field):
    attr = _find_width_attr(field)
    if attr is None:
        return None
    try:
        val = getattr(field, attr)
        return float(val() if callable(val) else val)
    except Exception:
        return None

def set_field_width(field, width_feet):
    attr = _find_width_attr(field)
    if attr is None:
        return False, u"Propriété largeur introuvable"
    try:
        setattr(field, attr, width_feet)
        return True, attr
    except Exception as e:
        return False, str(e)

# ─────────────────────────────────────────────────────────────────────────────
# Labels et couleurs des types de champs
# ─────────────────────────────────────────────────────────────────────────────
FIELD_TYPE_LABELS = {
    "Instance":          u"Occurrence",
    "ElementType":       u"Type",
    "Count":             u"Nombre",
    "Room":              u"Pièce",
    "Space":             u"Espace",
    "ProjectInfo":       u"Proj. Info",
    "Formula":           u"Calculé",
    "CombinedParameter": u"Combiné",
    "Area":              u"Aire",
}

FIELD_TYPE_HEX = {
    u"Occurrence":  "#2563EB",
    u"Type":        "#7C3AED",
    u"Nombre":      "#059669",
    u"Pièce":       "#EA580C",
    u"Espace":      "#D97706",
    u"Proj. Info":  "#DC2626",
    u"Calculé":     "#4B5563",
    u"Combiné":     "#4B5563",
    u"Aire":        "#059669",
}
_HEX_DEFAULT = "#6B7280"


def _brush(hex_color):
    try:
        from System.Windows.Media import BrushConverter
        return BrushConverter().ConvertFromString(hex_color)
    except Exception:
        from System.Windows.Media import Brushes
        return Brushes.Gray


def get_field_type_label(field):
    try:
        ft = str(field.FieldType)
        ft_name = ft.split(".")[-1] if "." in ft else ft
        return FIELD_TYPE_LABELS.get(ft_name, ft_name)
    except Exception:
        return u"?"

# ─────────────────────────────────────────────────────────────────────────────
# XAML inline — ProgressWindow et ResultWindow
# (pas de dépendance aux fichiers externes)
# ─────────────────────────────────────────────────────────────────────────────
_RESULT_WINDOW_XAML = u"""<?xml version="1.0" encoding="utf-8"?>
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Terminé"
        SizeToContent="WidthAndHeight"
        MinWidth="400"
        ResizeMode="NoResize"
        WindowStartupLocation="CenterScreen">
    <Grid Margin="20">
        <Grid.RowDefinitions>
            <RowDefinition Height="*"/>
            <RowDefinition Height="16"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <Border Grid.Row="0"
                BorderBrush="#0078D4" BorderThickness="1"
                CornerRadius="4" Padding="16,12">
            <TextBlock x:Name="txtMessage"
                       TextWrapping="Wrap"
                       FontSize="14" FontWeight="Medium"
                       TextAlignment="Center"
                       VerticalAlignment="Center"/>
        </Border>
        <Button x:Name="btnClose"
                Grid.Row="2"
                Content="Fermer"
                Height="40"
                HorizontalAlignment="Stretch"
                IsDefault="True"/>
    </Grid>
</Window>"""

_PROGRESS_WINDOW_XAML = u"""<?xml version="1.0" encoding="utf-8"?>
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Opération en cours..."
        Width="500" Height="150"
        MinWidth="500"
        ResizeMode="NoResize"
        WindowStartupLocation="CenterScreen"
        Background="#F5F5F5">
    <Grid Margin="20">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="10"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="10"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock x:Name="txtStatus"
                   Grid.Row="0"
                   Text="Préparation..."
                   FontSize="14" FontWeight="SemiBold"
                   Foreground="#333333" TextWrapping="Wrap"/>
        <ProgressBar x:Name="progressBar"
                     Grid.Row="2"
                     Height="25" Minimum="0" Maximum="100" Value="0"
                     Background="#E0E0E0" Foreground="#0078D4"
                     BorderBrush="#AAAAAA" BorderThickness="1"/>
        <TextBlock x:Name="txtCurrent"
                   Grid.Row="4"
                   Text="0 / 0"
                   FontSize="12" Foreground="#666666"
                   HorizontalAlignment="Center"/>
    </Grid>
</Window>"""


def show_xaml_message(message, title=u"Terminé"):
    """Affiche une boîte de résultat — XAML intégré dans le script."""
    try:
        ui = XamlReader.Parse(_RESULT_WINDOW_XAML)
        ui.Title = title
        ui.FindName("txtMessage").Text = message
        ui.FindName("btnClose").Click += lambda s, e: ui.Close()
        ui.ShowDialog()
    except Exception:
        show_alert(title, message)

# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires Revit
# ─────────────────────────────────────────────────────────────────────────────
def get_all_schedules():
    return [
        s for s in FilteredElementCollector(doc).OfClass(ViewSchedule)
        if not s.IsTemplate
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Construction d'une ligne de tableau
# Colonnes : [CB 30] [Type 90] [Name *] [Width 65] [mm 30]
# ─────────────────────────────────────────────────────────────────────────────
_COL_CB   = 30
_COL_TYPE = 90
_COL_W    = 65
_COL_MM   = 30


def _make_column_row(cb, type_label, col_name, tb_width, row_idx):
    """Crée un Grid WPF pour une ligne du tableau en réutilisant cb et tb."""
    import System.Windows.Controls as WC
    import System.Windows          as WW

    row = WC.Grid()
    row.MinHeight  = 30
    row.Background = _brush("#FFFFFF") if row_idx % 2 == 0 else _brush("#F8F9FC")

    # Colonnes
    for w in [_COL_CB, _COL_TYPE]:
        cd = WC.ColumnDefinition()
        cd.Width = GridLength(w)
        row.ColumnDefinitions.Add(cd)
    cd_star = WC.ColumnDefinition()
    cd_star.Width = GridLength(1, GridUnitType.Star)
    row.ColumnDefinitions.Add(cd_star)
    for w in [_COL_W, _COL_MM]:
        cd = WC.ColumnDefinition()
        cd.Width = GridLength(w)
        row.ColumnDefinitions.Add(cd)

    # CheckBox — on le détache de son parent actuel si nécessaire
    _detach(cb)
    cb.VerticalAlignment   = WW.VerticalAlignment.Center
    cb.HorizontalAlignment = WW.HorizontalAlignment.Center
    WC.Grid.SetColumn(cb, 0)
    row.Children.Add(cb)

    # Badge type
    hex_fg = FIELD_TYPE_HEX.get(type_label, _HEX_DEFAULT)
    badge = WC.Border()
    badge.CornerRadius     = WW.CornerRadius(3)
    badge.Background       = _brush("#F0F4FF")
    badge.BorderBrush      = _brush(hex_fg)
    badge.BorderThickness  = Thickness(1)
    badge.Padding          = Thickness(4, 1, 4, 1)
    badge.Margin           = Thickness(3, 3, 3, 3)
    badge.VerticalAlignment   = WW.VerticalAlignment.Center
    badge.HorizontalAlignment = WW.HorizontalAlignment.Left
    lbl = WC.TextBlock()
    lbl.Text         = type_label
    lbl.FontSize     = 10
    lbl.Foreground   = _brush(hex_fg)
    lbl.TextTrimming = WW.TextTrimming.CharacterEllipsis
    badge.Child = lbl
    WC.Grid.SetColumn(badge, 1)
    row.Children.Add(badge)

    # Nom du paramètre
    name_tb = WC.TextBlock()
    name_tb.Text              = col_name
    name_tb.VerticalAlignment = WW.VerticalAlignment.Center
    name_tb.Margin            = Thickness(6, 0, 8, 0)
    name_tb.FontSize          = 12
    name_tb.TextTrimming      = WW.TextTrimming.CharacterEllipsis
    WC.Grid.SetColumn(name_tb, 2)
    row.Children.Add(name_tb)

    # TextBox largeur — on la détache de son parent actuel si nécessaire
    _detach(tb_width)
    tb_width.HorizontalAlignment = WW.HorizontalAlignment.Stretch
    tb_width.VerticalAlignment   = WW.VerticalAlignment.Center
    tb_width.TextAlignment       = WW.TextAlignment.Right
    tb_width.Margin              = Thickness(0, 3, 3, 3)
    tb_width.FontSize            = 12
    WC.Grid.SetColumn(tb_width, 3)
    row.Children.Add(tb_width)

    # "mm"
    mm_lbl = WC.TextBlock()
    mm_lbl.Text              = u"mm"
    mm_lbl.FontSize          = 11
    mm_lbl.Foreground        = _brush("#9CA3AF")
    mm_lbl.VerticalAlignment = WW.VerticalAlignment.Center
    mm_lbl.Margin            = Thickness(3, 0, 0, 0)
    WC.Grid.SetColumn(mm_lbl, 4)
    row.Children.Add(mm_lbl)

    return row


def _detach(element):
    """
    Détache un élément WPF de son parent visuel actuel.
    Nécessaire pour pouvoir le ré-ajouter dans un nouveau parent
    (un élément WPF ne peut appartenir qu'à un seul parent à la fois).
    """
    try:
        import System.Windows.Controls as WC
        parent = System.Windows.Media.VisualTreeHelper.GetParent(element)
        if parent is None:
            return
        if hasattr(parent, "Children"):
            parent.Children.Remove(element)
        elif hasattr(parent, "Child"):
            parent.Child = None
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Barre de progression
# ─────────────────────────────────────────────────────────────────────────────
class ProgressWindow(WPFWindow):
    def __init__(self, total, title=u"Opération en cours..."):
        self.UI = XamlReader.Parse(_PROGRESS_WINDOW_XAML)
        self.UI.Title    = title
        self.progressBar = self.UI.FindName("progressBar")
        self.txtStatus   = self.UI.FindName("txtStatus")
        self.txtCurrent  = self.UI.FindName("txtCurrent")
        self.total = total
        if self.progressBar:
            self.progressBar.Maximum = total
            self.progressBar.Value   = 0
        if self.txtCurrent:
            self.txtCurrent.Text = u"0 / {}".format(total)

    def update(self, current, name):
        from System.Windows.Threading import Dispatcher, DispatcherPriority
        if self.progressBar: self.progressBar.Value = current
        if self.txtStatus:   self.txtStatus.Text    = name
        if self.txtCurrent:  self.txtCurrent.Text   = u"{} / {}".format(current, self.total)
        Dispatcher.CurrentDispatcher.Invoke(
            DispatcherPriority.Background,
            System.Action(lambda: None)
        )

    def close(self):
        try: self.UI.Close()
        except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# Fenêtre principale
# ─────────────────────────────────────────────────────────────────────────────
class ColumnWidthEditorWindow(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(script_dir, "ScheduleColumnWidthEditor.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())

        # Éléments UI
        self.cboSchedule      = self.UI.FindName("cboSchedule")
        self.txtFilter        = self.UI.FindName("txtFilter")
        self.panelColumns     = self.UI.FindName("panelColumns")
        self.scrollColumns    = self.UI.FindName("scrollColumns")
        self.btnCheckAll      = self.UI.FindName("btnCheckAll")
        self.btnUncheckAll    = self.UI.FindName("btnUncheckAll")
        self.btnToggleAll     = self.UI.FindName("btnToggleAll")
        self.txtMassWidth     = self.UI.FindName("txtMassWidth")
        self.btnApplyMass     = self.UI.FindName("btnApplyMass")
        self.btnValider       = self.UI.FindName("btnValider")
        self.btnCancel        = self.UI.FindName("btnCancel")
        self.borderValidation = self.UI.FindName("borderValidation")
        self.txtValidation    = self.UI.FindName("txtValidation")

        # Données
        self.all_schedules    = []
        self.selected_sched   = None
        # Chaque item : (checkbox, textbox, ScheduleField, type_label, col_name)
        # Les objets cb et tb sont permanents — jamais recréés, seulement déplacés.
        self.all_items        = []
        self.last_clicked_idx = -1   # index dans la liste VISIBLE (après filtre)
        self.result           = False

        # Remplir la ComboBox
        schedules = sorted(get_all_schedules(), key=lambda s: s.Name)
        self.all_schedules = schedules
        self.cboSchedule.Items.Add(u"-- Sélectionnez une nomenclature --")
        for sched in schedules:
            self.cboSchedule.Items.Add(sched.Name)
        self.cboSchedule.SelectedIndex = 0

        # Événements
        self.cboSchedule.SelectionChanged += self._on_schedule_selected
        if self.txtFilter:
            self.txtFilter.TextChanged += self._on_filter_changed
        if self.btnCheckAll:
            self.btnCheckAll.Click   += lambda s, e: self._select_all(True)
        if self.btnUncheckAll:
            self.btnUncheckAll.Click += lambda s, e: self._select_all(False)
        if self.btnToggleAll:
            self.btnToggleAll.Click  += lambda s, e: self._toggle_all()
        if self.btnApplyMass:
            self.btnApplyMass.Click  += self._on_apply_mass
        if self.btnValider:
            self.btnValider.Click    += self._on_valider
        if self.btnCancel:
            self.btnCancel.Click     += lambda s, e: self.UI.Close()
        if self.scrollColumns:
            self.scrollColumns.PreviewMouseLeftButtonDown += self._on_mouse_down

    # ── Validation inline ─────────────────────────────────────────────────────
    def _show_validation(self, errors):
        if self.txtValidation:
            self.txtValidation.Text = u"\n".join(errors)
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Visible

    def _hide_validation(self):
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Collapsed

    # ── Activer/désactiver les contrôles ─────────────────────────────────────
    def _set_controls_enabled(self, enabled):
        for ctrl in [self.txtFilter, self.txtMassWidth, self.btnApplyMass,
                     self.btnCheckAll, self.btnUncheckAll, self.btnToggleAll]:
            if ctrl:
                ctrl.IsEnabled = enabled

    # ── Sélection nomenclature ────────────────────────────────────────────────
    def _on_schedule_selected(self, sender, args):
        try:
            idx = self.cboSchedule.SelectedIndex
            if idx <= 0:
                return
            sched = self.all_schedules[idx - 1]
            if sched == self.selected_sched:
                return
            self.selected_sched = sched
            self._populate_columns(sched)
            self._set_controls_enabled(True)
            self._hide_validation()
        except Exception:
            log(u"Erreur _on_schedule_selected : {}".format(traceback.format_exc()))

    # ── Population initiale du tableau ────────────────────────────────────────
    def _populate_columns(self, sched):
        import System.Windows.Controls as WC

        self.all_items        = []
        self.last_clicked_idx = -1
        self.panelColumns.Children.Clear()

        if self.txtFilter:
            self.txtFilter.Text = u""

        sched_def = sched.Definition
        for i in range(sched_def.GetFieldCount()):
            try:
                field      = sched_def.GetField(i)
                col_name   = field.GetName()
                type_label = get_field_type_label(field)
                w_feet     = get_field_width(field)
                w_mm       = feet_to_mm(w_feet) if w_feet is not None else 0.0

                cb = WC.CheckBox()
                cb.IsChecked = False

                tb = WC.TextBox()
                tb.Text = u"{:.0f}".format(w_mm)

                self.all_items.append((cb, tb, field, type_label, col_name))
            except Exception:
                continue

        # Afficher tous les items (pas de filtre au départ)
        self._render_visible()

    # ── Rendu du panel selon le filtre actuel ─────────────────────────────────
    def _render_visible(self):
        """
        Vide le StackPanel et re-insère uniquement les lignes correspondant
        au filtre actuel. Les objets cb et tb sont RÉUTILISÉS (pas recréés),
        donc leurs états (IsChecked, Text) sont préservés.
        """
        self.panelColumns.Children.Clear()
        self.last_clicked_idx = -1

        text = u""
        if self.txtFilter:
            text = self.txtFilter.Text.lower() if self.txtFilter.Text else u""

        visible_idx = 0
        for cb, tb, field, type_label, col_name in self.all_items:
            if not text or text in col_name.lower() or text in type_label.lower():
                row = _make_column_row(cb, type_label, col_name, tb, visible_idx)
                self.panelColumns.Children.Add(row)
                visible_idx += 1

    # ── Filtre ────────────────────────────────────────────────────────────────
    def _on_filter_changed(self, sender, args):
        if self.selected_sched is None:
            return
        try:
            self._render_visible()
        except Exception:
            log(u"Erreur filtre : {}".format(traceback.format_exc()))

    # ── Obtenir les items visibles ────────────────────────────────────────────
    def _get_visible_items(self):
        text = u""
        if self.txtFilter and self.txtFilter.Text:
            text = self.txtFilter.Text.lower()
        if not text:
            return list(self.all_items)
        return [
            item for item in self.all_items
            if text in item[4].lower() or text in item[3].lower()
        ]

    # ── MAJ+clic ──────────────────────────────────────────────────────────────
    def _on_mouse_down(self, sender, args):
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper

        # Trouver l'index de la ligne cliquée dans le StackPanel
        clicked_idx = -1
        try:
            current = args.OriginalSource
            while current is not None:
                try:
                    parent = VisualTreeHelper.GetParent(current)
                except Exception:
                    break
                if parent == self.panelColumns:
                    for i in range(self.panelColumns.Children.Count):
                        if self.panelColumns.Children[i] == current:
                            clicked_idx = i
                            break
                    break
                current = parent
        except Exception:
            return

        if clicked_idx < 0:
            return

        shift = (Keyboard.IsKeyDown(Key.LeftShift) or
                 Keyboard.IsKeyDown(Key.RightShift))

        if not shift:
            self.last_clicked_idx = clicked_idx
            return

        # MAJ+clic : cocher/décocher la plage
        try:
            visible = self._get_visible_items()
            if clicked_idx >= len(visible):
                return
            last  = self.last_clicked_idx if self.last_clicked_idx >= 0 else 0
            start = min(last, clicked_idx)
            end   = max(last, clicked_idx)
            target_state = not (visible[clicked_idx][0].IsChecked == True)
            for i in range(start, end + 1):
                if i < len(visible):
                    visible[i][0].IsChecked = target_state
            self.last_clicked_idx = clicked_idx
            args.Handled = True
        except Exception:
            pass

    # ── Tout / Aucun / Inverser ───────────────────────────────────────────────
    def _select_all(self, value):
        for item in self._get_visible_items():
            try: item[0].IsChecked = value
            except Exception: pass

    def _toggle_all(self):
        for item in self._get_visible_items():
            try: item[0].IsChecked = not (item[0].IsChecked == True)
            except Exception: pass

    # ── Application en masse ──────────────────────────────────────────────────
    def _on_apply_mass(self, sender, args):
        txt = (self.txtMassWidth.Text or u"").strip().replace(u",", u".")
        try:
            w_mm = float(txt)
            if w_mm <= 0:
                raise ValueError()
        except Exception:
            self._show_validation(
                [u"• Valeur invalide : «{}». Entrez un nombre positif.".format(txt)]
            )
            return

        self._hide_validation()
        count = 0
        for item in self._get_visible_items():
            cb, tb = item[0], item[1]
            if cb.IsChecked == True:
                tb.Text = u"{:.0f}".format(w_mm)
                count += 1

        if count == 0:
            self._show_validation(
                [u"• Aucune colonne sélectionnée. Cochez des colonnes avant d'appliquer."]
            )

    # ── Valider ───────────────────────────────────────────────────────────────
    def _on_valider(self, sender, args):
        if not self.selected_sched:
            self._show_validation([u"• Sélectionnez une nomenclature."])
            return

        errors   = []
        to_apply = []

        for cb, tb, field, type_label, col_name in self.all_items:
            txt = (tb.Text or u"").strip().replace(u",", u".")
            try:
                w_mm = float(txt)
                if w_mm <= 0:
                    raise ValueError()
                to_apply.append((field, mm_to_feet(w_mm), col_name, type_label))
            except Exception:
                errors.append(
                    u"• {} [{}] : valeur invalide «{}»".format(
                        col_name, type_label, tb.Text)
                )

        if errors:
            self._show_validation(errors)
            return

        self._hide_validation()

        log(u"## Nomenclature : **{}**".format(self.selected_sched.Name))

        # Afficher la barre de progression
        progress = ProgressWindow(
            len(to_apply),
            title=u"Application des largeurs en cours..."
        )
        progress.UI.Show()

        t = Transaction(
            doc, u"Configurer largeurs : {}".format(self.selected_sched.Name)
        )
        t.Start()

        success = 0
        failed  = 0
        for idx, (field, w_feet, col_name, type_label) in enumerate(to_apply, 1):
            progress.update(idx, u"{} [{}]".format(col_name, type_label))
            ok, msg = set_field_width(field, w_feet)
            if ok:
                success += 1
                log(u"  ➤ {} [{}] → {:.0f} mm".format(
                    col_name, type_label, feet_to_mm(w_feet)))
            else:
                failed += 1
                log(u"  ❌ {} [{}] : {}".format(col_name, type_label, msg))

        t.Commit()
        progress.close()
        log(u"**Appliqués : {}** | **Erreurs : {}**".format(success, failed))

        self.result = True
        self.UI.Close()

    def show_dialog(self):
        self.UI.ShowDialog()
        return self.result

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    try:
        log("# Configurer les largeurs de colonnes")
        log("---")

        win     = ColumnWidthEditorWindow()
        applied = win.show_dialog()

        if applied:
            log("## ✔ Largeurs appliquées")
            show_xaml_message(u"Largeurs de colonnes configurées.", title=u"Terminé")
        else:
            log("Annulé par l'utilisateur.")

    except Exception:
        tb = traceback.format_exc()
        log(u"Erreur critique : {}".format(tb))
        show_alert(
            "Erreur critique",
            u"Une erreur est survenue :\n\n{}".format(tb)
        )

if __name__ == "__main__":
    main()
