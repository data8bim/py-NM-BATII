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


#__title__ = 'Lignes → Sép. Pièces'
#__author__ = 'data8bim (d8b)'

import sys
import clr
from pyrevit import revit, DB, forms

# Références Revit
from Autodesk.Revit.DB import (
    ViewPlan,
    ModelCurve,
    DetailCurve,
    CurveElement,
    Plane,
    SketchPlane,
    FilteredElementCollector,
    BuiltInCategory
)

doc   = revit.doc
uidoc = revit.uidoc
view  = doc.ActiveView


# ── Fenêtre de résultat personnalisée ────────────────────────────────────────

class ResultWindow(forms.WPFWindow):
    """Charge ResultWindow.xaml et affiche un message."""

    def __init__(self, message, title="Limites de pièce"):
        forms.WPFWindow.__init__(self, 'ResultWindow.xaml')
        self.Title = title
        self.txtMessage.Text = message
        self.btnClose.Click += self._on_close

    def _on_close(self, sender, args):
        self.Close()

    @staticmethod
    def show(message, title="Limites de pièce", exit_after=False):
        """Affiche la fenêtre, puis quitte le script si exit_after=True."""
        win = ResultWindow(message, title)
        win.ShowDialog()
        if exit_after:
            sys.exit(0)


# ── 1. Vérifier que la vue active est un FloorPlan ───────────────────────────

if not isinstance(view, ViewPlan):
    ResultWindow.show(
        "❌ La vue active doit être un plan d'étage (Floor Plan).",
        exit_after=True
    )

# ── 2. Récupérer la sélection de lignes ─────────────────────────────────────

selected_ids = uidoc.Selection.GetElementIds()
if not selected_ids:
    ResultWindow.show(
        "⚠️ Sélectionnez une ou plusieurs lignes.",
        exit_after=True
    )

elements = [doc.GetElement(elid) for elid in selected_ids]
curves = []

for el in elements:
    if isinstance(el, (ModelCurve, DetailCurve, CurveElement)):
        try:
            crv = el.GeometryCurve
            if crv:
                curves.append(crv)
        except:
            continue

if not curves:
    ResultWindow.show(
        "⚠️ Aucune courbe exploitable trouvée dans la sélection.",
        exit_after=True
    )

# ── 3. Démarrer la transaction ───────────────────────────────────────────────

tx = DB.Transaction(doc, "Créer des séparateurs de pièce")
tx.Start()

try:
    # 4. Créer un SketchPlane basé sur la vue
    plane        = Plane.CreateByNormalAndOrigin(view.ViewDirection, view.Origin)
    sketch_plane = SketchPlane.Create(doc, plane)

    # 5. Convertir les courbes en CurveArray
    curve_array = DB.CurveArray()
    for crv in curves:
        curve_array.Append(crv)

    # 6. Créer les Room Boundary Lines
    created_ids = []
    lines = doc.Create.NewRoomBoundaryLines(sketch_plane, curve_array, view)
    if lines:
        for line in lines:
            created_ids.append(line.Id)

    tx.Commit()

    # 7. Message de succès
    ResultWindow.show(
        "✅ {} séparateur(s) de pièce créé(s).".format(len(created_ids))
    )

except Exception as e:
    tx.RollBack()
    ResultWindow.show(
        "❌ Erreur pendant la création :\n{}".format(str(e))
    )