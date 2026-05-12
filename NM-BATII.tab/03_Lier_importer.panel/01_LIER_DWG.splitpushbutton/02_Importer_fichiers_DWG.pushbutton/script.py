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



#__title__ = 'Imports DWG → Vues'
#__author__ = 'data8bim (d8b)'

import os
import sys
import traceback
import clr
import System
import System.Reflection

from Autodesk.Revit.DB import (
    DWGImportOptions,
    ViewPlan,
    ViewType,
    Transaction,
    FilteredElementCollector,
    ImportPlacement,
    ImportInstance,
    BuiltInParameter,
    ElementId
)
from Autodesk.Revit.UI import RevitCommandId, PostableCommand
from pyrevit import forms, revit

# Chargement de la config
from utils.config_loader import load_config
config = load_config() or {}
cfg = config.get("fichiers_lies_dwg", {})

# Préparer lib/ pour importer utils et styles WPF
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir))
lib_dir    = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

from utils.selection_fichier import pick_file_info
from dialogs.dialogs_styles_loader import load as load_styles
load_styles(lib_dir=lib_dir)

# Charger enums dynamiques
asm = System.Reflection.Assembly.GetAssembly(
    clr.GetClrType(DWGImportOptions)
)
layer_mode_type = next(
    (t for t in asm.GetTypes() if t.IsEnum and t.Name == "ImportLayerMode"),
    None
)

# WinForms / Drawing
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import DialogResult
from System.Drawing import Font

# Fallback enums
try:
    from Autodesk.Revit.DB import ImportColorMode
except ImportError:
    ImportColorMode = None
try:
    from Autodesk.Revit.DB import ImportUnit
except ImportError:
    ImportUnit = None


def scan_dwgs(folder, include_sub):
    paths = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".dwg"):
                paths.append(os.path.join(root, f))
        if not include_sub:
            break
    return paths


def get_enum_name(enum_type, predicate):
    for name in System.Enum.GetNames(enum_type):
        if predicate(name.lower()):
            return name
    return None


def get_existing_dwg_names():
    doc = revit.doc
    names = set()
    for inst in FilteredElementCollector(doc).OfClass(ImportInstance):
        sym = doc.GetElement(inst.GetTypeId())
        if not sym: continue
        p = sym.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if not p: continue
        val = p.AsString()
        if val and val.lower().endswith(".dwg"):
            names.add(val.lower())
    return names


