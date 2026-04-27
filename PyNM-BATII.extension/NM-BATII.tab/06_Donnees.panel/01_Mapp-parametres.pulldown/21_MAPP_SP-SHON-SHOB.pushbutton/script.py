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


#__title__ = 'SP - SHON - SHOB → Niveaux et infos projet'
#__doc__ = """Transfert les résulats des calculs de surfaces règlemantaires
#Description : Transfert les résulats des calculs de surfaces règlemantaires vers les niveaux et les informations projet. 
#Les valeurs des surfaces porté par les niveaux sont celles qui seront prise en compte par PLANON.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""


import clr

# 1) Charger les assemblies WPF
clr.AddReference("WindowsBase")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("System.Xaml")

import os
import sys
import re
import traceback
from collections import defaultdict

# 2) 🔥 Ajouter lib/ au sys.path
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir))
lib_dir    = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# 3) 🔥 Charger les styles personnalisés WPF
from dialogs.dialogs_styles_loader import load
load(lib_dir=lib_dir)

# 4) Imports pour instancier la fenêtre XAML
from System.IO             import File
from System.Windows.Markup import XamlReader

# 5) Revit & config
from pyrevit            import forms
from Autodesk.Revit.DB  import (
    FilteredElementCollector,
    ViewSchedule,
    SectionType,
    Level,
    Transaction,
    UnitUtils,
    UnitTypeId
)
from utils.config_loader                     import load_config
from utils.extrac_nom_fichier_convention     import extract_file_name_info


# -------------------------------------------------------------------
def show_xaml_message(message, title="Message"):
    """
    Charge ResultWindow.xaml, assigne Title et txtMessage.Text, puis ShowDialog().
    Utilise FindName() pour retrouver txtMessage et btnClose.
    """
    xaml_path    = os.path.join(script_dir, "ResultWindow.xaml")
    xaml_content = File.ReadAllText(xaml_path)
    window       = XamlReader.Parse(xaml_content)

    # Titre
    window.Title = title

    # Récupération des contrôles nommés
    txt_msg = window.FindName("txtMessage")
    btn     = window.FindName("btnClose")

    if txt_msg is None or btn is None:
        raise Exception("Impossible de trouver txtMessage ou btnClose dans le XAML")

    # Injection du texte
    txt_msg.Text = message

    # Fermer au clic
    btn.Click += lambda s, e: window.Close()

    # Affichage modal
    window.ShowDialog()
# -------------------------------------------------------------------


# Charger la configuration
config   = load_config() or {}
surf_cfg = config.get("surface", {}) or {}
nm_cfg   = config.get("nm_convention_noms_fichiers", {}) or {}

# Paramètres partagés
param_shon     = surf_cfg.get("param_shon",       "ANS - SURFACE - SHON")
param_shob     = surf_cfg.get("param_shob",       "ANS - SURFACE - SHOB")
param_plancher = surf_cfg.get("param_s_plancher", "ANS - SURFACE - S Plancher")

# Noms de colonnes
col_shon       = surf_cfg.get("col_shon",      "SHON")
col_shob       = surf_cfg.get("col_shob",      "SHOB")
col_plancher   = surf_cfg.get("col_plancher",  "Surface Plancher - SP")
col_filter     = surf_cfg.get("col_filter",    "Nom")

# Defaults schedules
default_shon_schedule     = surf_cfg.get("default_shon_schedule")
default_plancher_schedule = surf_cfg.get("default_plancher_schedule")

doc = __revit__.ActiveUIDocument.Document


def parse_area_value(text):
    """'123,45 m²' → 123.45 (float)"""
    if not text:
        return None
    m = re.search(r"[\d\.,]+", text)
    if not m:
        return None
    try:
        return float(m.group().replace(',', '.'))
    except:
        return None


def find_schedule(name):
    """Retourne la ViewSchedule dont vs.Name == name."""
    for vs in FilteredElementCollector(doc).OfClass(ViewSchedule):
        if vs.Name == name:
            return vs
    return None


def sum_fields_by_level(schedule_name, level_field, value_fields):
    """
    Lit la nomenclature, filtre sur col_filter, puis agrège par niveau.
    Renvoie dict: totals[field_name][level_name] = area.
    """
    vs = find_schedule(schedule_name)
    if not vs:
        show_xaml_message("Nomenclature introuvable : {0}".format(schedule_name),
                          title="Erreur")
        return {}

    body       = vs.GetTableData().GetSectionData(SectionType.Body)
    definition = vs.Definition

    # 1) champs visibles
    fields = []
    for i in range(definition.GetFieldCount()):
        f = definition.GetField(i)
        if not f.IsHidden:
            fields.append(f.GetName())

    # 2) index Niveau
    if level_field not in fields:
        show_xaml_message("Champ Niveau '{0}' absent dans '{1}'".format(
                           level_field, schedule_name),
                          title="Erreur")
        return {}
    idx_lvl = fields.index(level_field)

    # 3) index filtre
    idx_flt = fields.index(col_filter) if col_filter in fields else None

    # 4) index valeurs
    idx_vals = {}
    for vf in value_fields:
        if vf in fields:
            idx_vals[vf] = fields.index(vf)
        else:
            show_xaml_message("Champ '{0}' absent dans '{1}'".format(
                               vf, schedule_name),
                              title="Erreur")

    # 5) agrégation
    totals = {vf: defaultdict(float) for vf in idx_vals}
    for r in range(body.NumberOfRows):
        if idx_flt is not None and not body.GetCellText(r, idx_flt).strip():
            continue
        lvl_name = body.GetCellText(r, idx_lvl).strip()
        if not lvl_name:
            continue
        for vf, idx in idx_vals.items():
            area = parse_area_value(body.GetCellText(r, idx))
            if area is not None:
                totals[vf][lvl_name] += area

    return totals


