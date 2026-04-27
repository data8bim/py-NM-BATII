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



#__title__ = 'Niveaux depuis fichiers'
#__author__ = 'data8bim (d8b)'

import sys
import os
import re
import csv
import traceback
import clr


# Chargement de Revit
from Autodesk.Revit.DB import (
    Level, BuiltInCategory,
    FilteredElementCollector, Transaction
)


# WPF pour la boîte 
from pyrevit import forms, revit


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
from utils.selection_fichier import pick_file_info
from utils.extrac_nom_fichier_convention import extract_file_name_info

# 🔥 Charger les styles personnalisés WPF
from dialogs.dialogs_styles_loader import load
load(lib_dir=lib_dir)


def read_ordered_codes(csv_path):
    codes = []
    with open(csv_path, 'r') as f:
        rdr = csv.DictReader(f, delimiter=';')
        for row in rdr:
            c = row.get('Type-Niv-Demi')
            if c:
                codes.append(c)
    return codes

def parse_code_key(code):
    m = re.match(r"([A-Z])([+-])(\d+)_([0-9])", code)
    if not m:
        return 0.0
    _, sign, num, demi = m.groups()
    num, demi = int(num), int(demi)
    base = num if sign == '+' else -(num + 1)
    return base + demi / 10.0

def get_user_params(default_esp, origin_label):
    xaml_file = os.path.join(os.path.dirname(__file__), "LevelParamsWindow.xaml")
    win = forms.WPFWindow(xaml_file)

    win.txtEspacement.Text = str(default_esp)
    win.chkOrigin.Content = "Créer le niveau Origine {}".format(origin_label)
    win.chkOrigin.IsChecked = True

    result = {"esp": None, "create_origin": False}

    def on_ok(sender, e):
        try:
            result["esp"] = float(win.txtEspacement.Text.strip())
        except:
            result["esp"] = default_esp
        result["create_origin"] = win.chkOrigin.IsChecked
        win.Close()

    def on_cancel(sender, e):
        result["esp"] = None
        win.Close()

    win.btnOk.Click += on_ok
    win.btnCancel.Click += on_cancel

    win.ShowDialog()
    return result["esp"], result["create_origin"]

