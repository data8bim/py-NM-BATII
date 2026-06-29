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


#__title__ = 'Link X RVT'
#__author__ = 'data8bim (d8b)'

import clr
import os
import sys
import re

from pyrevit import forms, script
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    RevitLinkType,
    RevitLinkInstance,
    ImportPlacement,
    RevitLinkOptions,
    ModelPathUtils,
    Transaction,
    SiteLocation
)
from System.Collections.ObjectModel import ObservableCollection

# ----------------------------------------------------------------
# Fonctions utilitaires
# ----------------------------------------------------------------
script_dir = os.path.dirname(__file__)

def show_result(message):
    xaml = os.path.join(script_dir, "ResultWindow.xaml")
    win  = forms.WPFWindow(xaml)
    win.txtMessage.Text = message
    win.btnClose.Click += lambda s,e: win.Close()
    win.show_dialog()

def show_link_message(message):
    xaml = os.path.join(script_dir, "RVTLinkDialog.xaml")
    win  = forms.WPFWindow(xaml)
    win.txtMessage.Text = message
    win.btnOk.Click += lambda s,e: win.Close()
    win.show_dialog()

# ----------------------------------------------------------------
# Chargement des styles
# ----------------------------------------------------------------
ext_dir = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir))
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

from utils.selection_fichier import pick_file_info
from dialogs.dialogs_styles_loader import load as load_styles
load_styles(lib_dir=lib_dir)

# ----------------------------------------------------------------
# 1. Fenêtre de sélection
# ----------------------------------------------------------------
xaml1 = os.path.join(script_dir, "RVTLinkOptionsDialog.xaml")
win1  = forms.WPFWindow(xaml1)

file_info = pick_file_info(file_ext="rvt", title="Sélectionnez un fichier Revit")
if not file_info:
    show_result("Aucun fichier sélectionné.")
    script.exit()

folder_path         = file_info["folder"]
win1.txtFolder.Text = folder_path

class RvtItem(object):
    def __init__(self, name, path):
        self.Name       = name
        self.Path       = path
        self.IsSelected = False

def refresh_file_list():
    include_sub     = win1.chkIncludeSub.IsChecked
    exclude_backups = win1.chkExcludeBackups.IsChecked
    filter_text     = win1.txtFilter.Text.lower().strip()
    exclude_text    = win1.txtExcludeText.Text.lower().strip()
    backup_regex    = re.compile(r"\.\d+\.rvt$", re.IGNORECASE)

    if include_sub:
        candidates = [
            os.path.join(root, f)
            for root, _, files in os.walk(folder_path)
            for f in files if f.lower().endswith(".rvt")
        ]
    else:
        candidates = [
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if f.lower().endswith(".rvt")
        ]

    candidates.sort(key=lambda p: os.path.basename(p).lower())

    doc = __revit__.ActiveUIDocument.Document
    doc_folder = os.path.dirname(doc.PathName)
    active_path_norm = os.path.normcase(os.path.abspath(doc.PathName))

    linked_paths = set()
    for lt in FilteredElementCollector(doc).OfClass(RevitLinkType):
        ext = lt.GetExternalFileReference()
        if ext:
            user_path = ModelPathUtils.ConvertModelPathToUserVisiblePath(ext.GetPath())
            if not os.path.isabs(user_path):
                user_path = os.path.normpath(os.path.join(doc_folder, user_path))
            linked_paths.add(os.path.normcase(user_path))

    items = ObservableCollection[RvtItem]()
    for p in candidates:
        name    = os.path.basename(p)
        norm_p  = os.path.normcase(os.path.normpath(p))

        if norm_p == active_path_norm:
            continue
        if norm_p in linked_paths:
            continue
        if exclude_backups and backup_regex.search(name):
            continue
        if exclude_text and exclude_text in name.lower():
            continue
        if filter_text and filter_text not in name.lower():
            continue

        items.Add(RvtItem(name, p))

    win1.lstRvts.ItemsSource = items

def browse_folder(sender, args):
    nf = pick_file_info(file_ext="rvt", title="Sélectionnez un autre fichier Revit")
    if not nf:
        return
    global folder_path
    folder_path         = nf["folder"]
    win1.txtFolder.Text = folder_path
    refresh_file_list()

def select_all(sender, args):
    for itm in win1.lstRvts.ItemsSource:
        itm.IsSelected = True
    win1.lstRvts.Items.Refresh()

def deselect_all(sender, args):
    for itm in win1.lstRvts.ItemsSource:
        itm.IsSelected = False
    win1.lstRvts.Items.Refresh()

def invert_selection(sender, args):
    for itm in win1.lstRvts.ItemsSource:
        itm.IsSelected = not itm.IsSelected
    win1.lstRvts.Items.Refresh()

dialog1 = {"sel": [], "placement": 0, "pin": True, "relative": True}
def on_link_click(sender, args):
    dialog1["placement"] = win1.cmbPlacement.SelectedIndex
    dialog1["pin"]       = win1.chkPinLinks.IsChecked
    dialog1["sel"]       = [i for i in win1.lstRvts.ItemsSource if i.IsSelected]
    selected_path_type   = win1.cmbPathType.SelectedItem.Content
    dialog1["relative"]  = True if selected_path_type == "Relatif" else False
    win1.Close()

win1.btnBrowse.Click            += browse_folder
win1.chkIncludeSub.Click        += lambda s,e: refresh_file_list()
win1.chkExcludeBackups.Click    += lambda s,e: refresh_file_list()
win1.txtFilter.TextChanged      += lambda s,e: refresh_file_list()
win1.txtExcludeText.TextChanged += lambda s,e: refresh_file_list()
win1.btnSelectAll.Click         += select_all
win1.btnDeselectAll.Click       += deselect_all
win1.btnInvertSelection.Click   += invert_selection
win1.btnOk.Click                += on_link_click
win1.btnCancel.Click            += lambda s,e: win1.Close()

