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


#__title__ = 'Vues depuis fichiers +'
#__author__ = 'data8bim (d8b)'

import sys
import os
import re
import traceback

# Chargement de Revit
from Autodesk.Revit.DB import (
    ViewPlan,
    ViewDrafting,
    ViewFamily,
    ViewFamilyType,
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    Transaction
)

# WPF pour la boîte 
from pyrevit import forms, revit

# 1) Ajouter lib/ au sys.path
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# Import des modules partagés
from utils.config_loader import load_config
from utils.selection_fichier import pick_file_info
from utils.extrac_nom_fichier_convention import extract_file_name_info

# 🔥 Charger les styles personnalisés WPF
from dialogs.dialogs_styles_loader import load
load(lib_dir=lib_dir)
#if not load(lib_dir=lib_dir):
#    print("⚠️ Styles non chargés.")

def get_building_code(level_name, delim="_"):
    return level_name.split(delim)[0] if delim in level_name else level_name

def get_vft_name(vft):
    param = vft.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    return param.AsString() if param else None

def main():
    try:
        # 1. Charger config.json via le loader commun
        cfg = load_config()

        # 2. Lire les paramètres de nommage
        naming = cfg.get("nm_convention_noms_fichiers", {})
        use_rg           = naming.get("utiliser_regex", False)
        delim            = naming.get("delimiteur", "_")
        ib               = naming.get("pos_code_bat", 1)
        iniv             = naming.get("pos_code_niv", 2)
        idemi            = naming.get("pos_code_demi_niv", 3)
        pat_str          = naming.get("regle_regex", "")
        custom_type_name = cfg.get("vue_type_personnalise", "").strip()

        if use_rg:
            pat   = re.compile(pat_str)
            grp_b = naming.get("group_batiment")
            grp_n = naming.get("group_niveau")
            grp_d = naming.get("group_demi")

        # 3. Sélection du dossier via l'extension personnalisée
        file_info = pick_file_info(file_ext="dwg;*.pdf", title="Choisissez un fichier")
        if not file_info:
            return
        folder = file_info["folder"]

        # 4. Collecter les niveaux du projet
        doc = revit.doc
        levels = {
            lvl.Name: lvl
            for lvl in FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Levels)
                .WhereElementIsNotElementType()
        }
        buildings = {
            get_building_code(name, delim)
            for name in levels if delim in name
        }

        # 5. Scanner le dossier : identifier les fichiers candidats
        candidates = []
        for fn in os.listdir(folder):
            low = fn.lower()
            if not (low.endswith(".dwg") or low.endswith(".pdf")):
                continue

            # Extrait les nom de la convention de nommage
            info = extract_file_name_info(fn, naming)
            if not info or info.get("building") not in buildings:
                continue

            bat  = info.get("building")
            code = "{}_{}".format(info.get("level"), info.get("half"))
            lvl_name = "{}_{}".format(bat, code)
            if lvl_name not in levels:
                continue

            candidates.append((fn, lvl_name))

        if not candidates:
            forms.alert("Aucune vue à créer trouvée.", title="Info")
            return

        # 6. Fenêtre WPF de sélection
        xaml = os.path.join(os.path.dirname(__file__), "SelectViewsWindow.xaml")
        win  = forms.WPFWindow(xaml)

        options = [
            ("Plan d'étage",           ViewFamily.FloorPlan),
            ("Plans de faux-plafonds", ViewFamily.CeilingPlan),
            ("Plan de structure",      ViewFamily.StructuralPlan),
            ("Vue de dessin",          ViewFamily.Drafting),
        ]
        labels        = [lbl for lbl, _ in options]
        view_families = {lbl: enum for lbl, enum in options}

        win.cmbViewFamily.ItemsSource   = labels
        win.cmbViewFamily.SelectedIndex = 0
        win.lstViews.ItemsSource        = [c[0] for c in candidates]

        # Gestion correcte des boutons sans accès aux visuels
        win.btnSelectAll.Click += lambda s, e: [
            win.lstViews.SelectedItems.Add(item)
            for item in win.lstViews.Items
            if not win.lstViews.SelectedItems.Contains(item)
        ]

        win.btnDeselectAll.Click += lambda s, e: win.lstViews.SelectedItems.Clear()

        def invert_selection():
            new_selection = []
            for item in win.lstViews.Items:
                if not win.lstViews.SelectedItems.Contains(item):
                    new_selection.append(item)
            win.lstViews.SelectedItems.Clear()
            for item in new_selection:
                win.lstViews.SelectedItems.Add(item)

        win.btnInvert.Click += lambda s, e: invert_selection()

        win.btnCancel.Click += lambda s, e: setattr(win, "DialogResult", False)
        win.btnOk.Click     += lambda s, e: setattr(win, "DialogResult", True)

        if not win.ShowDialog():
            return

        # 7. Lecture de la sélection
        selected_files = [item for item in win.lstViews.SelectedItems]
        chosen_lbl     = win.cmbViewFamily.SelectedItem
        fam_enum       = view_families[chosen_lbl]

        # 8. Déterminer le ViewFamilyType
        all_vfts = list(FilteredElementCollector(doc).OfClass(ViewFamilyType))
        base_vft = next((vf for vf in all_vfts if vf.ViewFamily == fam_enum), None)
        if not base_vft:
            forms.alert("Le type de vue de base est introuvable.", title="Erreur")
            return

        if not custom_type_name:
            target_vft = base_vft
        else:
            target_vft = next(
                (vf for vf in all_vfts
                 if vf.ViewFamily == fam_enum and get_vft_name(vf) == custom_type_name),
                None
            )
            if target_vft is None:
                tx = Transaction(doc, "Créer type {}".format(custom_type_name))
                tx.Start()
                dup_res = base_vft.Duplicate(custom_type_name)
                target_vft = dup_res if isinstance(dup_res, ViewFamilyType) else doc.GetElement(dup_res)
                tx.Commit()

        vft_id = target_vft.Id

        # 9. Création des vues
        created = []
        t = Transaction(doc, "Créer vues depuis DWG")
        t.Start()

        existing_views = list(FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .OfClass(ViewPlan)) + list(FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .OfClass(ViewDrafting))

        # Vérifie si une vue du même nom ET même famille existe
        def is_duplicate(name, view_family):
            for v in existing_views:
                if v.Name != name:
                    continue
                if isinstance(v, ViewDrafting) and view_family == ViewFamily.Drafting:
                    return True
                if isinstance(v, ViewPlan):
                    vft = doc.GetElement(v.GetTypeId())
                    if vft.ViewFamily == view_family:
                        return True
            return False

        for name, key in candidates:
            if name not in selected_files or is_duplicate(name, fam_enum):
                continue

            if fam_enum == ViewFamily.Drafting:
                view = ViewDrafting.Create(doc, vft_id)
            else:
                lvl = levels.get(key)
                if not lvl:
                    continue
                view = ViewPlan.Create(doc, vft_id, lvl.Id)

            view.Name = name
            created.append(name)

        t.Commit()

        # 10. Fenêtre de confirmation personnalisée
        res_xaml = os.path.join(os.path.dirname(__file__), "ResultWindow.xaml")
        res_win  = forms.WPFWindow(res_xaml)
        res_win.txtMessage.Text = "✅ {} vues créées.".format(len(created))
        res_win.btnClose.Click += lambda s, e: setattr(res_win, "DialogResult", True)
        res_win.ShowDialog()

    except Exception:
        forms.alert(traceback.format_exc(), title="❌ Erreur Création vues")

if __name__ == "__main__":
    main()