def get_link_options():
    """
    Ouvre la fenêtre WPF pour choisir les DWG à lier,
    applique les valeurs par défaut de cfg sauf view_only forcé.
    """
    # Première sélection de dossier DWG
    file_info = pick_file_info(file_ext="dwg", title="Sélectionnez un fichier DWG")
    if not file_info:
        xaml = os.path.join(os.path.dirname(__file__), "ResultWindow.xaml")
        win = forms.WPFWindow(xaml)
        win.txtMessage.Text = "❌ Aucun fichier sélectionné."
        win.btnClose.Click += lambda s, e: setattr(win, "DialogResult", True)
        win.ShowDialog()
        return None, None, None

    base_folder = file_info["folder"]
    existing    = get_existing_dwg_names()
    xaml        = os.path.join(os.path.dirname(__file__), "DWGLinkOptionsDialog.xaml")

    if not os.path.isfile(xaml):
        forms.alert("XAML introuvable :\n{}".format(xaml), title="Erreur")
        return None, None, None

    win = forms.WPFWindow(xaml)
    win.Title = "Lier DWG aux vues"

    # Forcer vue active uniquement
    win.chkViewOnly.IsChecked = True
    win.chkViewOnly.IsEnabled = False
    win.chkViewOnly.Opacity     = 0.5

    # Defaults depuis cfg
    win.chkIncludeSub.IsChecked    = bool(cfg.get("include_sub", True))
    win.chkCorrectLines.IsChecked  = bool(cfg.get("correct_lines", True))

    win.txtFolder.Text = base_folder
    win.btnBrowse.IsEnabled = True
    win._paths = []

    # Parcourir DWG
    def on_browse(s, e):
        fi = pick_file_info(file_ext="dwg", title="Sélectionnez un fichier DWG")
        if not fi: return
        win.txtFolder.Text = fi["folder"]
        refresh()
    win.btnBrowse.Click += on_browse

    # Préparer combobox Units
    if ImportUnit and hasattr(win, "cmbUnits"):
        from System.Windows.Controls import ComboBoxItem
        items = [
            ("Mètres",      ImportUnit.Meter,      "Meter (m)"),
            ("Centimètres", ImportUnit.Centimeter, "Centimeter (cm)"),
            ("Millimètres", ImportUnit.Millimeter, "Millimeter (mm)"),
            ("Automatique", ImportUnit.Default,    "Auto-detect")
        ]
        win.cmbUnits.Items.Clear()
        for label, val, tip in items:
            it = ComboBoxItem()
            it.Content = label
            it.ToolTip = tip
            it.Tag = val
            win.cmbUnits.Items.Add(it)

        default_u = cfg.get("unit_default", "")
        sel = 0
        for i in range(win.cmbUnits.Items.Count):
            if win.cmbUnits.Items[i].Content.ToString() == default_u:
                sel = i
                break
        win.cmbUnits.SelectedIndex = sel

    # Préparer combobox ColorMode
    if hasattr(win, "cmbColorMode") and ImportColorMode:
        default_c = cfg.get("color_mode_default", "")
        sel = 0
        for i in range(win.cmbColorMode.Items.Count):
            it = win.cmbColorMode.Items[i]
            txt = getattr(it, "Content", it).ToString().lower()
            if default_c.lower() in txt:
                sel = i
                break
        win.cmbColorMode.SelectedIndex = sel

    # Préparer combobox Layers
    if hasattr(win, "cmbLayers"):
        default_l = cfg.get("layers_default", "")
        sel = 0
        for i in range(win.cmbLayers.Items.Count):
            it = win.cmbLayers.Items[i]
            txt = getattr(it, "Content", it).ToString()
            if default_l == txt:
                sel = i
                break
        win.cmbLayers.SelectedIndex = sel

    # Préparer combobox Placement
    if hasattr(win, "cmbPlacement"):
        default_p = cfg.get("placement_default", "")
        sel = 0
        for i in range(win.cmbPlacement.Items.Count):
            it = win.cmbPlacement.Items[i]
            tag = getattr(it, "Tag", None)
            name = get_enum_name(
                ImportPlacement,
                lambda x: default_p.lower() in x.lower()
            )
            if name and getattr(ImportPlacement, name) == tag:
                sel = i
                break
        win.cmbPlacement.SelectedIndex = sel

    # Rafraîchir la liste DWG
    def refresh(sender=None, args=None):
        fld = win.txtFolder.Text
        if os.path.isdir(fld):
            all_dwgs = scan_dwgs(fld, bool(win.chkIncludeSub.IsChecked))
            new_dwgs = [p for p in all_dwgs
                        if os.path.basename(p).lower() not in existing]
            win._paths = new_dwgs
            win.lstDwgs.ItemsSource = [os.path.relpath(p, fld) for p in new_dwgs]
            win.lstDwgs.IsEnabled = True
        else:
            win._paths = []
            win.lstDwgs.ItemsSource = []
            win.lstDwgs.IsEnabled = False

    win.chkIncludeSub.Checked   += refresh
    win.chkIncludeSub.Unchecked += refresh
    win.btnOk.Click     += lambda s, e: setattr(win, "DialogResult", True)
    win.btnCancel.Click += lambda s, e: setattr(win, "DialogResult", False)

    refresh()
    if not win.ShowDialog():
        return None, None, None

    # Construire DWGImportOptions
    opts = DWGImportOptions()
    if hasattr(opts, "ThisViewOnly"):
        opts.ThisViewOnly = True

    # Appliquer ColorMode
    if ImportColorMode and hasattr(win, "cmbColorMode"):
        txt = win.cmbColorMode.SelectedItem.Content.lower()
        if "conserver" in txt:
            opts.ColorMode = ImportColorMode.Preserved
        elif "inverser" in txt:
            opts.ColorMode = ImportColorMode.Inverted
        elif "noir" in txt:
            opts.ColorMode = ImportColorMode.BlackAndWhite

    # Appliquer Unit
    if ImportUnit and hasattr(win, "cmbUnits"):
        sel = win.cmbUnits.SelectedItem
        if hasattr(sel, "Tag") and sel.Tag is not None:
            opts.Unit = sel.Tag

    # Appliquer Layers
    layer_idx = win.cmbLayers.SelectedIndex
    opts.VisibleLayersOnly = (layer_idx != 0)

    # Appliquer Placement
    idx = win.cmbPlacement.SelectedIndex
    shared = get_enum_name(ImportPlacement, lambda x: "shared" in x)
    center = get_enum_name(ImportPlacement, lambda x: "center" in x)
    origin = get_enum_name(ImportPlacement, lambda x: "origin" in x)
    choice = shared if idx == 0 else center if idx == 1 else origin
    opts.Placement = getattr(ImportPlacement, choice)

    # Appliquer CorrectLines
    if hasattr(opts, "CorrectLines"):
        opts.CorrectLines = bool(win.chkCorrectLines.IsChecked)

    return opts, win.txtFolder.Text, win._paths