def main():
    try:
        cfg         = load_config()
        naming_cfg  = cfg.get('nm_convention_noms_fichiers', {})
        prm         = cfg.get('creer_niveaux', {})
        esp_default = prm.get('espacement_default', 5.0)

        mark_toit   = prm.get('Marq_Niv_Toit', '')
        mark_fond   = prm.get('Marq_Niv_Fondations', '')
        mark_pos    = prm.get('Idt_Niv_Batiment_pos', '')
        mark_neg    = prm.get('Idt_Niv_Batiment_neg', '')
        idt_rdc     = prm.get('Idt_Niv_Rdc', '')
        idt_rdc_bas = prm.get('Idt_Niv_Rdc_bas', '')
        eleva_rdc   = prm.get('Eleva_Niv_Rdc', 0.0)
        idt_orig    = prm.get('Idt_Niv_Origine', '')
        eleva_orig  = prm.get('Eleva_Niv_Origine', 0.0)

        file_info = pick_file_info(file_ext='dwg;*.pdf', title='Sélectionnez un DWG ou PDF')
        if not file_info:
            return
        dwg_dir  = file_info['folder']
        basename = file_info['basename']

        info = extract_file_name_info(basename, naming_cfg)
        if not info:
            forms.alert(
                "Nom non conforme à la convention :\n{}".format(basename),
                title='❌ Erreur Créer niveaux'
            )
            return
        bat_code = info.get('building', '')

        esp, create_origin = get_user_params(esp_default, idt_orig)
        if esp is None:
            return
        to_ft = lambda m: m * 3.28084

        fichiers       = [f for f in os.listdir(dwg_dir) if f.lower().endswith(('.dwg', '.pdf'))]
        codes_found     = set()
        rdc_bas_present = False
        for fn in fichiers:
            base = os.path.splitext(fn)[0]
            fi = extract_file_name_info(base, naming_cfg)
            if not fi or fi.get('building') != bat_code:
                continue
            code = "{}_{}".format(fi.get('level',''), fi.get('half',''))
            if 'X' in code:
                continue
            codes_found.add(code)
            if code == idt_rdc_bas:
                rdc_bas_present = True

        if not codes_found:
            forms.alert(
                "Aucun niveau valide trouvé pour le bâtiment '{}'".format(bat_code),
                title='❌ Erreur Créer niveaux'
            )
            return

        csv_path = os.path.join(os.path.dirname(__file__), 'Niv_depuis_fichiers_ORDRE_NIV.csv')
        if not os.path.isfile(csv_path):
            forms.alert(
                "Le fichier CSV d'ordre est introuvable :\n{}".format(csv_path),
                title='❌ Erreur Créer niveaux'
            )
            return
        all_codes   = read_ordered_codes(csv_path)
        full_global = [c for c in all_codes if c.endswith('_0')]
        demi_global = [c for c in all_codes if not c.endswith('_0')]

        missing = []
        if mark_toit and not any(c.startswith(mark_toit) for c in full_global):
            missing.append("Toit '{}'".format(mark_toit))
        if mark_fond and not any(c.startswith(mark_fond) for c in full_global):
            missing.append("Fondations '{}'".format(mark_fond))
        if mark_pos and not any(c.startswith(mark_pos) for c in full_global):
            missing.append("Bât pos '{}'".format(mark_pos))
        if mark_neg and not any(c.startswith(mark_neg) for c in full_global):
            missing.append("Bât neg '{}'".format(mark_neg))
        if idt_rdc and idt_rdc not in full_global:
            missing.append("RDC '{}' absent du CSV".format(idt_rdc))
        if missing:
            forms.alert("Le fichier CSV ne contient pas :\n- " + "\n- ".join(missing),
                        title='❌ Vérification CSV')
            return

        roof_global = [c for c in full_global if c.startswith(mark_toit)]
        fond_global = [c for c in full_global if c.startswith(mark_fond)]
        bat_global  = [c for c in full_global if c.startswith(mark_pos) or c.startswith(mark_neg)]

        if not rdc_bas_present:
            bat_global = [c for c in bat_global if c != idt_rdc_bas]

        roof_found = [c for c in roof_global if c in codes_found]
        fond_found = [c for c in fond_global if c in codes_found]
        bat_found  = [c for c in bat_global if c in codes_found]
        if idt_rdc and idt_rdc not in bat_found:
            bat_found.append(idt_rdc)
        if rdc_bas_present and idt_rdc_bas not in bat_found:
            bat_found.append(idt_rdc_bas)

        idx_min   = min(bat_global.index(c) for c in bat_found)
        idx_max   = max(bat_global.index(c) for c in bat_found)
        bat_range = bat_global[idx_min: idx_max + 1]

        codes_to_insert = [idt_rdc]
        if rdc_bas_present:
            codes_to_insert.append(idt_rdc_bas)
        for code in codes_to_insert:
            if code in bat_global and code not in bat_range:
                pos_csv   = bat_global.index(code)
                insert_at = sum(1 for c in bat_range if bat_global.index(c) < pos_csv)
                bat_range.insert(insert_at, code)

        idx_rdc = bat_range.index(idt_rdc)
        pos_m   = {}
        for i, lvl in enumerate(bat_range):
            pos_m[lvl] = eleva_rdc + (idx_rdc - i) * esp

        key_map    = {c: parse_code_key(c) for c in all_codes}
        demi_found = [c for c in demi_global if c in codes_found]
        bat_bt     = list(reversed(bat_range))
        for lo, hi in zip(bat_bt, bat_bt[1:]):
            h_lo, h_hi = pos_m[lo], pos_m[hi]
            k_lo, k_hi = key_map[lo], key_map[hi]
            for d in demi_found:
                k_d = key_map[d]
                if d in pos_m:
                    continue
                if k_lo < k_d < k_hi:
                    pos_m[d] = h_lo + ((k_d - k_lo)/(k_hi - k_lo))*(h_hi - h_lo)

        # 14) Toiture générale
        if roof_global:
            general_roof = roof_global[0]
            max_b = max(pos_m[l] for l in bat_range)
            for idx, lvl in enumerate(
                    sorted(roof_found, key=lambda x: key_map[x]), 1):
                pos_m[lvl] = max_b + idx * esp
            pos_m[general_roof] = max_b + (len(roof_found) + 1) * esp

        # 15) Fondation générale
        if fond_global:
            general_fond = fond_global[-1]
            min_b = min(pos_m[l] for l in bat_range)
            for idx, lvl in enumerate(
                    sorted(fond_found, key=lambda x: key_map[x], reverse=True), 1):
                pos_m[lvl] = min_b - idx * esp
            pos_m[general_fond] = min_b - (len(fond_found) + 1) * esp

        # 16) Origine optionnelle
        if create_origin and idt_orig:
            pos_m[idt_orig] = eleva_orig

        # 17) Création dans Revit
        sorted_levels = sorted(pos_m.items(), key=lambda x: x[1])
        doc = revit.doc
        existing = {
            lvl.Name for lvl in FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Levels)
                .WhereElementIsNotElementType()
        }
        created = []

        t = Transaction(doc, "Créer niveaux depuis CSV+DWG")
        t.Start()
        for code, elev_m in sorted_levels:
            name = "{}_{}".format(bat_code, code)
            if name not in existing:
                lvl = Level.Create(doc, to_ft(elev_m))
                lvl.Name = name
                created.append(name)
        t.Commit()

        # 18) Confirmation finale
        res_xaml = os.path.join(os.path.dirname(__file__), "ResultWindow.xaml")
        res_win  = forms.WPFWindow(res_xaml)

        nb = len(created)

        if nb == 0:
            msg = "❌ {} Aucun niveau n'a été créé.".format(nb)
        elif nb == 1:
            msg = "✅ {} niveau créé.".format(nb)
        else:
            msg = "✅ {} niveaux créés.".format(nb)

        res_win.txtMessage.Text = msg
        res_win.btnClose.Click += lambda s, e: setattr(res_win, "DialogResult", True)
        # ✅ FIX pyRevit 6 : show_dialog() supprimé → ShowDialog() (WPF natif)
        res_win.ShowDialog()
        

    except Exception:
        forms.alert(traceback.format_exc(), title="❌ Erreur inattendue")


if __name__ == '__main__':
    main()