refresh_file_list()
win1.show_dialog()

sel_items = dialog1["sel"]
if not sel_items:
    show_result("Aucun fichier sélectionné.")
    script.exit()

# ----------------------------------------------------------------
# 2. Liaison des fichiers RVT avec 4 modes de placement
# ----------------------------------------------------------------
from Autodesk.Revit.DB import XYZ

def get_center_bbox(doc, element):
    bbox = element.get_BoundingBox(doc.ActiveView)
    if bbox:
        return (bbox.Min + bbox.Max) / 2
    return XYZ(0, 0, 0)

doc = __revit__.ActiveUIDocument.Document
placement_mode = dialog1["placement"]
pin_links      = dialog1["pin"]
use_relative   = dialog1["relative"]

linked_pairs = []
t = Transaction(doc, "Lier fichiers RVT")
t.Start()
for itm in sel_items:
    full = os.path.abspath(itm.Path)
    if not os.path.exists(full):
        show_result("Fichier introuvable :\n{}".format(full))
        continue

    mp   = ModelPathUtils.ConvertUserVisiblePathToModelPath(full)
    opts = RevitLinkOptions(use_relative)

    try:
        link_result = RevitLinkType.Create(doc, mp, opts)
        link_type_id = link_result.ElementId
        lt = doc.GetElement(link_type_id)

        if lt is None or not isinstance(lt, RevitLinkType):
            raise Exception("Type de lien invalide")

        # Mode 0 : Emplacement partagé
        if placement_mode == 0:
            show_link_message("Sélectionnez l'emplacement pour :\n{}".format(itm.Name))
            try:
                inst = RevitLinkInstance.Create(doc, lt.Id, ImportPlacement.Shared)
                inst.Pinned = pin_links
            except:
                show_link_message("⚠️ Le modèle hôte et le lien\n« {} »\nne partagent pas le même système de coordonnées.\n\nLe positionnement Centre à centre va être utilisé.".format(itm.Name))
                inst = RevitLinkInstance.Create(doc, lt.Id)
                center_link = get_center_bbox(doc, inst)
                center_host = XYZ(0, 0, 0)
                offset = center_host - center_link
                inst.Location.Move(offset)
                inst.Pinned = pin_links

        # Mode 1 : Origine vers origine
        elif placement_mode == 1:
            inst = RevitLinkInstance.Create(doc, lt.Id, ImportPlacement.Origin)
            inst.Pinned = pin_links

        # Mode 2 : Point de base à point de base
        elif placement_mode == 2:
            inst = RevitLinkInstance.Create(doc, lt.Id)
            inst.MoveBasePointToHostBasePoint(True)
            inst.Pinned = pin_links

        # Mode 3 : Centre à centre (simulé)
        elif placement_mode == 3:
            inst = RevitLinkInstance.Create(doc, lt.Id)
            center_link = get_center_bbox(doc, inst)
            center_host = XYZ(0, 0, 0)
            offset = center_host - center_link
            inst.Location.Move(offset)
            inst.Pinned = pin_links

        linked_pairs.append((itm, inst))

    except Exception as err:
        show_result("❌ Erreur lors de la liaison du fichier :\n{}\n{}".format(itm.Name, str(err)))
t.Commit()




# ----------------------------------------------------------------
# 3. Paramétrage des liens (sur le type)
# ----------------------------------------------------------------
def get_parameter(elem, names):
    for n in names:
        p = elem.LookupParameter(n)
        if p:
            return p
    return None

class LinkSettings(object):
    def __init__(self, rvt_item, instance):
        self.Instance         = instance
        self.Name             = rvt_item.Name
        self.ReferenceOptions = ["Superposition", "Attachement"]
        self.ReferenceType    = "Superposition"
        self.RoomBounding     = True

settings_items = [LinkSettings(itm, inst) for itm, inst in linked_pairs]

xaml2 = os.path.join(script_dir, "RVTLinkSettingsDialog.xaml")
win2  = forms.WPFWindow(xaml2)
win2.dgLinks.ItemsSource = settings_items

# Appliquer en masse à la sélection
def apply_mass_settings(sender, args):
    selected = [row for row in win2.dgLinks.SelectedItems]
    if not selected:
        show_result("Aucune ligne sélectionnée.")
        return

    ref_type = win2.cmbMassReferenceType.SelectedItem.Content
    room_bound = win2.chkMassRoomBounding.IsChecked

    for row in selected:
        row.ReferenceType = ref_type
        row.RoomBounding  = room_bound

    win2.dgLinks.Items.Refresh()

win2.btnApplyMass.Click += apply_mass_settings

# Appliquer les paramètres dans Revit
def on_settings_ok(sender, args):
    tr = Transaction(doc, "Appliquer paramètres Liens RVT")
    tr.Start()
    for ls in settings_items:
        link_type_elem = doc.GetElement(ls.Instance.GetTypeId())

        p_ref = get_parameter(link_type_elem, ["Type de référence", "Reference Type"])
        if p_ref:
            val = 0 if ls.ReferenceType == "Superposition" else 1
            p_ref.Set(val)

        p_room = get_parameter(link_type_elem, ["Limite de pièce", "Room Bounding"])
        if p_room:
            p_room.Set(1 if ls.RoomBounding else 0)

    tr.Commit()
    win2.Close()

win2.btnSettingsOk.Click     += on_settings_ok

win2.show_dialog()


# ----------------------------------------------------------------
# 4. Message final
# ----------------------------------------------------------------
show_result("Tous les fichiers ont été liés\net configurés avec succès.")