def collect_levels():
    """Retourne { nom_niveau: élément Level }."""
    levels = {}
    for lvl in FilteredElementCollector(doc).OfClass(Level).ToElements():
        levels[lvl.Name] = lvl
    return levels


def main():
    # 1) Extraire code bâtiment
    file_name = os.path.basename(doc.PathName)
    info      = extract_file_name_info(file_name, nm_cfg)
    if not info or not info.get("building"):
        show_xaml_message(
            "Impossible d'extraire le code bâtiment depuis le nom de fichier.\n"
            "Vérifiez la convention de nommage dans config.json.",
            title="Erreur"
        )
        return
    building_code = info["building"]

    # 2) Lister les schedules
    sched_names = [
        vs.Name
        for vs in FilteredElementCollector(doc).OfClass(ViewSchedule).ToElements()
    ]

    # 3) Choix SHON/SHOB
    if default_shon_schedule and default_shon_schedule in sched_names:
        shon_name = default_shon_schedule
    else:
        cand = [n for n in sched_names if col_shon in n or col_shob in n] or sched_names
        shon_name = forms.SelectFromList.show(
            cand, title="Choisir SHON/SHOB", button_name="OK"
        )
        if not shon_name:
            show_xaml_message("Abandon SHON/SHOB.", title="Annulé")
            return

    # 4) Choix Surface Plancher
    plank_cand = [n for n in sched_names if "PLANCHER" in n.upper()]
    if default_plancher_schedule and default_plancher_schedule in plank_cand:
        plancher_name = default_plancher_schedule
    else:
        cand2 = plank_cand or sched_names
        plancher_name = forms.SelectFromList.show(
            cand2, title="Choisir Surface Plancher", button_name="OK"
        )
        if not plancher_name:
            show_xaml_message("Abandon Surface Plancher.", title="Annulé")
            return

    # 5) Totaux par niveau
    ss_totals = sum_fields_by_level(shon_name,     "Niveau", [col_shon, col_shob])
    pl_totals = sum_fields_by_level(plancher_name, "Niveau", [col_plancher])
    if not ss_totals and not pl_totals:
        return

    # 6) Filtrer niveaux
    levels   = collect_levels()
    all_lvls = set()
    if col_shon     in ss_totals:
        all_lvls |= set(ss_totals[col_shon].keys())
    if col_shob     in ss_totals:
        all_lvls |= set(ss_totals[col_shob].keys())
    if col_plancher in pl_totals:
        all_lvls |= set(pl_totals[col_plancher].keys())

    filtered_lvls = {lvl for lvl in all_lvls if lvl.startswith(building_code)}
    if not filtered_lvls:
        show_xaml_message(
            "Aucun niveau ne commence par '{0}'.\nVérifiez la convention de nommage.".format(
                building_code),
            title="Attention"
        )
        return

    # 6bis) Vérification niveaux manquants
    missing_lvls = [lvl for lvl in filtered_lvls if lvl not in levels]
    if missing_lvls:
        show_xaml_message(
            "Niveau(s) manquant(s) :\n  " + "\n  ".join(sorted(missing_lvls)),
            title="Erreur"
        )
        return

    # 7) Écriture paramètres Niveau
    t = Transaction(doc, "MàJ surfaces niveau + projet")
    t.Start()
    for lvl_name in sorted(filtered_lvls):
        lvl_elem = levels.get(lvl_name)
        if not lvl_elem:
            show_xaml_message(
                "Niveau absent : {0}".format(lvl_name),
                title="Attention"
            )
            continue

        for vf, prm in [
            (col_shon,     param_shon),
            (col_shob,     param_shob),
            (col_plancher, param_plancher)
        ]:
            src = ss_totals if vf in ss_totals else pl_totals
            if vf in src:
                area  = src[vf].get(lvl_name, 0.0)
                param = lvl_elem.LookupParameter(prm)
                if param and not param.IsReadOnly:
                    ival = UnitUtils.ConvertToInternalUnits(
                        area, UnitTypeId.SquareMeters
                    )
                    param.Set(ival)

    # 8) Somme projet
    shon_dict = ss_totals.get(col_shon, {})
    shob_dict = ss_totals.get(col_shob, {})
    plan_dict = pl_totals.get(col_plancher, {})

    total_shon  = sum(shon_dict.get(lvl, 0.0) for lvl in filtered_lvls)
    total_shob  = sum(shob_dict.get(lvl, 0.0) for lvl in filtered_lvls)
    total_splan = sum(plan_dict.get(lvl, 0.0) for lvl in filtered_lvls)

    proj_info = doc.ProjectInformation
    for total, prm in [
        (total_shon,  param_shon),
        (total_shob,  param_shob),
        (total_splan, param_plancher)
    ]:
        param = proj_info.LookupParameter(prm)
        if param and not param.IsReadOnly:
            ival = UnitUtils.ConvertToInternalUnits(
                total, UnitTypeId.SquareMeters
            )
            param.Set(ival)

    t.Commit()
    show_xaml_message("Mise à jour terminée.", title="Succès")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        show_xaml_message(err, title="Erreur inattendue")
