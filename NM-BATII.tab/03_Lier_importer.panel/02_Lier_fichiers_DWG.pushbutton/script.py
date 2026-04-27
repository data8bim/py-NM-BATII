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


#__title__ = 'Lier DWG → Vues'
#__author__ = 'data8bim (d8b)'

import os
import sys
import traceback
import clr
import System
import System.Reflection

from Autodesk.Revit.DB import (
    DWGImportOptions,
    View,
    Transaction,
    FilteredElementCollector,
    ImportPlacement,
    ImportInstance,
    BuiltInParameter,
    ElementId
)
from pyrevit import forms, revit

# 1) Ajouter lib/ au sys.path pour importer les utilitaires partagés
script_dir = os.path.dirname(__file__)
ext_dir = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# Import des utilitaires
from utils.config_loader import load_config
from utils.selection_fichier import pick_file_info

# Charger les styles WPF
from dialogs.dialogs_styles_loader import load as load_styles
load_styles(lib_dir=lib_dir)

# Charger la configuration globale
config = load_config() or {}
# Extraire la section dédiée aux DWG
cfg = config.get("fichiers_lies_dwg", {})

# Charger l’assembly DWG pour inspecter l’énum ImportLayerMode
asm = System.Reflection.Assembly.GetAssembly(
    clr.GetClrType(DWGImportOptions)
)
layer_mode_type = None
for t in asm.GetTypes():
    if t.IsEnum and t.Name == "ImportLayerMode":
        layer_mode_type = t
        break

# Références WinForms + Drawing
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import (
    DialogResult
)
from System.Drawing import Font

# Fallback enums
try:
    from Autodesk.Revit.DB import ImportColorMode
except ImportError:
    ImportColorMode = None
try:
    from Autodesk.Revit.DB import ImportLayers
except ImportError:
    ImportLayers = None
try:
    from Autodesk.Revit.DB import ImportUnit
except ImportError:
    ImportUnit = None


def scan_dwgs(folder, include_sub):
    """
    Parcours un dossier pour lister tous les fichiers .dwg.
    """
    paths = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".dwg"):
                paths.append(os.path.join(root, f))
        if not include_sub:
            break
    return paths


def get_enum_name(enum_type, predicate):
    """
    Renvoie le nom de la première valeur d'un enum dont
    predicate(name.lower()) retourne True.
    """
    for name in System.Enum.GetNames(enum_type):
        if predicate(name.lower()):
            return name
    return None


def get_existing_dwg_names():
    """
    Récupère les noms de DWG déjà liés.
    """
    doc = revit.doc
    existing = set()
    for inst in FilteredElementCollector(doc).OfClass(ImportInstance):
        sym = doc.GetElement(inst.GetTypeId())
        if not sym:
            continue
        p = sym.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if not p:
            continue
        val = p.AsString()
        if val and val.lower().endswith(".dwg"):
            existing.add(val.lower())
    return existing