def show_file_dialog(fname, index, total):
    xaml = os.path.join(os.path.dirname(__file__), "LinkDialog.xaml")
    win = forms.WPFWindow(xaml)
    win.Title = "Liaison du fichier"
    win.lblMessage.Text = "Liaison du fichier : {}".format(fname)
    win.progressBar.Minimum = 0
    win.progressBar.Maximum = total
    win.progressBar.Value = index - 1
    win._cancelled = False
    win.btnCancel.Click += lambda s, e: setattr(win, "_cancelled", True) or win.Close()
    win.Show()
    return win


def main():
    doc = revit.doc
    try:
        opts, folder, paths = get_link_options()
        if not opts or not paths:
            return

        # Récupérer les plans 2D Vues en plans (FloorPlan)
        plans = FilteredElementCollector(doc) \
            .OfClass(ViewPlan) \
            .WhereElementIsNotElementType()
        views = {
            v.Name.lower(): v
            for v in plans
            if not v.IsTemplate and v.ViewType == ViewType.FloorPlan
        }

        old_ids = {
            inst.Id.IntegerValue
            for inst in FilteredElementCollector(doc).OfClass(ImportInstance)
        }

        t = Transaction(doc, "Link DWG aux vues")
        t.Start()
        linked = []

        for idx, p in enumerate(paths, start=1):
            fname = os.path.basename(p)
            view = views.get(fname.lower())
            if not view:
                continue

            dlg = show_file_dialog(fname, idx, len(paths))
            if getattr(dlg, "_cancelled", False):
                break

            ok = doc.Link(p, opts, view)
            if not ok:
                # nouvelle tentative centre a centre
                center = get_enum_name(ImportPlacement, lambda x: "center" in x)
                opts.Placement = getattr(ImportPlacement, center)
                ok = doc.Link(p, opts, view)

            if not ok:
                dlg.Close()
                continue

            # Repérer nouvelles instances
            new_ids = {
                inst.Id.IntegerValue
                for inst in FilteredElementCollector(doc).OfClass(ImportInstance)
            } - old_ids

            for nid in new_ids:
                inst_new = doc.GetElement(ElementId(nid))
                inst_new.Pinned = True
                sym = doc.GetElement(inst_new.GetTypeId())
                if sym:
                    sym.Name = fname

            old_ids.update(new_ids)
            linked.append(fname)
            dlg.progressBar.Value = idx
            dlg.Close()

        t.Commit()

        # Ouvre Gestion des liens pour rafraîchir l'affichage
        uiapp = __revit__  # noqa
        manage_links_cmd = RevitCommandId.LookupPostableCommandId(
            PostableCommand.ManageLinks
        )
        uiapp.PostCommand(manage_links_cmd)

        # Une fois la boîte fermée, afficher la fenêtre de résultat
        count = len(linked)
        if count == 0:
            message = "❌ Aucun DWG lié."
        elif count == 1:
            message = "✅ 1 fichier DWG lié."
        else:
            message = "✅ {} fichiers DWG liés.".format(count)

        xaml = os.path.join(os.path.dirname(__file__), "ResultWindow.xaml")
        res = forms.WPFWindow(xaml)
        res.txtMessage.Text = message
        res.btnClose.Click += lambda s, e: setattr(res, "DialogResult", True)
        res.ShowDialog()

    except Exception:
        forms.alert(
            "Erreur lors de lier les DWG :\n{}".format(traceback.format_exc()),
            title="Erreur Lier DWG"
        )


if __name__ == "__main__":
    main()
