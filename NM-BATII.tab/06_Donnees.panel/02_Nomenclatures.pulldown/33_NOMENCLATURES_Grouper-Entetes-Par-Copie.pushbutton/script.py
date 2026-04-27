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


#__title__ = "GOUPER ENTETES\npar copie"
#__doc__ = """Copier les regroupements d'en-tetes d'une nomenclature.
#Description: Copie les regroupements d'en-tetes d'une nomenclature source vers les nomenclatures de destinations sélectionnées.

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

# -------------------------
# Chemins / loader standard
# -------------------------
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir, os.pardir))
lib_dir    = os.path.join(ext_dir, "lib")
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

# -------------------------
# Logs
# -------------------------
doc = revit.doc

_cfg = load_config() or {}

def _parse_bool_like(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
    return None

ACTIVER_LOGS = True
try:
    parsed = _parse_bool_like(_cfg.get("activer_logs_scripts", True))
    if parsed is not None:
        ACTIVER_LOGS = parsed
except Exception:
    ACTIVER_LOGS = True

_output = None
if ACTIVER_LOGS:
    try:
        _output = script.get_output()
    except Exception:
        _output = None

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

# -------------------------
# Utilitaires Revit
# -------------------------
def get_all_schedules():
    collector = FilteredElementCollector(doc).OfClass(ViewSchedule)
    result = []
    for s in collector:
        if not s.IsTemplate:
            result.append(s)
    return result


def get_field_key(field):
    """Cle unique : ParameterId::FieldType, ou prefixe CALC/COMB."""
    if field.IsCalculatedField:
        return "CALC::{}".format(field.ColumnHeading)
    if field.IsCombinedParameterField:
        return "COMB::{}".format(field.ColumnHeading)
    return "{}::{}".format(field.ParameterId.IntegerValue, int(field.FieldType))


def get_col_to_fieldkey(schedule):
    sched_def = schedule.Definition
    result    = {}
    col_pos   = 0
    for i in range(sched_def.GetFieldCount()):
        field = sched_def.GetField(i)
        if not field.IsHidden:
            result[col_pos] = get_field_key(field)
            col_pos += 1
    return result


def get_fieldkey_to_col(schedule):
    sched_def = schedule.Definition
    result    = {}
    col_pos   = 0
    for i in range(sched_def.GetFieldCount()):
        field = sched_def.GetField(i)
        if not field.IsHidden:
            key         = get_field_key(field)
            result[key] = col_pos
            col_pos    += 1
    return result


def find_header_row(schedule):
    td        = schedule.GetTableData()
    sec       = td.GetSectionData(SectionType.Body)
    last_col  = sec.LastColumnNumber
    first_col = sec.FirstColumnNumber

    for row in range(sec.FirstRowNumber, min(sec.FirstRowNumber + 20, sec.LastRowNumber + 1)):
        is_clean = True
        for col in range(first_col, min(first_col + 10, last_col + 1)):
            merged = sec.GetMergedCell(row, col)
            if merged.Left != merged.Right:
                is_clean = False
                break
            if merged.Top != row:
                is_clean = False
                break
        if is_clean:
            return row
    return None


def read_existing_groups(schedule):
    td        = schedule.GetTableData()
    sec       = td.GetSectionData(SectionType.Body)
    last_col  = sec.LastColumnNumber
    first_col = sec.FirstColumnNumber
    header_row = find_header_row(schedule)
    if header_row is None:
        return []

    groups = []
    for row in range(sec.FirstRowNumber, header_row):
        visited = []
        col     = first_col
        while col <= last_col:
            if col in visited:
                col += 1
                continue
            merged = sec.GetMergedCell(row, col)
            if merged.Left != merged.Right and merged.Top == row:
                caption = schedule.GetCellText(SectionType.Body, row, merged.Left).strip()
                groups.append((row, merged.Left, merged.Right, caption))
                for c in range(merged.Left, merged.Right + 1):
                    visited.append(c)
                col = merged.Right + 1
            else:
                col += 1
    groups.sort(key=lambda x: -x[0])
    return groups


def ranges_overlap(left1, right1, left2, right2):
    return left1 <= right2 and left2 <= right1


def ungroup_overlapping(target, template_ranges_in_target):
    existing = read_existing_groups(target)
    if not existing:
        log("  Aucun groupe existant dans la cible")
        return

    to_ungroup = []
    for row, left_e, right_e, caption in existing:
        for left_t, right_t in template_ranges_in_target:
            if ranges_overlap(left_e, right_e, left_t, right_t):
                to_ungroup.append((row, left_e, right_e, caption))
                break

    if not to_ungroup:
        log("  Aucun groupe existant a supprimer")
        return

    to_ungroup.sort(key=lambda x: -x[0])
    ungrouped = 0
    for row, left_e, right_e, caption in to_ungroup:
        try:
            can = target.CanUngroupHeaders(0, left_e, 0, right_e)
            if can:
                with Transaction(doc, "Desgrouper : " + caption) as t:
                    t.Start()
                    target.UngroupHeaders(0, left_e, 0, right_e)
                    t.Commit()
                ungrouped += 1
            else:
                try:
                    can2 = target.CanUngroupHeaders(row, left_e, row, right_e)
                    if can2:
                        with Transaction(doc, "Desgrouper : " + caption) as t:
                            t.Start()
                            target.UngroupHeaders(row, left_e, row, right_e)
                            t.Commit()
                        ungrouped += 1
                except Exception:
                    pass
        except Exception as e:
            log("  [UNGROUP ERREUR] '{}' : {}".format(caption, e))
    log("  {} groupe(s) supprime(s)".format(ungrouped))


def read_groups_from_template(template):
    log("## Lecture des groupes : **{}**".format(template.Name))
    col_to_key = get_col_to_fieldkey(template)
    log("  Champs visibles : **{}**".format(len(col_to_key)))

    header_row = find_header_row(template)
    if header_row is None:
        log("  **ERREUR** : impossible de trouver la ligne des noms de colonnes")
        return []

    log("  Lignes de groupes : rows 0 a {}".format(header_row - 1))

    td        = template.GetTableData()
    sec       = td.GetSectionData(SectionType.Body)
    last_col  = sec.LastColumnNumber
    first_col = sec.FirstColumnNumber
    all_groups = []

    for row in range(sec.FirstRowNumber, header_row):
        visited = []
        col     = first_col
        while col <= last_col:
            if col in visited:
                col += 1
                continue
            merged = sec.GetMergedCell(row, col)
            if merged.Left != merged.Right and merged.Top == row:
                caption = template.GetCellText(SectionType.Body, row, merged.Left).strip()
                if caption:
                    keys_in_group = []
                    for c in range(merged.Left, merged.Right + 1):
                        k = col_to_key.get(c, "")
                        if k:
                            keys_in_group.append(k)
                    if keys_in_group:
                        all_groups.append((row, caption, keys_in_group,
                                           merged.Left, merged.Right))
                        log("  [N{}] **'{}'** cols {}-{} ({} champs)".format(
                            row, caption, merged.Left, merged.Right, len(keys_in_group)))
                    else:
                        log("  [IGNORE] '{}' : aucune cle trouvee".format(caption))
                for c in range(merged.Left, merged.Right + 1):
                    visited.append(c)
                col = merged.Right + 1
            else:
                col += 1

    all_groups.sort(key=lambda x: -x[0])
    log("  **Total : {} groupe(s)**".format(len(all_groups)))
    return all_groups


def apply_groups_to_schedule(target, all_groups):
    applied = 0
    skipped = 0
    fieldkey_to_col = get_fieldkey_to_col(target)

    template_ranges_in_target = []
    for item in all_groups:
        keys_in_group = item[2]
        positions = []
        for k in keys_in_group:
            col = fieldkey_to_col.get(k)
            if col is not None:
                positions.append(col)
        if len(positions) >= 2:
            template_ranges_in_target.append((min(positions), max(positions)))
        elif len(positions) == 1:
            template_ranges_in_target.append((positions[0], positions[0]))

    if template_ranges_in_target:
        log("  **Nettoyage des groupes existants...**")
        ungroup_overlapping(target, template_ranges_in_target)

    log("  **Application des groupes...**")
    for item in all_groups:
        row           = item[0]
        caption       = item[1]
        keys_in_group = item[2]

        positions_in_target = []
        nb_found   = 0
        nb_missing = 0
        for k in keys_in_group:
            col = fieldkey_to_col.get(k)
            if col is not None:
                positions_in_target.append(col)
                nb_found += 1
            else:
                nb_missing += 1

        if nb_found == 0:
            log("  [IGNORE][N{}] '{}' : aucun champ present".format(row, caption))
            skipped += 1
            continue
        if nb_found == 1:
            log("  [IGNORE][N{}] '{}' : 1 seul champ, groupe impossible".format(row, caption))
            skipped += 1
            continue
        if nb_missing > 0:
            log("  [INFO][N{}] '{}' : {}/{} champs presents, {} absents".format(
                row, caption, nb_found, len(keys_in_group), nb_missing))

        left  = min(positions_in_target)
        right = max(positions_in_target)

        try:
            can = target.CanGroupHeaders(0, left, 0, right)
            if can:
                with Transaction(doc, "Grouper : " + caption) as t:
                    t.Start()
                    target.GroupHeaders(0, left, 0, right, caption)
                    t.Commit()
                log("  [OK][N{}] **'{}'** cols {}-{}".format(row, caption, left, right))
                applied += 1
            else:
                log("  [SKIP][N{}] '{}' : CanGroupHeaders=False cols {}-{}".format(
                    row, caption, left, right))
                skipped += 1
        except Exception as e:
            log("  [ERREUR][N{}] '{}' : {}".format(row, caption, e))
            skipped += 1

    return applied, skipped


# -------------------------
# Interface Source
# -------------------------
class SourceWindow(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(script_dir, "SourceScheduleSelector.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())

        self.lstSchedules = self.UI.FindName("lstSchedules")
        self.txtSearch    = self.UI.FindName("txtSearch")
        self.btnOk        = self.UI.FindName("btnOk")

        self.all_schedules = []
        self.result        = None

        schedules = get_all_schedules()
        schedules.sort(key=lambda s: s.Name)
        self.all_schedules = schedules

        for sched in schedules:
            self.lstSchedules.Items.Add(sched.Name)

        self.btnOk.Click += self._on_ok
        if self.txtSearch:
            self.txtSearch.TextChanged += self._on_search

    def _on_search(self, sender, args):
        text          = self.txtSearch.Text.lower()
        selected_name = None
        if self.lstSchedules.SelectedIndex >= 0:
            selected_name = str(self.lstSchedules.SelectedItem)

        self.lstSchedules.Items.Clear()
        new_index = -1
        for sched in self.all_schedules:
            if not text or text in sched.Name.lower():
                self.lstSchedules.Items.Add(sched.Name)
                if selected_name and sched.Name == selected_name:
                    new_index = self.lstSchedules.Items.Count - 1
        if new_index >= 0:
            self.lstSchedules.SelectedIndex = new_index

    def _on_ok(self, sender, args):
        if self.lstSchedules.SelectedIndex < 0:
            forms.alert("Selectionnez une nomenclature source.")
            return
        selected_name = str(self.lstSchedules.SelectedItem)
        for sched in self.all_schedules:
            if sched.Name == selected_name:
                self.result = sched
                break
        self.UI.Close()

    def show_dialog(self):
        self.UI.ShowDialog()
        return self.result


# -------------------------
# Interface Destinations
# Style identique a la section Categories de CreateSchedules
# -------------------------
class DestWindow(WPFWindow):
    def __init__(self, source):
        self.source = source
        xaml_path   = os.path.join(script_dir, "DestinationScheduleSelector.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())

        self.lstSchedules  = self.UI.FindName("lstSchedules")
        self.txtSearch     = self.UI.FindName("txtSearch")
        self.btnCheckAll   = self.UI.FindName("btnCheckAll")
        self.btnUncheckAll = self.UI.FindName("btnUncheckAll")
        self.btnToggleAll  = self.UI.FindName("btnToggleAll")
        self.btnOk         = self.UI.FindName("btnOk")

        # Liste de tuples (CheckBox, schedule) — meme pattern que CreateSchedules
        self.sched_checkboxes  = []
        self.all_schedules     = []
        self.last_selected_idx = -1
        self.result            = None

        schedules = get_all_schedules()
        schedules.sort(key=lambda s: s.Name)

        for sched in schedules:
            if sched.Id == source.Id:
                continue
            self.all_schedules.append(sched)
            cb           = System.Windows.Controls.CheckBox()
            cb.Content   = sched.Name
            cb.Margin    = Thickness(0, 2, 0, 2)
            cb.IsChecked = False
            self.sched_checkboxes.append((cb, sched))
            self.lstSchedules.Items.Add(cb)

        # Boutons
        if self.btnCheckAll:
            self.btnCheckAll.Click   += lambda s, e: self._select_all(True)
        if self.btnUncheckAll:
            self.btnUncheckAll.Click += lambda s, e: self._select_all(False)
        if self.btnToggleAll:
            self.btnToggleAll.Click  += lambda s, e: self._toggle_all()
        if self.btnOk:
            self.btnOk.Click += self._on_ok

        # Recherche
        if self.txtSearch:
            self.txtSearch.TextChanged += self._on_search

        # CTRL+clic et MAJ+clic — meme pattern que CreateSchedules
        self.lstSchedules.PreviewMouseLeftButtonDown += self._on_mouse_down

    def _select_all(self, value):
        """Cocher/decocher toutes les checkboxes VISIBLES."""
        for i in range(self.lstSchedules.Items.Count):
            cb = self.lstSchedules.Items[i]
            try:
                cb.IsChecked = value
            except Exception:
                pass

    def _toggle_all(self):
        """Inverser toutes les checkboxes VISIBLES."""
        for i in range(self.lstSchedules.Items.Count):
            cb = self.lstSchedules.Items[i]
            try:
                cb.IsChecked = not cb.IsChecked
            except Exception:
                pass

    def _on_search(self, sender, args):
        """Filtrer la liste selon le texte, en conservant les selections."""
        text = self.txtSearch.Text.lower()

        # Sauvegarder les noms coches
        checked_names = set()
        for cb, sched in self.sched_checkboxes:
            if cb.IsChecked:
                checked_names.add(sched.Name)

        self.lstSchedules.Items.Clear()
        for cb, sched in self.sched_checkboxes:
            if not text or text in sched.Name.lower():
                # Restaurer l'etat coche
                cb.IsChecked = sched.Name in checked_names
                self.lstSchedules.Items.Add(cb)

    def _on_mouse_down(self, sender, args):
        """Gerer CTRL+clic et MAJ+clic — identique a CreateSchedules."""
        from System.Windows.Input import Keyboard, Key
        from System.Windows.Media import VisualTreeHelper

        try:
            clicked_item  = args.OriginalSource
            current       = clicked_item
            clicked_index = -1

            while current is not None:
                if hasattr(current, "__class__") and current.__class__.__name__ == "ListBoxItem":
                    clicked_index = self.lstSchedules.ItemContainerGenerator.IndexFromContainer(current)
                    break
                try:
                    current = VisualTreeHelper.GetParent(current)
                except Exception:
                    break

            if clicked_index < 0 or clicked_index >= self.lstSchedules.Items.Count:
                return

            clicked_cb = self.lstSchedules.Items[clicked_index]

        except Exception:
            return

        # CTRL+clic : toggle uniquement la checkbox cliquee
        if Keyboard.IsKeyDown(Key.LeftCtrl) or Keyboard.IsKeyDown(Key.RightCtrl):
            try:
                clicked_cb.IsChecked       = not clicked_cb.IsChecked
                self.last_selected_idx     = clicked_index
                args.Handled               = True
            except Exception:
                pass
            return

        # MAJ+clic : cocher/decocher une plage
        if Keyboard.IsKeyDown(Key.LeftShift) or Keyboard.IsKeyDown(Key.RightShift):
            try:
                last = self.last_selected_idx if self.last_selected_idx >= 0 else 0
                start        = min(last, clicked_index)
                end          = max(last, clicked_index)
                target_state = not clicked_cb.IsChecked
                for i in range(start, end + 1):
                    if i < self.lstSchedules.Items.Count:
                        self.lstSchedules.Items[i].IsChecked = target_state
                self.last_selected_idx = clicked_index
                args.Handled           = True
            except Exception:
                pass
            return

        # Clic normal : mettre a jour le dernier index
        try:
            self.last_selected_idx = clicked_index
        except Exception:
            pass

    def _on_ok(self, sender, args):
        checked_names = set()
        for cb, sched in self.sched_checkboxes:
            if cb.IsChecked:
                checked_names.add(sched.Name)

        if not checked_names:
            forms.alert("Selectionnez au moins une nomenclature cible.")
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
        self.txtStatus   = self.UI.FindName("txtStatus")
        self.txtCurrent  = self.UI.FindName("txtCurrent")
        self.total       = total

        if self.progressBar:
            self.progressBar.Maximum = total
            self.progressBar.Value   = 0
        if self.txtCurrent:
            self.txtCurrent.Text = "0 / {}".format(total)

    def update(self, current, name):
        if self.progressBar:
            self.progressBar.Value = current
        if self.txtStatus:
            self.txtStatus.Text = name
        if self.txtCurrent:
            self.txtCurrent.Text = "{} / {}".format(current, self.total)
        Dispatcher.CurrentDispatcher.Invoke(
            DispatcherPriority.Background,
            System.Action(lambda: None)
        )

    def show(self):
        if self.UI:
            self.UI.Show()

    def close(self):
        if self.UI:
            try:
                self.UI.Close()
            except Exception:
                pass


# -------------------------
# Boite de dialogue résultat
# -------------------------
def show_result(message, title="Termine"):
    xaml_path = os.path.join(script_dir, "ResultWindow.xaml")
    if not os.path.exists(xaml_path):
        forms.alert(message, title=title)
        return
    try:
        with codecs.open(xaml_path, "r", "utf-8") as f:
            result_ui = XamlReader.Parse(f.read())
        result_ui.Title = title
        txt = result_ui.FindName("txtMessage")
        btn = result_ui.FindName("btnClose")
        if txt:
            txt.Text = message
        if btn:
            btn.Click += lambda s, e: result_ui.Close()
        result_ui.ShowDialog()
    except Exception:
        forms.alert(message, title=title)


# -------------------------
# Main
# -------------------------
def main():
    log("# Grouper les en-têtes de nomenclatures")
    log("---")

    # Etape 1 : selection de la source
    win_src = SourceWindow()
    source  = win_src.show_dialog()
    if not source:
        log("Annule par l'utilisateur.")
        return

    log("## Source : **{}**".format(source.Name))

    # Lire les groupes de la source
    all_groups = read_groups_from_template(source)

    if not all_groups:
        forms.alert(
            "Aucun groupe d'en-têtes trouve dans la nomenclature source.\n"
            "Creez d'abord les groupes manuellement dans Revit.",
            title="Aucun groupe"
        )
        return

    log("**{} groupe(s) lu(s) dans la source**".format(len(all_groups)))

    # Etape 2 : selection des destinations
    win_dest = DestWindow(source)
    targets  = win_dest.show_dialog()
    if not targets:
        log("Annule par l'utilisateur.")
        return

    log("## Destinations : **{}**".format(len(targets)))
    for t in targets:
        log("  - {}".format(t.Name))

    # Barre de progression
    progress = ProgressWindow(len(targets))
    progress.show()

    # Application
    log("---")
    log("# Application des groupements")
    log("---")

    total_applied = 0
    total_skipped = 0
    errors        = 0

    for idx, target in enumerate(targets):
        progress.update(idx + 1, target.Name)
        log("### -> **{}**".format(target.Name))
        try:
            applied, skipped = apply_groups_to_schedule(target, all_groups)
            total_applied   += applied
            total_skipped   += skipped
            log("  {} applique(s), {} ignore(s)".format(applied, skipped))
        except Exception as e:
            log("  **ERREUR** : {}".format(e))
            errors += 1

    progress.close()

    log("---")
    log("## Termine")
    log("- Nomenclatures traitees : **{}**".format(len(targets)))
    log("- Groupes appliques : **{}**".format(total_applied))
    log("- Groupes ignores : **{}**".format(total_skipped))
    if errors > 0:
        log("- **Erreurs : {}**".format(errors))

    msg = u"{} nomenclature(s) traitee(s)".format(len(targets))
    if errors > 0:
        msg += u"\n{} erreur(s)".format(errors)

    show_result(msg, title="Groupements termines")


if __name__ == "__main__":
    main()