def get_link_options():
    """
    Ouvre le dialogue WPF pour paramétrer et choisir les DWG à lier.
    Retourne (opts, dossier, liste_de_chemins) ou (None, None, None) si annulé.
    """
    # Sélection d'un DWG pour fixer base_folder
    file_info = pick_file_info(file_ext="dwg", title="Sélectionnez un fichier DWG")
    if not file_info:
        # message d'annulation
        result_xaml = os.path.join(os.path.dirname(__file__), "ResultWindow.xaml")
        res_win = forms.WPFWindow(result_xaml)
        res_win.txtMessage.Text = "❌ Aucun fichier sélectionné."
        res_win.btnClose.Click += lambda s, e: setattr(res_win, "DialogResult", True)
        res_win.ShowDialog()
        return None, None, None

    base_folder = file_info["folder"]
    existing = get_existing_dwg_names()

    # Charger le XAML
    xaml = os.path.join(os.path.dirname(__file__), "DWGLinkOptionsDialog.xaml")
    if not os.path.isfile(xaml):
        forms.alert("XAML introuvable :\n{}".format(xaml), title="Erreur")
        return None, None, None

    win = forms.WPFWindow(xaml)
    win.Title = "Lier DWG aux vues"
    win.lstDwgs.IsEnabled = False
    win._paths = []

    # Dossier de travail
    win.txtFolder.Text = base_folder
    # Activation du bouton Parcourir pour utiliser pick_file_info
    win.btnBrowse.IsEnabled = True

    # Raccrocher le bouton Parcourir à pick_file_info
    def on_browse(sender, args):
        file_info = pick_file_info(file_ext="dwg", title="Sélectionnez un fichier DWG")
        if not file_info:
            return
        win.txtFolder.Text = file_info["folder"]
        # Relance le scan + rafraîchissement
        refresh()

    win.btnBrowse.Click += on_browse

    # Inclure sous-dossiers
    win.chkIncludeSub.IsChecked = bool(cfg.get("include_sub", True))

    # Préparer cmbUnits
    if ImportUnit and hasattr(win, "cmbUnits"):
        from System.Windows.Controls import ComboBoxItem
        unit_items = [
            ("Mètres",      ImportUnit.Meter,      "Meter (m)"),
            ("Centimètres", ImportUnit.Centimeter, "Centimeter (cm)"),
            ("Millimètres", ImportUnit.Millimeter, "Millimeter (mm)"),
            ("Automatique", ImportUnit.Default,    "Auto-detect")
        ]
        win.cmbUnits.Items.Clear()
        for label, enum_val, tooltip in unit_items:
            item = ComboBoxItem()
            item.Content = label
            item.ToolTip = tooltip
            item.Tag = enum_val
            win.cmbUnits.Items.Add(item)

        # Sélection par défaut
        default_unit = cfg.get("unit_default")
        sel = 0
        if default_unit:
            for i in range(win.cmbUnits.Items.Count):
                if win.cmbUnits.Items[i].Content.ToString() == default_unit:
                    sel = i
                    break
        win.cmbUnits.SelectedIndex = sel

    # Préparer cmbColorMode
    if hasattr(win, "cmbColorMode"):
        default_color = cfg.get("color_mode_default", "")
        sel = 0
        for i in range(win.cmbColorMode.Items.Count):
            item = win.cmbColorMode.Items[i]
            txt = getattr(item, "Content", item).ToString().lower()
            if default_color.lower() in txt:
                sel = i
                break
        win.cmbColorMode.SelectedIndex = sel

    # Préparer cmbLayers
    if hasattr(win, "cmbLayers"):
        default_layer = cfg.get("layers_default", "")
        sel = 0
        for i in range(win.cmbLayers.Items.Count):
            item = win.cmbLayers.Items[i]
            text = getattr(item, "Content", item).ToString()
            if text == default_layer:
                sel = i
                break
        win.cmbLayers.SelectedIndex = sel

    # Préparer cmbPlacement
    if hasattr(win, "cmbPlacement"):
        default_place = cfg.get("placement_default", "")
        sel = 0
        for i in range(win.cmbPlacement.Items.Count):
            item = win.cmbPlacement.Items[i]
            tag = getattr(item, "Tag", None)
            name = get_enum_name(
                ImportPlacement,
                lambda x: default_place.lower() in x.lower()
            )
            if name and getattr(ImportPlacement, name) == tag:
                sel = i
                break
        win.cmbPlacement.SelectedIndex = sel

    # Cases à cocher
    win.chkCorrectLines.IsChecked = bool(cfg.get("correct_lines", True))
    win.chkViewOnly.IsChecked    = bool(cfg.get("view_only", True))

    # Rafraîchir la liste des DWG
    def refresh(sender=None, args=None):
        fld = win.txtFolder.Text
        if os.path.isdir(fld):
            all_dwgs = scan_dwgs(fld, bool(win.chkIncludeSub.IsChecked))
            new_dwgs = [
                p for p in all_dwgs
                if os.path.basename(p).lower() not in existing
            ]
            win._paths = new_dwgs
            rels = [os.path.relpath(p, fld) for p in new_dwgs]
            win.lstDwgs.ItemsSource = rels
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

    # Construction des options
    opts = DWGImportOptions()

    # Calques
    layer_idx = win.cmbLayers.SelectedIndex
    opts.VisibleLayersOnly = (layer_idx != 0)

    # Couleurs
    if ImportColorMode and hasattr(win, "cmbColorMode"):
        sel_text = win.cmbColorMode.SelectedItem.Content.lower()
        if "conserver" in sel_text:
            opts.ColorMode = ImportColorMode.Preserved
        elif "inverser" in sel_text:
            opts.ColorMode = ImportColorMode.Inverted
        elif "noir" in sel_text:
            opts.ColorMode = ImportColorMode.BlackAndWhite
        else:
            opts.ColorMode = ImportColorMode.Preserved

    # Unités
    if ImportUnit and hasattr(win, "cmbUnits"):
        sel_item = win.cmbUnits.SelectedItem
        if hasattr(sel_item, "Tag"):
            opts.Unit = sel_item.Tag

    # Placement
    idx = win.cmbPlacement.SelectedIndex
    shared_name = get_enum_name(ImportPlacement, lambda x: "shared" in x)
    center_name = get_enum_name(ImportPlacement, lambda x: "center" in x)
    origin_name = get_enum_name(ImportPlacement, lambda x: "origin" in x)
    choice = (
        shared_name if idx == 0
        else center_name if idx == 1
        else origin_name
    )
    opts.Placement = getattr(ImportPlacement, choice)

    # Correction des lignes
    if hasattr(opts, "CorrectLines"):
        opts.CorrectLines = bool(win.chkCorrectLines.IsChecked)

    # Vues uniquement
    opts.ThisViewOnly = bool(win.chkViewOnly.IsChecked)

    return opts, win.txtFolder.Text, win._paths


