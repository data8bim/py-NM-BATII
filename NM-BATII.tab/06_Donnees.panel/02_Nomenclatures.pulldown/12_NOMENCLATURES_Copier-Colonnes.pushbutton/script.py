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


#__title__ = "Copier\nCOLONNES"
#__doc__ = """Copie les colonnes d'une nomenclature
#Description: Copie les colonnes d’une nomenclature source vers les nomenclatures de destination sélectionnées, avec possibilité de réorganiser l’ordre des colonnes.

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
from Autodesk.Revit.DB import ScheduleFieldId   # import explicite pour DotNetList[ScheduleFieldId]
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
    if isinstance(v, bool):   return v
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
# Fonctions utilitaires
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


def show_warning():
    """
    Affiche la fenêtre d'avertissement avant l'exécution du script.
    Retourne True si l'utilisateur clique sur Continuer, False s'il annule.
    """
    xaml_path = os.path.join(script_dir, "WarningWindow.xaml")
    if not os.path.exists(xaml_path):
        return forms.alert(
            u"AVERTISSEMENT\n\n"
            u"Ce script ne copie PAS :\n"
            u"  • Les paramètres calculés\n"
            u"  • Les paramètres combinés\n\n"
            u"Ces paramètres devront être recréés manuellement.\n\n"
            u"Continuer ?",
            title=u"Avertissement", yes=True, no=True
        )
    try:
        with codecs.open(xaml_path, "r", "utf-8") as f:
            window = XamlReader.Parse(f.read())

        confirmed       = [False]
        btn_continuer   = window.FindName("btnContinuer")
        btn_annuler     = window.FindName("btnAnnuler")

        def on_continuer(s, e):
            confirmed[0] = True
            window.Close()

        def on_annuler(s, e):
            window.Close()

        if btn_continuer: btn_continuer.Click += on_continuer
        if btn_annuler:   btn_annuler.Click   += on_annuler

        window.ShowDialog()
        return confirmed[0]

    except Exception:
        log(u"Erreur show_warning : {}".format(traceback.format_exc()))
        return True   # En cas d'erreur XAML on continue quand même


def _is_param_applicable(param_id, target_cat_id, field_name):
    """
    Vérifie si le paramètre est utilisable dans la catégorie de la nomenclature cible.
    Inspiré de is_parameter_applicable_to_category du script de création.

    - param_id.IntegerValue < 0  → BuiltInParameter → toujours applicable
    - Paramètre partagé          → vérifier les ParameterBindings :
        applicable si lié à la catégorie cible OU à ProjectInformation
    """
    try:
        if param_id.IntegerValue < 0:
            return True   # BuiltInParameter : toujours applicable

        if param_id == ElementId.InvalidElementId:
            return False

        bm = doc.ParameterBindings
        it = bm.ForwardIterator()
        it.Reset()
        project_info_id = ElementId(BuiltInCategory.OST_ProjectInformation)
        param_found = False

        while it.MoveNext():
            defn    = it.Key
            binding = it.Current

            # Correspondance par Id ou par nom
            match = (defn.Id == param_id)
            if not match:
                try:
                    match = (defn.Name == field_name)
                except Exception:
                    pass
            if not match:
                continue

            param_found = True

            if hasattr(binding, 'Categories') and binding.Categories is not None:
                for cat in binding.Categories:
                    try:
                        if cat.Id == project_info_id or cat.Id == target_cat_id:
                            return True
                    except Exception:
                        pass
                return False  # lié à d'autres catégories (Pièce, Espace…)

        if not param_found:
            # Paramètre introuvable dans les bindings → probablement BuiltIn
            return True

        return False

    except Exception:
        return True   # en cas d'erreur on laisse l'API trancher


