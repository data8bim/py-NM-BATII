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



#__title__ = 'Enregistrer depuis fichiers'
#__author__ = 'data8bim (d8b)'

import os
import sys
import traceback

# WinForms pour boîtes de dialogue personnalisées
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import (
    Form, TextBox, Button, Label,
    AnchorStyles, FormStartPosition, FormBorderStyle,
    Clipboard
)
from System.Drawing import Point, Size, Font, FontStyle

# WPF pour la boîte "Enregistrer sous"
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
from System.IO import StreamReader
from System.Windows.Markup import XamlReader
from System.Windows import Application, WindowStartupLocation

from pyrevit import forms, revit
from Autodesk.Revit.DB import SaveAsOptions

# 1) 🔥 Ajouter lib/ au sys.path
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# Import des modules partagés
from utils.config_loader import load_config
from utils.extrac_nom_fichier_convention import extract_file_name_info
from utils.nom_enegistre_revit import normalize_level_code, build_rvt_name
from utils.selection_fichier import pick_file_info

# 🔥 Charger les styles personnalisés WPF
from dialogs.dialogs_styles_loader import load
load(lib_dir=lib_dir)
#if not load(lib_dir=lib_dir):
#    print("⚠️ Styles non chargés.")



def show_file_exists_dialog(path):
    xaml_path = os.path.join(script_dir, "FileExistsDialog.xaml")
    win = forms.WPFWindow(xaml_path)
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.txtPath.Text = path

    choice = {"replace": None}
    win.btnRename.Click += lambda s, e: (
        setattr(win, "DialogResult", True),
        choice.update({"replace": False})
    )
    win.btnReplace.Click += lambda s, e: (
        setattr(win, "DialogResult", True),
        choice.update({"replace": True})
    )

    if not win.show_dialog():
        return False

    return choice["replace"]

def show_rename_dialog(default_name):
    xaml_path = os.path.join(script_dir, "RenameDialog.xaml")
    win = forms.WPFWindow(xaml_path)
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.txtName.Text = default_name

    result = {"value": None}
    win.btnOk.Click += lambda s, e: (
        setattr(win, "DialogResult", True),
        result.update({"value": win.txtName.Text.strip()})
    )
    win.btnCancel.Click += lambda s, e: (
        setattr(win, "DialogResult", False),
        result.update({"value": None})
    )

    win.show_dialog()
    return result["value"]

def show_path_dialog(path):
    xaml_path = os.path.join(script_dir, "PathDialog.xaml")
    win = forms.WPFWindow(xaml_path)
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.txtPath.Text = path
    win.btnCopy.Click += lambda s, e: Clipboard.SetText(path)
    win.btnClose.Click += lambda s, e: setattr(win, "DialogResult", True)
    win.show_dialog()

def main():
    try:
        #load_dialog_styles()
        load(lib_dir=lib_dir)


        file_info = pick_file_info(file_ext="dwg;*.pdf", title="Choisissez un fichier DWG ou PDF")
        if not file_info:
            return

        src = file_info["full_path"]
        selected_folder = file_info["folder"]
        base = file_info["basename"]

        cfg = load_config()
        naming = cfg.get("nm_convention_noms_fichiers", {})

        info = extract_file_name_info(base, naming)
        if not info:
            forms.alert("Nom non conforme à la convention.", title="Erreur")
            return

        info["level"] = normalize_level_code(info.get("level"))
        lvl_ovr = naming.get("valeur_pour_sans_niveau","").strip()
        if lvl_ovr:
            info["level"] = lvl_ovr
        half_ovr = naming.get("valeur_si_nul","").strip()
        if half_ovr:
            info["half"] = half_ovr

        base_name = build_rvt_name(info, naming)
        root_name = os.path.splitext(base_name)[0]
        suffix = naming.get("valeur_si_bim_2d","").strip()

        saveas_xaml = os.path.join(script_dir, "SaveAsDialog.xaml")
        if not os.path.isfile(saveas_xaml):
            forms.alert("XAML introuvable :\n{0}".format(saveas_xaml), title="Erreur")
            return

        win = forms.WPFWindow(saveas_xaml)
        win.WindowStartupLocation = WindowStartupLocation.CenterScreen

        def refresh_name():
            name = root_name
            if win.chkBIM2D.IsChecked and suffix:
                name += suffix
            win.txtName.Text = name + ".rvt"

        win.chkBIM2D.Checked += lambda s, e: refresh_name()
        win.chkBIM2D.Unchecked += lambda s, e: refresh_name()
        win.btnOk.Click += lambda s, e: setattr(win, "DialogResult", True)
        win.btnCancel.Click += lambda s, e: setattr(win, "DialogResult", False)

        win.chkBIM2D.IsChecked = True
        refresh_name()

        if not win.show_dialog():
            return

        user_name = win.txtName.Text.strip()
        if not user_name.lower().endswith(".rvt"):
            user_name += ".rvt"

        doc = revit.doc
        folder = os.path.dirname(doc.PathName) if doc.PathName else os.path.dirname(selected_folder)
        target = os.path.join(folder, user_name)

        while os.path.exists(target):
            replace = show_file_exists_dialog(target)
            if replace:
                opts = SaveAsOptions()
                opts.OverwriteExistingFile = True
                doc.SaveAs(target, opts)
                break

            nouvelle = show_rename_dialog(user_name)
            if not nouvelle:
                return
            if not nouvelle.lower().endswith(".rvt"):
                nouvelle += ".rvt"
            user_name = nouvelle
            target = os.path.join(folder, user_name)
        else:
            opts = SaveAsOptions()
            opts.OverwriteExistingFile = True
            doc.SaveAs(target, opts)

        show_path_dialog(target)

    except Exception:
        forms.alert(traceback.format_exc(), title="❌ Erreur inattendue")

# Exécution directe pour pyRevit
main()
