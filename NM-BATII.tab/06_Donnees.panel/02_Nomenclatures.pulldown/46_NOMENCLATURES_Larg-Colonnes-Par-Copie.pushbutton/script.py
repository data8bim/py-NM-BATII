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


#__title__ = "Largeurs COLONNES\npar copie"
#__doc__ = """Copier les largeurs de colonnes d'une nomenclature
#Description: Copier les largeurs de colonnes d'une nomenclature source
#vers une sélection de nomenclatures de destination.
#Les largeurs sont copiées vers les colonnes de même nom présentes
#dans chaque nomenclature cible.

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
from System.Windows.Threading import Dispatcher, DispatcherPriority

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
doc = revit.doc
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
        if _output:
            _output.print_md(msg)
        else:
            print(msg)
    except Exception:
        try:
            print(msg)
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────────────
# Conversions
# ─────────────────────────────────────────────────────────────────────────────
def mm_to_feet(mm):
    """Convertit mm en pieds (unité interne Revit)."""
    return mm / 304.8

def feet_to_mm(feet):
    """Convertit pieds en mm pour l'affichage."""
    return feet * 304.8

# ─────────────────────────────────────────────────────────────────────────────
# Découverte de la propriété largeur sur ScheduleField
# (le nom varie selon la version de Revit)
# ─────────────────────────────────────────────────────────────────────────────
_WIDTH_ATTR = None   # mis en cache au premier appel

def _find_width_attr(field):
    """Retourne le nom de la propriété largeur disponible sur ScheduleField."""
    global _WIDTH_ATTR
    if _WIDTH_ATTR is not None:
        return _WIDTH_ATTR
    for candidate in ["ColumnWidth", "Width", "GridColumnWidth", "HeaderWidth"]:
        if hasattr(field, candidate):
            _WIDTH_ATTR = candidate
            return _WIDTH_ATTR
    return None


def get_field_width(field):
    """
    Lit la largeur d'un champ en pieds.
    Retourne (width_feet: float, attr_name: str) ou (None, diagnostic: str).
    """
    attr = _find_width_attr(field)
    if attr is None:
        candidates = sorted([
            a for a in dir(field)
            if not a.startswith("_") and
            any(k in a.lower() for k in ("width", "size", "column", "dim"))
        ])
        return None, u"Attr introuvable. Disponibles : {}".format(candidates)
    try:
        val = getattr(field, attr)
        if callable(val):
            val = val()
        return float(val), attr
    except Exception as e:
        return None, u"Erreur lecture {} : {}".format(attr, str(e))