def copy_single_field(src_field, target_sched, position_mode, ref_field_name=None):
    """
    Copie un seul champ dans target_sched et le positionne.

    position_mode : "first" | "last" | "after" | "before"
    ref_field_name : nom du paramètre de référence (pour "after" / "before")

    Retourne (success: bool, message: str)
    """
    tgt_def       = target_sched.Definition
    param_id      = src_field.ParameterId
    field_type    = src_field.FieldType
    field_name    = src_field.GetName()
    target_cat_id = tgt_def.CategoryId

    # ── Vérifier si le paramètre est déjà présent avec le MÊME FieldType ─────
    # On compare ParameterId + FieldType : le même paramètre peut légitimement
    # exister plusieurs fois avec des types différents (Instance, ProjectInfo,
    # Pièce, Espace…), ce n'est pas un doublon.
    for i in range(tgt_def.GetFieldCount()):
        f = tgt_def.GetField(i)
        if f.ParameterId == param_id and f.FieldType == field_type:
            return False, u"Paramètre déjà présent (même type)"

    # ── Vérifier que le paramètre est applicable à la catégorie cible ─────────
    if not _is_param_applicable(param_id, target_cat_id, field_name):
        return False, u"Non applicable à la catégorie cible"

    # ── Ajouter le paramètre ──────────────────────────────────────────────────
    # Essais successifs : type source → Instance → ElementType
    new_field = None
    for ft in [field_type, ScheduleFieldType.Instance, ScheduleFieldType.ElementType]:
        # Ne pas réessayer un type déjà présent
        already = any(
            tgt_def.GetField(i).ParameterId == param_id and
            tgt_def.GetField(i).FieldType   == ft
            for i in range(tgt_def.GetFieldCount())
        )
        if already:
            continue
        try:
            new_field = tgt_def.AddField(ft, param_id)
            break
        except Exception:
            continue

    if new_field is None:
        return False, u"Impossible d'ajouter le paramètre"

    # ── Repositionner ────────────────────────────────────────────────────────
    # AddField place toujours le champ en dernière position.
    # Pour "last", rien à faire.
    if position_mode == "last":
        return True, ""

    field_count = tgt_def.GetFieldCount()  # inclut maintenant le nouveau champ

    # Construire la liste ordonnée des FieldId (sans le nouveau champ)
    ordered_ids = []
    for i in range(field_count):
        fid = tgt_def.GetField(i).FieldId
        if fid != new_field.FieldId:
            ordered_ids.append(fid)

    if position_mode == "first":
        ordered_ids.insert(0, new_field.FieldId)
    elif position_mode in ("after", "before") and ref_field_name:
        ref_idx = -1
        for i, fid in enumerate(ordered_ids):
            if tgt_def.GetField(fid).GetName() == ref_field_name:
                ref_idx = i
                break
        if ref_idx >= 0:
            insert_at = ref_idx + 1 if position_mode == "after" else ref_idx
            ordered_ids.insert(insert_at, new_field.FieldId)
        else:
            # Référence introuvable → on laisse en dernière position
            ordered_ids.append(new_field.FieldId)
    else:
        ordered_ids.append(new_field.FieldId)

    # Appliquer le nouvel ordre via SetFieldOrder
    from System.Collections.Generic import List as DotNetList
    cs_list = DotNetList[ScheduleFieldId]()
    for fid in ordered_ids:
        cs_list.Add(fid)
    tgt_def.SetFieldOrder(cs_list)

    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Fenêtre 1 — Sélection de la nomenclature SOURCE et du paramètre
