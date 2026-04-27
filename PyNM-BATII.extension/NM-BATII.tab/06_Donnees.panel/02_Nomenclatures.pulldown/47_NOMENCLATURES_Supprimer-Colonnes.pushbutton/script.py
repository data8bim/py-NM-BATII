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


#__title__ = "Supprimer PARAMÈTRES"
#__doc__ = """Sélectionner des paramètres (colonnes) d'une nomenclature source
#et les supprimer en masse sur une sélection de nomenclatures de destination.
#Seuls les paramètres effectivement présents dans chaque nomenclature cible
#sont supprimés. Les paramètres absents sont ignorés sans erreur.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""

import clr
clr.AddReference("WindowsBase")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("System.Xaml")

import System
from System.Windows.Markup    import XamlReader
from System.Windows           import Thickness
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
    from dialogs.dialogs_styles_loader import load as load_dialog_styles
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
# Utilitaires
# ─────────────────────────────────────────────────────────────────────────────
def get_all_schedules():
    return [
        s for s in FilteredElementCollector(doc).OfClass(ViewSchedule)
        if not s.IsTemplate
    ]


def load_xaml(filename):
    """Charge un fichier XAML depuis le dossier du script."""
    xaml_path = os.path.join(script_dir, filename)
    with codecs.open(xaml_path, "r", "utf-8") as f:
        return XamlReader.Parse(f.read())


def show_confirm(src_name, field_names, dest_count):
    """
    Affiche la fenêtre de confirmation personnalisée.
    Retourne True si l'utilisateur clique sur Supprimer, False sinon.
    """
    try:
        ui = load_xaml("ConfirmWindow.xaml")

        txt_msg     = ui.FindName("txtMessage")
        txt_summary = ui.FindName("txtSummary")
        btn_confirm = ui.FindName("btnConfirm")
        btn_cancel  = ui.FindName("btnCancel")

        if txt_msg:
            txt_msg.Text = (
                u"Vous allez supprimer {} paramètre(s) "
                u"de {} nomenclature(s) cibles."
            ).format(len(field_names), dest_count)

        if txt_summary:
            txt_summary.Text = u"\n".join(u"• {}".format(n) for n in field_names)

        confirmed = [False]

        def on_confirm(s, e):
            confirmed[0] = True
            ui.Close()

        def on_cancel(s, e):
            ui.Close()

        if btn_confirm: btn_confirm.Click += on_confirm
        if btn_cancel:  btn_cancel.Click  += on_cancel

        ui.ShowDialog()
        return confirmed[0]

    except Exception:
        # Fallback vers forms.alert si le XAML est absent
        field_names_str = u", ".join(field_names)
        return forms.alert(
            u"Supprimer {} paramètre(s) :\n{}\n\nsur {} nomenclature(s) ?\n\nCette action est irréversible.".format(
                len(field_names), field_names_str, dest_count
            ),
            title=u"Confirmation", yes=True, no=True
        )


def show_result(message, title=u"Terminé"):
    try:
        ui = load_xaml("ResultWindow.xaml")
        ui.Title = title
        ui.FindName("txtMessage").Text = message
        ui.FindName("btnClose").Click += lambda s, e: ui.Close()
        ui.ShowDialog()
    except Exception:
        forms.alert(message, title=title)