def show_file_dialog(fname, index, total):
    """
    Affiche une fenêtre de progression pour le fichier en cours de liaison.
    """
    xaml = os.path.join(os.path.dirname(__file__), "LinkDialog.xaml")
    win = forms.WPFWindow(xaml)
    win.Title = "Liaison du fichier"
    win.lblMessage.Text = "Liaison du fichier : {}".format(fname)
    win.progressBar.Minimum = 0
    win.progressBar.Maximum = total
    win.progressBar.Value = index - 1
    win._cancelled = False

    def on_cancel(s, e):
        win._cancelled = True
        win.Close()

    win.btnCancel.Click += on_cancel
    win.Show()
    return win


def main():
    try:
        doc = revit.doc
        opts, folder, paths = get_link_options()
        if not opts or not paths:
            return

        # Préparer transaction
        shared_name = get_enum_name(ImportPlacement, lambda x: "shared" in x)
        center_name = get_enum_name(ImportPlacement, lambda x: "center" in x)
        shared = getattr(ImportPlacement, shared_name)
        center = getattr(ImportPlacement, center_name)

        old_ids = {
            inst.Id.IntegerValue
            for inst in FilteredElementCollector(doc).OfClass(ImportInstance)
        }

        # Collecter les vues cibles
        views = {}
        all_views = (
            FilteredElementCollector(doc)
              .OfClass(View)
              .WhereElementIsNotElementType()
        )
        for v in all_views:
            if (not v.IsTemplate and
                v.ViewType.ToString() in (
                    "FloorPlan", "CeilingPlan",
                    "StructuralPlan", "DraftingView"
                )):
                views[v.Name.lower()] = v

        t = Transaction(doc, "Link DWG aux vues")
        t.Start()
        linked = []

        total = len(paths)
        for idx, p in enumerate(paths, start=1):
            fname = os.path.basename(p)
            view = views.get(fname.lower())
            if not view:
                continue

            dialog = show_file_dialog(fname, idx, total)
            if getattr(dialog, "_cancelled", False):
                break

            ok = doc.Link(p, opts, view)
            if not ok and opts.Placement == shared:
                opts.Placement = center
                ok = doc.Link(p, opts, view)
            if not ok:
                dialog.Close()
                continue

            new_ids = {
                inst.Id.IntegerValue
                for inst in FilteredElementCollector(doc).OfClass(ImportInstance)
            } - old_ids

            for nid in new_ids:
                inst_new = doc.GetElement(ElementId(nid))
                inst_new.Pinned = True
                sym = doc.GetElement(inst_new.GetTypeId())
                sym.Name = fname

            old_ids.update(new_ids)
            linked.append(fname)
            dialog.progressBar.Value = idx
            dialog.Close()

        t.Commit()

        # Résultat final
        count = len(linked)
        if count == 0:
            message = "❌ Aucun DWG lié."
        elif count == 1:
            message = "✅ 1 fichier DWG lié."
        else:
            message = "✅ {} fichiers DWG liés.".format(count)

        result_xaml = os.path.join(
            os.path.dirname(__file__), "ResultWindow.xaml"
        )
        res_win = forms.WPFWindow(result_xaml)
        res_win.txtMessage.Text = message
        res_win.btnClose.Click += lambda s, e: setattr(res_win, "DialogResult", True)
        res_win.ShowDialog()

    except Exception:
        forms.alert(
            "Erreur lors de lier les DWG :\n{}".format(traceback.format_exc()),
            title="Erreur Lier DWG"
        )


if __name__ == "__main__":
    main()