# ─────────────────────────────────────────────────────────────────────────────
class SourceWindow(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(script_dir, "SourceScheduleSelector.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())

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

        # Données
        self.all_schedules    = []
        self.field_checkboxes = []   # [(CheckBox, name, ScheduleField), ...]
        self.last_field_idx   = -1   # pour MAJ+clic
        self.result_schedule  = None
        self.result_fields    = []   # liste de ScheduleField sélectionnés

        # Charger les nomenclatures
        schedules = sorted(get_all_schedules(), key=lambda s: s.Name)
        self.all_schedules = schedules
        for sched in schedules:
            self.lstSchedules.Items.Add(sched.Name)

        # Événements
        self.lstSchedules.SelectionChanged += self._on_schedule_selected
        self.btnOk.Click                   += self._on_ok

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

        # MAJ+clic sur la liste des paramètres
        self.lstFields.PreviewMouseLeftButtonDown += self._on_mouse_down_fields

    # ── Validation inline ─────────────────────────────────────────────────────
    def _show_validation(self, errors):
        if self.txtValidation:
            self.txtValidation.Text = "\n".join(errors)
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Visible

    def _hide_validation(self):
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Collapsed

    # ── Recherche nomenclature ────────────────────────────────────────────────
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

    # ── Sélection d'une nomenclature → peuple la liste des paramètres ─────────
    def _on_schedule_selected(self, sender, args):
        sel_name = self.lstSchedules.SelectedItem
        if not sel_name:
            return
        selected_sched = next(
            (s for s in self.all_schedules if s.Name == sel_name), None
        )
        if not selected_sched:
            return

        # Construire les cases à cocher des paramètres
        self.field_checkboxes = []
        self.lstFields.Items.Clear()
        sched_def = selected_sched.Definition
        for i in range(sched_def.GetFieldCount()):
            field = sched_def.GetField(i)
            name  = field.GetName()
            cb = System.Windows.Controls.CheckBox()
            cb.Content   = name
            cb.IsChecked = False
            cb.Margin    = Thickness(0, 2, 0, 2)
            self.field_checkboxes.append((cb, name, field))
            self.lstFields.Items.Add(cb)

        # Activer la colonne paramètres
        self.lstFields.IsEnabled = True
        for btn in [self.btnCheckAllFields, self.btnUncheckAllFields, self.btnToggleAllFields]:
            if btn:
                btn.IsEnabled = True
        if self.txtSearchField:
            self.txtSearchField.IsEnabled = True
            self.txtSearchField.Text = ""

        self._hide_validation()

    # ── Recherche paramètre ───────────────────────────────────────────────────
    def _on_search_field(self, sender, args):
        text = self.txtSearchField.Text.lower()
        checked_names = {name for cb, name, _ in self.field_checkboxes
                         if cb.IsChecked == True}
        self.lstFields.Items.Clear()
        for cb, name, field in self.field_checkboxes:
            if not text or text in name.lower():
                cb.IsChecked = name in checked_names
                self.lstFields.Items.Add(cb)

    # ── Sélection tout / aucun / inverser (paramètres) ────────────────────────
    def _select_all_fields(self, value):
        for i in range(self.lstFields.Items.Count):
            try:
                self.lstFields.Items[i].IsChecked = value
            except Exception:
                pass

    def _toggle_all_fields(self):
        for i in range(self.lstFields.Items.Count):
            try:
                cb = self.lstFields.Items[i]
                cb.IsChecked = not (cb.IsChecked == True)
            except Exception:
                pass

    # ── MAJ+clic sur la liste des paramètres ─────────────────────────────────
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
                # L'état cible = inverse de la case cliquée
                target_state = not (clicked_cb.IsChecked == True)
                for i in range(start, end + 1):
                    if i < self.lstFields.Items.Count:
                        self.lstFields.Items[i].IsChecked = target_state
                self.last_field_idx = clicked_index
                args.Handled = True
            except Exception:
                pass
            return

        # Clic normal : mémoriser l'index pour un futur MAJ+clic
        try:
            self.last_field_idx = clicked_index
        except Exception:
            pass

    # ── OK ────────────────────────────────────────────────────────────────────
    def _on_ok(self, sender, args):
        errors = []
        sched_name = self.lstSchedules.SelectedItem
        if not sched_name:
            errors.append("• Sélectionnez une nomenclature source.")

        selected_fields = [
            field for cb, name, field in self.field_checkboxes
            if cb.IsChecked == True
        ]
        if not selected_fields:
            errors.append("• Sélectionnez au moins un paramètre à copier.")

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
# Fenêtre 2 — Sélection des destinations et de la position
# ─────────────────────────────────────────────────────────────────────────────
class DestWindow(WPFWindow):
    def __init__(self, source, src_fields, all_dest_field_names):
        self.source     = source
        self.src_fields = src_fields   # liste de ScheduleField

        xaml_path = os.path.join(script_dir, "DestinationScheduleSelector.xaml")
        with codecs.open(xaml_path, "r", "utf-8") as f:
            self.UI = XamlReader.Parse(f.read())

        # Éléments UI
        self.lstSchedules     = self.UI.FindName("lstSchedules")
        self.txtSearch        = self.UI.FindName("txtSearch")
        self.btnCheckAll      = self.UI.FindName("btnCheckAll")
        self.btnUncheckAll    = self.UI.FindName("btnUncheckAll")
        self.btnToggleAll     = self.UI.FindName("btnToggleAll")
        self.btnOk            = self.UI.FindName("btnOk")
        self.rbFirst          = self.UI.FindName("rbFirst")
        self.rbLast           = self.UI.FindName("rbLast")
        self.rbAfter          = self.UI.FindName("rbAfter")
        self.rbBefore         = self.UI.FindName("rbBefore")
        self.cboRefField      = self.UI.FindName("cboRefField")
        self.txtRefHint       = self.UI.FindName("txtRefHint")
        self.txtSourceName    = self.UI.FindName("txtSourceName")
        self.txtFieldName     = self.UI.FindName("txtFieldName")
        self.borderValidation = self.UI.FindName("borderValidation")
        self.txtValidation    = self.UI.FindName("txtValidation")

        # Bandeau info
        if self.txtSourceName:
            self.txtSourceName.Text = source.Name
        if self.txtFieldName:
            names = [f.GetName() for f in src_fields]
            display = u", ".join(names[:4])
            if len(names) > 4:
                display += u" (+ {})".format(len(names) - 4)
            self.txtFieldName.Text = display

        # Données
        self.sched_checkboxes  = []
        self.all_schedules     = []
        self.last_selected_idx = -1
        self.result            = None
        self.position_mode     = "last"
        self.ref_field_name    = None

        # Nomenclatures cibles
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

        # ComboBox de référence
        for name in all_dest_field_names:
            self.cboRefField.Items.Add(name)

        # Position par défaut
        if self.rbLast:     self.rbLast.IsChecked = True
        if self.cboRefField: self.cboRefField.IsEnabled = False
        if self.txtRefHint:  self.txtRefHint.Visibility = System.Windows.Visibility.Visible

        # Événements
        if self.btnCheckAll:   self.btnCheckAll.Click   += lambda s, e: self._select_all(True)
        if self.btnUncheckAll: self.btnUncheckAll.Click += lambda s, e: self._select_all(False)
        if self.btnToggleAll:  self.btnToggleAll.Click  += lambda s, e: self._toggle_all()
        if self.btnOk:         self.btnOk.Click         += self._on_ok
        if self.txtSearch:     self.txtSearch.TextChanged += self._on_search

        for rb in [self.rbFirst, self.rbLast, self.rbAfter, self.rbBefore]:
            if rb: rb.Checked += self._on_position_changed

        self.lstSchedules.PreviewMouseLeftButtonDown += self._on_mouse_down

    # ── Validation inline ─────────────────────────────────────────────────────
    def _show_validation(self, errors):
        if self.txtValidation:
            self.txtValidation.Text = "\n".join(errors)
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Visible

    def _hide_validation(self):
        if self.borderValidation:
            self.borderValidation.Visibility = System.Windows.Visibility.Collapsed

    # ── Recherche ─────────────────────────────────────────────────────────────
    def _on_search(self, sender, args):
        text = self.txtSearch.Text.lower()
        checked_names = {sched.Name for cb, sched in self.sched_checkboxes
                         if cb.IsChecked == True}
        self.lstSchedules.Items.Clear()
        for cb, sched in self.sched_checkboxes:
            if not text or text in sched.Name.lower():
                cb.IsChecked = sched.Name in checked_names
                self.lstSchedules.Items.Add(cb)

    # ── Sélection tout / aucun / inverser ─────────────────────────────────────
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

    # ── CTRL+clic / MAJ+clic ──────────────────────────────────────────────────
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

    # ── Radio position ────────────────────────────────────────────────────────
    def _on_position_changed(self, sender, args):
        use_ref = (self.rbAfter.IsChecked == True or self.rbBefore.IsChecked == True)
        if self.cboRefField:  self.cboRefField.IsEnabled = use_ref
        if self.txtRefHint:
            self.txtRefHint.Visibility = (
                System.Windows.Visibility.Collapsed if use_ref
                else System.Windows.Visibility.Visible
            )

    # ── OK / Appliquer ────────────────────────────────────────────────────────
    def _on_ok(self, sender, args):
        errors = []

        checked_names = {sched.Name for cb, sched in self.sched_checkboxes
                         if cb.IsChecked == True}
        if not checked_names:
            errors.append(u"• Sélectionnez au moins une nomenclature cible.")

        if (self.rbAfter.IsChecked == True or self.rbBefore.IsChecked == True):
            if not self.cboRefField or self.cboRefField.SelectedItem is None:
                errors.append(
                    u"• Sélectionnez un paramètre de référence"
                    u" pour la position (« Après » ou « Avant »)."
                )

        if errors:
            self._show_validation(errors)
            return

        self._hide_validation()

        self.result = [
            sched for cb, sched in self.sched_checkboxes
            if sched.Name in checked_names
        ]

        if self.rbFirst.IsChecked == True:
            self.position_mode = "first";  self.ref_field_name = None
        elif self.rbLast.IsChecked == True:
            self.position_mode = "last";   self.ref_field_name = None
        elif self.rbAfter.IsChecked == True:
            self.position_mode = "after";  self.ref_field_name = str(self.cboRefField.SelectedItem)
        elif self.rbBefore.IsChecked == True:
            self.position_mode = "before"; self.ref_field_name = str(self.cboRefField.SelectedItem)

        self.UI.Close()

    def show_dialog(self):
        self.UI.ShowDialog()
        return self.result, self.position_mode, self.ref_field_name


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


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    try:
        log("# Copier des paramètres de nomenclature")
        log("---")

        # ── Avertissement ────────────────────────────────────────────────────
        if not show_warning():
            log("Annulé par l'utilisateur (avertissement).")
            return

        # ── Étape 1 : SOURCE + PARAMÈTRES ───────────────────────────────────
        win_src = SourceWindow()
        source, src_fields = win_src.show_dialog()
        if not source or not src_fields:
            log("Annulé (étape 1).")
            return

        log("## Source : **{}**".format(source.Name))
        log("## Paramètres sélectionnés : **{}**".format(len(src_fields)))
        for f in src_fields:
            log("- {}".format(f.GetName()))
        log("---")

        # ── Construire la liste ordonnée pour la ComboBox de référence ──────
        # Règle : champs de la nomenclature source dans leur ordre d'origine,
        #         puis champs présents uniquement dans les destinations (tri alpha).
        src_field_names_ordered = []
        src_def = source.Definition
        for i in range(src_def.GetFieldCount()):
            src_field_names_ordered.append(src_def.GetField(i).GetName())

        dest_only_names = set()
        for sched in get_all_schedules():
            if sched.Id == source.Id:
                continue
            sched_def = sched.Definition
            for i in range(sched_def.GetFieldCount()):
                name = sched_def.GetField(i).GetName()
                if name not in set(src_field_names_ordered):
                    dest_only_names.add(name)

        ordered_combo_fields = src_field_names_ordered + sorted(dest_only_names)

        # ── Étape 2 : DESTINATIONS + POSITION ───────────────────────────────
        win_dest = DestWindow(source, src_fields, ordered_combo_fields)
        dests, position_mode, ref_field_name = win_dest.show_dialog()
        if not dests:
            log("Annulé (étape 2).")
            return

        log("## Destinations : **{}**".format(len(dests)))
        for d in dests:
            log("- {}".format(d.Name))

        _pos_label = {
            "first":  "Première position",
            "last":   "Dernière position",
            "after":  u"Après « {} »".format(ref_field_name),
            "before": u"Avant « {} »".format(ref_field_name),
        }.get(position_mode, position_mode)
        log("## Position : **{}**".format(_pos_label))
        log("---")

        # ── Barre de progression (paramètres × destinations) ─────────────────
        total_ops = len(src_fields) * len(dests)
        progress  = ProgressWindow(total_ops)
        progress.UI.Show()

        # ── Transaction ──────────────────────────────────────────────────────
        field_names_str = u", ".join(f.GetName() for f in src_fields)
        t = Transaction(doc, u"Copier paramètres : {}".format(field_names_str))
        t.Start()

        success_count = 0
        skipped_count = 0
        error_count   = 0
        op_idx        = 0

        for src_field in src_fields:
            fname = src_field.GetName()
            log("### **{}**".format(fname))

            for idx, target in enumerate(dests, 1):
                op_idx += 1
                progress.update(op_idx, u"{} → {}".format(fname, target.Name))
                log("  **[{}/{}]** {}".format(idx, len(dests), target.Name))

                try:
                    ok, msg = copy_single_field(
                        src_field, target, position_mode, ref_field_name
                    )
                    if ok:
                        success_count += 1
                        log("    ➤ Ajouté")
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
        log("**Ajoutés : {}** | **Ignorés : {}** | **Erreurs : {}**".format(
            success_count, skipped_count, error_count
        ))

        message = (
            u"{} paramètre(s) × {} nomenclature(s)\n\n"
            u"  Ajoutés  : {}\n"
            u"  Ignorés  : {}\n"
            u"  Erreurs  : {}"
        ).format(len(src_fields), len(dests), success_count, skipped_count, error_count)
        show_xaml_message(message, title=u"Terminé")

    except Exception:
        tb = traceback.format_exc()
        log("Erreur critique : {}".format(tb))
        show_alert(
            "Erreur critique",
            u"Une erreur est survenue :\n\n{}".format(tb)
        )


if __name__ == "__main__":
    main()