# ─────────────────────────────────────────────────────────────────────────────
# Logique : suppression d'un champ dans une nomenclature cible
#
# Correspondance par priorité décroissante :
#   1. ParameterId + FieldType  (correspondance exacte)
#   2. ParameterId seul
#   3. Nom + FieldType
#   4. Nom seul
# ─────────────────────────────────────────────────────────────────────────────
def delete_field(src_field, target_sched):
    tgt_def   = target_sched.Definition
    src_name  = src_field.GetName()
    src_pid   = src_field.ParameterId
    src_ftype = src_field.FieldType
    valid_pid = (src_pid != ElementId.InvalidElementId)

    candidates = []
    for i in range(tgt_def.GetFieldCount()):
        try:
            f = tgt_def.GetField(i)
            candidates.append((f.FieldId, f.ParameterId, f.FieldType, f.GetName()))
        except Exception:
            pass

    field_id_to_remove = None

    # Priorité 1 : ParameterId + FieldType
    if valid_pid:
        for fid, pid, ftype, fname in candidates:
            if pid == src_pid and ftype == src_ftype:
                field_id_to_remove = fid
                break

    # Priorité 2 : ParameterId seul
    if field_id_to_remove is None and valid_pid:
        for fid, pid, ftype, fname in candidates:
            if pid == src_pid:
                field_id_to_remove = fid
                break

    # Priorité 3 : Nom + FieldType
    if field_id_to_remove is None:
        for fid, pid, ftype, fname in candidates:
            if fname == src_name and ftype == src_ftype:
                field_id_to_remove = fid
                break

    # Priorité 4 : Nom seul
    if field_id_to_remove is None:
        for fid, pid, ftype, fname in candidates:
            if fname == src_name:
                field_id_to_remove = fid
                break

    if field_id_to_remove is None:
        return False, u"Paramètre absent"

    try:
        tgt_def.RemoveField(field_id_to_remove)
        return True, u""
    except Exception as e:
        return False, u"Erreur : {}".format(str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Fenêtre 1 — SOURCE + paramètres à supprimer
# ─────────────────────────────────────────────────────────────────────────────
class SourceWindow(WPFWindow):
    def __init__(self):
        self.UI = load_xaml("SourceScheduleSelector.xaml")
        self.UI.Title = u"Supprimer des paramètres — Étape 1 / 2 : Source et paramètres"

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
        self.field_checkboxes = []
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

            self.field_checkboxes = []
            self.lstFields.Items.Clear()
            sched_def = selected_sched.Definition
            for i in range(sched_def.GetFieldCount()):
                try:
                    field = sched_def.GetField(i)
                    name  = field.GetName()
                    cb = System.Windows.Controls.CheckBox()
                    cb.Content   = name
                    cb.IsChecked = False
                    cb.Margin    = Thickness(0, 2, 0, 2)
                    self.field_checkboxes.append((cb, name, field))
                    self.lstFields.Items.Add(cb)
                except Exception:
                    continue

            self.lstFields.IsEnabled = True
            for btn in [self.btnCheckAllFields, self.btnUncheckAllFields,
                        self.btnToggleAllFields]:
                if btn: btn.IsEnabled = True
            if self.txtSearchField:
                self.txtSearchField.IsEnabled = True
                self.txtSearchField.Text = u""
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
            errors.append(u"• Sélectionnez au moins un paramètre à supprimer.")
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
# Fenêtre 2 — DESTINATIONS
# ─────────────────────────────────────────────────────────────────────────────
class DestWindow(WPFWindow):
    def __init__(self, source, src_fields):
        self.source     = source
        self.src_fields = src_fields

        self.UI = load_xaml("DestinationScheduleSelector.xaml")

        self.lstSchedules     = self.UI.FindName("lstSchedules")
        self.txtSearch        = self.UI.FindName("txtSearch")
        self.btnCheckAll      = self.UI.FindName("btnCheckAll")
        self.btnUncheckAll    = self.UI.FindName("btnUncheckAll")
        self.btnToggleAll     = self.UI.FindName("btnToggleAll")
        self.btnOk            = self.UI.FindName("btnOk")
        self.txtSourceName    = self.UI.FindName("txtSourceName")
        self.txtFieldName     = self.UI.FindName("txtFieldName")
        self.chkIncludeSource = self.UI.FindName("chkIncludeSource")
        self.borderValidation = self.UI.FindName("borderValidation")
        self.txtValidation    = self.UI.FindName("txtValidation")

        if self.txtSourceName:
            self.txtSourceName.Text = source.Name
        if self.txtFieldName:
            names   = [f.GetName() for f in src_fields]
            display = u", ".join(names[:4])
            if len(names) > 4:
                display += u" (+ {})".format(len(names) - 4)
            self.txtFieldName.Text = display

        self.sched_checkboxes  = []
        self.all_schedules     = []
        self.last_selected_idx = -1
        self.result            = None
        self.include_source    = False

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
        self.include_source = (self.chkIncludeSource is not None and
                               self.chkIncludeSource.IsChecked == True)
        self.UI.Close()

    def show_dialog(self):
        self.UI.ShowDialog()
        return self.result, self.include_source


# ─────────────────────────────────────────────────────────────────────────────
# Barre de progression
# ─────────────────────────────────────────────────────────────────────────────
class ProgressWindow(WPFWindow):
    def __init__(self, total):
        self.UI = load_xaml("ProgressWindow.xaml")
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
        if self.progressBar: self.progressBar.Value = current
        if self.txtStatus:   self.txtStatus.Text    = name
        if self.txtCurrent:  self.txtCurrent.Text   = u"{} / {}".format(current, self.total)
        Dispatcher.CurrentDispatcher.Invoke(
            DispatcherPriority.Background,
            System.Action(lambda: None)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    try:
        log("# Suppression de paramètres de nomenclature")
        log("---")

        # ── Étape 1 : SOURCE + PARAMÈTRES ────────────────────────────────────
        win_src = SourceWindow()
        source, src_fields = win_src.show_dialog()
        if not source or not src_fields:
            log("Annulé (étape 1).")
            return

        log(u"## Source : **{}**".format(source.Name))
        log(u"## Paramètres à supprimer : **{}**".format(len(src_fields)))
        for f in src_fields:
            log(u"- {}".format(f.GetName()))
        log("---")

        # ── Étape 2 : DESTINATIONS ───────────────────────────────────────────
        win_dest = DestWindow(source, src_fields)
        dests, include_source = win_dest.show_dialog()
        if not dests:
            log("Annulé (étape 2).")
            return

        log(u"## Destinations : **{}**".format(len(dests)))
        for d in dests:
            log(u"- {}".format(d.Name))
        if include_source:
            log(u"- *(source incluse)*")
        log("---")

        # ── Confirmation ─────────────────────────────────────────────────────
        field_names = [f.GetName() for f in src_fields]
        total_targets = len(dests) + (1 if include_source else 0)
        if not show_confirm(source.Name, field_names, total_targets):
            log("Annulé (confirmation).")
            return

        # ── Barre de progression ─────────────────────────────────────────────
        all_targets = list(dests) + ([source] if include_source else [])
        total_ops = len(src_fields) * len(all_targets)
        progress  = ProgressWindow(total_ops)
        progress.UI.Show()

        # ── Transaction ──────────────────────────────────────────────────────
        t = Transaction(doc, u"Supprimer paramètres : {}".format(u", ".join(field_names)))
        t.Start()

        success_count = 0
        skipped_count = 0
        error_count   = 0
        op_idx        = 0

        for src_field in src_fields:
            fname = src_field.GetName()
            log(u"### **{}**".format(fname))

            for idx, target in enumerate(all_targets, 1):
                op_idx += 1
                label = u"[SOURCE] {}".format(target.Name) if target.Id == source.Id else target.Name
                progress.update(op_idx, u"{} → {}".format(fname, label))
                log(u"  **[{}/{}]** {}".format(idx, len(all_targets), label))

                try:
                    ok, msg = delete_field(src_field, target)
                    if ok:
                        success_count += 1
                        log(u"    ➤ Supprimé")
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
        log(u"## ✔ Terminé")
        log(u"**Supprimés : {}** | **Ignorés : {}** | **Erreurs : {}**".format(
            success_count, skipped_count, error_count
        ))

        message = (
            u"{} paramètre(s) × {} nomenclature(s)\n\n"
            u"  Supprimés : {}\n"
            u"  Ignorés   : {}\n"
            u"  Erreurs   : {}"
        ).format(len(src_fields), len(all_targets), success_count, skipped_count, error_count)
        show_result(message, title=u"Terminé")

    except Exception:
        tb = traceback.format_exc()
        log(u"Erreur critique : {}".format(tb))
        forms.alert(
            u"Une erreur est survenue :\n\n{}".format(tb),
            title="Erreur critique"
        )


if __name__ == "__main__":
    main()
