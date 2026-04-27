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


#__title__ = 'Liste DWG'
#__author__ = 'data8bim (d8b)'

import os
from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ImportInstance,
    BuiltInParameter
)

# Charger la boîte XAML
xaml_path = os.path.join(
    os.path.dirname(__file__),
    "DWGLinkedDumpDialog.xaml"
)
if not os.path.isfile(xaml_path):
    forms.alert("XAML introuvable :\n{}".format(xaml_path), title="Erreur")
    raise SystemExit

win = forms.WPFWindow(xaml_path)
win.Title = "DWG liés – Diagnostic"

doc = revit.doc
lines = []

for inst in FilteredElementCollector(doc).OfClass(ImportInstance):
    lines.append("=== ImportInstance Id={} Nom='{}' ===".format(
        inst.Id.IntegerValue, inst.Name
    ))

    # Type associé (ImportSymbol)
    typ = doc.GetElement(inst.GetTypeId())
    if typ:
        ptype = typ.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        type_name = ptype.AsString() if ptype else "<sans nom>"
    else:
        type_name = "<introuvable>"
    lines.append("  Type: {}".format(type_name))

    # Recherche Paramètres de l'instance
    for p in inst.Parameters:
        try:
            val = p.AsValueString() or p.AsString() or str(p.AsDouble())
        except:
            val = "<inaccessible>"
        lines.append("  Paramètre '{}': {}".format(p.Definition.Name, val))

    # Recherche Paramètres du type
    if typ:
        lines.append("  --- Paramètres du type ---")
        for p in typ.Parameters:
            try:
                val = p.AsValueString() or p.AsString() or str(p.AsDouble())
            except:
                val = "<inaccessible>"
            lines.append("  Type.Paramètre '{}': {}".format(p.Definition.Name, val))

    lines.append("")  # espace

# Injecter dans la TextBox
win.txtDump.Text = "\n".join(lines) if lines else "Aucune liaison DWG détectée."

# Bouton de fermeture
win.btnClose.Click += lambda s,e: win.Close()

# Afficher la boîte
win.show_dialog()