def set_field_width(field, width_feet):
    """
    Écrit la largeur d'un champ en pieds.
    Retourne (ok: bool, message: str).
    """
    attr = _find_width_attr(field)
    if attr is None:
        return False, u"Propriété largeur introuvable"
    try:
        setattr(field, attr, width_feet)
        return True, attr
    except Exception as e:
        return False, u"Erreur écriture {} : {}".format(attr, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────────────────────────────────────
def get_all_schedules():
    return [
        s for s in FilteredElementCollector(doc).OfClass(ViewSchedule)
        if not s.IsTemplate
    ]


def show_xaml_message(message, title="Information"):
    try:
        xaml_path = os.path.join(script_dir, "ResultWindow.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            ui = XamlReader.Parse(f.read())
        ui.Title = title
        ui.FindName("txtMessage").Text = message
        ui.FindName("btnClose").Click += lambda s, e: ui.Close()
        ui.ShowDialog()
    except Exception:
        show_alert(title, message)

# ─────────────────────────────────────────────────────────────────────────────
# Logique principale : copie d'une largeur de colonne
# ─────────────────────────────────────────────────────────────────────────────
def copy_column_width(src_field, target_sched):
    """
    Copie la largeur de src_field vers la colonne correspondante dans target_sched.

    Correspondance par priorité décroissante :
      1. ParameterId  +  FieldType  (correspondance exacte)
      2. ParameterId  seul          (même paramètre, type différent — fallback)
      3. Nom          +  FieldType  (paramètre builtin ou sans ID valide)
      4. Nom          seul          (dernier recours)

    Retourne (success: bool, message: str)
    """
    tgt_def    = target_sched.Definition
    src_name   = src_field.GetName()
    src_pid    = src_field.ParameterId
    src_ftype  = src_field.FieldType
    valid_pid  = (src_pid != ElementId.InvalidElementId)

    # Lire la largeur source
    src_width, diag = get_field_width(src_field)
    if src_width is None:
        return False, u"Largeur source illisible — {}".format(diag)

    # ── Construire les candidats une seule fois ───────────────────────────────
    candidates = []
    for i in range(tgt_def.GetFieldCount()):
        try:
            f = tgt_def.GetField(i)
            candidates.append((f, f.ParameterId, f.FieldType, f.GetName()))
        except Exception:
            pass

    # ── Priorité 1 : ParameterId + FieldType ─────────────────────────────────
    if valid_pid:
        for f, pid, ftype, fname in candidates:
            if pid == src_pid and ftype == src_ftype:
                ok, msg = set_field_width(f, src_width)
                if ok:
                    return True, u"{:.1f} mm [PID+Type]".format(feet_to_mm(src_width))
                return False, msg

    # ── Priorité 2 : ParameterId seul ────────────────────────────────────────
    if valid_pid:
        for f, pid, ftype, fname in candidates:
            if pid == src_pid:
                ok, msg = set_field_width(f, src_width)
                if ok:
                    return True, u"{:.1f} mm [PID seul]".format(feet_to_mm(src_width))
                return False, msg

    # ── Priorité 3 : Nom + FieldType ─────────────────────────────────────────
    for f, pid, ftype, fname in candidates:
        if fname == src_name and ftype == src_ftype:
            ok, msg = set_field_width(f, src_width)
            if ok:
                return True, u"{:.1f} mm [Nom+Type]".format(feet_to_mm(src_width))
            return False, msg

    # ── Priorité 4 : Nom seul ─────────────────────────────────────────────────
    for f, pid, ftype, fname in candidates:
        if fname == src_name:
            ok, msg = set_field_width(f, src_width)
            if ok:
                return True, u"{:.1f} mm [Nom seul]".format(feet_to_mm(src_width))
            return False, msg

    return False, u"Colonne absente dans la cible"

# ─────────────────────────────────────────────────────────────────────────────
# Fenêtre 1 — Sélection SOURCE + colonnes
# ─────────────────────────────────────────────────────────────────────────────
class SourceWindow(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(script_dir, "SourceScheduleSelector.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())

        self.UI.Title = u"Copier les largeurs — Étape 1 / 2 : Source et colonnes"

        self.lstSchedules        = self.UI.FindName("lstSchedules")
        self.lstFields           = self.UI.FindName("lstFields")
        self.txtSearch           = self.UI.FindName("txtSearch")
        self.txtSearchField      = self.UI.FindName("txtSearchField")
        self.btnOk               = self.UI.FindName("btnOk")
        self.btnCheckAllFields   = self.UI.FindName("btnCheckAllFields")
        self.btnUncheckAllFields = self.UI.FindName("btnUncheckAllFields")
        self.btnToggleAllFields  = self.UI.FindName("btnToggleAllFields")
        self.borderValidation    = self.UI.FindName("borderValidation")
        self.txtValidation       = self.UI.FindName("txtValidation")

        self.all_schedules    = []
        self.field_checkboxes = []   # [(CheckBox, name, ScheduleField), ...]
        self.last_field_idx   = -1
        self.result_schedule  = None
        self.result_fields    = []

        schedules = sorted(get_all_schedules(), key=lambda s: s.Name)
        self.all_schedules = schedules
        for sched in schedules:
            self.lstSchedules.Items.Add(sched.Name)

        self.lstSchedules.SelectionChanged        += self._on_schedule_selected
        self.lstSchedules.PreviewMouseLeftButtonUp += self._on_schedule_selected
        self.btnOk.Click                          += self._on_ok

        if self.txtSearch:
            self.txtSearch.TextChanged += self._on_search_schedule
        if self.txtSearchField:
            self.txtSearchField.TextChanged += self._on_search_field
        if self.btnCheckAllFields:
            self.btnCheckAllFields.Click   += lambda s, e: self._select_all_fields(True)
        if self.btnUncheckAllFields:
            self.btnUncheckAllFields.Click += lambda s, e: self._select_all_fields(False)
        if self.btnToggleAllFields:
            self.btnToggleAllFields.Click  += lambda s, e: self._toggle_all_fields()

        self.lstFields.PreviewMouseLeftButtonDown += self._on_mouse_down_fields

    def _show_validation(self, errors):
        if self.txtValidation:
            self.txtValidation.Text = u"\n".join(errors)
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Visible

    def _hide_validation(self):
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Collapsed

    def _on_search_schedule(self, sender, args):
        text = self.txtSearch.Text.lower()
        sel_name = self.lstSchedules.SelectedItem
        self.lstSchedules.Items.Clear()
        for sched in self.all_schedules:
            if not text or text in sched.Name.lower():
                self.lstSchedules.Items.Add(sched.Name)
        if sel_name:
            for i in range(self.lstSchedules.Items.Count):
                if self.lstSchedules.Items[i] == sel_name:
                    self.lstSchedules.SelectedIndex = i
                    break

    def _on_schedule_selected(self, sender, args):
        try:
            sel_name = self.lstSchedules.SelectedItem
            if not sel_name:
                return
            selected_sched = next(
                (s for s in self.all_schedules if s.Name == sel_name), None
            )
            if not selected_sched:
                return

            # Éviter de repeupler si c'est déjà la même nomenclature
            if (self.field_checkboxes and
                    self.lstFields.Items.Count > 0 and
                    self.lstSchedules.SelectedItem == sel_name and
                    len(self.field_checkboxes) == selected_sched.Definition.GetFieldCount()):
                return

            self.field_checkboxes = []
            self.lstFields.Items.Clear()
            sched_def = selected_sched.Definition

            for i in range(sched_def.GetFieldCount()):
                try:
                    field = sched_def.GetField(i)
                    name  = field.GetName()
                    w, _  = get_field_width(field)
                    if w is not None:
                        label = u"{} ({:.0f} mm)".format(name, feet_to_mm(w))
                    else:
                        label = u"{} (? mm)".format(name)

                    cb = System.Windows.Controls.CheckBox()
                    cb.Content   = label
                    cb.IsChecked = False
                    cb.Margin    = Thickness(0, 2, 0, 2)
                    self.field_checkboxes.append((cb, name, field))
                    self.lstFields.Items.Add(cb)
                except Exception:
                    continue

            self.lstFields.IsEnabled = True
            for btn in [self.btnCheckAllFields, self.btnUncheckAllFields, self.btnToggleAllFields]:
                if btn:
                    btn.IsEnabled = True
            if self.txtSearchField:
                self.txtSearchField.IsEnabled = True
                self.txtSearchField.Text = ""

            self._hide_validation()

        except Exception:
            log(u"Erreur _on_schedule_selected : {}".format(traceback.format_exc()))

    def _on_search_field(self, sender, args):
        text = self.txtSearchField.Text.lower()
        checked_names = {name for cb, name, _ in self.field_checkboxes
                         if cb.IsChecked == True}
        self.lstFields.Items.Clear()
        for cb, name, field in self.field_checkboxes:
            if not text or text in name.lower():
                cb.IsChecked = name in checked_names
                self.lstFields.Items.Add(cb)

    def _select_all_fields(self, value):
        for i in range(self.lstFields.Items.Count):
            try: self.lstFields.Items[i].IsChecked = value
            except Exception: pass

    def _toggle_all_fields(self):
        for i in range(self.lstFields.Items.Count):
            try:
                cb = self.lstFields.Items[i]
                cb.IsChecked = not (cb.IsChecked == True)
            except Exception: pass

    def _on_mouse_down_fields(self, sender, args):
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper
        try:
            current = args.OriginalSource
            clicked_index = -1
            while current is not None:
                if (hasattr(current, "__class__") and
                        current.__class__.__name__ == "ListBoxItem"):
                    clicked_index = (
                        self.lstFields.ItemContainerGenerator
                        .IndexFromContainer(current)
                    )
                    break
                try:    current = VisualTreeHelper.GetParent(current)
                except Exception: break
            if clicked_index < 0 or clicked_index >= self.lstFields.Items.Count:
                return
            clicked_cb = self.lstFields.Items[clicked_index]
        except Exception:
            return

        if Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift):
            try:
                last  = self.last_field_idx if self.last_field_idx >= 0 else 0
                start = min(last, clicked_index)
                end   = max(last, clicked_index)
                target_state = not (clicked_cb.IsChecked == True)
                for i in range(start, end + 1):
                    if i < self.lstFields.Items.Count:
                        self.lstFields.Items[i].IsChecked = target_state
                self.last_field_idx = clicked_index
                args.Handled = True
            except Exception: pass
            return

        try: self.last_field_idx = clicked_index
        except Exception: pass

    def _on_ok(self, sender, args):
        errors = []
        sched_name = self.lstSchedules.SelectedItem
        if not sched_name:
            errors.append(u"• Sélectionnez une nomenclature source.")

        selected_fields = [
            field for cb, name, field in self.field_checkboxes
            if cb.IsChecked == True
        ]
        if not selected_fields:
            errors.append(u"• Sélectionnez au moins une colonne à copier.")

        if errors:
            self._show_validation(errors)
            return

        self._hide_validation()
        self.result_schedule = next(
            (s for s in self.all_schedules if s.Name == sched_name), None
        )
        self.result_fields = selected_fields
        self.UI.Close()

    def show_dialog(self):
        self.UI.ShowDialog()
        return self.result_schedule, self.result_fields


# ─────────────────────────────────────────────────────────────────────────────
# Fenêtre 2 — Sélection des destinations
# ─────────────────────────────────────────────────────────────────────────────
class DestWindow(WPFWindow):
    def __init__(self, source, src_fields):
        self.source     = source
        self.src_fields = src_fields

        xaml_path = os.path.join(script_dir, "DestinationScheduleSelector.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())

        self.lstSchedules     = self.UI.FindName("lstSchedules")
        self.txtSearch        = self.UI.FindName("txtSearch")
        self.btnCheckAll      = self.UI.FindName("btnCheckAll")
        self.btnUncheckAll    = self.UI.FindName("btnUncheckAll")
        self.btnToggleAll     = self.UI.FindName("btnToggleAll")
        self.btnOk            = self.UI.FindName("btnOk")
        self.txtSourceName    = self.UI.FindName("txtSourceName")
        self.txtFieldName     = self.UI.FindName("txtFieldName")
        self.borderValidation = self.UI.FindName("borderValidation")
        self.txtValidation    = self.UI.FindName("txtValidation")

        if self.txtSourceName:
            self.txtSourceName.Text = source.Name
        if self.txtFieldName:
            names = [f.GetName() for f in src_fields]
            display = u", ".join(names[:4])
            if len(names) > 4:
                display += u" (+ {})".format(len(names) - 4)
            self.txtFieldName.Text = display

        self.sched_checkboxes  = []
        self.all_schedules     = []
        self.last_selected_idx = -1
        self.result            = None

        schedules = sorted(get_all_schedules(), key=lambda s: s.Name)
        for sched in schedules:
            if sched.Id == source.Id:
                continue
            self.all_schedules.append(sched)
            cb = System.Windows.Controls.CheckBox()
            cb.Content   = sched.Name
            cb.Margin    = Thickness(0, 2, 0, 2)
            cb.IsChecked = False
            self.sched_checkboxes.append((cb, sched))
            self.lstSchedules.Items.Add(cb)

        if self.btnCheckAll:   self.btnCheckAll.Click   += lambda s, e: self._select_all(True)
        if self.btnUncheckAll: self.btnUncheckAll.Click += lambda s, e: self._select_all(False)
        if self.btnToggleAll:  self.btnToggleAll.Click  += lambda s, e: self._toggle_all()
        if self.btnOk:         self.btnOk.Click         += self._on_ok
        if self.txtSearch:     self.txtSearch.TextChanged += self._on_search

        self.lstSchedules.PreviewMouseLeftButtonDown += self._on_mouse_down

    def _show_validation(self, errors):
        if self.txtValidation:
            self.txtValidation.Text = u"\n".join(errors)
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Visible

    def _hide_validation(self):
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Collapsed

    def _on_search(self, sender, args):
        text = self.txtSearch.Text.lower()
        checked_names = {sched.Name for cb, sched in self.sched_checkboxes
                         if cb.IsChecked == True}
        self.lstSchedules.Items.Clear()
        for cb, sched in self.sched_checkboxes:
            if not text or text in sched.Name.lower():
                cb.IsChecked = sched.Name in checked_names
                self.lstSchedules.Items.Add(cb)

    def _select_all(self, value):
        for i in range(self.lstSchedules.Items.Count):
            try: self.lstSchedules.Items[i].IsChecked = value
            except Exception: pass

    def _toggle_all(self):
        for i in range(self.lstSchedules.Items.Count):
            try:
                cb = self.lstSchedules.Items[i]
                cb.IsChecked = not (cb.IsChecked == True)
            except Exception: pass

    def _on_mouse_down(self, sender, args):
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper
        try:
            current = args.OriginalSource
            clicked_index = -1
            while current is not None:
                if (hasattr(current, "__class__") and
                        current.__class__.__name__ == "ListBoxItem"):
                    clicked_index = (
                        self.lstSchedules.ItemContainerGenerator
                        .IndexFromContainer(current)
                    )
                    break
                try: current = VisualTreeHelper.GetParent(current)
                except Exception: break
            if clicked_index < 0 or clicked_index >= self.lstSchedules.Items.Count:
                return
            clicked_cb = self.lstSchedules.Items[clicked_index]
        except Exception:
            return

        if Keyboard.IsKeyDown(Key.LeftCtrl) or Keyboard.IsKeyDown(Key.RightCtrl):
            try:
                clicked_cb.IsChecked = not (clicked_cb.IsChecked == True)
                self.last_selected_idx = clicked_index
                args.Handled = True
            except Exception: pass
            return

        if Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift):
            try:
                last  = self.last_selected_idx if self.last_selected_idx >= 0 else 0
                start = min(last, clicked_index)
                end   = max(last, clicked_index)
                target_state = not (clicked_cb.IsChecked == True)
                for i in range(start, end + 1):
                    if i < self.lstSchedules.Items.Count:
                        self.lstSchedules.Items[i].IsChecked = target_state
                self.last_selected_idx = clicked_index
                args.Handled = True
            except Exception: pass
            return

        try: self.last_selected_idx = clicked_index
        except Exception: pass

    def _on_ok(self, sender, args):
        checked_names = {sched.Name for cb, sched in self.sched_checkboxes
                         if cb.IsChecked == True}
        if not checked_names:
            self._show_validation([u"• Sélectionnez au moins une nomenclature cible."])
            return
        self._hide_validation()
        self.result = [
            sched for cb, sched in self.sched_checkboxes
            if sched.Name in checked_names
        ]
        self.UI.Close()

    def show_dialog(self):
        self.UI.ShowDialog()
        return self.result


# ─────────────────────────────────────────────────────────────────────────────
# Barre de progression
# ─────────────────────────────────────────────────────────────────────────────
class ProgressWindow(WPFWindow):
    def __init__(self, total):
        xaml_path = os.path.join(script_dir, "ProgressWindow.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())

        self.progressBar = self.UI.FindName("progressBar")
        self.txtStatus   = self.UI.FindName("txtStatus")
        self.txtCurrent  = self.UI.FindName("txtCurrent")
        self.total = total

        if self.progressBar:
            self.progressBar.Maximum = total
            self.progressBar.Value   = 0
        if self.txtCurrent:
            self.txtCurrent.Text = "0 / {}".format(total)

    def update(self, current, name):
        if self.progressBar: self.progressBar.Value = current
        if self.txtStatus:   self.txtStatus.Text    = name
        if self.txtCurrent:  self.txtCurrent.Text   = "{} / {}".format(current, self.total)
        Dispatcher.CurrentDispatcher.Invoke(
            DispatcherPriority.Background,
            System.Action(lambda: None)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    try:
        log("# Copier les largeurs de colonnes")
        log("---")

        # ── Étape 1 : SOURCE + COLONNES ──────────────────────────────────────
        win_src = SourceWindow()
        source, src_fields = win_src.show_dialog()
        if not source or not src_fields:
            log("Annulé (étape 1).")
            return

        log("## Source : **{}**".format(source.Name))
        log("## Colonnes sélectionnées : **{}**".format(len(src_fields)))
        for f in src_fields:
            w, _ = get_field_width(f)
            w_mm = feet_to_mm(w) if w is not None else 0.0
            log(u"- {} ({:.0f} mm)".format(f.GetName(), w_mm))
        log("---")

        # ── Étape 2 : DESTINATIONS ───────────────────────────────────────────
        win_dest = DestWindow(source, src_fields)
        dests = win_dest.show_dialog()
        if not dests:
            log("Annulé (étape 2).")
            return

        log("## Destinations : **{}**".format(len(dests)))
        for d in dests:
            log("- {}".format(d.Name))
        log("---")

        # ── Barre de progression ─────────────────────────────────────────────
        total_ops = len(src_fields) * len(dests)
        progress  = ProgressWindow(total_ops)
        progress.UI.Show()

        # ── Transaction ──────────────────────────────────────────────────────
        col_names_str = u", ".join(f.GetName() for f in src_fields)
        t = Transaction(doc, u"Copier largeurs colonnes : {}".format(col_names_str))
        t.Start()

        success_count = 0
        skipped_count = 0
        error_count   = 0
        op_idx        = 0

        for src_field in src_fields:
            fname = src_field.GetName()
            w, _  = get_field_width(src_field)
            w_mm  = feet_to_mm(w) if w is not None else 0.0
            log(u"### **{}** ({:.0f} mm)".format(fname, w_mm))

            for idx, target in enumerate(dests, 1):
                op_idx += 1
                progress.update(op_idx, u"{} → {}".format(fname, target.Name))
                log(u"  **[{}/{}]** {}".format(idx, len(dests), target.Name))

                try:
                    ok, msg = copy_column_width(src_field, target)
                    if ok:
                        success_count += 1
                        log(u"    ➤ Largeur copiée : {}".format(msg))
                    else:
                        skipped_count += 1
                        log(u"    ⚠ Ignoré : {}".format(msg))
                except Exception:
                    tb = traceback.format_exc()
                    error_count += 1
                    log(u"    ❌ Erreur : {}".format(tb))

        t.Commit()
        progress.UI.Close()

        log("---")
        log("## ✔ Terminé")
        log("**Copiées : {}** | **Ignorées : {}** | **Erreurs : {}**".format(
            success_count, skipped_count, error_count
        ))

        message = (
            u"{} colonne(s) × {} nomenclature(s)\n\n"
            u"  Copiées  : {}\n"
            u"  Ignorées : {}\n"
            u"  Erreurs  : {}"
        ).format(len(src_fields), len(dests), success_count, skipped_count, error_count)
        show_xaml_message(message, title=u"Terminé")

    except Exception:
        tb = traceback.format_exc()
        log(u"Erreur critique : {}".format(tb))
        show_alert(
            "Erreur critique",
            u"Une erreur est survenue :\n\n{}".format(tb)
        )


if __name__ == "__main__":
    main()
