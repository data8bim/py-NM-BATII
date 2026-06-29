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


#__title__ = "Texte → Pièces\n[SELECTION]"
#__doc__ = """Transfère les valeurs des notes textuelles
#Description : Transfère les valeurs des notes textuelles sélectionnées dans la vue vers un paramètre cible des pièces qui les contiennent.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""

import clr, os, sys
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    StorageType,
    TextNote,
    XYZ,
    ViewPlan
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

doc    = revit.doc
uidoc  = revit.uidoc
MARKER = u"✔ "

# -----------------------------------------------------------------------------
# 1) Vérifier qu’on est bien dans une vue en plan (étage ou plafond)
#    et récupérer son niveau via la propriété GenLevel
# -----------------------------------------------------------------------------
view = doc.ActiveView
if not isinstance(view, ViewPlan):
    show_alert(u"Information", "Ouvrez d’abord une vue en plan (étage ou plafond).")
    script.exit()

level = view.GenLevel
if not level:
    show_alert(u"Information", "Impossible de récupérer le niveau associé à la vue.")
    script.exit()

# On ajoute un petit déport en Z pour s'assurer d'être à l'intérieur de la pièce
view_level = level.Elevation + 0.1

# -----------------------------------------------------------------------------
# 2) Chargement des styles WPF
# -----------------------------------------------------------------------------
script_dir = os.path.dirname(__file__)
lib_dir    = os.path.abspath(os.path.join(script_dir, "..", "..", "..", "lib"))
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

from dialogs.dialogs_styles_loader import load as load_styles, show_alert
load_styles(lib_dir=lib_dir)

# -----------------------------------------------------------------------------
# 3) Dernier paramètre choisi
# -----------------------------------------------------------------------------
settings_file = os.path.join(script_dir, "last_param.txt")
try:
    with open(settings_file, "r") as f:
        last_param = f.read().strip()
except:
    last_param = None

# -----------------------------------------------------------------------------
# 4) Récupérer les paramètres string d’instance des pièces
# -----------------------------------------------------------------------------
def get_room_text_params():
    rooms = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    if not rooms:
        show_alert(u"Information", "Aucune pièce trouvée.")
        script.exit()

    sample = rooms[0]
    return sorted({
        p.Definition.Name
        for p in sample.Parameters
        if not p.IsReadOnly and p.StorageType == StorageType.String
    })

# -----------------------------------------------------------------------------
# 5) Fenêtre de sélection du paramètre
# -----------------------------------------------------------------------------
class ParamDialog(WPFWindow):
    def __init__(self, xaml_file):
        super(ParamDialog, self).__init__(xaml_file)
        params = get_room_text_params()
        self.ParamSelector.ItemsSource = params
        if last_param in params:
            self.ParamSelector.SelectedItem = last_param
        self.SelectNotesButton.Click += self.on_ok
        self.CancelButton.Click      += self.on_cancel
        self.selected_param = None

    def on_ok(self, sender, args):
        self.selected_param = self.ParamSelector.SelectedItem
        if not self.selected_param:
            show_alert(u"Information", "Veuillez choisir un paramètre.")
            return
        try:
            with open(settings_file, "w") as f:
                f.write(self.selected_param)
        except:
            pass
        self.Close()

    def on_cancel(self, sender, args):
        script.exit()

# -----------------------------------------------------------------------------
# 6) Filtre de sélection : Notes Textuelles
# -----------------------------------------------------------------------------
class TextNoteFilter(object, ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, TextNote)
    def AllowReference(self, reference, point):
        return False

# -----------------------------------------------------------------------------
# 7) Fenêtre de résultat
# -----------------------------------------------------------------------------
class ResultWindow(WPFWindow):
    def __init__(self, xaml_file, message):
        super(ResultWindow, self).__init__(xaml_file)
        self.txtMessage.Text = message
        self.btnClose.Click += self.on_close
        self.KeyDown += self.on_key

    def on_close(self, sender, args):
        self.Close()

    def on_key(self, sender, args):
        key = args.Key.ToString()
        if key in ["Escape", "Enter", "Return"]:
            self.Close()

# -----------------------------------------------------------------------------
# === FLUX PRINCIPAL ===
# -----------------------------------------------------------------------------

# A) Choix du paramètre
xaml_param = script.get_bundle_file("param_dialog.xaml")
pd         = ParamDialog(xaml_param)
pd.ShowDialog()
param_name = pd.selected_param
if not param_name:
    script.exit()

# B) Sélection des notes textuelles
sel_filter = TextNoteFilter()
try:
    picked_refs = uidoc.Selection.PickObjects(
        ObjectType.Element,
        sel_filter,
        "Sélectionnez vos Notes Textuelles puis Terminer"
    )
except OperationCanceledException:
    picked_refs = []

if not picked_refs:
    rw = ResultWindow(
        script.get_bundle_file("ResultWindow.xaml"),
        u"❌ Aucune note sélectionnée."
    )
    rw.ShowDialog()
    script.exit()

# C) Regrouper les notes par pièce via la vue en plan
room_to_notes = {}
for reference in picked_refs:
    note = doc.GetElement(reference)
    pt2d = note.Coord
    pt3d = XYZ(pt2d.X, pt2d.Y, view_level)
    room = doc.GetRoomAtPoint(pt3d)
    if room:
        room_to_notes.setdefault(room.Id, []).append(note)

single_note_rooms = {
    rid: notes[0]
    for rid, notes in room_to_notes.items()
    if len(notes) == 1
}

if not single_note_rooms:
    rw = ResultWindow(
        script.get_bundle_file("ResultWindow.xaml"),
        u"❌ Aucune pièce avec exactement une note."
    )
    rw.ShowDialog()
    script.exit()

# D) Transaction : copie du texte dans le paramètre de la pièce
processed = set()
with revit.Transaction("Copie Note → Pièce"):
    for room_id, note in single_note_rooms.items():
        text = note.Text
        room  = doc.GetElement(room_id)
        param = room.LookupParameter(param_name)
        if not param or param.IsReadOnly:
            continue

        param.Set(text)
        if not text.startswith(MARKER):
            note.Text = MARKER + text

        processed.add(room_id)

# E) Affichage du résultat
count = len(processed)
if   count == 0:
    msg = u"❌ Aucun paramètre n’a été mis à jour."
elif count == 1:
    msg = u"✅ 1 pièce mise à jour sur « {} ».".format(param_name)
else:
    msg = u"✅ {} pièces mises à jour sur « {} ».".format(count, param_name)

rw = ResultWindow(
    script.get_bundle_file("ResultWindow.xaml"),
    msg
)
rw.ShowDialog()
